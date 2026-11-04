"""
سلسلة الإشارات: إشارة الساعة ← إشارة السهم على اليومي ← إشارة القطاع على اليومي.

لكل سهم ادّى إشارة في موجة قطاع يومية، بندوّر على آخر إشارة ليه على فريم الساعة قبلها
(إشارة سهم جوه موجة قطاع ساعة لنفس القطاع، في حدود ٦٠ يوم قبل إشارة اليومي)، وبنطلّع:
  - تاريخ ووقت إشارة الساعة وسعرها، وتاريخ إشارة السهم اليومية وسعرها، والمدة بينهم بأيام التداول، وفرق السعر.
  - تاريخ إشارة القطاع اليومية، وترتيب الإشارات.
  - أداء السهم من سعر إشارة الساعة، ومن يوم تأكيد القطاع (أول إغلاق يكون فيه السهم والقطاع الاتنين ادّوا إشارة)،
    بعد ٢٠ و٦٠ و٩٠ و١٢٠ يوم تداول، والعائد فوق متوسط السوق في نفس المدة. (من غير خصم تكلفة)

المخرج: chain_signals.csv (كل إشارة) و chain_summary.csv (الملخص).
محتاج: prices.csv و prices_1h.csv و egx_sectors.csv و egx_hourly.py في نفس الفولدر.
"""
import numpy as np
import pandas as pd

import egx_hourly as H

HORIZONS = (20, 60, 90, 120)
LOOKBACK_DAYS = 60


