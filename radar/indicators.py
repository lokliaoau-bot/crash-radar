# -*- coding: utf-8 -*-
"""10 个股灾预警指标。

每个指标返回：现在的读数、红黄绿灯、以及「历史上每个时点的灯」（只用当时已经能拿到的数据，
供 history.py 检验它准不准）。所有红黄灯门槛都是事先定好的常用标准，没有拿历史数据去调。
"""
import numpy as np
import pandas as pd

RED, YEL, GRN = 2, 1, 0

GROUPS = [
    ("value", "贵不贵", "只说明跌起来会多深，不管什么时候跌"),
    ("economy", "经济会不会衰退", "衰退通常伴随股市大跌"),
    ("stress", "现在有没有在出事", "反应快，但提前量短"),
]


def _pct_expanding(vals, min_n):
    """每个时点的值在它之前（含当时）全部历史里的百分位。只看过去，不偷看未来。"""
    out = np.full(len(vals), np.nan)
    for i in range(min_n - 1, len(vals)):
        out[i] = (vals[:i + 1] <= vals[i]).mean() * 100
    return out


def _pct_lights(s, min_n, high_is_bad=True):
    pct = pd.Series(_pct_expanding(s.values, min_n), index=s.index)
    risk = pct if high_is_bad else 100 - pct
    light = pd.Series(np.where(risk >= 90, RED, np.where(risk >= 75, YEL, GRN)), index=s.index)
    return pct, light.where(pct.notna())


def _quantile_line(s, q):
    return float(np.nanquantile(s.values, q))


def _append_live(s, ts, v):
    """历史序列末尾接上「今天」这一点（同一天已有的旧值让位）。"""
    return pd.concat([s[s.index < ts], pd.Series([v], index=[ts])])


