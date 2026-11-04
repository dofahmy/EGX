"""
صفحة توصيات الفكرة (أ): "كسر ساعة ثم كسر يومي" — signals.html

الإشارة: السهم يكسر على الساعة (أعلى إغلاق في ٦٠ شمعة، أول كسر بعد ٦٠ شمعة من غير كسر)، وبعدها
في خلال ١٠ أيام تداول يكسر على اليومي (أعلى إغلاق في ٦٠ جلسة، أول كسر بعد ٢٠ جلسة من غير كسر).
سعر الشراء = إغلاق يوم كسر اليومي.
الأهداف: +٥٪ و+١٠٪ و+٢٠٪ و+٥٠٪ من سعر الشراء — الهدف بيتحسب اتحقق لو أعلى سعر في أي جلسة بعد الشراء وصله،
والرقم = بعد كام جلسة من يوم الشراء.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from datadir import D

TARGETS = (5, 10, 20, 50)
LINK_DAYS = 10
CAIRO = ZoneInfo("Africa/Cairo")
status = {"built": None, "error": None, "signals": 0, "running": False}


def fresh(B, gap):
    prev = B.astype(float).shift(1).rolling(gap, min_periods=1).max().fillna(0).astype(bool)
    return B & ~prev


def compute():
    from egx_hourly import wide
    from egx_web_1h import drop_open_bar
    sectors = pd.read_csv("egx_sectors.csv", encoding="utf-8-sig")
    names = sectors.set_index("ticker")["name"].to_dict()
    secmap = sectors.set_index("ticker")["sector"].to_dict()

    Ch, _ = wide(pd.read_csv(D("prices_1h.csv")), "dt", sectors)
    have = Ch.notna().cumsum().gt(0).sum(axis=1)
    t0 = have[have >= 0.5 * Ch.shape[1]].index[0].normalize()
    Ch = drop_open_bar(Ch.loc[t0:]).ffill(limit=10)
    hb = fresh(Ch > Ch.rolling(60, min_periods=40).max().shift(1), 60)

    p = pd.read_csv(D("prices.csv"))
    p.loc[p["volume"] <= 0, ["close", "high"]] = np.nan
    C, _ = wide(p, "date", sectors)
    Hh = p.pivot_table(index="date", columns="ticker", values="high").sort_index()
    Hh.index = pd.to_datetime(Hh.index)
    Hh = Hh.reindex(index=C.index, columns=C.columns)
    Lw = p.pivot_table(index="date", columns="ticker", values="low").sort_index()
    Lw.index = pd.to_datetime(Lw.index)
    Lw = Lw.reindex(index=C.index, columns=C.columns)
    Cf = C.ffill(limit=10)
    db = fresh(Cf > Cf.rolling(60, min_periods=40).max().shift(1), 20)
    idx = Cf.index
    n = len(idx)
    start = idx.searchsorted(t0 + pd.Timedelta(days=30))

    # موجات القطاع اليومية (نفس صفحة موجات القطاعات)
    from egx_hourly import system, DAILY
    Sd = sectors[sectors["ticker"].isin(C.columns)].set_index("ticker")
    _, _, waves, _ = system(C, Sd, DAILY)
    win = {}
    for i, s_ in waves:
        for tt in Sd.index[Sd["sector"] == s_]:
            win.setdefault(tt, []).append((i - 9, i + 40, i))

    rows = []
    for t in db.columns:
        if t not in secmap or t not in hb:
            continue
        ht = Ch.index[hb[t].fillna(False).values]
        for k in np.where(db[t].fillna(False).values)[0]:
            if k < start:
                continue
            day = idx[k]
            prev = ht[(ht < day + pd.Timedelta(hours=14, minutes=30)) & (ht >= idx[max(0, k - LINK_DAYS)])]
            if not len(prev):
                continue
            h0 = prev[0]
            buy = float(Cf[t].iat[k])
            hi = Hh[t].values[k + 1:]
            lo = Lw[t].values[k + 1:]
            hits = {}
            for x in TARGETS:
                w = np.where(hi >= buy * (1 + x / 100))[0]
                hits[str(x)] = int(w[0] + 1) if len(w) else None
            lastp = Cf[t].iloc[k:].dropna()
            minlow = np.nanmin(lo) if len(lo) and np.isfinite(lo).any() else np.nan
            sec_i = next((i for lo_i, hi_i, i in win.get(t, []) if lo_i <= k <= hi_i), None)
            if sec_i is None:
                ss, sd_ = "لسه", None
            elif sec_i < k:
                ss, sd_ = "قبل", idx[sec_i].strftime("%Y-%m-%d")
            else:
                ss, sd_ = "بعد", idx[sec_i].strftime("%Y-%m-%d")
            rows.append({
                "ss": ss, "sd": sd_,
                "t": t, "n": names.get(t, t), "s": secmap.get(t),
                "ht": h0.strftime("%Y-%m-%d %H:%M"), "hp": round(float(Ch[t].loc[h0]), 3),
                "d": day.strftime("%Y-%m-%d"), "bp": round(buy, 3),
                "lp": round(float(lastp.iloc[-1]), 3), "ld": lastp.index[-1].strftime("%Y-%m-%d"),
                "age": int(n - 1 - k),
                "dd": None if np.isnan(minlow) else round((minlow / buy - 1) * 100, 1),
                "hit": hits,
            })
    rows.sort(key=lambda r: (r["d"], r["n"]), reverse=True)
    return rows, idx[-1].strftime("%Y-%m-%d"), Ch.index[-1].strftime("%Y-%m-%d %H:%M")


def build_page():
    rows, last_day, last_hour = compute()
    data = {"rows": rows, "targets": list(TARGETS), "last_day": last_day, "last_hour": last_hour,
            "built": datetime.now(CAIRO).strftime("%Y-%m-%d %H:%M")}
    html = TEMPLATE.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    open(D("signals.tmp.html"), "w", encoding="utf-8").write(html)
    os.replace(D("signals.tmp.html"), D("signals.html"))
    status["built"] = data["built"]
    status["signals"] = len(rows)
    print(f"[توصيات] الصفحة اتعملت — {len(rows)} إشارة — آخر يوم {last_day}", flush=True)


def run():
    if status["running"]:
        return
    status["running"] = True
    status["error"] = None
    try:
        if os.path.exists(D("prices_1h.csv")) and os.path.exists(D("prices.csv")):
            build_page()
    except Exception as e:
        status["error"] = str(e)[:200]
        print("[توصيات] فشل:", e, flush=True)
    finally:
        status["running"] = False


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>توصيات: كسر ساعة ثم يومي</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;600;700&family=Reem+Kufi:wght@600&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4f6f8;--panel:#fff;--ink:#14213a;--muted:#5b6880;--line:#dde3ec;--accent:#1d5c8f;--accent-soft:#e3eef8;
--up:#137a4b;--up-bg:#e1f3ea;--down:#b4372f;--down-bg:#fbe6e4;--wait:#e9ecf1;
--font-display:"Reem Kufi","IBM Plex Sans Arabic",Tahoma,sans-serif;--font-body:"IBM Plex Sans Arabic",Tahoma,"Segoe UI",sans-serif;color-scheme:light}
@media (prefers-color-scheme: dark){:root{--bg:#0f1622;--panel:#172131;--ink:#e7edf6;--muted:#9aa8bd;--line:#2a3850;--accent:#6fb0e6;--accent-soft:#1d3349;
--up:#5fd39b;--up-bg:#163628;--down:#ff8a7f;--down-bg:#3d1d1c;--wait:#243045;color-scheme:dark}}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--ink);font-family:var(--font-body);font-size:15px;line-height:1.6}
header{background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.wrap{max-width:1280px;margin:0 auto;padding:0 20px}
.top{display:flex;flex-wrap:wrap;align-items:flex-end;gap:14px 22px;padding:14px 0}
h1{font-family:var(--font-display);font-size:23px;margin:0;flex:1 1 260px}
h1 small{display:block;font-family:var(--font-body);font-size:13px;font-weight:400;color:var(--muted)}
nav a{color:var(--accent);font-weight:600;text-decoration:none;margin-inline-start:12px;font-size:14px}
.controls{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end}
.controls label{display:flex;flex-direction:column;font-size:12px;color:var(--muted);gap:4px}
input,select{font:inherit;font-size:14px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 10px}
main{padding:20px 0 60px;display:flex;flex-direction:column;gap:20px}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px}
h2{font-family:var(--font-display);font-size:19px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin:0 0 14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile{border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.tile .k{font-size:12px;color:var(--muted)}.tile .v{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
.tile .s{font-size:12px;color:var(--muted)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th{font-size:12px;font-weight:600;color:var(--muted);text-align:right;padding:8px 10px;border-bottom:2px solid var(--line);white-space:nowrap;background:var(--panel);position:sticky;top:0}
td{padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap;font-variant-numeric:tabular-nums;vertical-align:middle}
td.c{text-align:center}
.nm b{display:block}.nm span{font-size:12px;color:var(--muted)}
.dt{font-size:12px;color:var(--muted)}
.hit{display:inline-flex;flex-direction:column;align-items:center;justify-content:center;min-width:56px;border-radius:6px;padding:2px 6px;background:var(--up-bg);color:var(--up);line-height:1.25}
.hit .ok{font-size:17px;font-weight:700}.hit .n{font-size:11px}
.no{display:inline-block;min-width:56px;border-radius:6px;padding:4px 6px;background:var(--wait);color:var(--muted);font-size:12px}
.up{color:var(--up)}.down{color:var(--down)}
.note{font-size:13px;color:var(--muted);margin:6px 0 0}
.empty{color:var(--muted)}
</style>
</head>
<body>
<header><div class="wrap top">
  <h1>توصيات: كسر ساعة ثم كسر يومي<small id="asof"></small></h1>
  <div class="controls">
    <label>من تاريخ<input type="date" id="from"></label>
    <label>القطاع<select id="sec"><option value="">كل القطاعات</option></select></label>
    <label>السهم<input type="search" id="q" placeholder="اكتبي اسم السهم"></label>
    <label>الحالة<select id="st"><option value="">الكل</option><option value="open">لسه ماوصلش +٥٪</option><option value="t5">وصل +٥٪</option><option value="t20">وصل +٢٠٪</option></select></label>
    <label>القطاع أكد؟<select id="sx"><option value="">الكل</option><option value="لسه">لسه ماأكدش</option><option value="قبل">أكد قبل السهم</option><option value="بعد">أكد بعد السهم</option></select></label>
  </div>
  <nav><a href="/">موجات القطاعات</a><a href="/1h">فريم الساعة</a></nav>
</div></header>
<div class="wrap"><main>
  <section>
    <h2>ملخص الإشارات في الفترة</h2>
    <p class="sub" id="sum-sub"></p>
    <div class="tiles" id="tiles"></div>
  </section>
  <section>
    <h2>كل التوصيات</h2>
    <p class="sub">الأحدث فوق. علامة ✓ يعني السهم وصل للهدف، والرقم تحتها بعد كام جلسة من يوم الشراء. الهدف بيتحسب من أعلى سعر في الجلسة.</p>
    <div class="scroll"><table><thead><tr>
      <th>السهم</th><th>كسر الساعة</th><th>سعر الساعة</th><th>كسر اليومي (الشراء)</th><th>سعر الشراء</th><th>إشارة القطاع</th>
      <th>+٥٪</th><th>+١٠٪</th><th>+٢٠٪</th><th>+٥٠٪</th><th>آخر سعر</th><th>من الشراء</th><th>أقصى نزول</th>
    </tr></thead><tbody id="rows"></tbody></table></div>
    <p class="note">الإشارة: السهم كسر أعلى إغلاق في ٦٠ شمعة ساعة، وبعدها في خلال ١٠ أيام تداول كسر أعلى إغلاق في ٦٠ جلسة على اليومي. سعر الشراء = إغلاق يوم كسر اليومي. "أقصى نزول" = أقل سعر وصله بعد الشراء. "إشارة القطاع" = إشارة موجة القطاع اليومية لو السهم جوه موجتها (من ١٠ جلسات قبلها لحد ٤٠ بعدها)، و"لسه ماأكدش" يعني قطاعه مادّاش إشارة حوالين كسر السهم لحد دلوقتي.</p>
    <p class="note">الاختبار التاريخي من ٢٠٢٢: الإشارات دي كسبت السوق بحوالي ٢٪ في أول ٢٠ يوم بعد التكلفة، وبعد ٩٠ يوم الميزة اختفت. ده سجل للإشارات ومش توصية بالشرا أو البيع.</p>
  </section>
</main></div>
<script>
const D=/*__DATA__*/null;
const AR=n=>String(n).replace(/\d/g,d=>"٠١٢٣٤٥٦٧٨٩"[d]);
const MON=["يناير","فبراير","مارس","أبريل","مايو","يونيو","يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"];
const fd=s=>{const [ds,tm]=s.split(" ");const [y,m,d]=ds.split("-");return AR(+d)+" "+MON[+m-1]+" "+AR(y)+(tm?" — "+AR(tm):"")};
const num=x=>x==null?"—":AR(Number(x).toLocaleString("en-US",{maximumFractionDigits:3}));
const pct=x=>x==null?"—":(x>0?"+":"")+AR(x.toFixed(1))+"٪";
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const $=id=>document.getElementById(id);
$("asof").textContent="آخر يوم في الأسعار: "+fd(D.last_day)+" — آخر شمعة ساعة: "+fd(D.last_hour)+" — اتحدثت "+AR(D.built);
[...new Set(D.rows.map(r=>r.s))].sort((a,b)=>a.localeCompare(b,"ar")).forEach(s=>{const o=document.createElement("option");o.value=s;o.textContent=s;$("sec").appendChild(o)});
$("from").value=D.last_day.slice(0,4)+"-01-01";
function cell(r,x){const n=r.hit[String(x)];
  if(n!=null)return `<span class="hit" title="وصل +${x}٪ بعد ${n} جلسة"><span class="ok">✓</span><span class="n">${AR(n)} جلسة</span></span>`;
  return `<span class="no">لسه</span>`}
function render(){
  const f=$("from").value||"0000", s=$("sec").value, q=$("q").value.trim(), st=$("st").value, sx=$("sx").value;
  let R=D.rows.filter(r=>r.d>=f&&(!s||r.s===s)&&(!q||r.n.includes(q)||r.t.toLowerCase().includes(q.toLowerCase())));
  if(sx)R=R.filter(r=>r.ss===sx);
  if(st==="open")R=R.filter(r=>r.hit["5"]==null);
  if(st==="t5")R=R.filter(r=>r.hit["5"]!=null);
  if(st==="t20")R=R.filter(r=>r.hit["20"]!=null);
  $("sum-sub").textContent=`${AR(R.length)} توصية من ${fd(f.length>4?f:D.rows.length?D.rows[D.rows.length-1].d:D.last_day)}. نسبة اللي وصلوا كل هدف، ووسيط عدد الجلسات لحد ما وصلوا.`;
  const tiles=[`<div class="tile"><div class="k">عدد التوصيات</div><div class="v">${AR(R.length)}</div></div>`];
  for(const x of D.targets){const h=R.map(r=>r.hit[String(x)]).filter(v=>v!=null).sort((a,b)=>a-b);
    const med=h.length?h[Math.floor((h.length-1)/2)]:null;
    tiles.push(`<div class="tile"><div class="k">وصلوا +${AR(x)}٪</div><div class="v">${R.length?AR(Math.round(h.length/R.length*100))+"٪":"—"}</div><div class="s">${AR(h.length)} سهم${med!=null?" — وسيط "+AR(med)+" جلسة":""}</div></div>`)}
  $("tiles").innerHTML=tiles.join("");
  $("rows").innerHTML=R.length?R.map(r=>{const ret=(r.lp/r.bp-1)*100;return `<tr>
    <td class="nm"><b>${esc(r.n)}</b><span>${esc(r.s)} — ${esc(r.t)}</span></td>
    <td class="dt">${fd(r.ht)}</td><td>${num(r.hp)}</td>
    <td>${fd(r.d)}<div class="dt">من ${AR(r.age)} جلسة</div></td><td><b>${num(r.bp)}</b></td>
    <td>${r.ss==="لسه"?'<span class="no">لسه ماأكدش</span>':`${fd(r.sd)}<div class="dt">${r.ss==="قبل"?"قبل السهم":"بعد السهم"}</div>`}</td>
    ${D.targets.map(x=>`<td class="c">${cell(r,x)}</td>`).join("")}
    <td>${num(r.lp)}</td><td class="${ret>0?"up":ret<0?"down":""}">${pct(ret)}</td><td class="down">${r.dd==null?"—":pct(r.dd)}</td></tr>`}).join("")
    :`<tr><td colspan="13" class="empty">مفيش توصيات بالشروط دي.</td></tr>`;
}
["from","sec","q","st","sx"].forEach(id=>$(id).addEventListener("input",render));
render();
</script>
</body>
</html>"""

if __name__ == "__main__":
    run()
