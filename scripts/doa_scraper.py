#!/usr/bin/env python3
"""
GOVIYA — DOA InfoHub Daily Scraper
Runs on GitHub Actions every morning at 3:45 AM UTC (9:15 AM Sri Lanka)
Only 9 crops available on DOA InfoHub
"""
import os, time, logging, requests
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("doa")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
DOA_URL      = "https://infohub.doa.gov.lk/wp-admin/admin-ajax.php"

DOA_CROPS = {
    "Beans":        "Beans",
    "Carrot":       "Carrot",
    "Cabbage":      "Cabbage",
    "Tomato":       "Tomato",
    "Brinjal":      "Brinjal",
    "Snake Gourd":  "Snake Gourd",
    "Pumpkin":      "Pumpkin",
    "Green Chilli": "Chilli Green",
    "Lime":         "Lime",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}

def num(s):
    try:
        v = float(str(s).replace(",","").strip())
        return v if v > 0 else None
    except (ValueError, AttributeError):
        return None

def main():
    db = create_client(SUPABASE_URL, SUPABASE_KEY)
    crops   = {c["name_en"].lower(): c["id"] for c in db.table("crops").select("id,name_en").execute().data}
    markets = {m["name_en"].lower(): m["id"] for m in db.table("markets").select("id,name_en").execute().data}
    log.info(f"Loaded {len(crops)} crops, {len(markets)} markets")

    peliyagoda_id = markets.get("peliyagoda dec")
    dambulla_id   = markets.get("dambulla dec")
    total = 0

    for doa_name, db_name in DOA_CROPS.items():
        crop_id = crops.get(db_name.lower())
        if not crop_id:
            log.warning(f"Crop not found: {db_name}")
            continue
        try:
            r = requests.get(
                DOA_URL,
                params={"action": "get_veg_data", "item": doa_name},
                headers={**HEADERS, "Referer": f"https://infohub.doa.gov.lk/vegetable-prices-all/?item={doa_name}"},
                timeout=30,
            )
            if r.status_code != 200:
                log.warning(f"HTTP {r.status_code} for {doa_name}")
                continue

            data = r.json()
            if not data or not isinstance(data, list):
                log.warning(f"No data for {doa_name}")
                continue

            # Only save the most recent 2 days (today + yesterday)
            recent = sorted(data, key=lambda x: x.get("Date",""), reverse=True)[:2]
            records = []

            for row in recent:
                date = (row.get("Date") or "")[:10]
                if not date:
                    continue

                d_today = num(row.get("Dambulla_Today_Wholesale"))
                d_yday  = num(row.get("Dambulla_Yesterday_Wholesale"))
                if d_today and dambulla_id:
                    records.append({
                        "crop_id": crop_id, "market_id": dambulla_id,
                        "price_date": date, "price_avg": d_today,
                        "price_min": min(d_today,d_yday) if d_yday else d_today,
                        "price_max": max(d_today,d_yday) if d_yday else d_today,
                        "price_yesterday": d_yday, "source": "DOA_INFOHUB",
                    })

                p_today = num(row.get("Pettah_Today_Wholesale"))
                p_yday  = num(row.get("Pettah_Yesterday_Wholesale"))
                if p_today and peliyagoda_id:
                    records.append({
                        "crop_id": crop_id, "market_id": peliyagoda_id,
                        "price_date": date, "price_avg": p_today,
                        "price_min": min(p_today,p_yday) if p_yday else p_today,
                        "price_max": max(p_today,p_yday) if p_yday else p_today,
                        "price_yesterday": p_yday, "source": "DOA_INFOHUB",
                    })

            if records:
                resp = db.table("prices").upsert(
                    records, on_conflict="crop_id,market_id,price_date"
                ).execute()
                saved = len(resp.data) if resp.data else len(records)
                total += saved
                log.info(f"  ✓ {doa_name}: saved {saved} records")

        except Exception as e:
            log.error(f"Error for {doa_name}: {e}")

        time.sleep(0.8)

    log.info(f"✅ DOA scraper done. Total saved: {total}")

if __name__ == "__main__":
    main()
