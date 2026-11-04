#!/usr/bin/env python3
"""
novida_twin.py — find EGX stocks whose historical price path looks like Novida (AMPI)
from a start date until today, and show what happened to them AFTERWARDS.

Run on the server that has DATABASE_URL and market_candles_1d:
    python novida_twin.py --target AMPI.CA --start 2025-06-22 --out /data/novida_twin

Outputs:
    matches.csv        top matches (symbol, window dates, similarity, what happened next)
    overlay.png        Novida vs the best 6 matches, rebased to 100
    summary.txt        Arabic summary
"""
import argparse, os
from pathlib import Path
import numpy as np, pandas as pd
from sqlalchemy import create_engine, text


def znorm(x):
    s = x.std()
    return (x - x.mean()) / s if s > 0 else x * 0


def resample_path(x, n):
    """stretch/shrink a path to n points (so slower/faster twins still match)."""
    xi = np.linspace(0, len(x) - 1, n)
    return np.interp(xi, np.arange(len(x)), x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', default='AMPI.CA')
    ap.add_argument('--start', default='2025-06-22')
    ap.add_argument('--suffix', default='.CA')
    ap.add_argument('--out', default='novida_twin')
    ap.add_argument('--top', type=int, default=25)
    ap.add_argument('--step', type=int, default=3, help='slide step in trading days')
    ap.add_argument('--speeds', default='0.75,1,1.33', help='window length multipliers (slower/faster twins)')
    ap.add_argument('--close-col', default='c'); ap.add_argument('--volume-col', default='v')
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    url = os.environ['DATABASE_URL']
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    eng = create_engine(url)
    q = text(f'''SELECT symbol, session_date AS date, {a.close_col} AS c, {a.volume_col} AS v
                 FROM market_candles_1d WHERE symbol LIKE :suf''')
    with eng.connect() as cn:
        d = pd.concat(pd.read_sql(q, cn, params={'suf': '%' + a.suffix}, chunksize=500_000), ignore_index=True)
    d['date'] = pd.to_datetime(d.date)
    d['c'] = pd.to_numeric(d.c, errors='coerce'); d['v'] = pd.to_numeric(d.v, errors='coerce')
    d = d.dropna(subset=['c']).query('c > 0').drop_duplicates(['symbol', 'date']).sort_values(['symbol', 'date'])
    if a.target not in set(d.symbol):
        raise SystemExit(f'{a.target} not found. Close names: ' +
                         ', '.join(s for s in d.symbol.unique() if 'AMP' in s.upper()))

    # ---------- template: Novida since start ----------
    t = d[(d.symbol == a.target) & (d.date >= a.start)]
    tc = np.log(t.c.values)
    N = len(tc)
    if N < 40:
        raise SystemExit(f'only {N} trading days for {a.target} since {a.start}')
    T = znorm(tc)
    t_range = tc.max() - tc.min()
    t_peak = np.exp(tc.max() - tc[0]) - 1
    t_end = np.exp(tc[-1] - tc[0]) - 1
    t_dd = np.exp(tc[-1] - tc.max()) - 1
    t_peak_pos = int(np.argmax(tc)) / N
    t_maxjump = np.abs(np.diff(tc)).max()
    print(f'template {a.target}: {t.date.iloc[0].date()} -> {t.date.iloc[-1].date()}  {N} sessions | '
          f'peak {t_peak:+.0%} at {t_peak_pos:.0%} of the way | now {t_end:+.0%} | from peak {t_dd:+.0%}')

    speeds = [float(s) for s in a.speeds.split(',')]
    rows = []
    for sym, g in d.groupby('symbol'):
        c = np.log(g.c.values); dates = g.date.values; vol = g.v.values
        if sym == a.target:  # only the stock's own history BEFORE the template
            keep = dates < np.datetime64(a.start)
            c, dates, vol = c[keep], dates[keep], vol[keep]
        for sp in speeds:
            L = int(round(N * sp))
            if len(c) < L + 20:
                continue
            for i in range(0, len(c) - L, a.step):
                w = c[i:i + L]
                jumps = np.abs(np.diff(w))
                if jumps.max() > max(np.log(1.35), t_maxjump * 1.2):   # likely bonus/split, skip
                    continue
                rng = w.max() - w.min()
                if not (0.6 * t_range <= rng <= 1.7 * t_range):          # similar size of move
                    continue
                W = znorm(resample_path(w, N))
                corr = float(np.dot(W, T) / N)
                if corr < 0.80:
                    continue
                rows.append((sym, sp, i, L, corr))
    if not rows:
        raise SystemExit('no matches with correlation >= 0.80')
    m = pd.DataFrame(rows, columns=['symbol', 'speed', 'i', 'L', 'corr'])

    # keep best non-overlapping window per symbol (max 2 per symbol)
    best = []
    for sym, g in m.sort_values('corr', ascending=False).groupby('symbol', sort=False):
        taken = []
        for r in g.itertuples():
            if all(abs(r.i - j) > r.L for j in taken):
                taken.append(r.i); best.append(r)
            if len(taken) == 2:
                break
    m = pd.DataFrame(best).sort_values('corr', ascending=False).head(a.top * 2)

    # ---------- describe each match + what came next ----------
    series = {s: g for s, g in d.groupby('symbol')}
    out_rows, paths = [], []
    for r in m.itertuples():
        g = series[r.symbol]
        if r.symbol == a.target:
            g = g[g.date < a.start]
        c = g.c.values; dt = g.date.values
        w = np.log(c[r.i:r.i + r.L])
        peak = np.exp(w.max() - w[0]) - 1
        endr = np.exp(w[-1] - w[0]) - 1
        dd = np.exp(w[-1] - w.max()) - 1
        rm = np.sqrt(np.mean((resample_path(w - w[0], N) - (tc - tc[0])) ** 2))
        e = r.i + r.L - 1
        fwd = {}
        for h in (20, 60, 120, 250):
            fwd[f'after_{h}d'] = (c[e + h] / c[e] - 1) if e + h < len(c) else np.nan
        fut = c[e:e + 251]
        fwd['max_up_next_year'] = fut.max() / c[e] - 1 if len(fut) > 20 else np.nan
        fwd['max_down_next_year'] = fut.min() / c[e] - 1 if len(fut) > 20 else np.nan
        out_rows.append(dict(symbol=r.symbol, start=pd.Timestamp(dt[r.i]).date(), end=pd.Timestamp(dt[e]).date(),
                             sessions=r.L, corr=round(r.corr, 3), shape_rmse=round(rm, 3),
                             peak=peak, end_vs_start=endr, end_vs_peak=dd,
                             price_start=c[r.i], price_end=c[e], **fwd))
        paths.append((r.symbol, pd.Timestamp(dt[r.i]).date(), resample_path(w - w[0], N)))
    res = pd.DataFrame(out_rows)
    # final score: shape correlation, penalised by size mismatch
    res['score'] = res['corr'] - 0.5 * res['shape_rmse']
    res = res.sort_values('score', ascending=False).head(a.top).reset_index(drop=True)
    pct = ['peak', 'end_vs_start', 'end_vs_peak', 'after_20d', 'after_60d', 'after_120d', 'after_250d',
           'max_up_next_year', 'max_down_next_year']
    show = res.copy()
    for k in pct:
        show[k] = (show[k] * 100).round(1)
    show.to_csv(out / 'matches.csv', index=False, encoding='utf-8-sig')
    pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
    print(show.drop(columns=['score']).to_string())

    # ---------- plot ----------
    try:
        import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(12, 6), dpi=130)
        x = np.linspace(0, 100, N)
        keep = {(s, str(st)) for s, st in zip(res.symbol.head(6), res.start.head(6).astype(str))}
        for s, st, p in paths:
            if (s, str(st)) in keep:
                ax.plot(x, 100 * np.exp(p), lw=1.2, alpha=.75, label=f'{s} from {st}')
        ax.plot(x, 100 * np.exp(tc - tc[0]), lw=3, color='black', label=f'{a.target} from {a.start}')
        ax.set_xlabel('% of the period'); ax.set_ylabel('rebased to 100'); ax.grid(alpha=.3); ax.legend(fontsize=8)
        ax.set_title(f'{a.target} vs historical look-alikes')
        fig.tight_layout(); fig.savefig(out / 'overlay.png')
    except Exception as ex:
        print('plot skipped:', ex)

    # ---------- Arabic summary ----------
    valid = res.dropna(subset=['after_120d'])
    lines = [f'نوفيدا من {a.start}: {N} جلسة، القمة {t_peak:+.0%} من البداية، ودلوقتي {t_end:+.0%} من البداية و{t_dd:+.0%} من القمة.',
             f'أقرب {len(res)} شبيه (معامل التشابه {res["corr"].min():.2f} لـ {res["corr"].max():.2f}):']
    for r in res.head(10).itertuples():
        nxt = '' if pd.isna(r.after_120d) else f' | بعدها بـ 120 جلسة: {r.after_120d:+.0%}'
        lines.append(f'- {r.symbol} من {r.start} لـ {r.end}: تشابه {r.corr:.2f}, قمة {r.peak:+.0%}, '
                     f'نزل من القمة {r.end_vs_peak:+.0%}{nxt}')
    if len(valid) >= 5:
        lines += ['', f'اللي حصل بعد نهاية الشبيه (من {len(valid)} حالة ليها بيانات كفاية):',
                  f'- بعد 60 جلسة: الوسيط {valid.after_60d.median():+.0%}، طلع في {(valid.after_60d > 0).mean():.0%} من الحالات',
                  f'- بعد 120 جلسة: الوسيط {valid.after_120d.median():+.0%}، طلع في {(valid.after_120d > 0).mean():.0%} من الحالات',
                  f'- أقصى صعود خلال سنة: الوسيط {valid.max_up_next_year.median():+.0%}',
                  f'- أقصى نزول خلال سنة: الوسيط {valid.max_down_next_year.median():+.0%}',
                  'تنبيه: ده تشابه في شكل الرسم بس، مش في ظروف الشركة، والعينة صغيرة.']
    (out / 'summary.txt').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))
    print(f'\nsaved -> {out}/matches.csv, overlay.png, summary.txt')


if __name__ == '__main__':
    main()
