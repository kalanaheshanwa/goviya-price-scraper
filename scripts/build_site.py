#!/usr/bin/env python3
"""Build the Goviya static website from data/cbsl/*.json into _site/.

Sinhala pages live at the site root, English pages under /en/.
No frameworks: plain HTML + a little CSS, so pages stay tiny on slow phones.
"""
import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "cbsl"
SITE = ROOT / "_site"
CHART_DAYS = 30

# item name as printed by CBSL (lower-case) -> (Sinhala name, emoji)
ITEMS = {
    "beans": ("බෝංචි", "🫘"), "carrot": ("කැරට්", "🥕"), "cabbage": ("ගෝවා", "🥬"),
    "tomato": ("තක්කාලි", "🍅"), "brinjal": ("වම්බටු", "🍆"), "pumpkin": ("වට්ටක්කා", "🎃"),
    "snake gourd": ("පතෝල", "🥒"), "green chilli": ("අමු මිරිස්", "🌶️"), "lime": ("දෙහි", "🍋"),
    "red onion (local)": ("රතු ලූනු (දේශීය)", "🧅"), "red onion (imp)": ("රතු ලූනු (ආනයනික)", "🧅"),
    "big onion (local)": ("ලොකු ලූනු (දේශීය)", "🧅"), "big onion (imp)": ("ලොකු ලූනු (ආනයනික)", "🧅"),
    "potato (local)": ("අර්තාපල් (දේශීය)", "🥔"), "potato (imp)": ("අර්තාපල් (ආනයනික)", "🥔"),
    "dried chilli (imp)": ("වියළි මිරිස් (ආනයනික)", "🌶️"), "coconut (avg.)": ("පොල්", "🥥"),
    "coconut oil": ("පොල්තෙල්", "🫙"), "red dhal": ("රතු පරිප්පු", "🫘"),
    "sugar (white)": ("සුදු සීනි", "🧂"), "egg (white)": ("බිත්තර (සුදු)", "🥚"),
    "katta (imp)": ("කට්ටා කරවල (ආනයනික)", "🐟"), "sprat (imp)": ("හාල්මැස්සන් (ආනයනික)", "🐟"),
    "banana (sour)": ("ඇඹුල් කෙසෙල්", "🍌"), "papaw": ("පැපොල්", "🥭"), "pineapple": ("අන්නාසි", "🍍"),
    "apple (imp)": ("ඇපල් (ආනයනික)", "🍎"), "orange (imp)": ("දොඩම් (ආනයනික)", "🍊"),
    "samba": ("සම්බා", "🍚"), "nadu": ("නාඩු", "🍚"), "kekulu (white)": ("සුදු කැකුළු", "🍚"),
    "kekulu (red)": ("රතු කැකුළු", "🍚"), "ponni samba (imp)": ("පොන්නි සම්බා (ආනයනික)", "🍚"),
    "nadu (imp)": ("නාඩු (ආනයනික)", "🍚"), "kekulu (white) (imp)": ("සුදු කැකුළු (ආනයනික)", "🍚"),
    "kelawalla": ("කෙලවල්ලා", "🐟"), "thalapath": ("තලපත්", "🐟"), "balaya": ("බලයා", "🐟"),
    "paraw": ("පරාව්", "🐟"), "salaya": ("සාලයා", "🐟"), "hurulla": ("හුරුල්ලා", "🐟"),
    "linna": ("ලින්නා", "🐟"),
}
# market key -> (English, Sinhala)
MARKETS = {
    "w_pettah": ("Pettah wholesale", "පිටකොටුව තොග"),
    "w_dambulla": ("Dambulla wholesale", "දඹුල්ල තොග"),
    "r_pettah": ("Pettah retail", "පිටකොටුව සිල්ලර"),
    "r_dambulla": ("Dambulla retail", "දඹුල්ල සිල්ලර"),
    "r_narahenpita": ("Narahenpita retail", "නාරාහේන්පිට සිල්ලර"),
    "w_marandagahamula": ("Marandagahamula wholesale", "මරඳගහමුල තොග"),
    "w_peliyagoda": ("Peliyagoda wholesale", "පෑලියගොඩ තොග"),
    "w_negombo": ("Negombo wholesale", "මීගමුව තොග"),
    "r_negombo": ("Negombo retail", "මීගමුව සිල්ලර"),
}
# The five tabs on the home page; rice and fish use their own markets in some columns.
TABS = ["w_pettah", "w_dambulla", "r_pettah", "r_dambulla", "r_narahenpita"]
TAB_COLS = {
    "default": TABS,
    "rice": ["w_pettah", "w_marandagahamula", "r_pettah", "r_dambulla", "r_narahenpita"],
    "fish": ["w_peliyagoda", "w_negombo", None, "r_negombo", "r_narahenpita"],
}
SECTIONS = [("vegetables", "Vegetables", "එළවළු"), ("other", "Other food", "වෙනත් ආහාර"),
            ("fruits", "Fruits", "පලතුරු"), ("rice", "Rice", "සහල්"), ("fish", "Fish", "මාළු")]
