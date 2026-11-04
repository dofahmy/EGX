#!/usr/bin/env python3
"""
tycoon_replay.py — scenario: "what if Novida (AMPI) followed Tycoon's path exactly".

Takes Tycoon's daily % moves and turnover (as % of its shares) between two dates,
and replays them on top of Novida's last close and Novida's share count.

    python3 tycoon_replay.py --csv /data/prices.csv --out /data/tycoon_replay
    (options: --src TYCN --dst AMPI --from 2025-12-09 --to 2026-06-17
              --src-shares 52250000 --dst-shares 29924028)

Outputs: replay.csv (day by day), replay.png (price + volume), summary.txt
This is a what-if scenario for reading, not a forecast and not a trading plan.
"""
import argparse
from pathlib import Path
import numpy as np, pandas as pd


def load(csv):
    d = pd.read_csv(csv)
    d.columns = [c.strip().lower() for c in d.columns]
    sym = 'ticker' if 'ticker' in d else 'symbol'
    d = d.rename(columns={sym: 'symbol'})
    d['symbol'] = d.symbol.astype(str).str.upper().str.replace('.CA', '', regex=False)
    d['date'] = pd.to_datetime(d.date)
    return d.sort_values(['symbol', 'date'])


def pick(d, names):
    for n in names:
        g = d[d.symbol == n]
        if len(g):
            return n, g.copy()
    near = [s for s in d.symbol.unique() if any(n[:3] in s for n in names)]
    raise SystemExit(f'none of {names} found. similar: {near[:20]}')


def unsplit(g):
    """undo splits / bonus shares: a one-day drop of >55% is treated as a corporate action."""
    g = g.copy()
    r = g.close / g.close.shift()
    for idx in g.index[r < 0.45]:
        f = round(1 / r[idx])
        if f >= 2:
            before = g.index < idx
            for k in ('open', 'high', 'low', 'close'):
                if k in g:
                    g.loc[before, k] = g.loc[before, k] / f
            if 'volume' in g:
                g.loc[before, 'volume'] = g.loc[before, 'volume'] * f
            print(f'  split/bonus detected on {g.loc[idx, "date"].date()} (1:{f}) - adjusted earlier prices')
    return g


