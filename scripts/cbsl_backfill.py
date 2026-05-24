#!/usr/bin/env python3
"""
GOVIYA — CBSL Historical Backfill
Scrapes the CBSL listing page to get exact PDF URLs, then downloads and parses them.
"""
import os, re, time, logging, requests, pdfplumber, io
from datetime import date
from bs4 import BeautifulSoup
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cbsl_backfill")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
CBSL_LISTING = "https://www.cbsl.gov.lk/en/statistics/economic-indicators/price-report"
HEADERS = {"User-Agent": "Mozilla/5.0 (GoviyaBot/1.0)"}

START_YEAR  = 2020
START_MONTH = 7

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

def get_existing_dates(db):
    result = db.table("prices").select("price_date").eq("source","CBSL").execute()
    return set(r["price_date"] for r in result.data)

def scrape_pdf_urls_for_month(year, month):
    """Scrape the CBSL listing page for a specific month and return {date_str: url} dict."""
    url = f"{CBSL_LISTING}?field_date_value[value][year]={year}&field_date_value[value][month]={month}"
    pdf_map = {}
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            log.warning(f"  Listing page {year}-{month:02d} returned {r.status_code}")
            return pdf_map
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "pricerpt/price_report_" in href and href.endswith(".pdf"):
                # Extract date from URL filename
                fname = href.split("/")[-1]
                m = re.search(r"price_report_(\d{8})", fname)
                if m:
                    d = m.group(1)
                    date_str = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                    full_url = href if href.startswith("http") else f"https://www.cbsl.gov.lk{href}"
                    pdf_map[date_str] = full_url
    except Exception as e:
        log.warning(f"  Error scraping listing {year}-{month:02d}: {e}")
    return pdf_map

def download_pdf(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            return r.content
    except Exception:
        pass
    return None

def parse_pdf(content, price_date, crops, markets):
    records = []
    dambulla_id   = markets.get("dambulla dec")
    peliyagoda_id = markets.get("peliyagoda dec")
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
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
                            if today_col >= len(row) or not mkt_id:
                                return
                            try:
                                yday  = float(str(row[yday_col] or "").replace(",","").strip()) if yday_col < len(row) else None
                                today = float(str(row[today_col] or "").replace(",","").strip())
                                if today > 0:
                                    reason = next((v for k,v in reasons.items() if k in crop_raw.lower()), None)
                                    records.append({
                                        "crop_id": crop_id, "market_id": mkt_id,
                                        "price_date": price_date,
                                        "price_avg": today,
                                        "price_min": min(today,yday) if yday else today,
                                        "price_max": max(today,yday) if yday else today,
                                        "price_yesterday": yday, "source": "CBSL",
                                        "price_reason": reason,
                                    })
                            except (ValueError, TypeError):
                                pass
                        add(peliyagoda_id, 2, 3)
                        add(dambulla_id,   4, 5)
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

def main():
    db = create_client(SUPABASE_URL, SUPABASE_KEY)
    crops   = {c["name_en"].lower(): c["id"] for c in db.table("crops").select("id,name_en").execute().data}
    markets = {m["name_en"].lower(): m["id"] for m in db.table("markets").select("id,name_en").execute().data}
    log.info(f"Loaded {len(crops)} crops, {len(markets)} markets")

    existing = get_existing_dates(db)
    log.info(f"Skipping {len(existing)} dates already in DB")

    today = date.today()
    total_saved = 0
    total_pdfs  = 0

    year, month = START_YEAR, START_MONTH
    while (year, month) <= (today.year, today.month):
        log.info(f"--- Scraping {year}-{month:02d} ---")
        pdf_map = scrape_pdf_urls_for_month(year, month)
        log.info(f"  Found {len(pdf_map)} PDFs listed for {year}-{month:02d}")

        for date_str, pdf_url in sorted(pdf_map.items()):
            if date_str in existing:
                continue
            pdf = download_pdf(pdf_url)
            if not pdf:
                log.info(f"  {date_str} — download failed: {pdf_url.split('/')[-1]}")
                continue
            records = parse_pdf(pdf, date_str, crops, markets)
            if records:
                saved = save(db, records)
                total_saved += saved
                total_pdfs  += 1
                log.info(f"  ✅ {date_str} — {saved} prices (total: {total_saved})")
            else:
                log.info(f"  {date_str} — PDF found, no prices parsed")
            time.sleep(0.5)

        # next month
        if month == 12:
            year += 1
            month = 1
        else:
