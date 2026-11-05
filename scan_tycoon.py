#!/usr/bin/env python3
"""
scan_tycoon.py — which EGX stocks look RIGHT NOW like Tycoon did
   (A) in the 20 sessions BEFORE its move, and (B) in the FIRST 20 sessions of its move.

    python3 /app/scan_tycoon.py --tycoon /data/tycoon_replay/tv_prices.csv --csv /data/prices.csv --tv --out /data/scan_tycoon
      --tv   : refresh every stock's latest bars from TradingView (recommended; prices.csv may be old)
"""
import argparse, time
from pathlib import Path
import numpy as np, pandas as pd

FEATS = ['chg', 'rng', 'volx', 'pos', 'updn', 'vola']
NAMES = {'chg': 'التغير %', 'rng': 'المدى %', 'volx': 'الحجم ÷ الطبيعي', 'pos': 'الإغلاق في المدى %',
         'updn': 'حجم الصعود ÷ النزول', 'vola': 'تذبذب يومي %'}


def norm(d):
    d = d.copy(); d.columns = [c.lower() for c in d.columns]
    d = d.rename(columns={'symbol': 'ticker', 'datetime': 'date'})
    d['ticker'] = d.ticker.astype(str).str.upper().str.replace('.CA', '', regex=False).str.split(':').str[-1]
    d['date'] = pd.to_datetime(d.date).dt.normalize()
    for k in ('open', 'high', 'low', 'close', 'volume'):
        d[k] = pd.to_numeric(d[k], errors='coerce')
    return d.dropna(subset=['close']).drop_duplicates(['ticker', 'date']).sort_values(['ticker', 'date'])


def feats(w, base):
    r = w.close.pct_change().dropna()
    lo, hi = w.low.min(), w.high.max(); rng = hi - lo
    up = w.volume[w.close.diff() > 0].mean(); dn = w.volume[w.close.diff() < 0].mean()
    x = np.log(w.close.values); x = x - x.mean(); x = x / (x.std() or 1)
    return dict(chg=(w.close.iloc[-1] / w.close.iloc[0] - 1) * 100, rng=rng / lo * 100 if lo else 0,
                volx=w.volume.median() / base if base else np.nan, pos=(w.close.iloc[-1] - lo) / rng * 100 if rng else 50,
                updn=(up / dn) if dn and dn > 0 and not np.isnan(up) else 1.0, vola=r.std() * 100), x