def egx_days(start, n):
    out, d = [], start
    while len(out) < n:
        d += pd.Timedelta(days=1)
        if d.weekday() not in (4, 5):        # Fri, Sat closed
            out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default='/data/prices.csv')
    ap.add_argument('--src', default='TYCN,ANFI')
    ap.add_argument('--dst', default='AMPI')
    ap.add_argument('--from', dest='frm', default='2025-12-09')
    ap.add_argument('--to', default='2026-06-17')
    ap.add_argument('--src-shares', type=float, default=52_250_000, help='Tycoon shares after the 1:10 split')
    ap.add_argument('--dst-shares', type=float, default=29_924_028)
    ap.add_argument('--out', default='tycoon_replay')
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    d = load(a.csv)
    sname, s = pick(d, [x.strip().upper() for x in a.src.split(',')])
    dname, t = pick(d, [a.dst.upper()])
    s = unsplit(s)
    w = s[(s.date >= a.frm) & (s.date <= a.to)].reset_index(drop=True)
    if len(w) < 10:
        raise SystemExit(f'{sname}: only {len(w)} rows between {a.frm} and {a.to}')

    # Tycoon path, relative to the first day
    rel = {k: (w[k] / w.close.iloc[0]).values for k in ('open', 'high', 'low', 'close') if k in w}
    turn = (w.volume / a.src_shares).values            # daily turnover as share of all shares
    base_src = s[s.date < a.frm].tail(60)
    base_turn_src = (base_src.volume / a.src_shares).median()

    t = t.dropna(subset=['close'])
    p0 = float(t.close.iloc[-1]); day0 = t.date.iloc[-1]
    base_turn_dst = (t.tail(60).volume / a.dst_shares).median()

    dates = egx_days(day0, len(w))
    r = pd.DataFrame({'day': np.arange(1, len(w) + 1), 'date': [x.date() for x in dates],
                      'tycoon_date': w.date.dt.date})
    for k, v in rel.items():
        r[k] = np.round(p0 * v, 2)
    r['change_%'] = np.round(r.close.pct_change().fillna(r.close.iloc[0] / p0 - 1) * 100, 2)
    r['volume_same_turnover'] = np.round(turn * a.dst_shares).astype(int)          # same % of shares as Tycoon
    r['volume_scaled_to_novida'] = np.round(turn / base_turn_src * base_turn_dst * a.dst_shares).astype(int)
    r['vs_normal_volume_x'] = np.round(turn / base_turn_src, 1)
    r.to_csv(out / 'replay.csv', index=False, encoding='utf-8-sig')

    pk = r.close.idxmax()
    lines = [
        f'سيناريو: نوفيدا ماشية بالظبط زي {sname} من {a.frm} لـ {a.to} ({len(w)} جلسة).',
        f'نقطة البداية: آخر إغلاق لنوفيدا {p0:.2f} يوم {day0.date()}.',
        f'القمة في السيناريو: {r.close[pk]:.2f} (+{(r.close[pk]/p0-1)*100:.0f}%) في الجلسة {pk+1} ({r.date[pk]}).',
        f'آخر السيناريو: {r.close.iloc[-1]:.2f} ({(r.close.iloc[-1]/p0-1)*100:+.0f}%).',
        f'أكبر نزول من قمة لقاع جوه الطريق: {((r.close / r.close.cummax()) - 1).min()*100:.0f}%.',
        f'أيام صعود: {(r["change_%"] > 0).sum()} | أيام نزول: {(r["change_%"] < 0).sum()}',
        f'حجم تداول {sname} العادي قبل الحركة: {base_turn_src*100:.2f}% من أسهمه يوميًا؛ '
        f'ونوفيدا العادي: {base_turn_dst*100:.2f}% من أسهمها.',
        f'أعلى يوم حجم في السيناريو: {r.vs_normal_volume_x.max():.0f} ضعف الطبيعي (الجلسة {int(r.vs_normal_volume_x.idxmax())+1}).',
        '',
        'مراحل الطريق (كل 20 جلسة):',
    ]
    for i in range(0, len(r), 20):
        seg = r.iloc[i:i + 20]
        lines.append(f'- الجلسات {i+1}-{i+len(seg)}: من {seg.open.iloc[0] if "open" in seg else seg.close.iloc[0]:.2f} '
                     f'لـ {seg.close.iloc[-1]:.2f} | متوسط الحجم {seg.vs_normal_volume_x.mean():.1f}x الطبيعي')
    lines += ['', 'تنبيه: ده تقليد رياضي لشكل سهم تاني، مش توقع. تايكون نفسه بعد القمة الرقابة رفضت زيادة رأس ماله.']
    (out / 'summary.txt').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))

    try:
        import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
        fig, (ax, bx) = plt.subplots(2, 1, figsize=(13, 7), dpi=130, sharex=True,
                                     gridspec_kw={'height_ratios': [3, 1]})
        x = pd.to_datetime(r.date)
        ax.plot(pd.to_datetime(t.date.tail(120)), t.close.tail(120), color='gray', lw=1.2, label=f'{dname} actual')
        ax.plot(x, r.close, color='tab:green', lw=2, label=f'{dname} if it copies {sname}')
        ax.axhline(p0, color='gray', ls=':', lw=1)
        ax.scatter([x[pk]], [r.close[pk]], color='red', zorder=5)
        ax.annotate(f'{r.close[pk]:.2f}', (x[pk], r.close[pk]), textcoords='offset points', xytext=(5, 5))
        ax.set_ylabel('price (EGP)'); ax.grid(alpha=.3); ax.legend()
        bx.bar(x, r.volume_scaled_to_novida / 1e6, color='tab:blue', width=1)
        bx.set_ylabel('volume (M shares)'); bx.grid(alpha=.3)
        ax.set_title(f'Scenario: {dname} replaying {sname} {a.frm} -> {a.to}')
        fig.tight_layout(); fig.savefig(out / 'replay.png')
    except Exception as ex:
        print('plot skipped:', ex)
    print(f'\nsaved -> {out}/replay.csv, replay.png, summary.txt')


if __name__ == '__main__':
    main()
