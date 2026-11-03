"""ينزّل أسعار أسهم egx_sectors.csv من ياهو فايننس ويعمل الصفحة من جديد."""
import os
import pandas as pd


def download_prices(days=1900):
    import yfinance as yf
    ts = pd.read_csv("egx_sectors.csv", encoding="utf-8-sig")["ticker"].tolist()
    data = yf.download([f"{t}.CA" for t in ts], period=f"{days}d", interval="1d", group_by="ticker",
                       auto_adjust=True, threads=True, progress=False)
    frames = []
    for t in ts:
        sym = f"{t}.CA"
        if sym not in data.columns.get_level_values(0):
            continue
        d = data[sym].dropna(subset=["Close"])
        if d.empty:
            continue
        d = d.reset_index().rename(columns=str.lower)
        d["ticker"] = t
        frames.append(d[["date", "ticker", "open", "high", "low", "close", "volume"]])
    if len(frames) < 50:
        raise RuntimeError(f"الأسعار ماجاتش كاملة ({len(frames)} سهم بس)")
    out = pd.concat(frames)
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out.to_csv("prices.tmp.csv", index=False)
    os.replace("prices.tmp.csv", "prices.csv")
    return out["ticker"].nunique(), out["date"].max()


def run():
    try:
        n, last = download_prices()
        print(f"[تحديث] أسعار {n} سهم لحد {last}", flush=True)
    except Exception as e:
        print(f"[تحديث] فشل تنزيل الأسعار: {e}", flush=True)
        if not os.path.exists("prices.csv"):
            return False
    import egx_web
    egx_web.main()
    return True


if __name__ == "__main__":
    run()
