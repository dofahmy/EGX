"""
فكرتين للدخول، ومقارنتهم:

 أ. "ساعة ثم يومي" (من غير قطاع): السهم يكسر على الساعة (أعلى إغلاق في ٦٠ شمعة) وبعدها في خلال ١٠ أيام
    تداول يكسر على اليومي (أعلى إغلاق في ٦٠ جلسة). الدخول على إغلاق يوم كسر اليومي.
 ب. نفس "ساعة ثم يومي" بس بنستنى القطاع يأكد: لازم القطاع يدّي إشارة يومية والسهم يكون جوه موجته.
    الدخول على إغلاق اليوم اللي فيه الاتنين اتحققوا (يوم السهم أو يوم القطاع، أيهم أخير).
 ج. للمقارنة: كل كسر يومي من غير كسر ساعة قبله.

الكسر "جديد" = مفيش كسر قبله لنفس السهم في آخر ٢٠ جلسة (اليومي) أو ٦٠ شمعة (الساعة).
النتيجة بعد ٢٠ و٦٠ و٩٠ و١٢٠ يوم تداول، بعد خصم التكلفة، والعائد فوق متوسط السوق.
تي محسوبة على أيام الدخول (كل يوم دخول = عينة)، عشان الأسهم اللي دخلت نفس اليوم مش مستقلة.

المخرج: ideas_all.csv (كل الإشارات) و ideas_A_<سنة>.csv و ideas_B_<سنة>.csv و ideas_summary.csv
"""
import argparse

import numpy as np
import pandas as pd

import egx_hourly as H
from datadir import D

HORIZONS = (20, 60, 90, 120)
LINK_DAYS = 10


def fresh(B, gap):
    """أول كسر بعد فترة من غير كسر."""
    prev = B.astype(float).shift(1).rolling(gap, min_periods=1).max().fillna(0).astype(bool)
    return B & ~prev


