#!/usr/bin/env python3
"""Download the Central Bank of Sri Lanka (CBSL) daily price report PDFs and
save each day's prices as a JSON file in data/cbsl/YYYY-MM-DD.json.

Run:  python scripts/cbsl_fetch.py          (checks the last DAYS days, default 10)
      DAYS=75 python scripts/cbsl_fetch.py  (first run / backfill)
      python scripts/cbsl_fetch.py file.pdf (parse one local PDF and print it)
"""
import datetime as dt
import io
import json
import os
import re
import statistics
import sys
from pathlib import Path

import pdfplumber
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cbsl"
BASE = "https://www.cbsl.gov.lk/sites/default/files/cbslweb_documents/statistics/pricerpt/"
NAMES = ["price_report_{d}_e.pdf", "price_report_{d}_e_0.pdf", "price_report_{d}e.pdf"]
UA = {"User-Agent": "Mozilla/5.0 (compatible; GoviyaPriceBot/1.0)"}

# Which market each of the 5 column pairs means, per section of the report.
COLS = {
    "default": ["w_pettah", "w_dambulla", "r_pettah", "r_dambulla", "r_narahenpita"],
    "rice": ["w_pettah", "w_marandagahamula", "r_pettah", "r_dambulla", "r_narahenpita"],
    "fish": ["w_peliyagoda", "w_negombo", None, "r_negombo", "r_narahenpita"],
}
SECTIONS = {"VEGETABLES": "vegetables", "OTHER": "other", "FRUITS": "fruits", "RICE": "rice", "FISH": "fish"}
NUM = re.compile(r"^\d[\d,]*(\.\d+)?$")
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


def group_lines(words, tol=3):
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in lines]


def parse_pdf(fileobj):
    """Return {"date": "YYYY-MM-DD", "items": [...]} from a CBSL price report PDF."""
    with pdfplumber.open(fileobj) as pdf:
        words = None
        for page in pdf.pages:
            ws = page.extract_words(x_tolerance=1.5, y_tolerance=2)
            if sum(w["text"] in ("Yesterday", "Today") for w in ws) >= 8:
                words = ws
                break
    if words is None:
        raise ValueError("price table page not found")
    lines = group_lines(words)

    cols, date = None, None
    for l in lines:
        heads = [w for w in l if w["text"] in ("Yesterday", "Today")]
        if len(heads) >= 8 and cols is None:
            cols = [(w["x0"] + w["x1"]) / 2 for w in heads]
        text = " ".join(w["text"] for w in l)
        if date is None and "Commodit" in text:
            m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
            if m and m.group(2).lower() in MONTHS:
                date = dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    if not cols or len(cols) != 10:
        raise ValueError(f"expected 10 price columns, found {len(cols or [])}")
    if date is None:  # fallback: first "10 November 2026"-style date anywhere on the page
        for l in lines:
            m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", " ".join(w["text"] for w in l))
            if m and m.group(2).lower() in MONTHS:
                date = dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
                break
    if date is None:
        raise ValueError("report date not found")
    left_edge = cols[0] - 30

    items, section = [], None
    for l in lines:
        joined = "".join(w["text"] for w in l).upper()
        if joined in SECTIONS:
            section = SECTIONS[joined]
            continue
        if section is None:
            continue
        left = [w for w in l if (w["x0"] + w["x1"]) / 2 < left_edge]
        unit_i = next((i for i, w in enumerate(left) if w["text"].startswith("Rs")), None)
        if unit_i is None or unit_i == 0:
            continue
        name = " ".join(w["text"] for w in left[:unit_i]).strip()
        unit = "".join(w["text"] for w in left[unit_i:]).replace("Rs.", "").strip("/ .") or "kg"
        vals = [None] * 10
        for w in l:
            c = (w["x0"] + w["x1"]) / 2
            if c < left_edge or not NUM.match(w["text"]):
                continue
            i = min(range(10), key=lambda k: abs(cols[k] - c))
            vals[i] = float(w["text"].replace(",", ""))
        keys = COLS.get(section, COLS["default"])
        prices = {}
        for k, key in enumerate(keys):
            y, t = vals[2 * k], vals[2 * k + 1]
            if key and (y is not None or t is not None):
                prices[key] = [y, t]
        if prices:
            items.append({"name": name, "unit": unit, "section": section, "p": prices})

    # Sanity checks: fail loudly instead of saving nonsense.
    veg = [p[1] for it in items if it["section"] == "vegetables" for p in it["p"].values() if p[1]]
    if len(items) < 25 or len(veg) < 15 or not 20 <= statistics.median(veg) <= 5000:
        raise ValueError(f"parsed data looks wrong: {len(items)} items, {len(veg)} vegetable prices")
    return {"date": date.isoformat(), "source": "CBSL", "items": items}


def fetch(day):
    d = day.strftime("%Y%m%d")
    for pat in NAMES:
        url = BASE + pat.format(d=d)
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return url, r.content
    return None, None


def main():
    if len(sys.argv) > 1:
        print(json.dumps(parse_pdf(sys.argv[1]), indent=1))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    days = int(os.environ.get("DAYS", "10"))
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()  # Sri Lanka date
    new, failed = 0, 0
    for n in range(days):
        day = today - dt.timedelta(days=n)
        if day.weekday() >= 5 or (OUT / f"{day}.json").exists():
            continue
        try:
            url, content = fetch(day)
        except requests.RequestException as e:
            print(f"{day}: download error {e}")
            failed += 1
            continue
        if not content:
            print(f"{day}: no report published")
            continue
        try:
            data = parse_pdf(io.BytesIO(content))
        except Exception as e:  # noqa: BLE001
            print(f"{day}: PARSE FAILED - {e}")
            failed += 1
            continue
        data["url"] = url
        (OUT / f"{data['date']}.json").write_text(json.dumps(data, ensure_ascii=False, indent=0))
        print(f"{day}: saved {len(data['items'])} items (report date {data['date']})")
        new += 1
    have = sorted(p.stem for p in OUT.glob("*.json"))
    print(f"new files: {new}, failed: {failed}, latest saved: {have[-1] if have else 'none'}")
    if failed or not have:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
