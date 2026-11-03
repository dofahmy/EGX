"""
بيعمل صفحة ويب تفاعلية لموجات القطاعات: egx_sectors.html
تفتحيها في المتصفح، وتختاري أي فترة، وتشوفي آخر موجة لكل قطاع أو كل الموجات،
والأسهم البدري واللي لحقت واللي لسه، وكل سهم عامل إيه لحد آخر الفترة.

التشغيل (كل يوم بعد تحديث الأسعار):
    py egx_prices.py --days 1900
    py egx_web.py
    start egx_sectors.html        (ويندوز)   /   open egx_sectors.html   (ماك)
"""
import json

import numpy as np
import pandas as pd

from egx_sector_screener import load, build, ignitions, WINDOW


def main():
    C, S = load()
    names = S["name"].to_dict()
    Cf, sec, big, mkt, Sx, new, ma50 = build(C, S)
    idx = Cf.index
    n = len(idx)
    ign, s10 = ignitions(Sx, sec, big, new)
    pre = Sx.rolling(63).sum().shift(10)

    tick = [t for t in Cf.columns if t in sec.index]
    def rnd(x):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        return round(float(x), 3 if abs(x) >= 1 else 4)
    close = {t: [rnd(v) for v in Cf[t].values] for t in tick}
    mk = (1 + mkt.fillna(0)).cumprod()

    brk = {}
    for s in big:
        mem = sec[sec == s].index
        any10 = new[mem].rolling(10, min_periods=1).max().fillna(0)
        brk[s] = [int(v) for v in any10.sum(axis=1).values]

    waves = []
    for i, s in ign:
        mem = sec[sec == s].index
        st = []
        for t in mem:
            w = new[t].iloc[i - 9:min(i + WINDOW, n - 1) + 1]
            w = w[w.fillna(False).astype(bool)]
            if len(w):
                st.append([t, int(idx.get_loc(w.index[0]))])
        st.sort(key=lambda x: x[1])
        waves.append({"s": s, "i": int(i), "st": st})

    data = {
        "dates": [d.strftime("%Y-%m-%d") for d in idx],
        "names": {t: names.get(t, t) for t in tick},
        "sectors": {s: [t for t in sec[sec == s].index if t in close] for s in big},
        "close": close,
        "mkt": [round(float(v), 6) for v in mk.values],
        "s10": {s: [None if np.isnan(v) else round(float(v), 4) for v in s10[s].values] for s in big},
        "pre": {s: [None if np.isnan(v) else round(float(v), 4) for v in pre[s].values] for s in big},
        "brk": brk,
        "sxc": {s: [round(float(v), 5) for v in Sx[s].fillna(0).cumsum().values] for s in big},
        "waves": waves,
        "window": WINDOW,
    }
    html = open("egx_web_template.html", encoding="utf-8").read().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    open("egx_sectors.html", "w", encoding="utf-8").write(html)
    print(f"تم: egx_sectors.html — {len(waves)} موجة، آخر يوم {idx[-1].date()}")


if __name__ == "__main__":
    main()