UNITS_SI = {"kg": "කි.ග්‍රෑ.", "Nut": "ගෙඩිය", "Ltr": "ලීටරය", "Each": "එකක්"}
DAYS_SI = ["සඳුදා", "අඟහරුවාදා", "බදාදා", "බ්‍රහස්පතින්දා", "සිකුරාදා", "සෙනසුරාදා", "ඉරිදා"]
MONTHS_SI = ["ජනවාරි", "පෙබරවාරි", "මාර්තු", "අප්‍රේල්", "මැයි", "ජූනි", "ජූලි", "අගෝස්තු",
             "සැප්තැම්බර්", "ඔක්තෝබර්", "නොවැම්බර්", "දෙසැම්බර්"]
T = {
    "en": dict(site="Goviya", tag="Daily market prices in Sri Lanka", prices_for="Prices for",
               source="Source: Central Bank of Sri Lanka daily price report", item="Item", today="Price (Rs.)",
               change="Change", yday="Previous day", market="Market", movers="Biggest changes today",
               up="Up", down="Down", chart="Price over the last {n} days (Rs.)", low="Lowest", high="Highest",
               share="Share on WhatsApp", about="About", home="Home", other_lang="සිංහල", all_markets="Price in each market",
               no_data="No price reported", old="These are the latest prices available. Newer prices have not been published yet.",
               per="per", back="← All prices", same="No change",
               about_body="<p>Goviya shows daily wholesale and retail prices of vegetables, fruits, rice, fish and other food in Sri Lanka's main markets, so farmers, traders and buyers can see a fair price at a glance.</p><p>Prices come from the daily price report published by the Central Bank of Sri Lanka on working days. The site checks for a new report several times a day. Each page shows the date the prices are for.</p><p>Prices are a guide only. Actual prices change through the day and by quality.</p>"),
    "si": dict(site="ගොවියා", tag="ශ්‍රී ලංකාවේ දෛනික වෙළඳපොළ මිල", prices_for="මිල ගණන්:",
               source="මූලාශ්‍රය: ශ්‍රී ලංකා මහ බැංකුවේ දෛනික මිල වාර්තාව", item="භාණ්ඩය", today="මිල (රු.)",
               change="වෙනස", yday="පෙර දිනය", market="වෙළඳපොළ", movers="අද වැඩිම මිල වෙනස්වීම්",
               up="ඉහළට", down="පහළට", chart="පසුගිය දින {n} මිල (රු.)", low="අඩුම", high="වැඩිම",
               share="WhatsApp එකෙන් යවන්න", about="අප ගැන", home="මුල් පිටුව", other_lang="English", all_markets="එක් එක් වෙළඳපොළේ මිල",
               no_data="මිලක් වාර්තා වී නැත", old="මේවා දැනට ඇති අලුත්ම මිල ගණන්ය. ඊට පසු මිල තවම ප්‍රකාශයට පත් කර නැත.",
               per="එක්", back="← සියලු මිල", same="වෙනසක් නැත",
               about_body="<p>ගොවියා වෙබ් අඩවිය ශ්‍රී ලංකාවේ ප්‍රධාන වෙළඳපොළවල එළවළු, පලතුරු, සහල්, මාළු සහ වෙනත් ආහාරවල දෛනික තොග සහ සිල්ලර මිල පෙන්වයි. ගොවීන්ට, වෙළෙන්දන්ට සහ පාරිභෝගිකයන්ට සාධාරණ මිල ඉක්මනින් දැනගත හැක.</p><p>මිල ගණන් ශ්‍රී ලංකා මහ බැංකුව වැඩ කරන දිනවල ප්‍රකාශ කරන දෛනික මිල වාර්තාවෙන් ලබා ගනී. අලුත් වාර්තාවක් තිබේදැයි දිනකට කිහිප වතාවක් පරීක්ෂා කෙරේ. සෑම පිටුවකම මිල අදාළ දිනය පෙන්වයි.</p><p>මිල ගණන් මඟ පෙන්වීමක් පමණි. සැබෑ මිල දවස තුළ සහ ගුණාත්මකභාවය අනුව වෙනස් වේ.</p>"),
}
CSS = """
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Noto Sans Sinhala","Iskoola Pota",sans-serif;background:#f4f7f2;color:#1b2a1f;line-height:1.45}
a{color:#1f6f3d;text-decoration:none}header{background:#1f6f3d;color:#fff;padding:12px 16px}
header .row{display:flex;justify-content:space-between;align-items:center;max-width:760px;margin:auto}
header a{color:#fff}header .logo{font-size:1.35rem;font-weight:700}header small{display:block;opacity:.85;font-size:.8rem}
.lang{border:1px solid #ffffff88;border-radius:16px;padding:4px 12px;font-size:.85rem}
main{max-width:760px;margin:auto;padding:12px 12px 40px}
.date{background:#fff;border-left:5px solid #f2a900;border-radius:8px;padding:10px 12px;margin:0 0 12px}
.date b{font-size:1.05rem}.date small{display:block;color:#5a6b5e}
.note{background:#fff6dd;border-radius:8px;padding:8px 12px;margin:0 0 12px;font-size:.9rem}
.tabs{display:flex;gap:6px;overflow-x:auto;padding-bottom:6px;margin-bottom:8px}
.tabs a{white-space:nowrap;background:#fff;border:1px solid #cfd9d0;border-radius:18px;padding:7px 12px;font-size:.9rem;color:#1b2a1f}
.tabs a.on{background:#1f6f3d;color:#fff;border-color:#1f6f3d}
h1{font-size:1.3rem;margin:8px 0}h2{font-size:1.05rem;margin:18px 0 6px;color:#1f6f3d}h2 small{color:#5a6b5e;font-weight:400}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden}
td,th{padding:9px 10px;border-bottom:1px solid #edf1ec;text-align:left;font-size:.95rem}
th{font-size:.78rem;color:#5a6b5e;font-weight:600}td.n,th.n{text-align:right;white-space:nowrap}
td.p{font-weight:700;font-size:1.02rem}.u{color:#c0392b}.d{color:#1e8449}.z{color:#8a978c}
td small{color:#7c8a7f;font-weight:400}tr:last-child td{border-bottom:0}
.movers{display:grid;grid-template-columns:1fr 1fr;gap:8px}.movers div{background:#fff;border-radius:8px;padding:8px 10px;font-size:.9rem}
.movers b{display:block;margin-bottom:4px}.movers p{margin:3px 0}
.card{background:#fff;border-radius:8px;padding:10px 12px;margin-bottom:12px}
.btn{display:inline-block;background:#25d366;color:#fff;border-radius:22px;padding:10px 18px;font-weight:600;margin:12px 0}
.legend span{display:inline-block;margin-right:12px;font-size:.82rem}.legend i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:4px}
footer{max-width:760px;margin:auto;padding:0 12px 30px;color:#5a6b5e;font-size:.82rem}
@media(max-width:420px){td,th{padding:8px 6px}.movers{grid-template-columns:1fr}}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def key(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def item_name(name, lang):
    return ITEMS.get(key(name), (name, ""))[0] if lang == "si" else name


def emoji(name):
    return ITEMS.get(key(name), ("", "•"))[1]


def unit(u, lang):
    return UNITS_SI.get(u, u) if lang == "si" else u


def market(k, lang):
    return MARKETS.get(k, (k, k))[1 if lang == "si" else 0]


def fmt(v):
    if v is None:
        return "–"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def fmt_date(d, lang):
    if lang == "si":
        return f"{d.year} {MONTHS_SI[d.month - 1]} {d.day}, {DAYS_SI[d.weekday()]}"
    return d.strftime("%A, %-d %B %Y")


def change_cell(y, t, lang):
    if y is None or t is None:
        return '<td class="n z">–</td>'
    diff = t - y
    if abs(diff) < 0.005:
        return '<td class="n z">0</td>'
    cls, arrow = ("u", "▲") if diff > 0 else ("d", "▼")
    pct = f" <small>({abs(diff) / y * 100:.0f}%)</small>" if y else ""
    return f'<td class="n {cls}">{arrow} {fmt(abs(diff))}{pct}</td>'


def page(lang, depth, path_other, title, body, desc=""):
    """Wrap body in the shared layout. depth = folders below this language's root."""
    t = T[lang]
    up = "../" * depth
    root_other = up + ("en/" if lang == "si" else "../")
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<meta name="description" content="{esc(desc or t['tag'])}"><style>{CSS}</style></head><body>
<header><div class="row"><a class="logo" href="{up or './'}">🌾 {t['site']}<small>{t['tag']}</small></a>
<a class="lang" href="{root_other}{path_other}">{t['other_lang']}</a></div></header>
<main>{body}</main>
<footer><p>{t['source']}.</p><p><a href="{up or './'}">{t['home']}</a> · <a href="{up}about/">{t['about']}</a></p></footer>
</body></html>"""


def write(rel, text):
    p = SITE / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def chart(series, dates, lang):
    """series: {market_key: [value or None per date]} -> inline SVG line chart."""
    vals = [v for s in series.values() for v in s if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    W, H, L, R, TP, B = 340, 170, 44, 8, 10, 22
    n = len(dates)
    x = lambda i: L + (W - L - R) * (i / max(n - 1, 1))
    y = lambda v: TP + (H - TP - B) * (1 - (v - lo) / (hi - lo))
    colors = ["#1f6f3d", "#f2a900", "#2e6fbf"]
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="price chart">']
    for frac in (0, .5, 1):
        v = lo + (hi - lo) * frac
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e3e9e2"/>'
                   f'<text x="{L - 5}" y="{y(v) + 4:.1f}" font-size="10" text-anchor="end" fill="#5a6b5e">{fmt(round(v))}</text>')
    legend = []
    for ci, (mk, s) in enumerate(series.items()):
        pts = [(x(i), y(v)) for i, v in enumerate(s) if v is not None]
        if len(pts) < 2:
            continue
        c = colors[ci % 3]
        out.append(f'<polyline fill="none" stroke="{c}" stroke-width="2" points="' +
                   " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + '"/>')
        out.append(f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3" fill="{c}"/>')
        legend.append(f'<span><i style="background:{c}"></i>{esc(market(mk, lang))}</span>')
    short = lambda d: f"{d.month}/{d.day}"
    out.append(f'<text x="{L}" y="{H - 6}" font-size="10" fill="#5a6b5e">{short(dates[0])}</text>'
               f'<text x="{W - R}" y="{H - 6}" font-size="10" text-anchor="end" fill="#5a6b5e">{short(dates[-1])}</text></svg>')
    return "".join(out) + f'<div class="legend">{"".join(legend)}</div>'


def build():
    files = sorted(DATA.glob("*.json"))
    if not files:
        raise SystemExit("no data files in data/cbsl - run scripts/cbsl_fetch.py first")
    days = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    latest = days[-1]
    date = dt.date.fromisoformat(latest["date"])
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()
    stale = (today - date).days > 4
    hist = days[-CHART_DAYS:]
    hist_dates = [dt.date.fromisoformat(d["date"]) for d in hist]
    hist_idx = [{key(it["name"]): it for it in d["items"]} for d in hist]

    if SITE.exists():
        shutil.rmtree(SITE)
    for lang in ("si", "en"):
        t = T[lang]
        base = "" if lang == "si" else "en/"
        datebox = (f'<p class="date"><b>{t["prices_for"]} {fmt_date(date, lang)}</b><small>{t["source"]}</small></p>'
                   + (f'<p class="note">{t["old"]}</p>' if stale else ""))

        # ---- home page, one per market tab ----
        for ti, tab in enumerate(TABS):
            rel = "" if ti == 0 else f"m/{tab}/"
            depth = 0 if ti == 0 else 2
            up = "../" * depth
            tabs = "".join(f'<a class="{"on" if k == tab else ""}" href="{up}{"" if i == 0 else f"m/{k}/"}">{esc(market(k, lang))}</a>'
                           for i, k in enumerate(TABS))
            body = [datebox, f'<nav class="tabs">{tabs}</nav>']
            if ti == 0:  # biggest movers across the two wholesale markets
                moves = []
                for it in latest["items"]:
                    for mk in ("w_pettah", "w_dambulla"):
                        y, tv = it["p"].get(mk, [None, None])
                        if y and tv and y != tv:
                            moves.append(((tv - y) / y * 100, it, mk, tv))
                if moves:
                    def rows(sel, cls, arrow):
                        return "".join(
                            f'<p><a href="{up}crop/{slug(it["name"])}/">{emoji(it["name"])} {esc(item_name(it["name"], lang))}</a> '
                            f'<span class="{cls}">{arrow} {abs(pc):.0f}%</span><br><small>{esc(market(mk, lang))} · {fmt(tv)}</small></p>'
                            for pc, it, mk, tv in sel)
                    ups = sorted([m for m in moves if m[0] > 0], key=lambda m: -m[0])[:3]
                    downs = sorted([m for m in moves if m[0] < 0], key=lambda m: m[0])[:3]
                    body.append(f'<h2>{t["movers"]}</h2><div class="movers"><div><b class="u">▲ {t["up"]}</b>{rows(ups, "u", "▲") or "–"}</div>'
                                f'<div><b class="d">▼ {t["down"]}</b>{rows(downs, "d", "▼") or "–"}</div></div>')
            for sec, sec_en, sec_si in SECTIONS:
                mk = TAB_COLS.get(sec, TAB_COLS["default"])[ti]
                rows = []
                for it in latest["items"]:
                    if it["section"] != sec or not mk or mk not in it["p"]:
                        continue
                    y, tv = it["p"][mk]
                    if tv is None:
                        continue
                    rows.append(f'<tr><td><a href="{up}crop/{slug(it["name"])}/">{emoji(it["name"])} {esc(item_name(it["name"], lang))}</a> '
                                f'<small>/{esc(unit(it["unit"], lang))}</small></td><td class="n p">{fmt(tv)}</td>{change_cell(y, tv, lang)}</tr>')
                if not rows:
                    continue
                sub = f' <small>· {esc(market(mk, lang))}</small>' if mk != tab else ""
                body.append(f'<h2>{sec_si if lang == "si" else sec_en}{sub}</h2><table><tr><th>{t["item"]}</th>'
                            f'<th class="n">{t["today"]}</th><th class="n">{t["change"]}</th></tr>{"".join(rows)}</table>')
            title = f'{t["site"]} – {market(tab, lang)} – {fmt_date(date, lang)}'
            write(base + rel + "index.html", page(lang, depth, rel, title, "".join(body)))

        # ---- one page per item ----
        for it in latest["items"]:
            s = slug(it["name"])
            nm = item_name(it["name"], lang)
            rows = "".join(
                f'<tr><td>{esc(market(mk, lang))}</td><td class="n p">{fmt(tv)}</td><td class="n">{fmt(y)}</td>{change_cell(y, tv, lang)}</tr>'
                for mk, (y, tv) in it["p"].items())
            series = {}
            for mk in it["p"]:
                if mk.startswith("w_") or len(series) == 0:
                    series[mk] = [(h.get(key(it["name"]), {}).get("p", {}).get(mk) or [None, None])[1] for h in hist_idx]
            series = dict(list(series.items())[:3])
            svg = chart(series, hist_dates, lang)
            stats = ""
            for mk, sv in series.items():
                v = [x for x in sv if x is not None]
                if len(v) >= 2:
                    stats += f'<p>{esc(market(mk, lang))}: {t["low"]} {fmt(min(v))} · {t["high"]} {fmt(max(v))}</p>'
            first = next(iter(it["p"].items()))
            share = f'{emoji(it["name"])} {nm} – {market(first[0], lang)}: Rs. {fmt(first[1][1])}/{unit(it["unit"], lang)} ({date.isoformat()}) – {t["site"]}'
            body = (f'<p><a href="../../">{t["back"]}</a></p><h1>{emoji(it["name"])} {esc(nm)} <small>/{esc(unit(it["unit"], lang))}</small></h1>{datebox}'
                    f'<h2>{t["all_markets"]}</h2><table><tr><th>{t["market"]}</th><th class="n">{t["today"]}</th>'
                    f'<th class="n">{t["yday"]}</th><th class="n">{t["change"]}</th></tr>{rows}</table>'
                    + (f'<h2>{t["chart"].format(n=len(hist))}</h2><div class="card">{svg}{stats}</div>' if svg else "")
                    + f'<a class="btn" href="https://wa.me/?text={quote(share)}">{t["share"]}</a>')
            title = f'{nm} {t["prices_for"]} {date.isoformat()} – {t["site"]}'
            write(f"{base}crop/{s}/index.html", page(lang, 2, f"crop/{s}/", title, body, f"{nm}: {t['tag']}"))

        # ---- about ----
        write(f"{base}about/index.html",
              page(lang, 1, "about/", f'{t["about"]} – {t["site"]}', f'<h1>{t["about"]}</h1><div class="card">{t["about_body"]}</div>'))

    (SITE / ".nojekyll").write_text("")
    print(f"built site for {latest['date']}: {sum(1 for _ in SITE.rglob('*.html'))} pages")


if __name__ == "__main__":
    build()
