"""
بيحدّث الأسعار ويعمل الصفحة من جديد.
المصدر الأساسي: تريدنج فيو. لو فشل: ياهو. ولو الاتنين فشلوا: الأسعار المتخزنة (prices_seed.csv.gz).
- أول تشغيل للسيرفر: بيحاول ينزّل ٥ سنين كاملين من تريدنج فيو علشان كل الأسعار تبقى من مصدر واحد.
- بعد كده: آخر ١٥ جلسة بس، وبيضيفهم.
"""
import os
import time

import pandas as pd

import tv_prices

status = {"error": None, "last_price_date": None, "tickers_updated": 0, "source": None, "full_tv": False}
COLS = tv_prices.COLS


def base_prices():
    if os.path.exists("prices.csv"):
        return pd.read_csv("prices.csv")
    if os.path.exists("prices_seed.csv.gz"):
        return pd.read_csv("prices_seed.csv.gz")
    return pd.DataFrame(columns=COLS)


def yahoo_recent(tickers, period="10d", chunk=25):
    import yfinance as yf
    frames = []
    for k in range(0, len(tickers), chunk):
        part = tickers[k:k + chunk]
        try:
            data = yf.download([f"{t}.CA" for t in part], period=period, interval="1d", group_by="ticker",
                               auto_adjust=True, threads=False, progress=False)
        except Exception:
            data = None
        if data is None or data.empty:
            if k == 0:
                break
            continue
        for t in part:
            sym = f"{t}.CA"
            if sym not in data.columns.get_level_values(0):
                continue
            d = data[sym].dropna(subset=["Close"])
            if d.empty:
                continue
            d = d.reset_index().rename(columns=str.lower)
            d["ticker"] = t
            d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
            frames.append(d[COLS])
        time.sleep(2)
    return pd.concat(frames) if frames else pd.DataFrame(columns=COLS)


def run():
    status["error"] = None
    p = base_prices()
    tickers = pd.read_csv("egx_sectors.csv", encoding="utf-8-sig")["ticker"].tolist()
    new, src = pd.DataFrame(columns=COLS), None

    # ١. تريدنج فيو
    try:
        bars = 15 if status["full_tv"] else 2000
        print(f"[تحديث] تريدنج فيو: {bars} جلسة لـ {len(tickers)} سهم", flush=True)
        new, failed = tv_prices.fetch(tickers, bars=bars, log=lambda m: print(m, flush=True))
        if new["ticker"].nunique() >= 150:
            src = "تريدنج فيو"
            new, shift = tv_prices.align(new, p)  # بيقارن بالأسعار القديمة ويصلّح أي فرق يوم في التواريخ
            if shift:
                print(f"[تحديث] اتصلّح فرق {shift} يوم في تواريخ تريدنج فيو", flush=True)
            if bars > 15:
                status["full_tv"] = True
                keep = p[~p["ticker"].isin(new["ticker"].unique())]  # الأسهم اللي تريدنج فيو ماجابهاش تفضل من المتخزن
                p = keep
        else:
            status["error"] = f"تريدنج فيو رجّع {new['ticker'].nunique()} سهم بس"
            new = pd.DataFrame(columns=COLS)
    except Exception as e:
        status["error"] = f"تريدنج فيو فشل: {str(e)[:200]}"

    # ٢. ياهو كبديل
    if src is None:
        try:
            new = yahoo_recent(tickers)
            if new["ticker"].nunique() >= 50:
                src = "ياهو"
            else:
                status["error"] = (status["error"] or "") + " — وياهو كمان فشل"
        except Exception as e:
            status["error"] = (status["error"] or "") + f" — وياهو فشل: {str(e)[:150]}"

    if src:
        p = tv_prices.merge(p, new)
    status["source"] = src or "الأسعار المتخزنة"
    status["tickers_updated"] = int(new["ticker"].nunique()) if src else 0
    if p.empty:
        print("[تحديث] مفيش أسعار خالص", status["error"], flush=True)
        return False
    p.to_csv("prices.tmp.csv", index=False)
    os.replace("prices.tmp.csv", "prices.csv")
    status["last_price_date"] = str(p["date"].max())[:10]
    print(f"[تحديث] المصدر: {status['source']} — أسعار لحد {status['last_price_date']} — {status['tickers_updated']} سهم"
          + (f" — تنبيه: {status['error']}" if status["error"] else ""), flush=True)
    import egx_web
    egx_web.main()
    return True


if __name__ == "__main__":
    run()
