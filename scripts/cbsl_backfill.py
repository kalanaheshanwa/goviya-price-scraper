#!/usr/bin/env python3
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

def scrape_all_pdf_urls():
    pdf_map = {}
    page = 0
    while True:
        url = f"{CBSL_LISTING}?page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                log.warning(f"  Page {page} returned {r.status_code}, stopping")
                break
            soup = BeautifulSoup(r.text, "html.parser")
            found_on_page = 0
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "pricerpt/price_report_" in href and href.endswith(".pdf"):
                    fname = href.split("/")[-1]
                    m = re.search(r"price_report_(\d{8})", fname)
                    if m:
                        d = m.group(1)
                        date_str = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                        full_url = href if href.startswith("http") else f"https://www.cbsl.gov.lk{href}"
                        pdf_map[date_str] = full_url
                        found_on_page += 1
            log.info(f"  Page {page}: {found_on_page} PDFs (total so far: {len(pdf_map)})")
            if found_on_page == 0:
                log.info("  No PDFs found on page, stopping")
                break
            oldest = min(pdf_map.keys())
            if oldest < "2020-07-28":
                log.info(f"  Reached {oldest}, old enough — stopping pagination")
                break
            page += 1
            time.sleep(0.3)
        except Exception as e:
            log.warning(f"  Page {page} error: {e}")
            break
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
                        skip = ["item","unit","yesterday","today","wholesale",
                                "retail","vegetable","fruit","other","rice","fish"]
                        if any(w in crop_raw.lower() for w in skip) or len(crop_raw) < 2:
                            continue
                        mapped = CROP_MAP.get(crop_raw.lower())
                        if not mapped:
                            continue
                        crop_id = crops.get(mapped.lower())
                        if not crop_id:
                            continue
                        reason = next((v for k,v in reasons.items() if k in crop_raw.lower()), None)
                        if peliyagoda_id and len(row) > 3:
                            try:
                                yday  = float(str(row[2] or "").replace(",","").strip()) if row[2] else None
                                today = float(str(row[3] or "").replace(",","").strip())
                                if today > 0:
                                    records.append({
                                        "crop_id": crop_id, "market_id": peliyagoda_id,
                                        "price_date": price_date, "price_avg": today,
                                        "price_min": min(today,yday) if yday else today,
                                        "price_max": max(today,yday) if yday else today,
                                        "price_yesterday": yday, "source": "CBSL",
                                        "price_reason": reason,
                                    })
                            except (ValueError, TypeError):
                                pass
                        if dambulla_id and len(row) > 5:
                            try:
                                yday  = float(str(row[4] or "").replace(",","").strip()) if row[4] else None
                                today = float(str(row[5] or "").replace(",","").strip())
                                if today > 0:
                                    records.append({
                                        "crop_id": crop_id, "market_id": dambulla_id,
                                        "price_date": price_date, "price_avg": today,
                                        "price_min": min(today,yday) if yday else today,
                                        "price_max": max(today,yday) if yday else today,
                                        "price_yesterday": yday, "source": "CBSL",
                                        "price_reason": reason,
                                    })
                            except (ValueError, TypeError):
                                pass
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

    log.info("Scraping CBSL listing pages to build PDF URL map...")
    all_pdfs = scrape_all_pdf_urls()
    log.info(f"Total PDFs found on website: {len(all_pdfs)}")

    needed = {d: u for d, u in all_pdfs.items() if d >= "2020-07-29" and d not in existing}
    log.info(f"PDFs to download and parse: {len(needed)}")

    total_saved, total_pdfs = 0, 0
    for date_str, pdf_url in sorted(needed.items()):
        pdf = download_pdf(pdf_url)
        if not pdf:
            log.info(f"  {date_str} — download failed")
            continue
        records = parse_pdf(pdf, date_str, crops, markets)
        if records:
            saved = save(db, records)
            total_saved += saved
            total_pdfs  += 1
            log.info(f"  ✅ {date_str} — {saved} prices (total: {total_saved})")
        else:
            log.info(f"  {date_str} — no prices parsed")
        time.sleep(0.5)

    log.info(f"=== DONE === PDFs processed: {total_pdfs} | Prices saved: {total_saved}")

if __name__ == "__main__":
    main()
