"""
اختبار القاعدة: "بعد إشارة القطاع اليومية، ادخل السهم يوم ما يكسر على اليومي، بشرط يكون ادّى إشارة ساعة
قبل إشارة القطاع (الترتيب: ساعة ← قطاع ← سهم)". كل ده معروف يوم الدخول، فمفيش نظر للمستقبل.

بيقارنها بباقي إشارات السهم اللي جت بعد القطاع (من غير إشارة ساعة قبل القطاع)، بعد خصم التكلفة،
وتي محسوبة على الموجات (كل موجة قطاع = عينة واحدة) عشان الأسهم اللي في نفس الموجة مش مستقلة.
وفي الآخر: قائمة إشارات القاعدة في ٢٠٢٦ بأسعار وتواريخ الساعة واليومي، والسهم عمل إيه لحد آخر سعر.

محتاج chain_signals.csv (من egx_chain.py) و prices.csv.
"""
import argparse

import numpy as np
import pandas as pd

from datadir import D

HORIZONS = (20, 60, 90, 120)
RULE = "ساعة ← قطاع ← سهم"


def tstat(x):
    x = pd.Series(x).dropna()
    return np.nan if len(x) < 4 or x.std() == 0 else x.mean() / (x.std() / np.sqrt(len(x)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", type=float, default=0.5, help="تكلفة الصفقة كاملة بالـ٪")
    ap.add_argument("--year", type=int, default=2026)
    a = ap.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    T = pd.read_csv("chain_signals.csv", encoding="utf-8-sig")
    T["wave"] = T["القطاع"] + " " + T["إشارة القطاع (يومي)"].astype(str)
    after = T[pd.to_datetime(T["إشارة السهم (يومي)"]) > pd.to_datetime(T["إشارة القطاع (يومي)"])].copy()
    after["مجموعة"] = np.where(after["الترتيب"] == RULE, "القاعدة: ساعة قبل القطاع",
                               np.where(after["الترتيب"] == "قطاع ← ساعة ← سهم", "ساعة بعد القطاع", "من غير إشارة ساعة"))

    print(f"إشارات السهم اللي جت بعد إشارة القطاع: {len(after)} — تكلفة الصفقة {a.cost}٪")
    rows = []
    for g, e in after.groupby("مجموعة"):
        r = {"المجموعة": g, "إشارات": len(e), "موجات": e["wave"].nunique()}
        for h in HORIZONS:
            x = e[f"من التأكيد فوق السوق {h}ي ٪"] - a.cost
            raw = e[f"من التأكيد {h}ي ٪"] - a.cost
            w = (e.assign(x=x).groupby("wave")["x"].mean())
            r[f"{h}ي فوق السوق"] = x.mean()
            r[f"{h}ي العائد"] = raw.mean()
            r[f"{h}ي كسبان ٪"] = (raw.dropna() > 0).mean() * 100
            r[f"{h}ي تي"] = tstat(w)
            r[f"{h}ي عدد"] = int(x.notna().sum())
        rows.append(r)
    S = pd.DataFrame(rows)
    print("\n================ النتيجة بعد التكلفة (٪) ================")
    print("فوق السوق = عائد السهم ناقص متوسط كل الأسهم في نفس المدة. تي على مستوى الموجة.")
    print(S.round(2).to_string(index=False))

    # الفرق بين القاعدة وباقي الإشارات (على مستوى الموجة: نقارن جوه نفس الموجة لما يكون فيها الاتنين)
    print("\n================ القاعدة مقابل باقي الأسهم في نفس الموجة ================")
    for h in HORIZONS:
        c = f"من التأكيد فوق السوق {h}ي ٪"
        p = after.pivot_table(index="wave", columns="مجموعة", values=c, aggfunc="mean")
        if "القاعدة: ساعة قبل القطاع" not in p:
            continue
        others = p.drop(columns="القاعدة: ساعة قبل القطاع").mean(axis=1)
        d = (p["القاعدة: ساعة قبل القطاع"] - others).dropna()
        print(f"بعد {h} يوم: القاعدة أحسن من باقي أسهم نفس الموجة بمتوسط {d.mean():+.1f} نقطة — "
              f"أحسن في {(d > 0).mean() * 100:.0f}٪ من {len(d)} موجة — تي {tstat(d):.2f}")

    # حسب السنة
    print("\n================ القاعدة حسب السنة (فوق السوق بعد ٦٠ يوم، بعد التكلفة) ================")
    q = after[after["مجموعة"] == "القاعدة: ساعة قبل القطاع"].copy()
    q["سنة"] = q["إشارة السهم (يومي)"].astype(str).str[:4]
    o = after[after["مجموعة"] != "القاعدة: ساعة قبل القطاع"].copy()
    o["سنة"] = o["إشارة السهم (يومي)"].astype(str).str[:4]
    by = pd.DataFrame({"القاعدة": q.groupby("سنة")["من التأكيد فوق السوق 60ي ٪"].mean() - a.cost,
                       "إشارات القاعدة": q.groupby("سنة").size(),
                       "باقي الأسهم بعد القطاع": o.groupby("سنة")["من التأكيد فوق السوق 60ي ٪"].mean() - a.cost,
                       "إشاراتهم": o.groupby("سنة").size()})
    print(by.round(2).to_string())

    # قائمة السنة
    p = pd.read_csv(D("prices.csv"))
    p = p[p["volume"] > 0]
    last = p.sort_values("date").groupby("ticker").tail(1).set_index("ticker")
    L = q[q["سنة"] == str(a.year)].copy()
    L["آخر سعر"] = L["الرمز"].map(last["close"]).round(3)
    L["تاريخ آخر سعر"] = L["الرمز"].map(last["date"])
    L["من اليومي لحد آخر سعر ٪"] = ((L["آخر سعر"] / L["سعر إشارة السهم"] - 1) * 100).round(1)
    L["من الساعة لحد آخر سعر ٪"] = ((L["آخر سعر"] / L["سعر إشارة الساعة"] - 1) * 100).round(1)
    cols = ["السهم", "الرمز", "القطاع", "إشارة الساعة", "سعر إشارة الساعة", "إشارة القطاع (يومي)",
            "إشارة السهم (يومي)", "سعر إشارة السهم", "أيام تداول من الساعة للسهم", "فرق السعر ساعة←سهم ٪",
            "آخر سعر", "تاريخ آخر سعر", "من اليومي لحد آخر سعر ٪", "من الساعة لحد آخر سعر ٪",
            "من التأكيد 20ي ٪", "من التأكيد 60ي ٪", "من التأكيد 90ي ٪", "من التأكيد 120ي ٪"]
    L = L[cols].sort_values("إشارة السهم (يومي)")
    out = f"rule_{a.year}.csv"
    L.to_csv(out, index=False, encoding="utf-8-sig")
    S.round(3).to_csv("rule_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n================ إشارات القاعدة في {a.year}: {len(L)} ================")
    show = ["السهم", "القطاع", "إشارة الساعة", "سعر إشارة الساعة", "إشارة القطاع (يومي)", "إشارة السهم (يومي)",
            "سعر إشارة السهم", "آخر سعر", "من اليومي لحد آخر سعر ٪"]
    print(L[show].to_string(index=False))
    print(f"\nالقائمة كاملة في {out} (فيها كمان العائد بعد ٢٠ و٦٠ و٩٠ و١٢٠ يوم لما يبقى متاح)، والملخص في rule_summary.csv")
    print("تنبيه: أرقام ٢٠٢٦ لسه ماعدّاش عليها مدة كفاية، فأغلبها مالوش عائد ٩٠ و١٢٠ يوم. ودي مش توصية.")


if __name__ == "__main__":
    main()
