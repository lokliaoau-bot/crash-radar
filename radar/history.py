# -*- coding: utf-8 -*-
"""检验每个灯「历史上准不准」。

「股灾」＝ 从某个月底算起，未来 12 个月内标普 500 最多跌掉 20% 以上（不管后来有没有涨回来）。
两个数字：
  1. 亮红灯的月份里，后来真的出股灾的比例 vs. 所有月份的平均比例（平时）。
  2. 每一次熊市（见顶后跌 ≥20%），见顶前一年到跌满 10% 之间有没有亮过红灯。
月份前后重叠、熊市次数又少，这些数字只能当参考，不能当成精确概率。
"""
import numpy as np
import pandas as pd

from .indicators import RED

CRASH = -0.20
HORIZON = pd.Timedelta(days=365)


def forward_crash(spx):
    """每个月底：未来 12 个月内最低价相对当时跌了 ≥20% 吗？最近 12 个月没法判，不算。"""
    me = pd.date_range(spx.index[0], spx.index[-1] - HORIZON, freq="ME")
    vals = spx.values
    idx = spx.index
    out = []
    for t in me:
        i0 = idx.searchsorted(t, side="right") - 1
        i1 = idx.searchsorted(t + HORIZON, side="right")
        p0 = vals[i0]
        out.append(vals[i0 + 1:i1].min() / p0 - 1 <= CRASH)
    return pd.Series(out, index=me)


def bear_markets(spx, th=0.20):
    """之字形找熊市：跌 ≥20% 算熊市，从低点涨回 20% 算结束（一年内再跌的并回去）。返回 [(见顶日, 跌满10%的日子, 低点日)]。"""
    mode, ext_v, ext_d = "up", spx.iloc[0], spx.index[0]
    peaks = []
    for d, p in spx.items():
        if mode == "up":
            if p > ext_v:
                ext_v, ext_d = p, d
            elif p <= ext_v * (1 - th):
                peaks.append([ext_d, ext_v, None])
                mode, ext_v, ext_d = "down", p, d
        else:
            if p < ext_v:
                ext_v, ext_d = p, d
            elif p >= ext_v * (1 + th):
                peaks[-1][2] = ext_d
                mode, ext_v, ext_d = "up", p, d
    if mode == "down":
        peaks[-1][2] = ext_d
    # 低点后不到一年又「见顶」再跌 20%，算同一次熊市（1929-32、2000-02、2007-09 各算一次）
    merged = []
    for pk in peaks:
        if merged and pk[0] - merged[-1][2] < pd.Timedelta(days=365):
            merged[-1][2] = pk[2]
        else:
            merged.append(list(pk))
    out = []
    for pk_d, pk_v, tr_d in merged:
        after = spx[pk_d:]
        d10 = after.index[np.argmax(after.values <= pk_v * 0.9)]
        out.append((pk_d, d10, tr_d))
    return out


def evaluate(lights, crash, bears):
    """lights: 每个时点的灯（索引=当时已经知道的日期）。"""
    lights = lights.dropna()
    if lights.empty:
        return None
    start = lights.index[0]
    m = lights.reindex(crash.index, method="ffill")
    ok = m.notna() & (crash.index >= start)
    m, c = m[ok], crash[ok]
    if len(c) < 60:
        return None
    base = float(c.mean())
    red = m == RED
    n_red = int(red.sum())
    p_red = float(c[red].mean()) if n_red else None

    caught, total, rows = 0, 0, []
    for pk, d10, tr in bears:
        if pk - HORIZON < start:
            continue
        total += 1
        w = lights[(lights.index >= pk - HORIZON) & (lights.index <= d10)]
        hit = bool((w == RED).any())
        caught += hit
        rows.append({"peak": pk.strftime("%Y-%m"), "hit": hit})

    if n_red < 12 or total < 3:
        verdict = "样本太少"
    else:
        lift = p_red / base if base > 0 else np.nan
        if lift >= 1.5 and caught / total >= 0.5:
            verdict = "有用"
        elif lift >= 1.2:
            verdict = "有点用"
        elif lift <= 0.8:
            verdict = "反着来"
        else:
            verdict = "看不出"
    return {
        "since": c.index[0].strftime("%Y"),      # 实际检验起点（灯和标普日线都有数据之后）
        "months": int(len(c)),
        "base": round(base * 100),
        "red_months": n_red,
        "p_red": None if p_red is None else round(p_red * 100),
        "bears": total,
        "caught": caught,
        "episodes": rows,
        "verdict": verdict,
    }


def composite_lights(all_lights, need=3):
    """同时亮 ≥need 个红灯算「多灯齐亮」。只在 10 个指标都有数据的月份（1990 年以后）算。"""
    me = pd.date_range("1928-01-31", pd.Timestamp.today(), freq="ME")
    frame = pd.DataFrame({k: v.dropna().reindex(me, method="ffill") for k, v in all_lights.items()})
    full = frame.notna().all(axis=1)
    reds = (frame == RED).sum(axis=1)
    return pd.Series(np.where(reds >= need, RED, 0), index=me)[full], reds[full]
