"""
تنزيل أسعار يومية لأسهم البورصة المصرية من تريدنج فيو (مكتبة tvDatafeed غير الرسمية).

- من غير حساب بيشتغل غالبًا، ولو عندك حساب تريدنج فيو تقدري تحطي
  TV_USERNAME و TV_PASSWORD كمتغيرات بيئة.
- التواريخ بتتحسب بتوقيت القاهرة، وبيتأكد من المحاذاة مع الأسعار القديمة لو موجودة.

على جهازك:
    py -m pip install --upgrade git+https://github.com/rongardF/tvdatafeed.git
    py tv_prices.py --bars 1300          (أول مرة: ٥ سنين)
    py tv_prices.py                      (كل يوم: آخر ١٥ جلسة وبيضيفهم على prices.csv)
"""
import argparse
import os
import time

import pandas as pd

os.environ["TZ"] = "Africa/Cairo"
if hasattr(time, "tzset"):
    time.tzset()

COLS = ["date", "ticker", "open", "high", "low", "close", "volume"]


def client():
    from tvDatafeed import TvDatafeed
    u, p = os.environ.get("TV_USERNAME"), os.environ.get("TV_PASSWORD")
    try:
        return TvDatafeed(u, p) if u and p else TvDatafeed()
    except Exception:
        return TvDatafeed()


def fetch(tickers, bars=15, pause=0.4, log=print):
    from tvDatafeed import Interval
    tv = client()
    frames, failed = [], []
    for k, t in enumerate(tickers, 1):
        d = None
        for attempt in range(2):
            try:
                d = tv.get_hist(symbol=t, exchange="EGX", interval=Interval.in_daily, n_bars=bars)
                if d is not None and len(d):
                    break
            except Exception:
                d = None
            time.sleep(2)
        if d is None or not len(d):
            failed.append(t)
            continue
        d = d.reset_index().rename(columns={"datetime": "date"})
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        d["ticker"] = t
        frames.append(d[COLS])
        if k % 25 == 0:
            log(f"[تريدنج فيو] {k}/{len(tickers)}")
        time.sleep(pause)
    out = pd.concat(frames) if frames else pd.DataFrame(columns=COLS)
    return out, failed


def align(new, old):
    """لو التواريخ متزحلقة يوم عن الأسعار القديمة (فرق توقيت)، بيصلّحها."""
    if old is None or old.empty or new.empty:
        return new, 0
    o = old.copy()
    o["date"] = o["date"].astype(str).str[:10]
    sessions = sorted(o["date"].unique())
    pos = {d: i for i, d in enumerate(sessions)}
    best, score = 0, -1
    for shift in (-1, 0, 1):
        n = new.copy()
        n["date"] = n["date"].map(lambda d: sessions[pos[d] + shift] if d in pos and 0 <= pos[d] + shift < len(sessions) else None)
        m = n.dropna(subset=["date"]).merge(o, on=["date", "ticker"], suffixes=("", "_o"))
        if len(m) < 20:
            continue
        s = ((m["close"] - m["close_o"]).abs() / m["close_o"] < 0.01).mean()
        if s > score:
            best, score = shift, s
    if best == 0:
        return new, 0
    calendar = sorted(set(sessions) | set(new["date"]))
    cpos = {d: i for i, d in enumerate(calendar)}
    new = new.copy()
    new["date"] = new["date"].map(lambda d: calendar[cpos[d] + best] if 0 <= cpos[d] + best < len(calendar) else d)
    return new, best


def merge(old, new):
    if old is None or old.empty:
        return new.sort_values(["ticker", "date"])
    o = old.copy()
    o["date"] = o["date"].astype(str).str[:10]
    return pd.concat([o[COLS], new[COLS]]).drop_duplicates(["date", "ticker"], keep="last").sort_values(["ticker", "date"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=15, help="عدد الجلسات (١٣٠٠ = حوالي ٥ سنين)")
    ap.add_argument("--sectors", default="egx_sectors.csv")
    a = ap.parse_args()
    tickers = pd.read_csv(a.sectors, encoding="utf-8-sig")["ticker"].tolist()
    old = pd.read_csv("prices.csv") if os.path.exists("prices.csv") else None
    new, failed = fetch(tickers, bars=a.bars)
    if new.empty:
        raise SystemExit("تريدنج فيو مارجّعش أي أسعار.")
    new, shift = align(new, old)
    out = merge(old, new)
    out.to_csv("prices.tmp.csv", index=False)
    os.replace("prices.tmp.csv", "prices.csv")
    print(f"تم: {new['ticker'].nunique()} سهم من تريدنج فيو، آخر يوم {new['date'].max()}"
          + (f" (اتصلّح فرق يوم في التواريخ: {shift})" if shift else ""))
    if failed:
        print(f"مانزلش {len(failed)}: {', '.join(failed[:25])}")


if __name__ == "__main__":
    main()
