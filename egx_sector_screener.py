"""
ماسح موجات القطاعات — البورصة المصرية

بيطلّع لكل قطاع آخر إشارة قطاع في الفترة اللي تختاريها، وأول سهم فيها، والأسهم البدري،
والأسهم اللي لحقت، واللي لسه ماتحركتش، وكل سهم عامل إيه من إشارته لحد آخر الفترة.
ولو آخر الفترة هو النهارده: بيقولك أنهي قطاعات شغالة دلوقتي، وأنهي أسهم ادّت إشارة في آخر أيام.

قبل التشغيل (مرة واحدة):  py -m pip install openpyxl
تحديث الأسعار (كل يوم بعد القفلة):  py egx_prices.py --days 400

التشغيل:
    py egx_sector_screener.py                         # لحد آخر يوم في الأسعار، وبيدوّر في آخر سنة
    py egx_sector_screener.py --start 2025-01-01 --end 2025-12-31
    py egx_sector_screener.py --all                   # كل الموجات في الفترة مش آخر واحدة بس
    py egx_sector_screener.py --recent 5              # الإشارات الحديثة = آخر ٥ جلسات (الافتراضي)

المخرج: ملف إكسل اسمه sector_screen_<تاريخ النهاية>.xlsx
"""
import argparse

import numpy as np
import pandas as pd

# ---------- قواعد السيستم (نفس الاختبار) ----------
IGN_RET = 0.04      # القطاع فوق السوق في آخر ١٠ جلسات
IGN_BREADTH = 0.25  # ربع أسهم القطاع عملوا قمة ٦٠ جلسة في آخر ١٠ جلسات
IGN_MIN = 2         # وسهمين على الأقل
FRESH = 0.05        # القطاع ماكانش طالع أكتر من ٥٪ فوق السوق في الـ٦٣ جلسة اللي قبلهم
COOLDOWN = 63       # مفيش إشارة جديدة لنفس القطاع قبل ٦٣ جلسة
WINDOW = 40         # الإشارة بتفضل "نشطة" ٤٠ جلسة
LOOKBACK = 60       # إشارة السهم = إغلاق فوق أعلى إغلاق في ٦٠ جلسة


def load(prices="prices.csv", sectors="egx_sectors.csv", end=None):
    p = pd.read_csv(prices, parse_dates=["date"])
    p.loc[p["volume"] <= 0, "close"] = np.nan
    C = p.pivot_table(index="date", columns="ticker", values="close").sort_index()
    C = C.mask(C <= 0)
    r = C / C.ffill().shift(1) - 1
    C = C.mask(r.abs() > 0.5)  # قفزات أكبر من ٥٠٪ في يوم = غالبًا غلط بيانات
    if end is not None:
        C = C.loc[:pd.Timestamp(end)]
    s = pd.read_csv(sectors, encoding="utf-8-sig")
    s = s[s["ticker"].isin(C.columns)]
    return C, s.set_index("ticker")


def build(C, S):
    Cf = C.ffill(limit=10)
    sec = S["sector"]
    big = sec.value_counts()
    big = big[(big >= 5)].index.drop("أخرى", errors="ignore")
    d1 = (Cf / Cf.shift(1) - 1).clip(-0.5, 0.5)
    mkt = d1.mean(axis=1)
    Sx = pd.DataFrame({s: d1[sec[sec == s].index].mean(axis=1) for s in big}).sub(mkt, axis=0)
    new = Cf > Cf.rolling(LOOKBACK, min_periods=40).max().shift(1)
    ma50 = Cf.rolling(50).mean()
    return Cf, sec, big, mkt, Sx, new, ma50


