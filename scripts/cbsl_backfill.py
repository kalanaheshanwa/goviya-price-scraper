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

                        # Peliyagoda: columns 2 (yesterday), 3 (today)
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

                        # Dambulla: columns 4 (yesterday), 5 (today)
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
