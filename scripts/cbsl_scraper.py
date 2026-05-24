#!/usr/bin/env python3
"""
GOVIYA — CBSL Daily Price Scraper
Runs on GitHub Actions every morning at 3:30 AM UTC (9:00 AM Sri Lanka)
"""
import os, re, time, logging, requests, pdfplumber, io
from datetime import date, timedelta
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cbsl")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
CBSL_BASE    = "https://www.cbsl.gov.lk/sites/default/files/cbslweb_documents/statistics/pricerpt"

CROP_MAP = {
    "beans":"Beans","carrot":"Carrot","cabbage":"Cabbage","tomato":"Tomato",
    "brinjal":"Brinjal","pumpkin":"Pumpkin","snake gourd":"Snake Gourd",
    "green chilli":"Chilli Green","lime":"Lime","leeks":"Leeks",
    "red onion (local)":"Red Onion","red onion (imp)":"Red Onion",
    "big onion (local)":"Big Onion","big onion (imp)":"Big Onion",
    "potato (local)":"Potato","potato (imp)":"Potato","potato":"Potato",
    "dried chilli (imp)":"Chilli Dry","coconut (avg.)":"Coconut",
    "banana (sour)":"Banana","papaw":"Papaya","pineapple":"Pineapple",
    "samba":"Samba Rice","nadu":"Nadu Rice","kekulu (white)":"Kekulu Rice",
    "kekulu (red)":"Kekulu Red Rice","kelawalla":"Kelawalla",
    "thalapath":"Thalapath","balaya":"Balaya",
    "sugar (white)":"Sugar","egg (white)":"Eggs","coconut oil":"Coconut Oil",
    "red dhal":"Red Dhal","ginger":"Ginger","turmeric":"Turmeric","garlic":"Garlic",
}

def main():
    db = create_client(SUPABASE_URL, SUPABASE_KEY)
    crops   = {c["name_en"].lower(): c["id"] for c in db.table("crops").select("id,name_en").execute().data}
    markets = {m["name_en"].lower(): m["id"] for m in db.table("markets").select("id,name_en").execute().data}
    log.info(f"Loaded {len(crops)} crops, {len(markets)} markets")

    today = date.today()
    # Try today and last 3 days (in case of holiday)
    for days_back in range(4):
        target = today - timedelta(days=days_back)
        if target.weekday() >= 5:
            continue

        # Try both URL formats
        for url in [
            f"{CBSL_BASE}/price_report_{target.strftime('%Y%m%d')}_e.pdf",
            f"{CBSL_BASE}/price_report_{target.strftime('%Y%m%d')}e.pdf",
        ]:
            try:
                r = requests.get(url, timeout=30,
                    headers={"User-Agent": "Mozilla/5.0 (GoviyaBot/1.0)"})
                if r.status_code != 200 or len(r.content) < 1000:
                    continue

                log.info(f"Downloaded PDF for {target}: {len(r.content)//1024}KB")
                records = parse_pdf(r.content, target, crops, markets)
                if records:
                    saved = save(db, records)
                    log.info(f"✅ Saved {saved} prices for {target}")
                    return
            except Exception as e:
                log.warning(f"Error: {e}")

    log.warning("No PDF found for recent dates")

def parse_pdf(content, price_date, crops, markets):
    records = []
    dambulla_id   = markets.get("dambulla dec")
    peliyagoda_id = markets.get("peliyagoda dec")

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                # Extract reason text
                text = page.extract_text() or ""
                reasons = {}
                for m in re.finditer(
                    r"(?:Price of )([A-Za-z ]+?)\s+(increased|declined|remained)[^.]*?(?:due to|owing to)([^.]+)\.",
                    text, re.IGNORECASE):
                    reasons[m.group(1).strip().lower()] = f"Price {m.group(2)} due to {m.group(3).strip()}."

                for table in (page.extract_tables() or []):
                    for row in table:
                        if not row or not row[0]:
                            continue
                        crop_raw = str(row[0]).strip()
                        skip = ["item","unit","yesterday","today","wholesale","retail",
                                "vegetable","fruit","other","rice","fish"]
                        if any(w in crop_raw.lower() for w in skip) or len(crop_raw) < 2:
                            continue

                        mapped = CROP_MAP.get(crop_raw.lower())
                        if not mapped:
                            continue
                        crop_id = crops.get(mapped.lower())
                        if not crop_id:
                            continue

                        def add(mkt_id, yday_col, today_col):
                            if today_col >= len(row):
                                return
                            try:
                                yday  = float(str(row[yday_col] or "").replace(",","").strip()) if yday_col < len(row) else None
                                today = float(str(row[today_col] or "").replace(",","").strip())
                                if today > 0 and mkt_id:
                                    reason = next((v for k,v in reasons.items() if k in crop_raw.lower()), None)
                                    records.append({
                                        "crop_id": crop_id, "market_id": mkt_id,
                                        "price_date": price_date.isoformat(),
                                        "price_avg": today,
                                        "price_min": min(today,yday) if yday else today,
                                        "price_max": max(today,yday) if yday else today,
                                        "price_yesterday": yday, "source": "CBSL",
                                        "price_reason": reason,
                                    })
                            except (ValueError, TypeError):
                                pass

                        add(peliyagoda_id, 2, 3)  # Pettah
                        add(dambulla_id,   4, 5)  # Dambulla
    except Exception as e:
        log.error(f"Parse error: {e}")
    return records

def save(db, records):
    if not records:
        return 0
    seen, unique = {}, []
    for r in records:
        k = (r["crop_id"], r["market_id"], r["price_date"])
        if k not in seen:
            seen[k] = True
            unique.append(r)
    try:
        resp = db.table("prices").upsert(unique, on_conflict="crop_id,market_id,price_date").execute()
        return len(resp.data) if resp.data else len(unique)
    except Exception as e:
        log.error(f"Save error: {e}")
        return 0

if __name__ == "__main__":
    main()
