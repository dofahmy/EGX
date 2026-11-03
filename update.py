"""
بيحدّث الأسعار ويعمل الصفحة من جديد.
- لو مفيش prices.csv: بيبدأ من prices_seed.csv.gz (أسعار متخزنة في المشروع)، فالصفحة بتشتغل حتى لو ياهو قافل.
- بعدين بينزّل آخر ١٠ أيام من ياهو على دفعات صغيرة ويضيفها، فلو نجح جزء بس بيتحفظ.
"""
import os
import time

import pandas as pd

status = {"error": None, "last_price_date": None, "tickers_updated": 0}


def base_prices():
    if os.path.exists("prices.csv"):
        return pd.read_csv("prices.csv")
    if os.path.exists("prices_seed.csv.gz"):
        return pd.read_csv("prices_seed.csv.gz")
    return pd.DataFrame(columns=["date", "ticker", "open", "high", "low", "close", "volume"])


def fetch_recent(tickers, period="10d", chunk=25):
    import yfinance as yf
    frames, errors = [], []
    for k in range(0, len(tickers), chunk):
        part = tickers[k:k + chunk]
        data = None
        for attempt in range(2):
            try:
                data = yf.download([f"{t}.CA" for t in part], period=period, interval="1d", group_by="ticker",
                                   auto_adjust=True, threads=False, progress=False)
                if data is not None and not data.empty:
                    break
            except Exception as e:
                errors.append(str(e)[:200])
            time.sleep(5)
        if data is None or data.empty:
            if k == 0:
                errors.append("أول دفعة رجعت فاضية، فوقفت المحاولة (ياهو غالبًا مانع السيرفر).")
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
            frames.append(d[["date", "ticker", "open", "high", "low", "close", "volume"]])
        time.sleep(3)
    return frames, errors


def run():
    status["error"] = None
    p = base_prices()
    tickers = pd.read_csv("egx_sectors.csv", encoding="utf-8-sig")["ticker"].tolist()
    try:
        frames, errors = fetch_recent(tickers)
        status["tickers_updated"] = len({f["ticker"].iat[0] for f in frames})
        if frames:
            new = pd.concat(frames)
            new["date"] = pd.to_datetime(new["date"]).dt.strftime("%Y-%m-%d")
            p["date"] = p["date"].astype(str).str[:10]
            p = pd.concat([p, new]).drop_duplicates(["date", "ticker"], keep="last").sort_values(["ticker", "date"])
        if status["tickers_updated"] < 50:
            status["error"] = (f"ياهو رجّع أسعار {status['tickers_updated']} سهم بس. "
                               + (errors[-1] if errors else "غالبًا ياهو مانع طلبات السيرفر."))
    except Exception as e:
        status["error"] = f"فشل تنزيل الأسعار: {str(e)[:300]}"
    if p.empty:
        status["error"] = (status["error"] or "") + " — ومفيش أسعار متخزنة."
        print("[تحديث]", status["error"], flush=True)
        return False
    p.to_csv("prices.tmp.csv", index=False)
    os.replace("prices.tmp.csv", "prices.csv")
    status["last_price_date"] = str(p["date"].max())[:10]
    print(f"[تحديث] أسعار لحد {status['last_price_date']} — اتحدّث {status['tickers_updated']} سهم"
          + (f" — تنبيه: {status['error']}" if status["error"] else ""), flush=True)
    import egx_web
    egx_web.main()
    return True


if __name__ == "__main__":
    run()