def _d(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 贵不贵

def buffett(d):
    eq, gdp, spx = d["NCBEILQ027S"], d["GDP"], d["^GSPC"]
    qe = eq.index + pd.offsets.QuarterEnd(0)
    spx_qe = spx.reindex(qe, method="ffill").values
    # 美联储季度数据约 2.5 个月后才公布，回测时按 90 天后才「知道」；GDP 按 30 天
    z = pd.DataFrame({"eq": eq.values / 1000.0, "spx_qe": spx_qe}, index=qe + pd.Timedelta(days=90))
    g = pd.Series(gdp.values, index=gdp.index + pd.offsets.QuarterEnd(0) + pd.Timedelta(days=30))
    me = pd.date_range("1947-01-31", spx.index[-1], freq="ME")
    zm, gm = z.reindex(me, method="ffill"), g.reindex(me, method="ffill")
    ratio = (zm["eq"] * spx.reindex(me, method="ffill") / zm["spx_qe"] / gm * 100).dropna()
    # 今天：最新一季市值按标普涨跌推到今天，除以最新 GDP
    live = eq.iloc[-1] / 1000.0 * spx.iloc[-1] / spx.asof(qe[-1]) / gdp.iloc[-1] * 100
    s = _append_live(ratio, spx.index[-1], live)
    pct, lights = _pct_lights(s, 240)
    p = pct.iloc[-1]
    return dict(value=live, display="%.0f%%" % live, sub="比历史上 %.0f%% 的时候都贵" % p,
                light=int(lights.iloc[-1]), as_of=_d(spx.index[-1]), series=s, lights=lights,
                lines=[(_quantile_line(s, .75), YEL), (_quantile_line(s, .90), RED)],
                note="季度市值 %s，GDP %s" % (_d(qe[-1]), _d(gdp.index[-1] + pd.offsets.QuarterEnd(0))))


def _shiller_hist(d):
    """席勒月度表去掉还没过完的当月（它用月初价），今天的值另算。"""
    sh, spx = d["shiller"], d["^GSPC"]
    last = sh.dropna(subset=["CAPE"]).iloc[-1]
    hist = sh[sh.index <= spx.index[-1]].dropna(subset=["CAPE"])
    return sh, spx, last, hist


def cape(d):
    sh, spx, last, hist = _shiller_hist(d)
    e10 = last["P"] / last["CAPE"]                # 10 年平均实际利润（换算到当前价格单位）
    live = spx.iloc[-1] / e10
    s = _append_live(hist["CAPE"], spx.index[-1], live)
    pct, lights = _pct_lights(s, 240)
    return dict(value=live, display="%.1f" % live, sub="比历史上 %.0f%% 的时候都贵" % pct.iloc[-1],
                light=int(lights.iloc[-1]), as_of=_d(spx.index[-1]), series=s, lights=lights,
                lines=[(_quantile_line(s, .75), YEL), (_quantile_line(s, .90), RED)],
                note="席勒数据 %s" % _d(sh.dropna(subset=["CAPE"]).index[-1])[:7])


def ecy(d):
    sh, spx, last, hist = _shiller_hist(d)
    e10 = last["P"] / last["CAPE"]
    cape_now = spx.iloc[-1] / e10
    dgs10 = d["DGS10"]
    # 席勒最新一行 + 之后股价和 10 年利率的变化
    live = last["ECY"] + (1 / cape_now - 1 / last["CAPE"]) - (dgs10.iloc[-1] - last["GS10"]) / 100
    base = hist["ECY"].dropna() * 100
    s = _append_live(base, spx.index[-1], live * 100)
    pct, lights = _pct_lights(s, 240, high_is_bad=False)
    return dict(value=live * 100, display="%.2f%%" % (live * 100),
                sub="比历史上 %.0f%% 的时候都低" % (100 - pct.iloc[-1]),
                light=int(lights.iloc[-1]), as_of=_d(min(spx.index[-1], dgs10.index[-1])),
                series=s, lights=lights,
                lines=[(_quantile_line(s, .25), YEL), (_quantile_line(s, .10), RED)])


# ---------------------------------------------------------------- 经济

def yield_curve(d):
    # 用月平均判断倒挂（美联储研究的惯例），偶尔一两天轻微倒挂不算
    pre = (d["GS10"] - d["TB3MS"]).dropna()
    pre.index = pre.index + pd.offsets.MonthEnd(0)
    pre = pre[pre.index < "1982-01-01"]
    daily = d["T10Y3M"]
    post = daily.resample("ME").mean()
    post.index = post.index[:-1].append(pd.DatetimeIndex([daily.index[-1]]))   # 当月只到今天
    yc = pd.concat([pre, post])
    recent_min = yc.rolling(13).min()                   # 当月 + 前 12 个月
    lights = pd.Series(np.where(yc < 0, YEL, np.where(recent_min < 0, RED, GRN)), index=yc.index)
    inv = yc[yc < 0]
    if yc.iloc[-1] < 0:
        sub = "正在倒挂"
    elif lights.iloc[-1] == RED:
        sub = "倒挂刚结束（%s）" % _d(inv.index[-1])[:7]
    elif len(inv):
        sub = "上次倒挂结束于 %s" % _d(inv.index[-1])[:7]
    else:
        sub = "没有倒挂"
    v = daily.iloc[-1]
    return dict(value=v, display="%+.2f%%" % v, sub=sub, light=int(lights.iloc[-1]),
                as_of=_d(daily.index[-1]), series=yc, lights=lights, lines=[(0.0, YEL)])


def sahm(d):
    s = d["SAHMREALTIME"]
    avail = s.index + pd.offsets.MonthEnd(1) + pd.offsets.MonthEnd(1)   # 次月初公布
    lights = pd.Series(np.where(s >= 0.5, RED, np.where(s >= 0.3, YEL, GRN)), index=avail)
    v = s.iloc[-1]
    sub = "失业率在快速上升" if v >= 0.3 else "失业率没有快速上升"
    return dict(value=v, display="%.2f" % v, sub=sub, light=int(lights.iloc[-1]),
                as_of=_d(s.index[-1])[:7], series=pd.Series(s.values, index=avail), lights=lights,
                lines=[(0.3, YEL), (0.5, RED)])


# ---------------------------------------------------------------- 压力

def credit(d):
    s = d["BAA10Y"]
    widen = s - s.rolling("182D").min()
    ok = s.index >= s.index[0] + pd.Timedelta(days=182)
    lights = pd.Series(np.where(widen >= 0.6, RED, np.where(widen >= 0.3, YEL, GRN)), index=s.index)[ok]
    return dict(value=s.iloc[-1], display="%.2f%%" % s.iloc[-1], sub="半年内 %+.2f" % widen.iloc[-1],
                light=int(lights.iloc[-1]), as_of=_d(s.index[-1]), series=s, lights=lights, lines=[])


def nfci(d):
    s = d["NFCI"]
    avail = s.index + pd.Timedelta(days=5)                 # 周五数据，下周三公布
    lights = pd.Series(np.where(s >= 0, RED, np.where(s >= -0.25, YEL, GRN)), index=avail)
    v = s.iloc[-1]
    sub = "比平时紧" if v >= 0 else ("接近平时" if v >= -0.25 else "比平时宽松")
    return dict(value=v, display="%.2f" % v, sub=sub, light=int(lights.iloc[-1]), as_of=_d(s.index[-1]),
                series=pd.Series(s.values, index=avail), lights=lights, lines=[(-0.25, YEL), (0.0, RED)])


def vix(d):
    s = d["^VIX"]
    lights = pd.Series(np.where(s >= 30, RED, np.where(s >= 20, YEL, GRN)), index=s.index)
    v = s.iloc[-1]
    sub = "恐慌" if v >= 30 else ("紧张" if v >= 20 else "平静")
    return dict(value=v, display="%.1f" % v, sub=sub, light=int(lights.iloc[-1]), as_of=_d(s.index[-1]),
                series=s, lights=lights, lines=[(20.0, YEL), (30.0, RED)])


def trend(d):
    spx = d["^GSPC"]
    ma = spx.rolling(200).mean()
    dist = (spx / ma - 1) * 100
    below, falling = spx < ma, ma < ma.shift(20)
    lights = pd.Series(np.where(below & falling, RED, np.where(below, YEL, GRN)), index=spx.index)
    lights = lights[ma.shift(20).notna()]
    v = dist.iloc[-1]
    sub = "在 200 日均线上方" if v >= 0 else ("跌破均线，均线也在下行" if lights.iloc[-1] == RED else "跌破 200 日均线")
    return dict(value=v, display="%+.1f%%" % v, sub=sub, light=int(lights.iloc[-1]), as_of=_d(spx.index[-1]),
                series=dist.dropna(), lights=lights, lines=[(0.0, YEL)],
                note="标普500 %.0f" % spx.iloc[-1])


def audjpy(d):
    fx = (d["DEXUSAL"] * d["DEXJPUS"]).dropna()
    fx = fx[fx.index >= "1984-01-01"]                       # 1983 年底澳元才自由浮动
    y = d["AUDJPY=X"]
    fx = pd.concat([fx, y[y.index > fx.index[-1]]])
    lag = fx.reindex(fx.index - pd.Timedelta(days=91), method="ffill").values
    chg = pd.Series(fx.values / lag - 1, index=fx.index) * 100
    lights = pd.Series(np.where(chg <= -10, RED, np.where(chg <= -5, YEL, GRN)), index=fx.index)[chg.notna()]
    return dict(value=fx.iloc[-1], display="%.1f" % fx.iloc[-1], sub="3个月 %+.1f%%" % chg.iloc[-1],
                light=int(lights.iloc[-1]), as_of=_d(fx.index[-1]), series=fx, lights=lights, lines=[])


# ---------------------------------------------------------------- 文案（大白话，越短越好）

SPECS = [
    dict(key="buffett", deps=["NCBEILQ027S", "GDP", "^GSPC"], group="value", name="巴菲特指标", fn=buffett,
         explain="美股总市值 ÷ 美国 GDP，越高越贵。",
         sectors="科技、高估值成长股跌得最深",
         tip="巴菲特说这是衡量估值最好的单一指标。用美联储季度的企业股票市值，按标普最新涨跌推到今天，"
             "再除以最新 GDP。红灯＝比历史 90% 的时候都贵，黄灯＝75%。"),
    dict(key="cape", deps=["shiller", "^GSPC"], group="value", name="席勒市盈率", fn=cape,
         explain="股价 ÷ 过去 10 年平均利润，越高越贵。",
         sectors="全市场，尤其科技、成长股",
         tip="用 10 年平均利润（扣掉通胀），避免某一年利润特别好或特别差造成假象。"
             "红灯＝比历史 90% 的时候都贵，黄灯＝75%。"),
    dict(key="ecy", deps=["shiller", "^GSPC", "DGS10"], group="value", name="股债性价比", fn=ecy,
         explain="买股票比买国债多赚多少，越低越不划算。",
         sectors="高估值股承压；高股息股、债券相对占优",
         tip="席勒的「超额 CAPE 收益率」＝股票盈利收益率（1÷席勒市盈率）减国债实际利率。"
             "红灯＝比历史 90% 的时候都低，黄灯＝75%。"),
    dict(key="yield", deps=["T10Y3M"], group="economy", name="收益率曲线", fn=yield_curve,
         explain="长期利率比短期还低叫「倒挂」，常是衰退前兆。",
         sectors="银行（息差变薄）、周期股",
         tip="10 年期减 3 个月美债利率（按月平均判断）。黄灯＝正在倒挂；红灯＝倒挂刚结束（过去 12 个月倒挂过、现在翻正），"
             "历史上衰退多在这时开始。"),
    dict(key="sahm", deps=["SAHMREALTIME"], group="economy", name="萨姆规则", fn=sahm,
         explain="失业率快速上升就报警，衰退的早期信号。",
         sectors="零售、可选消费、银行坏账",
         tip="失业率 3 个月均值比过去 12 个月的最低点高出多少个百分点。≥0.5 红灯，≥0.3 黄灯。"),
    dict(key="credit", deps=["BAA10Y"], group="stress", name="企业债利差", fn=credit,
         explain="公司借钱比国家贵多少；突然变贵＝有人怕违约。",
         sectors="高负债公司、小盘股、房地产",
         tip="穆迪 Baa 企业债减 10 年美债利率。看半年内扩大了多少：≥0.6 个百分点红灯，≥0.3 黄灯。"),
    dict(key="nfci", deps=["NFCI"], group="stress", name="金融压力指数", fn=nfci,
         explain="借钱难不难、市场紧不紧；高于 0＝比平时紧。",
         sectors="银行、券商、保险",
         tip="芝加哥联储金融状况指数，汇总 105 个信贷、股市、银行指标。≥0 红灯，≥−0.25 黄灯。"),
    dict(key="vix", deps=["^VIX"], group="stress", name="恐慌指数 VIX", fn=vix,
         explain="市场预计未来一个月波动多大，越高越慌。",
         sectors="科技、小盘先跌；黄金、国债受益",
         tip="≥30 红灯（恐慌），≥20 黄灯（紧张）。它通常和下跌同时出现，提前量很少。"),
    dict(key="trend", deps=["^GSPC"], group="stress", name="大盘趋势", fn=trend,
         explain="标普 500 跌破 200 日均线、均线向下＝熊市走势。",
         sectors="全市场",
         tip="数字是标普 500 比 200 日均线高（低）多少。黄灯＝跌破均线；红灯＝跌破且均线本身在下行"
             "（比 20 个交易日前低）。"),
    dict(key="audjpy", deps=["AUDJPY=X"], group="stress", name="澳元兑日元", fn=audjpy,
         explain="全球风险胃口温度计；急跌＝资金在逃。",
         sectors="澳股矿业、能源、澳元资产",
         tip="澳元是「风险货币」，日元是「避险货币」。看 3 个月涨跌：≤−10% 红灯，≤−5% 黄灯。"
             "1984 年澳元自由浮动以后才计入历史。"),
]
