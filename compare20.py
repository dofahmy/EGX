#!/usr/bin/env python3
"""
compare20.py — Novida's last 20 sessions vs Tycoon's 20 sessions BEFORE and AFTER the move start.
    python3 /app/compare20.py --csv /data/tycoon_replay/tv_prices.csv --out /data/compare20
"""
import argparse
from pathlib import Path
import numpy as np, pandas as pd


def stats(w, base_vol):
    r = w.close.pct_change().dropna()
    rng = w.high.max() - w.low.min()
    return {
        'من': w.date.iloc[0].date(), 'لحد': w.date.iloc[-1].date(),
        'التغير %': round((w.close.iloc[-1] / w.close.iloc[0] - 1) * 100, 1),
        'المدى %': round(rng / w.low.min() * 100, 1),
        'الحجم ÷ الطبيعي': round(w.volume.median() / base_vol, 2),
        'أيام صعود': int((r > 0).sum()), 'أيام نزول': int((r < 0).sum()),
        'تذبذب يومي %': round(r.std() * 100, 2),
        'الإغلاق في المدى %': round((w.close.iloc[-1] - w.low.min()) / rng * 100) if rng else 50,
        'حجم أيام الصعود ÷ النزول': round(w.volume[w.close.diff() > 0].mean() / max(w.volume[w.close.diff() < 0].mean(), 1), 2),
    }


def window(g, end_idx, n=20):
    return g.iloc[max(0, end_idx - n + 1): end_idx + 1].reset_index(drop=True)


def shape(w):
    x = np.log(w.close.values); x = x - x.mean()
    return x / (x.std() or 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default='/data/tycoon_replay/tv_prices.csv')
    ap.add_argument('--src', default='TYCN'); ap.add_argument('--dst', default='AMPI')
    ap.add_argument('--start', default='2025-12-09', help='first day of Tycoon move')
    ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--out', default='compare20')
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(a.csv, parse_dates=['date'])
    d.columns = [c.lower() for c in d.columns]
    d = d.rename(columns={'symbol': 'ticker'})
    d['ticker'] = d.ticker.str.upper().str.replace('.CA', '', regex=False).str.split(':').str[-1]
    s = d[d.ticker == a.src].sort_values('date').reset_index(drop=True)
    t = d[d.ticker == a.dst].sort_values('date').reset_index(drop=True)
    i0 = int(s.index[s.date >= a.start][0])
    pre, post = window(s, i0 - 1, a.n), window(s, i0 + a.n - 1, a.n)
    now = window(t, len(t) - 1, a.n)
    bs = s.iloc[max(0, i0 - 80):i0 - a.n].volume.median()
    bt = t.iloc[-80:-a.n].volume.median()
    tab = pd.DataFrame({f'تايكون قبل الحركة': stats(pre, bs),
                        f'تايكون أول {a.n} يوم من الحركة': stats(post, bs),
                        f'نوفيدا آخر {a.n} يوم': stats(now, bt)})
    c_pre = float(np.dot(shape(pre), shape(now)) / a.n)
    c_post = float(np.dot(shape(post), shape(now)) / a.n)
    tab.loc['تشابه شكل الرسم مع نوفيدا'] = [round(c_pre, 2), round(c_post, 2), 1.0]
    tab.to_csv(out / 'compare20.csv', encoding='utf-8-sig')
    pd.set_option('display.width', 200)
    print(tab.to_string())

    try:
        import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
        fig, axs = plt.subplots(2, 3, figsize=(15, 6), dpi=130, gridspec_kw={'height_ratios': [3, 1]})
        for k, (w, b, title) in enumerate([(pre, bs, f'{a.src} before'), (post, bs, f'{a.src} first {a.n} days'),
                                           (now, bt, f'{a.dst} last {a.n} days')]):
            axs[0, k].plot(range(len(w)), w.close / w.close.iloc[0] * 100, marker='o', ms=3)
            axs[0, k].set_title(f'{title}\n{w.date.iloc[0].date()} -> {w.date.iloc[-1].date()}')
            axs[0, k].grid(alpha=.3); axs[0, k].set_ylim(70, 175)
            axs[1, k].bar(range(len(w)), w.volume / b, color='tab:blue'); axs[1, k].axhline(1, color='red', lw=1)
            axs[1, k].set_ylabel('vol / normal'); axs[1, k].grid(alpha=.3)
        fig.tight_layout(); fig.savefig(out / 'compare20.png')
    except Exception as ex:
        print('plot skipped:', ex)
    print(f'\nsaved -> {out}/compare20.csv, compare20.png')


if __name__ == '__main__':
    main()
