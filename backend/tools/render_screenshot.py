"""Design rendering of GoldScreen.kt (same structure, colours, texts and rules) fed with REAL engine JSON, captured
with headless Chrome at several phone sizes. It is NOT a capture from an Android device (the APK is built by CI).

    python tools/render_screenshot.py OUT.png W H "caption" decision.json [W H "caption" decision.json ...]
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

ALG = timezone(timedelta(hours=1))
C = dict(bg="#07070A", card="#111014", edge="#3A3018", gold="#D4AF37", goldl="#F3D46B", main="#F4F4F4", dim="#A3A3A8",
         green="#2ECC71", red="#E5484D", wait="#E8B931", grey="#6B6B70", track="#2A2A30")
LRI, PDI = "⁦", "⁩"


def hms(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(ALG).strftime("%H:%M:%S") if s else "—"


def bar(f, color, h=6):
    f = max(0.0, min(1.0, f))
    return f'<div class="track" style="height:{h}px"><div style="width:{f * 100:.0f}%;background:{color};height:100%;border-radius:9px"></div></div>'


def segs(fill, color):
    n = max(0, min(6, int(fill * 6 + 0.5)))
    return '<div class="segs">' + "".join(f'<i style="background:{color if i < n else C["track"]}"></i>' for i in range(6)) + "</div>"


def health(d):
    if d is None or (d["action"] == "UNAVAILABLE" and d.get("quote") is None):
        return "غير متاحة", C["red"]
    if d["mode"] == "DEMO" and d["data_freshness"]["is_fresh"]:
        return "بيانات تجريبية", C["wait"]
    if not d["data_freshness"]["is_fresh"]:
        return "بيانات متأخرة", C["wait"]
    return "بيانات حية", C["green"]


def kv(k, v):
    return f'<div class="kv"><span class="k">{escape(k)}</span><span class="v">{escape(v)}</span></div>'


def level_card(title, color, items, validated, rows):
    h = [f'<div class="panel" style="border-color:{color}99"><div class="lvh"><b style="color:{color}">{title}</b>'
         + ("" if validated else '<span class="tiny dim">قوة تقديرية</span>') + "</div>"]
    if not items:
        h.append('<div class="dim s11">لا مستويات قريبة</div>')
    for z in items[:rows]:
        fill = (z["strength"] / 100) if z.get("strength") is not None else {"قوي": .85, "متوسط": .55, "ضعيف": .25}.get(z["strength_label_ar"], 0)
        lab = str(z["strength"]) if z.get("strength") is not None else z["strength_label_ar"]
        h.append(f'<div class="lvr"><b class="nm" style="color:{color}">{z["name"]}</b><span class="lp">{z["price"]:.2f}</span>'
                 f'<span class="ls"><span class="tiny dim">{lab}</span>{segs(fill, color)}</span></div>')
    return "".join(h) + "</div>"


def screen(d, compact):
    lab, hc = health(d)
    o = []
    o.append(f'<div class="top"><div class="pill" style="border-color:{hc}"><i style="background:{hc}"></i>{lab}</div>'
             f'<div class="ttl"><b>GOLD AI QUANT</b>' + ("" if compact else '<span>الذكاء الاصطناعي للذهب</span>') + '</div>'
             '<div class="gear">⚙</div></div>')  # same Row order as TopBar() in GoldScreen.kt
    t = d.get("market_trend") or {}
    tcol = {"UP": C["green"], "DOWN": C["red"], "SIDEWAYS": C["wait"]}.get(t.get("direction"), C["grey"])
    ch = d.get("quote_change")
    chs = ""
    if ch is not None:
        up = ch >= 0
        pct = d.get("quote_change_pct")
        chs = (f'<div style="color:{C["green"] if up else C["red"]};font-weight:600;font-size:13px">{LRI}{"+" if up else ""}{ch:.2f}'
               + (f' ({"+" if up else ""}{pct:.2f}%)' if pct is not None else "") + f' {"▲" if up else "▼"}{PDI}</div>')
    o.append('<div class="row">'
             f'<div class="panel" style="flex:1.1;text-align:center"><div class="dim s12">XAU/USD</div>'
             f'<div class="price">{(d.get("quote") or 0):.2f}</div>{chs}<div class="dim tiny">آخر تحديث {hms(d.get("quote_timestamp_utc"))}</div></div>'
             f'<div class="panel" style="flex:1"><div class="s13 b">اتجاه السوق</div><div class="trend" style="color:{tcol}">{t.get("label_ar", "—")}</div>'
             f'<div class="kv"><span class="k s11">قوة الاتجاه:</span><b class="s12">{(LRI + str(t["strength"]) + "/100" + PDI) if t.get("strength") is not None else "—"}</b></div>{bar((t.get("strength") or 0) / 100, tcol)}</div>'
             '</div>')
    if d["mode"] == "DEMO":
        o.append('<div class="demo">تجريبي: أسعار اصطناعية — ليست توصيات حقيقية</div>')
    o.append(f'<div class="ask" style="height:{60 if compact else 70}px"><span>ماذا أفعل؟</span><span class="xh">⌖</span></div>')
    a = d["action"]
    title, col, sub = {"BUY": ("شراء", C["green"], "اجتازت محكمة القرار"), "SELL": ("بيع", C["red"], "اجتازت محكمة القرار"),
                       "WAIT": ("انتظار", C["wait"], "لا توجد صفقة مؤهلة الآن"),
                       "UNAVAILABLE": ("غير متاح", C["grey"], "البيانات غير كافية أو متأخرة")}[a]
    dc = [f'<div class="act"><b style="color:{col};font-size:{22 if a == "UNAVAILABLE" else 30}px;white-space:nowrap">{title}</b><span class="dim s11">{sub}</span></div>']
    if a in ("BUY", "SELL"):
        dc += [kv("الدخول", f'{LRI}{d["entry_min"]:.2f} – {d["entry_max"]:.2f}{PDI}'), kv("وقف الخسارة", f'{d["stop_loss"]:.2f}'),
               kv("الهدف", f'{d["tp1"]:.2f}'), kv("المدة المتوقعة", f'حتى {d["horizon_minutes"] // 60} ساعات')]
    elif a == "WAIT":
        better = d.get("wait_for_price") or d.get("alternative_entry_price")
        if better:
            dc.append(kv("سعر إعادة التقييم", f"{better:.2f}"))
        for r in d.get("reevaluate_ar", [])[:1 if compact else 2]:
            dc.append(f'<div class="s11 clamp2">• {escape(r)}</div>')
    else:
        dc.append(f'<div class="s12">{escape(d.get("warning_ar") or "")}</div>')
    pc = ['<div class="b s13">الاحتمالات</div>']
    shown = d["mode"] == "LIVE" and d.get("probability_target_before_stop") is not None and d["calibration_sample_count"] >= 300
    if shown:
        for lab2, p, c2 in (("الوصول للهدف", d["probability_target_before_stop"], C["green"]),
                            ("وقف الخسارة", d["probability_stop_before_target"], C["red"]),
                            ("عدم الوصول", d["probability_neither"], "#B8BCC4")):
            pc.append(f'<div class="kv"><span class="k s11">{lab2}</span><b style="color:{c2};font-size:15px">{round(p * 100)}%</b></div>{bar(p, c2, 5)}')
        pc.append(f'<div class="dim" style="font-size:9px">معايرة خارج العينة: {d["calibration_sample_count"]} حالة</div>')
    else:
        pc.append(f'<div style="color:{C["wait"]};font-weight:bold;font-size:15px">غير متاحة</div>'
                  f'<div class="dim s11">{"لا تُعرض في الوضع التجريبي" if d["mode"] == "DEMO" else "لم تجتز اختبارات المعايرة بعد"}</div>')
    o.append(f'<div class="row"><div class="panel" style="flex:1">{"".join(pc)}</div>'
             f'<div class="panel" style="flex:1.45;border-color:{col}">{"".join(dc)}</div></div>')
    ols = {x["horizon"]: x for x in d.get("outlooks", [])}  # HorizonsRow() in GoldScreen.kt: hours / week / month
    if ols:
        cells = []
        for hz in ("HOURS", "WEEK", "MONTH"):
            x = ols.get(hz)
            if not x:
                continue
            oc = {"BUY": C["green"], "SELL": C["red"], "UNAVAILABLE": C["grey"]}.get(x["action"], C["wait"])
            if x.get("hit_rate") is not None:
                st = f'{LRI}{round(x["hit_rate"] * 100)}% / {x["samples"]}{PDI}'
            elif x["validated"]:
                st = "محقَّق"
            else:
                st = "لا بيانات" if x["action"] == "UNAVAILABLE" else "غير محقَّق"
            cells.append(f'<div class="panel hz" style="flex:1;border-color:{oc}b3"><span class="dim s11">{x["label_ar"]}</span>'
                         f'<b class="clamp2" style="color:{oc};font-size:14px;font-weight:900">{escape(x["stance_ar"])}</b>'
                         f'<span class="tiny" style="color:{C["green"] if x["validated"] else C["dim"]}">{st}</span></div>')
        o.append('<div class="row">' + "".join(cells) + "</div>")
    lv = d.get("levels")
    if lv:
        rows = 2 if compact else 3
        o.append('<div class="row">' + level_card("الدعوم", C["green"], lv["supports"], lv["validated"], rows)
                 + level_card("المقاومات", C["red"], lv["resistances"], lv["validated"], rows) + "</div>")
    o.append(f'<div class="panel rsn"><div style="flex:1"><b style="color:{C["gold"]};font-size:14px">سبب القرار:</b>'
             f'<div class="s13 clamp3">{escape(d.get("reason_short_ar") or d.get("warning_ar") or "")}</div></div>'
             '<div class="det">التفاصيل ⌄</div></div>')
    o.append('<div class="dim center" style="font-size:10px">للتداول الورقي والبحث فقط. لا تنفيذ للصفقات ولا ضمان لأي نتيجة.</div>')
    return "".join(o)


CSS = f"""*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#1d1d22;font-family:'DejaVu Sans',sans-serif;padding:16px}}
.wrap{{display:flex;gap:22px;align-items:flex-start;justify-content:center;direction:ltr}}
.col{{display:flex;flex-direction:column;align-items:center;gap:8px}}
.phone{{background:{C['bg']};border:9px solid #000;border-radius:34px;overflow:hidden;direction:rtl;color:{C['main']}}}
.sb{{height:24px;font-size:11px;display:flex;justify-content:space-between;padding:4px 20px;direction:ltr;color:{C['main']}}}
.scr{{padding:4px 12px 10px;display:flex;flex-direction:column;gap:8px}}
.compact .scr{{gap:6px}}
.top{{height:40px;display:flex;align-items:center;gap:6px}}
.pill{{border:1px solid;border-radius:20px;padding:3px 8px;font-size:11px;white-space:nowrap;display:flex;align-items:center;gap:6px}}
.pill i{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.ttl{{flex:1;text-align:center;display:flex;flex-direction:column;min-width:0}}
.ttl b{{color:{C['gold']};font-size:18px;white-space:nowrap}} .ttl span{{color:{C['dim']};font-size:10px}}
.gear{{width:34px;height:34px;flex:none;border:1px solid {C['gold']};border-radius:50%;color:{C['gold']};display:flex;align-items:center;justify-content:center;font-size:18px}}
.row{{display:flex;gap:8px}}
.panel{{background:{C['card']};border:1px solid {C['edge']};border-radius:14px;padding:8px 10px;display:flex;flex-direction:column;gap:4px;min-width:0}}
.price{{font-size:28px;font-weight:bold}}
.trend{{font-size:22px;font-weight:900}}
.track{{background:{C['track']};border-radius:9px;width:100%;overflow:hidden}}
.demo{{background:{C['wait']};color:#000;font-weight:bold;font-size:12px;text-align:center;border-radius:8px;padding:4px}}
.ask{{background:linear-gradient({C['goldl']},{C['gold']},#B8901F);border:1px solid {C['goldl']};border-radius:40px;color:#000;display:flex;align-items:center;justify-content:center;gap:12px;font-weight:900;font-size:28px}}
.compact .ask{{font-size:25px}} .xh{{font-size:34px;font-weight:400}}
.act{{display:flex;align-items:center;gap:8px}} .act b{{font-size:30px;font-weight:900}}
.kv{{display:flex;justify-content:space-between;align-items:center;gap:6px}} .k{{color:{C['dim']};font-size:12px;white-space:nowrap}} .v{{font-size:13px;font-weight:600;white-space:nowrap}}
.lvh{{display:flex;justify-content:space-between;align-items:center}} .lvh b{{font-size:15px}}
.lvr{{display:flex;align-items:center;gap:4px}} .nm{{width:24px;font-size:12px}} .lp{{flex:1;font-size:13px;font-weight:600}}
.ls{{width:54px;display:flex;flex-direction:column;align-items:flex-end;gap:1px}}
.segs{{display:flex;gap:2px;direction:ltr}} .segs i{{width:6px;height:7px;border-radius:2px;display:block}}
.hz{{align-items:center;text-align:center;gap:2px}}
.rsn{{flex-direction:row;align-items:center;gap:8px}}
.det{{border:1px solid {C['gold']};border-radius:20px;padding:8px 12px;font-size:13px;white-space:nowrap}}
.clamp2,.clamp3{{display:-webkit-box;-webkit-box-orient:vertical;overflow:hidden;line-height:1.4}} .clamp2{{-webkit-line-clamp:2}} .clamp3{{-webkit-line-clamp:3}}
.dim{{color:{C['dim']}}} .b{{font-weight:bold}} .center{{text-align:center}}
.s11{{font-size:11px}} .s12{{font-size:12px}} .s13{{font-size:13px}} .tiny{{font-size:10px}}
.cap{{color:#ddd;font-size:12.5px;text-align:center;direction:rtl;line-height:1.5}}"""


def phone(d, w, h, caption):
    compact = h < 700
    return (f'<div class="col" style="width:{w + 18}px"><div class="phone {"compact" if compact else ""}" style="width:{w + 18}px;height:{h + 18}px">'
            f'<div class="sb"><span>21:15</span><span>▂▄▆ 82%</span></div><div class="scr">{screen(d, compact)}</div></div>'
            f'<div class="cap">{caption}</div></div>')


if __name__ == "__main__":
    out = Path(sys.argv[1])
    args = sys.argv[2:]
    cells, W, H = [], 0, 0
    for i in range(0, len(args), 4):
        w, h, cap, f = int(args[i]), int(args[i + 1]), args[i + 2], args[i + 3]
        cells.append(phone(json.loads(Path(f).read_text(encoding="utf-8")), w, h, cap))
        W += w + 40
        H = max(H, h)
    html = f'<!doctype html><html lang="ar"><head><meta charset="utf-8"><style>{CSS}</style></head><body><div class="wrap">{"".join(cells)}</div></body></html>'
    page = out.with_suffix(".html")
    page.write_text(html, encoding="utf-8")
    subprocess.run(["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=2", f"--window-size={W + 40},{H + 110}", f"--screenshot={out.resolve()}",
                    str(page.resolve())], check=True, capture_output=True, timeout=120)
    print("wrote", out)