def ignitions(Sx, sec, big, new):
    s10 = Sx.rolling(10).sum()
    pre = Sx.rolling(63).sum().shift(10)
    out, last = [], {s: -10**9 for s in big}
    for i in range(80, len(Sx)):
        for s in big:
            if i - last[s] < COOLDOWN:
                continue
            mem = sec[sec == s].index
            br = new[mem].iloc[i - 9:i + 1].any()
            if (s10[s].iat[i] >= IGN_RET and br.sum() >= IGN_MIN and br.mean() >= IGN_BREADTH
                    and pre[s].iat[i] < FRESH):
                out.append((i, s))
                last[s] = i
    return out, s10


def wave_rows(i, s, Cf, sec, names, new, mkt, ma50, L):
    idx = Cf.index
    mem = sec[sec == s].index
    rows, moved = [], set()
    for t in mem:
        w = new[t].iloc[i - 9:min(i + WINDOW, L) + 1]
        w = w[w.fillna(False).astype(bool)]
        if len(w):
            moved.add(t)
            j = idx.get_loc(w.index[0])
            rows.append((j, t))
    rows.sort()
    first_j = rows[0][0] if rows else None
    out = []
    mk = lambda a: (1 + mkt.iloc[a + 1:L + 1].fillna(0)).prod() - 1
    for j, t in rows:
        stage = "أول سهم" if j == first_j else ("بدري (قبل القطاع)" if j <= i else "لحق بعد الإشارة")
        p0, p1 = Cf[t].iat[j], Cf[t].iat[L]
        ret = p1 / p0 - 1 if p0 and not np.isnan(p1) else np.nan
        out.append({"المرحلة": stage, "السهم": names.get(t, t), "الرمز": t, "تاريخ إشارة السهم": idx[j].date(),
                    "جلسات من إشارة القطاع": j - i, "جلسات من إشارة السهم": L - j,
                    "السعر يوم الإشارة": round(p0, 3), "السعر في آخر الفترة": round(p1, 3) if not np.isnan(p1) else None,
                    "العائد من الإشارة": None if np.isnan(ret) else round(ret, 4),
                    "فوق السوق من الإشارة": None if np.isnan(ret) else round(ret - mk(j), 4),
                    "فوق متوسط ٥٠ يوم": "أيوه" if p1 > ma50[t].iat[L] else "لأ"})
    for t in mem:
        if t in moved or np.isnan(Cf[t].iat[L]):
            continue
        p0, p1 = Cf[t].iat[i], Cf[t].iat[L]
        ret = p1 / p0 - 1 if p0 else np.nan
        out.append({"المرحلة": "لسه ماكسرش", "السهم": names.get(t, t), "الرمز": t, "تاريخ إشارة السهم": None,
                    "جلسات من إشارة القطاع": None, "جلسات من إشارة السهم": None,
                    "السعر يوم الإشارة": round(p0, 3) if not np.isnan(p0) else None,
                    "السعر في آخر الفترة": round(p1, 3),
                    "العائد من الإشارة": None if np.isnan(ret) else round(ret, 4),
                    "فوق السوق من الإشارة": None if np.isnan(ret) else round(ret - mk(i), 4),
                    "فوق متوسط ٥٠ يوم": "أيوه" if p1 > ma50[t].iat[L] else "لأ"})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--recent", type=int, default=5)
    a = ap.parse_args()

    C, S = load(end=a.end)
    names = S["name"].to_dict()
    Cf, sec, big, mkt, Sx, new, ma50 = build(C, S)
    idx = Cf.index
    L = len(idx) - 1
    end = idx[L]
    start = pd.Timestamp(a.start) if a.start else end - pd.DateOffset(years=1)
    ign, s10 = ignitions(Sx, sec, big, new)
    ign = [(i, s) for i, s in ign if start <= idx[i] <= end]
    if not a.all:
        lastw = {}
        for i, s in ign:
            lastw[s] = (i, s)
        ign = sorted(lastw.values())

    summary, waves, recent = [], {}, []
    for i, s in ign:
        W = wave_rows(i, s, Cf, sec, names, new, mkt, ma50, L)
        since = L - i
        active = since <= WINDOW
        sx = Sx[s].iloc[i + 1:L + 1].sum()
        lst = lambda st: "، ".join(f"{n} ({d})" for n, d in zip(W[W["المرحلة"] == st]["السهم"], W[W["المرحلة"] == st]["تاريخ إشارة السهم"]))
        summary.append({"القطاع": s, "تاريخ إشارة القطاع": idx[i].date(), "من كام جلسة": since,
                        "الحالة": "نشطة" if active else "خلصت (عدّى ٤٠ جلسة)",
                        "القطاع فوق السوق من الإشارة": round(sx, 4),
                        "أول سهم / أسهم": lst("أول سهم"), "أسهم بدري": lst("بدري (قبل القطاع)"),
                        "لحقوا بعد الإشارة": lst("لحق بعد الإشارة"),
                        "لسه ماكسروش": "، ".join(W[W["المرحلة"] == "لسه ماكسرش"]["السهم"])})
        waves[(s, idx[i].date())] = W
        if active:
            rec = W[(W["جلسات من إشارة السهم"].notna()) & (W["جلسات من إشارة السهم"] < a.recent)]
            for _, r in rec.iterrows():
                recent.append({"القطاع": s, "تاريخ إشارة القطاع": idx[i].date(), **r.to_dict()})

    # القطاعات القريبة من إشارة
    pre = Sx.rolling(63).sum().shift(10)
    near = []
    for s in big:
        mem = sec[sec == s].index
        br = new[mem].iloc[L - 9:L + 1].any()
        near.append({"القطاع": s, "فوق السوق آخر ١٠ جلسات": round(s10[s].iat[L], 4),
                     "شرط ١ (≥٤٪)": "✓" if s10[s].iat[L] >= IGN_RET else "✗",
                     "أسهم كسرت آخر ١٠ جلسات": f"{int(br.sum())}/{len(mem)}",
                     "شرط ٢ (ربع القطاع وسهمين)": "✓" if (br.sum() >= IGN_MIN and br.mean() >= IGN_BREADTH) else "✗",
                     "الـ٦٣ جلسة اللي قبلها": round(pre[s].iat[L], 4),
                     "شرط ٣ (أقل من ٥٪)": "✓" if pre[s].iat[L] < FRESH else "✗"})
    near = pd.DataFrame(near).sort_values("فوق السوق آخر ١٠ جلسات", ascending=False)

    live = Cf.iloc[L].notna()
    market = {"آخر يوم": end.date(),
              "متوسط الأسهم آخر أسبوع": (1 + mkt.iloc[L - 4:L + 1]).prod() - 1,
              "متوسط الأسهم آخر شهر": (1 + mkt.iloc[L - 20:L + 1]).prod() - 1,
              "نسبة الأسهم فوق متوسط ٥٠ يوم": (Cf.iloc[L] > ma50.iloc[L])[live].mean()}

    out = f"sector_screen_{end.date()}.xlsx"
    write_xlsx(out, market, pd.DataFrame(summary), pd.DataFrame(recent), near, waves, start, end, a)
    print(f"آخر يوم: {end.date()} — الفترة من {start.date()}")
    print(f"السوق: أسبوع {market['متوسط الأسهم آخر أسبوع']*100:+.1f}٪ | شهر {market['متوسط الأسهم آخر شهر']*100:+.1f}٪ | فوق متوسط ٥٠ يوم {market['نسبة الأسهم فوق متوسط ٥٠ يوم']*100:.0f}٪")
    act = [x for x in summary if x["الحالة"] == "نشطة"]
    print(f"\nقطاعات نشطة دلوقتي: {len(act)}")
    for x in act:
        print(f"  {x['القطاع']}: إشارة {x['تاريخ إشارة القطاع']} من {x['من كام جلسة']} جلسة — فوق السوق من الإشارة {x['القطاع فوق السوق من الإشارة']*100:+.1f}٪")
    print(f"\nإشارات أسهم في آخر {a.recent} جلسات جوه قطاعات نشطة: {len(recent)}")
    for x in recent:
        print(f"  {x['السهم']} ({x['القطاع']}) — {x['تاريخ إشارة السهم']} بسعر {x['السعر يوم الإشارة']} — دلوقتي {x['السعر في آخر الفترة']} ({(x['العائد من الإشارة'] or 0)*100:+.1f}٪)")
    print(f"\nالملف: {out}")


