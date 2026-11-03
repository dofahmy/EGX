"""
موجات قطاعات البورصة المصرية — نسخة فريم الساعة، واختبارها مقارنة بالنسخة اليومية.

نفس القواعد بالظبط (قطاع فوق السوق + ربع أسهمه عملوا قمة جديدة + ماكانش طالع قبلها + فترة راحة،
وبعدها إشارة السهم = أول إغلاق فوق أعلى إغلاق في N شمعة)، بس على شموع الساعة. بنجرب ضبطين:
  - "سريع":     نفس عدد الشموع (١٠ / ٦٠ / ٦٣ / ٤٠ شمعة ساعة) والنسب أصغر (٢٪ بدل ٤٪، ٢٫٥٪ بدل ٥٪).
  - "نفس المدة": عدد الشموع × عدد شموع اليوم (يعني ١٠ أيام = ~٥٠ شمعة)، ونفس نسب اليومي.
                 ده نفس السيستم اليومي بس بيلقط الإشارة جوه اليوم بدل آخره.
وبنشغّل اليومي على نفس الفترة عشان المقارنة تبقى عادلة.

الاختبار: الدخول على إغلاق الشمعة اللي بعد الإشارة (مفيش نظر للمستقبل)، والنتيجة بعد ١ و٥ و٢٠ يوم تداول،
فوق متوسط السوق، وبعد خصم تكلفة تداول (الافتراضي ٠٫٥٪ دخول وخروج).

التشغيل:
  py egx_hourly.py                 (بينزّل شموع الساعة من تريدنج فيو لكل الأسهم ويحفظها في prices_1h.csv — ممكن ياخد ساعة)
  py egx_hourly.py --offline       (من الملف المحفوظ)
  py egx_hourly.py --cost 0.006    (تكلفة الصفقة كاملة)
محتاج: egx_sectors.csv و prices.csv (اليومي) في نفس الفولدر.
"""
import argparse
import json
import os
import threading
import time

import numpy as np
import pandas as pd

os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()

DAILY = dict(win=10, look=60, minp=40, pre=63, cool=63, active=40, ret=0.04, fresh=0.05, brd=0.25, mn=2)


def params(mode, bpd):
    if mode == "يومي":
        return DAILY
    if mode == "سريع":
        return dict(DAILY, ret=0.02, fresh=0.025)
    k = bpd  # نفس المدة
    return dict(win=10 * k, look=60 * k, minp=40 * k, pre=63 * k, cool=63 * k, active=40 * k,
                ret=0.04, fresh=0.05, brd=0.25, mn=2)


