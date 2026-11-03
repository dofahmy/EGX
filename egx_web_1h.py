"""
صفحة موجات القطاعات على فريم الساعة (egx_sectors_1h.html) — نفس صفحة اليومي ونفس القواعد،
بس كل "جلسة" بقت شمعة ساعة (١٠ شموع / ٦٠ شمعة / ٦٣ / ٤٠)، والنسب أصغر عشان الشمعة أقصر:
القطاع فوق السوق ٢٪ في آخر ١٠ شموع (بدل ٤٪)، وماكانش فوق السوق أكتر من ٢٫٥٪ في الـ٦٣ شمعة اللي قبلها (بدل ٥٪).

تحديث الشموع: أول مرة ٥٠٠٠ شمعة لكل سهم (حوالي ٤٥ دقيقة)، وبعد كده آخر ٤٠ شمعة بس.
الشمعة اللي لسه ماقفلتش بتتشال، عشان الإشارة تبقى على شمعة كاملة.
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

P = dict(win=10, look=60, minp=40, pre=63, cool=63, active=40, ret=0.02, fresh=0.025, brd=0.25, mn=2)
KEEP = 2500          # عدد الشموع اللي بتظهر في الصفحة (حوالي سنتين)
PATH = "prices_1h.csv"
CAIRO = ZoneInfo("Africa/Cairo")
status = {"error": None, "last_bar": None, "tickers": 0, "running": False, "built": None}


# ---------------- التحديث ----------------
def _client():
    from tvDatafeed import TvDatafeed
    u, p = os.environ.get("TV_USERNAME"), os.environ.get("TV_PASSWORD")
    try:
        return TvDatafeed(u, p) if u and p else TvDatafeed()
    except Exception:
        return TvDatafeed()


def update(log=print, timeout=45):
    from tvDatafeed import Interval
    os.environ["TZ"] = "UTC"
    if hasattr(time, "tzset"):
        time.tzset()
    tickers = pd.read_csv("egx_sectors.csv", encoding="utf-8-sig")["ticker"].tolist()
    old = pd.read_csv(PATH) if os.path.exists(PATH) else None
    have = set(old["ticker"].unique()) if old is not None else set()
    st = {"tv": _client()}

    def one(t, bars):
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
            st["tv"] = _client()
            return None
        return box.get("d")

    frames, got = [], 0
    full = sum(t not in have for t in tickers)
    log(f"[ساعة] تحديث {len(tickers)} سهم ({full} محتاجين تاريخ كامل)")
    for k, t in enumerate(tickers, 1):
        bars = 40 if t in have else 5000
        d = None
        for _ in range(2):
            d = one(t, bars)
            if d is not None and len(d):
                break
            time.sleep(1.5)
        if d is None or not len(d):
            continue
        d = d.reset_index()
        dt = pd.to_datetime(d["datetime"]).dt.tz_localize("UTC").dt.tz_convert("Africa/Cairo").dt.tz_localize(None)
        frames.append(pd.DataFrame({"dt": dt.dt.strftime("%Y-%m-%d %H:%M"), "ticker": t,
                                    "close": d["close"].values, "volume": d["volume"].values}))
        got += 1
        if k % 25 == 0:
            log(f"[ساعة] {k}/{len(tickers)}")
            if old is None and frames:  # أول مرة: نحفظ أول بأول
                pd.concat(frames).to_csv(PATH, index=False)
        time.sleep(0.3)
    if not frames:
        raise RuntimeError("تريدنج فيو مارجّعش شموع ساعة")
    new = pd.concat(frames)
    allp = new if old is None else pd.concat([old, new])
    allp = allp.drop_duplicates(["dt", "ticker"], keep="last").sort_values(["ticker", "dt"])
    allp.to_csv(PATH + ".tmp", index=False)
    os.replace(PATH + ".tmp", PATH)
    status["tickers"] = got
    return got


def drop_open_bar(C):
    """نشيل الشمعة اللي لسه شغالة (الشمعة بتتكتب بوقت فتحها)."""
    now = datetime.now(CAIRO).replace(tzinfo=None)
    end = C.index + pd.Timedelta(hours=1)
    end = end.where(C.index.hour != 14, C.index.normalize() + pd.Timedelta(hours=14, minutes=31))
    return C[end <= now]


# ---------------- الحسابات ----------------
def compute():
    from egx_hourly import wide
    sectors = pd.read_csv("egx_sectors.csv", encoding="utf-8-sig")
    C, S = wide(pd.read_csv(PATH), "dt", sectors)
    have = C.notna().cumsum().gt(0).sum(axis=1)
    C = C.loc[have[have >= 0.5 * C.shape[1]].index[0]:]
    C = drop_open_bar(C)
    bpd = int(round(C.groupby(C.index.date).size().median()))
    Cf = C.ffill(limit=10)
    sec = S["sector"]
    big = sec.value_counts()
    big = big[big >= 5].index.drop("أخرى", errors="ignore")
    d1 = (Cf / Cf.shift(1) - 1).clip(-0.5, 0.5)
    mkt = d1.mean(axis=1)
    Sx = pd.DataFrame({s: d1[sec[sec == s].index].mean(axis=1) for s in big}).sub(mkt, axis=0)
    new = Cf > Cf.rolling(P["look"], min_periods=P["minp"]).max().shift(1)
    s10 = Sx.rolling(P["win"]).sum()
    pre = Sx.rolling(P["pre"]).sum().shift(P["win"])
    n = len(Cf)
    waves, brk = [], {}
    for s in big:
        mem = sec[sec == s].index
        br = new[mem].astype(float).rolling(P["win"], min_periods=1).max()
        cnt = br.sum(axis=1)
        brk[s] = cnt
        cond = (s10[s] >= P["ret"]) & (cnt >= P["mn"]) & (cnt / len(mem) >= P["brd"]) & (pre[s] < P["fresh"])
        last = -10 ** 9
        for i in np.where(cond.fillna(False).values)[0]:
            if i < P["look"] + 20 or i - last < P["cool"]:
                continue
            last = i
            st = []
            for t in mem:
                w = new[t].iloc[i - P["win"] + 1:min(i + P["active"], n - 1) + 1].fillna(False).values
                if w.any():
                    st.append([t, int(i - P["win"] + 1 + np.argmax(w))])
            st.sort(key=lambda x: x[1])
            waves.append({"s": s, "i": int(i), "st": st})
    waves.sort(key=lambda w: w["i"])
    return C, Cf, S, sec, big, mkt, Sx, s10, pre, brk, waves, bpd


def build_page():
    C, Cf, S, sec, big, mkt, Sx, s10, pre, brk, waves, bpd = compute()
    n = len(Cf)
    cut = max(0, n - KEEP)
    sl = slice(cut, n)
    idx = Cf.index[sl]
    names = S["name"].to_dict()
    tick = [t for t in Cf.columns if t in sec.index]

    def rnd(x):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        return round(float(x), 3 if abs(x) >= 1 else 4)

    def ser(v, k=4):
        return [None if np.isnan(x) else round(float(x), k) for x in v]

    ws = []
    for w in waves:
        if w["i"] - P["win"] < cut:
            continue
        ws.append({"s": w["s"], "i": w["i"] - cut, "st": [[t, j - cut] for t, j in w["st"]]})
    mk = (1 + mkt.fillna(0)).cumprod()
    data = {
        "dates": [d.strftime("%Y-%m-%d %H:%M") for d in idx],
        "names": {t: names.get(t, t) for t in tick},
        "sectors": {s: [t for t in sec[sec == s].index if t in tick] for s in big},
        "close": {t: [rnd(v) for v in Cf[t].values[sl]] for t in tick},
        "mkt": [round(float(v), 6) for v in mk.values[sl]],
        "s10": {s: ser(s10[s].values[sl]) for s in big},
        "pre": {s: ser(pre[s].values[sl]) for s in big},
        "brk": {s: [int(v) for v in brk[s].fillna(0).values[sl]] for s in big},
        "sxc": {s: [round(float(v), 5) for v in Sx[s].fillna(0).cumsum().values[sl]] for s in big},
        "waves": ws,
        "window": P["active"],
    }
    tpl = open("egx_web_template.html", encoding="utf-8").read()
    html = adapt(tpl, bpd).replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    open("egx_sectors_1h.tmp.html", "w", encoding="utf-8").write(html)
    os.replace("egx_sectors_1h.tmp.html", "egx_sectors_1h.html")
    status["last_bar"] = str(idx[-1])
    status["built"] = datetime.now(CAIRO).strftime("%Y-%m-%d %H:%M")
    print(f"[ساعة] الصفحة اتعملت — {len(ws)} موجة — آخر شمعة {idx[-1]}", flush=True)


def adapt(t, bpd):
    """نفس قالب اليومي بعد تعديل الكلام والأرقام لفريم الساعة."""
    R = [
        # التواريخ فيها ساعة
        ('const fmt=s=>{const [y,m,d]=s.split("-");return AR(+d)+" "+MON[+m-1]+" "+AR(y)};',
         'const fmt=s=>{const [ds,tm]=s.split(" ");const [y,m,d]=ds.split("-");return AR(+d)+" "+MON[+m-1]+" "+AR(y)+(tm?" — "+AR(+tm.slice(0,2))+":"+tm.slice(3).replace(/\\d/g,c=>AR(+c)):"")};'),
        ('$("start").min=$("end").min=dates[0];$("start").max=$("end").max=dates[N-1];',
         '$("start").min=$("end").min=dates[0].slice(0,10);$("start").max=$("end").max=dates[N-1].slice(0,10);'),
        ('$("end").value=dates[N-1]; const d=new Date(dates[N-1]);d.setFullYear(d.getFullYear()-1);',
         '$("end").value=dates[N-1].slice(0,10); const d=new Date(dates[N-1].slice(0,10));d.setMonth(d.getMonth()-3);'),
        ('const endI=idxOf($("end").value||dates[N-1]);', 'const endI=idxOf(($("end").value||dates[N-1].slice(0,10))+" 23:59");'),
        # المربعات
        ('[["آخر أسبوع",L>=5?mret(L-5,L):null],["آخر شهر",L>=21?mret(L-21,L):null],["آخر ٣ شهور",L>=63?mret(L-63,L):null],["فوق متوسط ٥٠ يوم"',
         f'[["آخر يوم",L>={bpd}?mret(L-{bpd},L):null],["آخر أسبوع",L>={5 * bpd}?mret(L-{5 * bpd},L):null],["آخر شهر",L>={21 * bpd}?mret(L-{21 * bpd},L):null],["فوق متوسط ٥٠ شمعة"'),
        # الشروط
        ('ok(x.a!=null&&x.a>=0.04)', 'ok(x.a!=null&&x.a>=0.02)'),
        ('ok(x.p!=null&&x.p<0.05)', 'ok(x.p!=null&&x.p<0.025)'),
        ('شرط ١: ٤٪ أو أكتر', 'شرط ١: ٢٪ أو أكتر'),
        ('شرط ٣: أقل من ٥٪', 'شرط ٣: أقل من ٢٫٥٪'),
        ('سبق متوسط السوق بـ٤٪', 'سبق متوسط السوق بـ٢٪'),
        ('أقل من ٥٪. ومفيش', 'أقل من ٢٫٥٪. ومفيش'),
        ('موجات قطاعات البورصة المصرية', 'موجات قطاعات البورصة المصرية — فريم الساعة'),
    ]
    for a, b in R:
        if a not in t:
            print(f"[ساعة] تنبيه: ماتغيّرش جزء في القالب: {a[:50]}", flush=True)
        t = t.replace(a, b)
    t = t.replace("جلسات", "شموع").replace("جلسة", "شمعة").replace("آخر يوم في البيانات", "آخر شمعة في البيانات") \
         .replace("آخر يوم في الفترة", "آخر شمعة في الفترة").replace("آخر يوم:", "آخر شمعة:")
    t = t.replace('<a href="/1h" style="color:var(--accent);font-weight:600;text-decoration:none">فريم الساعة ←</a>',
                  '<a href="/" style="color:var(--accent);font-weight:600;text-decoration:none">اليومي ←</a>')
    # سطر المصدر
    import re
    t = re.sub(r'<p class="note">الأسعار من ياهو[^<]*</p>',
               '<p class="note">الشموع من تريدنج فيو كل ساعة (الشمعة اللي لسه ماقفلتش مش محسوبة). الشمعة = ساعة تداول، وفيه حوالي '
               f'{bpd} شموع في اليوم. الأسهم الضعيفة السيولة ممكن تعدّي ساعات من غير تداول. ده سجل وصفي ومش توصية: '
               'الاختبار التاريخي من ٢٠٢٢ ماطلّعش ميزة للقاعدة دي بعد التكلفة.</p>', t)
    return t


def run(log=print):
    if status["running"]:
        return False
    status["running"] = True
    status["error"] = None
    try:
        try:
            update(log)
        except Exception as e:
            status["error"] = f"تحديث: {str(e)[:150]}"
        if os.path.exists(PATH):
            build_page()
            return True
        return False
    except Exception as e:
        status["error"] = (status["error"] or "") + f" | الصفحة: {str(e)[:200]}"
        print("[ساعة]", status["error"], flush=True)
        return False
    finally:
        status["running"] = False


if __name__ == "__main__":
    run()