def write_xlsx(path, market, summary, recent, near, waves, start, end, a):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.utils import get_column_letter
    F = "Arial"
    HF = Font(name=F, bold=True, color="FFFFFF"); HFILL = PatternFill("solid", fgColor="1F4E78")
    BF = Font(name=F); BB = Font(name=F, bold=True)
    BRD = Border(bottom=Side(style="thin", color="BFBFBF"))
    GREEN = PatternFill("solid", fgColor="C6EFCE"); RED = PatternFill("solid", fgColor="FFC7CE")
    WAVE = PatternFill("solid", fgColor="DDEBF7")
    STAGE = {"أول سهم": PatternFill("solid", fgColor="FFF2CC"), "بدري (قبل القطاع)": PatternFill("solid", fgColor="FCE4D6"),
             "لحق بعد الإشارة": PatternFill("solid", fgColor="E2EFDA"), "لسه ماكسرش": PatternFill("solid", fgColor="EDEDED")}
    PCT = {"القطاع فوق السوق من الإشارة", "العائد من الإشارة", "فوق السوق من الإشارة", "فوق السوق آخر ١٠ جلسات",
           "الـ٦٣ جلسة اللي قبلها"}
    PRICE = {"السعر يوم الإشارة", "السعر في آخر الفترة"}

    def table(ws, df, r0=1, wide=()):
        if df.empty:
            ws.cell(r0, 1, "مفيش").font = BF
            return
        for j, c in enumerate(df.columns, 1):
            x = ws.cell(r0, j, c); x.font = HF; x.fill = HFILL
            x.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[r0].height = 34
        for i, row in enumerate(df.itertuples(index=False), r0 + 1):
            for j, v in enumerate(row, 1):
                col = df.columns[j - 1]
                x = ws.cell(i, j, None if (isinstance(v, float) and pd.isna(v)) else v); x.font = BF; x.border = BRD
                if col in PCT: x.number_format = '0.0%;-0.0%;"-"'
                elif col in PRICE: x.number_format = "#,##0.000"
                elif "تاريخ" in col: x.number_format = "yyyy-mm-dd"; x.alignment = Alignment(horizontal="center")
                if col in ("المرحلة", "السهم") and "المرحلة" in df.columns:
                    f = STAGE.get(row[list(df.columns).index("المرحلة")])
                    if f: x.fill = f
                if col in wide: x.alignment = Alignment(wrap_text=True, vertical="top")
        for j, c in enumerate(df.columns, 1):
            L = get_column_letter(j)
            if c in PCT:
                rng = f"{L}{r0 + 1}:{L}{r0 + len(df)}"
                ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["0"], fill=GREEN))
                ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"], fill=RED))
            w = 50 if c in wide else max(11, min(32, int(max([len(str(c))] + [len(str(v)) for v in df[c]]) * 1.1) + 2))
            cur = ws.column_dimensions[L].width
            ws.column_dimensions[L].width = max(w, cur or 0)

    wb = Workbook()
    ws = wb.active; ws.title = "السوق دلوقتي"; ws.sheet_view.rightToLeft = True
    ws.cell(1, 1, f"ماسح موجات القطاعات — الفترة من {start.date()} لـ {end.date()}" + (" (كل الموجات)" if a.all else " (آخر موجة لكل قطاع)")).font = Font(name=F, bold=True, size=13)
    r = 3
    for k, v in market.items():
        ws.cell(r, 1, k).font = BB
        c = ws.cell(r, 2, v); c.font = BF
        if isinstance(v, float): c.number_format = '0.0%'
        r += 1
    ws.cell(r + 1, 1, f"إشارات أسهم في آخر {a.recent} جلسات جوه قطاعات نشطة").font = Font(name=F, bold=True, size=12)
    table(ws, recent, r0=r + 2)
    r2 = r + 4 + max(len(recent), 1)
    ws.cell(r2, 1, "القطاعات وشروط الإشارة دلوقتي").font = Font(name=F, bold=True, size=12)
    table(ws, near, r0=r2 + 1)
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 30)

    w = wb.create_sheet("ملخص القطاعات"); w.sheet_view.rightToLeft = True
    table(w, summary, wide=("أول سهم / أسهم", "أسهم بدري", "لحقوا بعد الإشارة", "لسه ماكسروش"))
    w.freeze_panes = "C2"

    for s in summary["القطاع"].unique() if len(summary) else []:
        w = wb.create_sheet(s[:31]); w.sheet_view.rightToLeft = True; rr = 1
        for (sec_name, d), W in waves.items():
            if sec_name != s:
                continue
            row = summary[(summary["القطاع"] == s) & (summary["تاريخ إشارة القطاع"] == d)].iloc[0]
            h = w.cell(rr, 1, f"إشارة القطاع: {d}   |   من {row['من كام جلسة']} جلسة   |   {row['الحالة']}   |   القطاع فوق السوق من الإشارة: {row['القطاع فوق السوق من الإشارة']*100:+.1f}٪")
            h.font = BB; h.fill = WAVE
            w.merge_cells(start_row=rr, start_column=1, end_row=rr, end_column=len(W.columns))
            table(w, W, r0=rr + 1)
            rr += len(W) + 3

    w = wb.create_sheet("الشرح"); w.sheet_view.rightToLeft = True
    lines = ["إشارة القطاع: القطاع سبق متوسط السوق بـ٤٪ في آخر ١٠ جلسات + ربع أسهمه (وسهمين على الأقل) عملوا أعلى إغلاق في ٦٠ جلسة خلال الـ١٠ جلسات دول + أداؤه فوق السوق في الـ٦٣ جلسة اللي قبلها أقل من ٥٪. ومفيش إشارة جديدة لنفس القطاع قبل ٦٣ جلسة.",
             "إشارة السهم: أول إغلاق فوق أعلى إغلاق في الـ٦٠ جلسة اللي قبله، من ١٠ جلسات قبل إشارة القطاع لحد ٤٠ جلسة بعدها.",
             "الإشارة نشطة لمدة ٤٠ جلسة بعد إشارة القطاع. الإشارات الحديثة = أسهم ادّت إشارة في آخر جلسات جوه قطاع نشط.",
             "المراحل: أول سهم (أصفر)، بدري قبل إشارة القطاع (برتقالي)، لحق بعد الإشارة (أخضر)، لسه ماكسرش (رمادي، العائد محسوب من يوم إشارة القطاع).",
             "فوق السوق = عائد السهم ناقص متوسط عائد كل الأسهم بأوزان متساوية في نفس الفترة.",
             "الأسعار من ياهو فايننس ومعدّلة، وممكن تختلف عن الشاشة، وزيادات رأس المال المجانية ساعات بتتسجل غلط. سايب والمصري الخليجي بالدولار.",
             "ده سجل وصفي ومش توصية. الاختبار التاريخي ٢٠١٩–٢٠٢٦ ماطلّعش ميزة ثابتة للقاعدة دي بعد التكلفة والسيولة."]
    for i, t in enumerate(lines, 1):
        c = w.cell(i, 1, t); c.font = BF; c.alignment = Alignment(wrap_text=True)
    w.column_dimensions["A"].width = 130
    wb.save(path)


if __name__ == "__main__":
    main()