def tstat(x):
    x = pd.Series(x).dropna()
    return np.nan if len(x) < 4 or x.std() == 0 else x.mean() / (x.std() / np.sqrt(len(x)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", type=float, default=0.5)
    ap.add_argument("--year", type=int, default=2026)
    a = ap.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    sectors = pd.read_csv("egx_sectors.csv", encoding="utf-8-sig")
    names = sectors.set_index("ticker")["name"].to_dict()
    secmap = sectors.set_index("ticker")["sector"].to_dict()

    Ch, Sh = H.wide(pd.read_csv(D("prices_1h.csv")), "dt", sectors)
    have = Ch.notna().cumsum().gt(0).sum(axis=1)
    t0 = have[have >= 0.5 * Ch.shape[1]].index[0].normalize()
    Ch = Ch.loc[t0:]
    Chf = Ch.ffill(limit=10)
    hb = fresh(Chf > Chf.rolling(60, min_periods=40).max().shift(1), 60)

    Cd, Sd = H.wide(pd.read_csv(D("prices.csv")), "date", sectors)
    Cfd, mkt, waves, sigs = H.system(Cd, Sd, H.DAILY)  # موجات القطاع اليومية
    idx = Cfd.index
    db = fresh(Cfd > Cfd.rolling(60, min_periods=40).max().shift(1), 20)
    cm = (1 + mkt.fillna(0)).cumprod().values

    # لكل سهم: أوقات كسرات الساعة
    htimes = {t: Chf.index[hb[t].fillna(False).values] for t in hb.columns}
    # لكل سهم: موجات القطاع اليومية اللي هو جواها (من H.system: الإشارة j لازم تكون أول كسر جوه النافذة)
    win = {}
    for i, s in waves:
        for t in Sd.index[Sd["sector"] == s]:
            win.setdefault(t, []).append((i - 9, i + 40, i, s))

    rows = []
    start = idx.searchsorted(t0 + pd.Timedelta(days=30))
    for t in db.columns:
        if t not in secmap:
            continue
        ks = np.where(db[t].fillna(False).values)[0]
        ks = ks[ks >= start]
        ht = htimes.get(t, pd.DatetimeIndex([]))
        for k in ks:
            day = idx[k]
            close_t = day + pd.Timedelta(hours=14, minutes=30)
            lo = idx[max(0, k - LINK_DAYS)]
            prev = ht[(ht < close_t) & (ht >= lo)]
            r = {"السهم": names.get(t, t), "الرمز": t, "القطاع": secmap.get(t),
                 "كسر اليومي": day.date(), "سعر اليومي": round(Cfd[t].iat[k], 3)}
            if len(prev):
                h0 = prev[0]  # أول كسر ساعة في الفترة دي
                r["كسر الساعة"] = h0.strftime("%Y-%m-%d %H:%M")
                r["سعر الساعة"] = round(Chf[t].loc[h0], 3)
                r["فرق السعر ساعة←يومي ٪"] = round((r["سعر اليومي"] / r["سعر الساعة"] - 1) * 100, 2)
                r["أيام من الساعة لليومي"] = int(k - idx.searchsorted(h0.normalize()))
            # القطاع
            sec_i = None
            for lo_i, hi_i, i, s in win.get(t, []):
                if lo_i <= k <= hi_i:
                    sec_i = i
                    break
            if sec_i is not None:
                r["إشارة القطاع"] = idx[sec_i].date()
                e_b = max(k, sec_i)
                r["دخول ب (بعد تأكيد القطاع)"] = idx[e_b].date()
                r["سعر دخول ب"] = round(Cfd[t].iat[e_b], 3)
            for lab, e in (("أ", k), ("ب", max(k, sec_i) if sec_i is not None else None)):
                for h in HORIZONS:
                    if e is None or e + h >= len(idx):
                        r[f"{lab} {h}ي ٪"] = r[f"{lab} فوق السوق {h}ي ٪"] = np.nan
                        continue
                    p0, p1 = Cfd[t].iat[e], Cfd[t].iat[e + h]
                    ret = (p1 / p0 - 1) * 100 - a.cost
                    r[f"{lab} {h}ي ٪"] = round(ret, 2)
                    r[f"{lab} فوق السوق {h}ي ٪"] = round(ret - (cm[e + h] / cm[e] - 1) * 100, 2)
                r[f"دخول {lab}"] = None if e is None else idx[e]
            r["مجموعة"] = ("ب: ساعة ثم يومي + القطاع أكد" if (len(prev) and sec_i is not None) else
                           "أ بس: ساعة ثم يومي من غير قطاع" if len(prev) else "ج: يومي من غير ساعة")
            rows.append(r)
    T = pd.DataFrame(rows)
    T.drop(columns=[c for c in ("دخول أ", "دخول ب") if c in T]).to_csv("ideas_all.csv", index=False, encoding="utf-8-sig")

    # الملخص
    def block(e, lab, label):
        r = {"الفكرة": label, "إشارات": len(e)}
        for h in HORIZONS:
            x = e[f"{lab} فوق السوق {h}ي ٪"]
            raw = e[f"{lab} {h}ي ٪"]
            dd = e.assign(x=x).groupby(e[f"دخول {lab}"])["x"].mean()
            r[f"{h}ي العائد"] = raw.mean()
            r[f"{h}ي فوق السوق"] = x.mean()
            r[f"{h}ي كسبان ٪"] = (raw.dropna() > 0).mean() * 100
            r[f"{h}ي تي"] = tstat(dd)
        return r

    hasH = T["كسر الساعة"].notna() if "كسر الساعة" in T else pd.Series(False, index=T.index)
    hasS = T["إشارة القطاع"].notna() if "إشارة القطاع" in T else pd.Series(False, index=T.index)
    S = pd.DataFrame([
        block(T[hasH], "أ", "أ. ساعة ثم يومي (من غير ما نستنى القطاع)"),
        block(T[hasH & hasS], "ب", "ب. ساعة ثم يومي + نستنى القطاع يأكد"),
        block(T[hasH & ~hasS], "أ", "  منهم: ساعة ثم يومي والقطاع ماأكدش خالص"),
        block(T[~hasH], "أ", "ج. يومي من غير ساعة (للمقارنة)"),
        block(T, "أ", "كل الكسرات اليومية (للمقارنة)"),
    ])
    S.round(3).to_csv("ideas_summary.csv", index=False, encoding="utf-8-sig")
    print(f"الفترة: {T['كسر اليومي'].min()} لـ {T['كسر اليومي'].max()} — {len(T)} كسر يومي جديد — تكلفة {a.cost}٪")
    print(f"منهم {int(hasH.sum())} كان قبلهم كسر ساعة في آخر {LINK_DAYS} أيام، و{int((hasH & hasS).sum())} منهم القطاع أكد")
    print("\n================ النتيجة بعد التكلفة (٪) — فوق السوق = ناقص متوسط كل الأسهم ================")
    for _, r in S.iterrows():
        print(f"\n{r['الفكرة']} — {int(r['إشارات'])} إشارة")
        for h in HORIZONS:
            print(f"  بعد {h} يوم: العائد {r[f'{h}ي العائد']:+.1f}٪ — فوق السوق {r[f'{h}ي فوق السوق']:+.1f} "
                  f"(تي {r[f'{h}ي تي']:.2f}) — كسبان {r[f'{h}ي كسبان ٪']:.0f}٪")

    p = pd.read_csv(D("prices.csv"))
    p = p[p["volume"] > 0]
    last = p.sort_values("date").groupby("ticker").tail(1).set_index("ticker")
    y = str(a.year)
    for lab, m, ecol, pcol in (("A", hasH, "كسر اليومي", "سعر اليومي"), ("B", hasH & hasS, "دخول ب (بعد تأكيد القطاع)", "سعر دخول ب")):
        L = T[m & T["كسر اليومي"].astype(str).str.startswith(y)].copy()
        L["آخر سعر"] = L["الرمز"].map(last["close"]).round(3)
        L["من الدخول لحد آخر سعر ٪"] = ((L["آخر سعر"] / L[pcol] - 1) * 100).round(1)
        L["من الساعة لحد آخر سعر ٪"] = ((L["آخر سعر"] / L["سعر الساعة"] - 1) * 100).round(1)
        cols = ["السهم", "الرمز", "القطاع", "كسر الساعة", "سعر الساعة", "كسر اليومي", "سعر اليومي",
                "أيام من الساعة لليومي", "فرق السعر ساعة←يومي ٪"]
        if lab == "B":
            cols += ["إشارة القطاع", "دخول ب (بعد تأكيد القطاع)", "سعر دخول ب"]
        cols += ["آخر سعر", "من الدخول لحد آخر سعر ٪", "من الساعة لحد آخر سعر ٪"]
        L = L[cols].sort_values("كسر اليومي")
        L.to_csv(f"ideas_{lab}_{y}.csv", index=False, encoding="utf-8-sig")
        title = "أ. ساعة ثم يومي" if lab == "A" else "ب. ساعة ثم يومي + القطاع أكد"
        print(f"\n================ {title} — إشارات {y}: {len(L)} ================")
        show = [c for c in cols if c not in ("الرمز", "أيام من الساعة لليومي", "من الساعة لحد آخر سعر ٪")]
        print(L[show].to_string(index=False) if len(L) else "مفيش")
    print(f"\nالقوايم كاملة في ideas_A_{y}.csv و ideas_B_{y}.csv، وكل الإشارات في ideas_all.csv")
    print("تنبيه: من غير فلتر سيولة، والأرقام بعد خصم التكلفة. ودي مش توصية.")


if __name__ == "__main__":
    main()