def main():
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    sectors = pd.read_csv("egx_sectors.csv", encoding="utf-8-sig")
    names = sectors.set_index("ticker")["name"].to_dict()
    Ch, Sh = H.wide(pd.read_csv("prices_1h.csv"), "dt", sectors)
    have = Ch.notna().cumsum().gt(0).sum(axis=1)
    t0 = have[have >= 0.5 * Ch.shape[1]].index[0].normalize()
    Ch = Ch.loc[t0:]
    bpd = int(round(Ch.groupby(Ch.index.date).size().median()))
    Cd, Sd = H.wide(pd.read_csv("prices.csv"), "date", sectors)

    # الساعة: النسخة السريعة (نفس صفحة /1h)
    Cfh, _, _, sh = H.system(Ch, Sh, H.params("سريع", bpd))
    # اليومي: على كل البيانات، وبعدين ناخد الموجات اللي بعد بداية شموع الساعة
    Cfd, mkt, _, sd = H.system(Cd, Sd, H.DAILY)
    idx_d = Cfd.index
    sd = sd[idx_d[sd["j"]] >= t0 + pd.Timedelta(days=LOOKBACK_DAYS)].copy()
    cm = (1 + mkt.fillna(0)).cumprod()

    sh["time"] = Cfh.index[sh["j"]]
    sh["price"] = [Cfh[t].iat[j] for t, j in zip(sh["ticker"], sh["j"])]
    sh = sh.sort_values("time")
    by_t = {t: g for t, g in sh.groupby("ticker")}

    def perf(t, k0, p0):
        out = {}
        for h in HORIZONS:
            k1 = k0 + h
            if k1 >= len(idx_d) or p0 is None or np.isnan(p0):
                out[h] = (np.nan, np.nan)
                continue
            p1 = Cfd[t].iat[k1]
            r = p1 / p0 - 1
            out[h] = (r, r - (cm.iat[k1] / cm.iat[k0] - 1))
        return out

    rows = []
    for _, s in sd.iterrows():
        t, jd, i_d = s["ticker"], int(s["j"]), int(s["wave_i"])
        day_sig = idx_d[jd]
        close_time = day_sig + pd.Timedelta(hours=14, minutes=30)
        g = by_t.get(t)
        hrow = None
        if g is not None:
            c = g[(g["time"] < close_time) & (g["time"] >= day_sig - pd.Timedelta(days=LOOKBACK_DAYS)) & (g["sector"] == s["sector"])]
            if len(c):
                hrow = c.iloc[-1]
        p_d = Cfd[t].iat[jd]
        conf = max(jd, i_d)
        p_c = Cfd[t].iat[conf]
        r = {"السهم": names.get(t, t), "الرمز": t, "القطاع": s["sector"],
             "إشارة الساعة": None, "سعر إشارة الساعة": None,
             "إشارة السهم (يومي)": day_sig.date(), "سعر إشارة السهم": round(p_d, 3),
             "إشارة القطاع (يومي)": idx_d[i_d].date(),
             "تأكيد القطاع (يوم الدخول)": idx_d[conf].date(), "سعر يوم التأكيد": round(p_c, 3)}
        if hrow is not None:
            ht = hrow["time"]
            kh = idx_d.searchsorted(ht.normalize())  # يوم إشارة الساعة في اليومي
            kh = min(kh, len(idx_d) - 1)
            r["إشارة الساعة"] = ht.strftime("%Y-%m-%d %H:%M")
            r["سعر إشارة الساعة"] = round(hrow["price"], 3)
            r["أيام تداول من الساعة للسهم"] = int(jd - kh)
            r["فرق السعر ساعة←سهم ٪"] = round((p_d / hrow["price"] - 1) * 100, 2)
            r["فرق السعر ساعة←تأكيد القطاع ٪"] = round((p_c / hrow["price"] - 1) * 100, 2)
            sec_day = idx_d[i_d]
            if jd <= i_d:
                order = "ساعة ← سهم ← قطاع"
            elif ht.normalize() <= sec_day:
                order = "ساعة ← قطاع ← سهم"
            else:
                order = "قطاع ← ساعة ← سهم"
            r["الترتيب"] = order
            ph = perf(t, kh, hrow["price"])
            for h in HORIZONS:
                r[f"من الساعة {h}ي ٪"] = None if np.isnan(ph[h][0]) else round(ph[h][0] * 100, 2)
                r[f"من الساعة فوق السوق {h}ي ٪"] = None if np.isnan(ph[h][1]) else round(ph[h][1] * 100, 2)
        else:
            r["الترتيب"] = "مفيش إشارة ساعة قبلها"
        pc = perf(t, conf, p_c)
        for h in HORIZONS:
            r[f"من التأكيد {h}ي ٪"] = None if np.isnan(pc[h][0]) else round(pc[h][0] * 100, 2)
            r[f"من التأكيد فوق السوق {h}ي ٪"] = None if np.isnan(pc[h][1]) else round(pc[h][1] * 100, 2)
        rows.append(r)

    T = pd.DataFrame(rows).sort_values(["إشارة السهم (يومي)", "القطاع"])
    T.to_csv("chain_signals.csv", index=False, encoding="utf-8-sig")

    # الملخص
    srows = []
    groups = [("كل اللي ليهم إشارة ساعة قبلها", T["إشارة الساعة"].notna())] + \
             [(o, T["الترتيب"] == o) for o in ("ساعة ← سهم ← قطاع", "ساعة ← قطاع ← سهم", "قطاع ← ساعة ← سهم", "مفيش إشارة ساعة قبلها")]
    for lab, m in groups:
        e = T[m]
        if e.empty:
            continue
        r = {"المجموعة": lab, "إشارات": len(e)}
        if lab != "مفيش إشارة ساعة قبلها":
            r["وسيط الأيام ساعة←سهم"] = e["أيام تداول من الساعة للسهم"].median()
            r["وسيط فرق السعر ساعة←سهم ٪"] = e["فرق السعر ساعة←سهم ٪"].median()
            r["وسيط فرق السعر ساعة←تأكيد ٪"] = e["فرق السعر ساعة←تأكيد القطاع ٪"].median()
        for h in HORIZONS:
            if lab != "مفيش إشارة ساعة قبلها":
                x = e[f"من الساعة {h}ي ٪"].dropna()
                r[f"من الساعة {h}ي: متوسط"] = x.mean()
                r[f"من الساعة {h}ي: فوق السوق"] = e[f"من الساعة فوق السوق {h}ي ٪"].mean()
                r[f"من الساعة {h}ي: كسبان ٪"] = (x > 0).mean() * 100 if len(x) else np.nan
            y = e[f"من التأكيد {h}ي ٪"].dropna()
            r[f"من التأكيد {h}ي: متوسط"] = y.mean()
            r[f"من التأكيد {h}ي: فوق السوق"] = e[f"من التأكيد فوق السوق {h}ي ٪"].mean()
            r[f"من التأكيد {h}ي: كسبان ٪"] = (y > 0).mean() * 100 if len(y) else np.nan
        srows.append(r)
    # المقارنة العادلة: كل إشارات الساعة، سواء اتحولت لإشارة يومية بعدها أو لأ
    # (لأن اختيار إشارات الساعة اللي "بعدها جه إشارة يومي" بيستخدم معلومة من المستقبل)
    sh2 = sh[sh["time"] >= t0 + pd.Timedelta(days=LOOKBACK_DAYS)]
    allh = {h: [] for h in HORIZONS}
    allx = {h: [] for h in HORIZONS}
    for t, ht, p0 in zip(sh2["ticker"], sh2["time"], sh2["price"]):
        kh = min(idx_d.searchsorted(ht.normalize()), len(idx_d) - 1)
        ph = perf(t, kh, p0)
        for h in HORIZONS:
            allh[h].append(ph[h][0])
            allx[h].append(ph[h][1])
    r = {"المجموعة": "كل إشارات الساعة (من غير ما نعرف اللي بعدها)", "إشارات": len(sh2)}
    for h in HORIZONS:
        x = pd.Series(allh[h]).dropna() * 100
        r[f"من الساعة {h}ي: متوسط"] = x.mean()
        r[f"من الساعة {h}ي: فوق السوق"] = pd.Series(allx[h]).mean() * 100
        r[f"من الساعة {h}ي: كسبان ٪"] = (x > 0).mean() * 100 if len(x) else np.nan
    srows.insert(0, r)
    Sm = pd.DataFrame(srows)
    Sm.round(2).to_csv("chain_summary.csv", index=False, encoding="utf-8-sig")

    print(f"الفترة: من {T['إشارة السهم (يومي)'].min()} لـ {T['إشارة السهم (يومي)'].max()} — {len(T)} إشارة سهم يومية")
    print(f"منهم {int(T['إشارة الساعة'].notna().sum())} كان ليهم إشارة ساعة قبلها (في حدود {LOOKBACK_DAYS} يوم، لنفس القطاع)")
    print("\n================ الملخص (الأرقام ٪، من غير تكلفة) ================")
    for _, r in Sm.iterrows():
        print(f"\n— {r['المجموعة']}: {int(r['إشارات'])} إشارة")
        if "وسيط الأيام ساعة←سهم" in r and not pd.isna(r.get("وسيط الأيام ساعة←سهم")):
            print(f"  وسيط المدة من إشارة الساعة لإشارة السهم: {r['وسيط الأيام ساعة←سهم']:.0f} يوم تداول — "
                  f"وسيط فرق السعر: {r['وسيط فرق السعر ساعة←سهم ٪']:+.1f}٪ (ولحد تأكيد القطاع {r['وسيط فرق السعر ساعة←تأكيد ٪']:+.1f}٪)")
        for h in HORIZONS:
            a = f"  بعد {h} يوم: "
            if not pd.isna(r.get(f"من الساعة {h}ي: متوسط", np.nan)):
                a += (f"من الساعة {r[f'من الساعة {h}ي: متوسط']:+.1f}٪ (فوق السوق {r[f'من الساعة {h}ي: فوق السوق']:+.1f}، "
                      f"كسبان {r[f'من الساعة {h}ي: كسبان ٪']:.0f}٪) | ")
            if pd.isna(r.get(f"من التأكيد {h}ي: متوسط", np.nan)):
                print(a.rstrip(" |"))
                continue
            a += (f"من التأكيد {r[f'من التأكيد {h}ي: متوسط']:+.1f}٪ (فوق السوق {r[f'من التأكيد {h}ي: فوق السوق']:+.1f}، "
                  f"كسبان {r[f'من التأكيد {h}ي: كسبان ٪']:.0f}٪)")
            print(a)
    cols = ["السهم", "القطاع", "إشارة الساعة", "سعر إشارة الساعة", "إشارة السهم (يومي)", "سعر إشارة السهم",
            "أيام تداول من الساعة للسهم", "فرق السعر ساعة←سهم ٪", "إشارة القطاع (يومي)", "الترتيب",
            "من الساعة 60ي ٪", "من التأكيد 60ي ٪"]
    print("\n================ آخر ٢٥ إشارة ليها إشارة ساعة قبلها ================")
    print(T[T["إشارة الساعة"].notna()][cols].tail(25).to_string(index=False))
    print("\nمهم: أداء 'من الساعة' في المجموعات اللي فوق متضخم، لأننا اخترنا إشارات ساعة عارفين إن السهم كسر بعدها على اليومي.")
    print("الرقم العادل للدخول على إشارة الساعة هو سطر 'كل إشارات الساعة' اللي في الأول.")
    print("\nكل الإشارات بالتفصيل في chain_signals.csv، والملخص في chain_summary.csv")
    print("تنبيه: الأرقام من غير خصم تكلفة، والإشارات اللي لسه ماعدّاش عليها ١٢٠ يوم مالهاش رقم في الأعمدة الطويلة.")


if __name__ == "__main__":
    main()