def fetch_tv(tickers, bars=200):
    try:
        from tvDatafeed import TvDatafeed, Interval
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--break-system-packages',
                        'git+https://github.com/rongardF/tvdatafeed.git'], check=True)
        from tvDatafeed import TvDatafeed, Interval
    tv = TvDatafeed(); parts = []
    for i, s in enumerate(tickers, 1):
        for _ in range(2):
            try:
                x = tv.get_hist(symbol=s, exchange='EGX', interval=Interval.in_daily, n_bars=bars)
                if x is not None and len(x):
                    x = x.reset_index(); x['ticker'] = s; parts.append(x); break
            except Exception:
                time.sleep(1)
        if i % 25 == 0:
            print(f'  downloaded {i}/{len(tickers)}', flush=True)
    return norm(pd.concat(parts, ignore_index=True))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tycoon', default='/data/tycoon_replay/tv_prices.csv')
    ap.add_argument('--csv', default='/data/prices.csv')
    ap.add_argument('--tv', action='store_true')
    ap.add_argument('--start', default='2025-12-09'); ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--min-value', type=float, default=300_000, help='min median daily traded value EGP')
    ap.add_argument('--top', type=int, default=15); ap.add_argument('--out', default='scan_tycoon')
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True); n = a.n

    ty = norm(pd.read_csv(a.tycoon)); ty = ty[ty.ticker == 'TYCN'].reset_index(drop=True)
    i0 = int(ty.index[ty.date >= a.start][0])
    base_ty = ty.iloc[max(0, i0 - 80):i0 - n].volume.median()
    ref = {'A': feats(ty.iloc[i0 - n:i0].reset_index(drop=True), base_ty),
           'B': feats(ty.iloc[i0:i0 + n].reset_index(drop=True), base_ty)}

    mk = norm(pd.read_csv(a.csv))
    if a.tv:
        print(f'refreshing {mk.ticker.nunique()} stocks from TradingView ...', flush=True)
        mk = fetch_tv(sorted(mk.ticker.unique()))
    last_day = mk.date.max()
    print(f'market data: {mk.ticker.nunique()} stocks, last day {last_day.date()}', flush=True)

    # feature scale = spread across the market, so each feature counts equally
    rows, shapes = [], {}
    for s, g in mk.groupby('ticker'):
        g = g.reset_index(drop=True)
        if len(g) < 80 or s == 'TYCN' or (last_day - g.date.iloc[-1]).days > 7:
            continue
        w = g.iloc[-n:].reset_index(drop=True)
        if (w.close * w.volume).median() < a.min_value:
            continue
        f, x = feats(w, g.iloc[-80:-n].volume.median())
        f.update(ticker=s, close=w.close.iloc[-1], value_k=(w.close * w.volume).median() / 1e3,
                 frm=w.date.iloc[0].date(), to=w.date.iloc[-1].date())
        rows.append(f); shapes[s] = x
    m = pd.DataFrame(rows)
    scale = m[FEATS].replace([np.inf, -np.inf], np.nan).std()

    pd.set_option('display.width', 220); pd.set_option('display.max_columns', 20)
    report = []
    for key, title in (('A', f'شبه تايكون في الـ{n} يوم اللي قبل الطلوع'), ('B', f'شبه تايكون في أول {n} يوم من الطلوع')):
        rf, rx = ref[key]
        m[f'shape_{key}'] = [float(np.dot(shapes[s], rx) / n) for s in m.ticker]
        dist = sum(((m[k] - rf[k]) / scale[k]).abs().clip(upper=3) for k in FEATS) / len(FEATS)
        m[f'score_{key}'] = m[f'shape_{key}'] - 0.3 * dist
        top = m.sort_values(f'score_{key}', ascending=False).head(a.top)
        cols = ['ticker', 'close', f'shape_{key}'] + FEATS + ['value_k']
        t = top[cols].round(2).rename(columns={**NAMES, 'ticker': 'السهم', 'close': 'السعر',
                                               f'shape_{key}': 'تشابه الشكل', 'value_k': 'قيمة تداول يومية (ألف)'})
        refrow = {NAMES[k]: round(rf[k], 2) for k in FEATS}
        report += [f'\n=== {title} ===', 'تايكون وقتها: ' + ' | '.join(f'{k} {v}' for k, v in refrow.items()),
                   t.to_string(index=False)]
        t.to_csv(out / f'scan_{key}.csv', index=False, encoding='utf-8-sig')
    txt = '\n'.join(report)
    txt += f'\n\nالبيانات لحد {last_day.date()} | {len(m)} سهم بعد فلتر السيولة'
    (out / 'scan.txt').write_text(txt, encoding='utf-8'); print(txt)

    try:
        import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
        fig, axs = plt.subplots(1, 2, figsize=(14, 5), dpi=130)
        for ax, key in zip(axs, 'AB'):
            ax.plot(ref[key][1], color='black', lw=3, label='TYCN')
            for s in m.sort_values(f'score_{key}', ascending=False).ticker.head(5):
                ax.plot(shapes[s], lw=1.2, alpha=.8, label=s)
            ax.set_title('before the move' if key == 'A' else 'first 20 days of the move'); ax.legend(fontsize=8); ax.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(out / 'scan.png')
    except Exception as ex:
        print('plot skipped:', ex)
    print(f'saved -> {out}/scan.txt, scan_A.csv, scan_B.csv, scan.png')


if __name__ == '__main__':
    main()