# ---------------- التنزيل ----------------
def fetch(tickers, bars=5000, timeout=45, path="prices_1h.csv"):
    from tvDatafeed import TvDatafeed, Interval
    u, p = os.environ.get("TV_USERNAME"), os.environ.get("TV_PASSWORD")
    st = {"tv": TvDatafeed(u, p) if u and p else TvDatafeed()}

    def one(t):
        box = {}

        def run():
            try:
                box["d"] = st["tv"].get_hist(symbol=t, exchange="EGX", interval=Interval.in_1_hour, n_bars=bars)
            except Exception as e:
                box["e"] = e
        th = threading.Thread(target=run, daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive() or "e" in box:
            st["tv"] = TvDatafeed(u, p) if u and p else TvDatafeed()
            return None
        return box.get("d")

    old = pd.read_csv(path) if os.path.exists(path) else None
    done = set(old["ticker"].unique()) if old is not None else set()
    frames = [old] if old is not None else []
    todo = [t for t in tickers if t not in done]
    print(f"شموع الساعة: {len(done)} سهم متنزّلين قبل كده، فاضل {len(todo)}", flush=True)
    for k, t in enumerate(todo, 1):
        d = None
        for _ in range(2):
            d = one(t)
            if d is not None and len(d):
                break
            time.sleep(2)
        if d is None or not len(d):
            print(f"[تخطي] {t}", flush=True)
            continue
        d = d.reset_index()
        dt = pd.to_datetime(d["datetime"])
        dt = dt.dt.tz_localize("UTC").dt.tz_convert("Africa/Cairo").dt.tz_localize(None)
        frames.append(pd.DataFrame({"dt": dt.dt.strftime("%Y-%m-%d %H:%M"), "ticker": t,
                                    "close": d["close"].values, "volume": d["volume"].values}))
        if k % 10 == 0 or k == len(todo):
            pd.concat(frames).to_csv(path, index=False)
            print(f"  {k}/{len(todo)} — آخر سهم {t}: {len(d)} شمعة من {dt.min():%Y-%m-%d}", flush=True)
        time.sleep(0.4)
    out = pd.concat(frames)
    out.to_csv(path, index=False)
    return out


# ---------------- البيانات ----------------
def wide(p, tcol, sectors):
    p = p.copy()
    p.loc[p["volume"] <= 0, "close"] = np.nan
    C = p.pivot_table(index=tcol, columns="ticker", values="close", aggfunc="last").sort_index()
    C.index = pd.to_datetime(C.index)
    C = C.mask(C <= 0)
    r = C / C.ffill().shift(1) - 1
    C = C.mask(r.abs() > 0.5)
    S = sectors[sectors["ticker"].isin(C.columns)].set_index("ticker")
    return C, S


# ---------------- السيستم (نسخة متجّهة من egx_sector_screener) ----------------
def system(C, S, P):
    Cf = C.ffill(limit=10 * max(1, P["win"] // 10))
    sec = S["sector"]
    big = sec.value_counts()
    big = big[big >= 5].index.drop("أخرى", errors="ignore")
    d1 = (Cf / Cf.shift(1) - 1).clip(-0.5, 0.5)
    mkt = d1.mean(axis=1)
    Sx = pd.DataFrame({s: d1[sec[sec == s].index].mean(axis=1) for s in big}).sub(mkt, axis=0)
    new = Cf > Cf.rolling(P["look"], min_periods=P["minp"]).max().shift(1)
    s10 = Sx.rolling(P["win"]).sum()
    pre = Sx.rolling(P["pre"]).sum().shift(P["win"])
    waves, sigs = [], []
    start = P["look"] + 20  # زي الأصلي: ٨٠ جلسة في اليومي
    for s in big:
        mem = sec[sec == s].index
        br = new[mem].astype(float).rolling(P["win"], min_periods=1).max()
        cnt = br.sum(axis=1)
        share = cnt / len(mem)
        cond = (s10[s] >= P["ret"]) & (cnt >= P["mn"]) & (share >= P["brd"]) & (pre[s] < P["fresh"])
        last = -10 ** 9
        for i in np.where(cond.fillna(False).values)[0]:
            if i < start or i - last < P["cool"]:
                continue
            last = i
            waves.append((i, s))
            lo, hi = i - P["win"] + 1, min(i + P["active"], len(Cf) - 1)
            for t in mem:
                w = new[t].iloc[lo:hi + 1].fillna(False).values
                if w.any():
                    j = lo + int(np.argmax(w))
                    sigs.append({"sector": s, "wave_i": i, "j": j, "ticker": t, "lag": j - i})
    return Cf, mkt, waves, pd.DataFrame(sigs)


def evaluate(Cf, mkt, sigs, bpd, cost, H=(1, 5, 20)):
    if sigs.empty:
        return sigs
    cm = (1 + mkt.fillna(0)).cumprod()
    out = sigs.copy()
    n = len(Cf)
    # الدخول على إغلاق الشمعة اللي بعد ما الإشارتين يبقوا معروفين: إشارة السهم وإشارة القطاع.
    # (السهم اللي كسر قبل القطاع مانعرفش إنه جزء من موجة غير يوم إشارة القطاع)
    e = (np.maximum(out["j"].values, out["wave_i"].values) + 1).clip(max=n - 1)
    tick = out["ticker"].values
    px = Cf.values
    col = {t: k for k, t in enumerate(Cf.columns)}
    p0 = np.array([px[e[k], col[tick[k]]] for k in range(len(out))])
    out["entry_time"] = Cf.index[e]
    for h in H:
        x = np.minimum(e + h * bpd, n - 1)
        ok = (e + h * bpd) <= n - 1
        p1 = np.array([px[x[k], col[tick[k]]] for k in range(len(out))])
        r = p1 / p0 - 1
        m = cm.values[x] / cm.values[e] - 1
        out[f"r{h}"] = np.where(ok, r - cost, np.nan)
        out[f"x{h}"] = np.where(ok, r - m - cost, np.nan)
    return out


def summarize(E, label, H=(1, 5, 20)):
    rows = []
    for stage, m in (("كل الإشارات", E["lag"] > -10 ** 9), ("قبل/مع القطاع", E["lag"] <= 0), ("بعد القطاع", E["lag"] > 0)):
        e = E[m]
        r = {"النسخة": label, "الأسهم": stage, "إشارات": len(e), "موجات": e["wave_i"].nunique()}
        for h in H:
            x = e[f"x{h}"].dropna()
            day = e.assign(d=e["entry_time"].dt.date).groupby("d")[f"x{h}"].mean().dropna()  # عنقدة باليوم
            r[f"فوق السوق بعد {h} يوم ٪"] = x.mean() * 100
            r[f"كسبان {h} ٪"] = (e[f"r{h}"].dropna() > 0).mean() * 100
            r[f"تي {h}"] = day.mean() / (day.std() / np.sqrt(len(day))) if len(day) > 3 and day.std() > 0 else np.nan
        rows.append(r)
    return rows


def match_waves(W_d, W_h, idx_d, idx_h, label):
    """لكل موجة يومية: هل النسخة دي لقطت نفس القطاع قبلها بكام يوم."""
    rows = []
    for i, s in W_d:
        d0 = idx_d[i]
        cands = [idx_h[k] for k, s2 in W_h if s2 == s and abs((idx_h[k] - d0).days) <= 15]
        if cands:
            best = min(cands, key=lambda t: abs((t - d0).days))
            rows.append({"القطاع": s, "اليومي": d0.date(), label: best, "فرق بالأيام": (best.normalize() - d0).days})
        else:
            rows.append({"القطاع": s, "اليومي": d0.date(), label: None, "فرق بالأيام": np.nan})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--cost", type=float, default=0.005)
    ap.add_argument("--bars", type=int, default=5000)
    a = ap.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    sectors = pd.read_csv("egx_sectors.csv", encoding="utf-8-sig")
    ph = pd.read_csv("prices_1h.csv") if a.offline else fetch(sectors["ticker"].tolist(), bars=a.bars)
    Ch, S = wide(ph, "dt", sectors)
    bpd = int(round(Ch.groupby(Ch.index.date).size().median()))
    # الفترة المشتركة: من أول يوم نص الأسهم أو أكتر عندها شموع ساعة
    have = Ch.notna().cumsum().gt(0).sum(axis=1)
    t0 = have[have >= 0.5 * Ch.shape[1]].index[0].normalize()
    Ch = Ch.loc[t0:]
    pdly = pd.read_csv("prices.csv")
    Cd, Sd = wide(pdly, "date", sectors)
    Cd = Cd.loc[Ch.index[0].normalize():]
    print(f"\nشموع الساعة: {Ch.index[0]:%Y-%m-%d} لـ {Ch.index[-1]:%Y-%m-%d %H:%M} — {Ch.shape[1]} سهم — {bpd} شمعة في اليوم")
    print(f"اليومي على نفس الفترة: {Cd.index[0].date()} لـ {Cd.index[-1].date()} — تكلفة الصفقة {a.cost * 100:.1f}٪")

    rows, results = [], {}
    for mode in ("يومي", "سريع", "نفس المدة"):
        P = params(mode, bpd)
        C, SS, per = (Cd, Sd, 1) if mode == "يومي" else (Ch, S, bpd)
        Cf, mkt, waves, sigs = system(C, SS, P)
        E = evaluate(Cf, mkt, sigs, per, a.cost)
        results[mode] = (Cf, waves, E)
        print(f"\n{mode}: {len(waves)} موجة قطاع — {len(E)} إشارة سهم")
        if len(E):
            rows += summarize(E, mode)
            E.assign(entry_time=E["entry_time"].astype(str), ticker=E["ticker"]).to_csv(
                f"hourly_signals_{mode}.csv", index=False, encoding="utf-8-sig")
    T = pd.DataFrame(rows)
    print("\n================ النتايج (بعد خصم التكلفة) ================")
    print("فوق السوق = عائد السهم ناقص متوسط السوق في نفس المدة. تي محسوبة على متوسط كل يوم دخول (مش كل صفقة لوحدها).")
    print(T.round(2).to_string(index=False))

    print("\n================ هل الساعة بتلقط الموجة بدري؟ ================")
    Cf_d, W_d, _ = results["يومي"]
    for mode in ("سريع", "نفس المدة"):
        Cf_h, W_h, _ = results[mode]
        M = match_waves(W_d, W_h, Cf_d.index, Cf_h.index, mode)
        got = M["فرق بالأيام"].dropna()
        print(f"\n{mode}: لقط {len(got)} من {len(M)} موجة يومية (في حدود ١٥ يوم) — "
              f"وسيط الفرق {got.median() if len(got) else float('nan'):+.0f} يوم (سالب = الساعة بدري) — "
              f"بدري في {(got < 0).mean() * 100 if len(got) else 0:.0f}٪")
        extra = len(W_h) - len(got)
        print(f"وعمل {extra} موجة زيادة مالهاش مقابل في اليومي")
        print(M.tail(12).to_string(index=False))

    T.round(4).to_csv("hourly_results.csv", index=False, encoding="utf-8-sig")
    print("\nالجدول في hourly_results.csv — وكل إشارة في hourly_signals_<النسخة>.csv")
    print("تنبيه: شموع الساعة في تريدنج فيو بتغطي حوالي ٤ سنين بس، والأسهم الضعيفة السيولة بيبقى فيها ساعات كتير من غير تداول.")


if __name__ == "__main__":
    main()
