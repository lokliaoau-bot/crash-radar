# -*- coding: utf-8 -*-
"""数据下载。每个序列有一串来源，按顺序试，第一个成功的就用：

    FRED（美联储圣路易斯分行）→ ALFRED（同一家的另一个站）→ 官方原始发布方（美国财政部、
    CBOE、欧洲央行）→ 上一次的缓存

新数据和缓存合并（新的覆盖旧的，缓存补上新来源缺的年份），所以「只给近几年」的备用来源也能用。
是否「数据偏旧」看数据本身的日期，不看这一轮有没有下载成功。
"""
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")

# FRED 会拦「伪装成浏览器」的请求头；在 GitHub 云端机器上更严：时好时坏，连 curl 也常被拦
# （2026-10-21 实测：5 次定时运行里 4 次 11 个序列全部读超时）。所以它只是第一顺位，后面都有备胎。
FRED_HEADERS = {"User-Agent": "crash-radar/1.0"}
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}
MAX_AGE = 6 * 3600          # 不强制刷新时，6 小时内的缓存直接用
HOST_FAILS_TO_SKIP = 2      # 同一个站这一轮连续失败 2 次，后面的序列就不再找它（省得每个都等超时）

# 数据日期超过多少天算「偏旧」（按发布节奏留余量：季度数据要等下个季度公布，可以旧到 200 多天）
MAX_DAYS = {
    "NCBEILQ027S": 270, "GDP": 230, "SAHMREALTIME": 75, "NFCI": 16,
    "T10Y3M": 7, "DGS10": 7, "BAA10Y": 7, "GS10": 400, "TB3MS": 400, "DEXUSAL": 60, "DEXJPUS": 60,
    "^GSPC": 5, "^VIX": 5, "AUDJPY=X": 5, "shiller": 62,
}


# ---------------------------------------------------------------- 站点熔断

_fails, _lock = {}, threading.Lock()


def _host(url):
    return url.split("/")[2]


def _blocked(url):
    # 测试用：CRASH_RADAR_BLOCK="fred.stlouisfed.org,query1.finance.yahoo.com" 模拟这些站连不上
    if _host(url) in os.environ.get("CRASH_RADAR_BLOCK", "").split(","):
        return True
    with _lock:
        return _fails.get(_host(url), 0) >= HOST_FAILS_TO_SKIP


def _guard(url):
    if _blocked(url):
        raise RuntimeError("%s 这一轮已连续失败，跳过" % _host(url))


def _mark(url, ok):
    with _lock:
        h = _host(url)
        _fails[h] = 0 if ok else _fails.get(h, 0) + 1


def _get_text(url, timeout=15, curl=False, headers=None):
    """下载文本。curl=True 时优先用系统 curl（FRED 在云端只放行 curl）。"""
    _guard(url)
    try:
        if curl and shutil.which("curl"):
            p = subprocess.run(["curl", "-s", "-f", "-L", "-m", str(timeout), url],
                               capture_output=True, timeout=timeout + 10)
            if p.returncode != 0 or not p.stdout:
                raise RuntimeError("curl 退出码 %d" % p.returncode)
            text = p.stdout.decode("utf-8", "replace")
        else:
            r = requests.get(url, headers=headers or FRED_HEADERS, timeout=timeout)
            r.raise_for_status()
            text = r.text
    except Exception:
        _mark(url, False)
        raise
    _mark(url, True)
    return text


def _csv_series(text, date_col=0, value_col=1, date_format=None):
    df = pd.read_csv(io.StringIO(text))
    v = pd.to_numeric(df.iloc[:, value_col] if isinstance(value_col, int) else df[value_col], errors="coerce")
    d = pd.to_datetime(df.iloc[:, date_col] if isinstance(date_col, int) else df[date_col], format=date_format)
    s = pd.Series(v.values, index=pd.DatetimeIndex(d)).dropna().sort_index()
    return s[~s.index.duplicated(keep="last")]


# ---------------------------------------------------------------- 各个来源

def _api_key():
    k = os.environ.get("FRED_API_KEY", "").strip()
    if not k:
        p = os.path.join(ROOT, "fred_api_key.txt")      # 本机可选：放一个文件（已在 .gitignore）
        if os.path.exists(p):
            k = open(p, encoding="utf-8").read().strip()
    return k


def fred_api(sid):
    """FRED 官方接口，要免费的 API key；有 key 时最稳（任何机器都能连）。"""
    key = _api_key()
    if not key:
        raise RuntimeError("没有 FRED_API_KEY")
    url = ("https://api.stlouisfed.org/fred/series/observations?series_id=%s&api_key=%s&file_type=json"
           % (sid, key))
    obs = json.loads(_get_text(url, timeout=20))["observations"]
    s = pd.Series(pd.to_numeric([o["value"] for o in obs], errors="coerce"),
                  index=pd.to_datetime([o["date"] for o in obs])).dropna()
    return s


def fred_graph(sid):
    return _csv_series(_get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + sid, curl=True))


def alfred_graph(sid):
    # 列名带版本日期（如 BAA10Y_20261022），内容和 FRED 最新版一样
    return _csv_series(_get_text("https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=" + sid, curl=True))


def _treasury_years():
    t = pd.Timestamp.today()
    return [t.year - 1, t.year] if t.month == 1 else [t.year]   # 一月初也拿上一年，免得跨年断档


def _treasury(col_long, col_short=None):
    parts = []
    for y in _treasury_years():
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
               "%d/all?type=daily_treasury_yield_curve&field_tdr_date_value=%d&page&_format=csv" % (y, y))
        df = pd.read_csv(io.StringIO(_get_text(url, timeout=45, headers=YAHOO_HEADERS)))
        d = pd.to_datetime(df["Date"], format="%m/%d/%Y")
        v = pd.to_numeric(df[col_long], errors="coerce")
        if col_short:
            v = v - pd.to_numeric(df[col_short], errors="coerce")
        parts.append(pd.Series(v.values, index=d))
    return pd.concat(parts).dropna().sort_index().round(2)


def treasury_10y3m(_):
    """FRED 的 T10Y3M 就是财政部 10 年期减 3 个月（同一份数据），只给今年。"""
    return _treasury("10 Yr", "3 Mo")


def treasury_10y(_):
    return _treasury("10 Yr")


def _yahoo(sym, host):
    url = "https://%s/v8/finance/chart/%s" % (host, sym)
    _guard(url)
    try:
        r = requests.get(url, params={"period1": -1325635200, "period2": int(time.time()), "interval": "1d"},
                         headers=YAHOO_HEADERS, timeout=30)
        r.raise_for_status()
    except Exception:
        _mark(url, False)
        raise
    _mark(url, True)
    res = r.json()["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    dates = pd.to_datetime([t + off for t in res["timestamp"]], unit="s").normalize()
    s = pd.Series(res["indicators"]["quote"][0]["close"], index=dates, dtype="float64").dropna()
    return s[~s.index.duplicated(keep="last")]


def yahoo1(sym):
    return _yahoo(sym, "query1.finance.yahoo.com")


def yahoo2(sym):
    return _yahoo(sym, "query2.finance.yahoo.com")


def cboe_vix(_):
    text = _get_text("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
                     timeout=30, curl=True)
    return _csv_series(text, "DATE", "CLOSE", "%m/%d/%Y")


def fred_sp500(_):
    return fred_graph("SP500")          # 只有近 10 年，靠和缓存合并补全历史


def ecb_audjpy(_):
    """欧洲央行参考汇率：日元/欧元 ÷ 澳元/欧元 = 澳元兑日元（1999 年起）。"""
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
    _guard(url)
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        df = pd.read_csv(z.open(z.namelist()[0]))
    d = pd.to_datetime(df["Date"])
    s = pd.to_numeric(df["JPY"], errors="coerce") / pd.to_numeric(df["AUD"], errors="coerce")
    return pd.Series(s.values, index=d).dropna().sort_index()


def _shiller_url():
    _guard("https://shillerdata.com/")
    html = requests.get("https://shillerdata.com/", timeout=30).text
    m = re.search(r'href="([^"]*ie_data\.xls[^"]*)"', html)
    if not m:
        raise ValueError("shillerdata.com 首页找不到 ie_data.xls 链接")
    u = m.group(1)
    return "https:" + u if u.startswith("//") else u


def shiller(_):
    """席勒月度数据：S&P 均价、CAPE、超额CAPE收益率、10年期利率。"""
    r = requests.get(_shiller_url(), timeout=60)
    r.raise_for_status()
    x = pd.read_excel(io.BytesIO(r.content), sheet_name="Data", header=None, engine="xlrd")
    head = [str(v).strip() for v in x.iloc[7]]
    if head[0] != "Date" or head[12] != "CAPE" or head[16] != "Yield":
        raise ValueError("席勒表格式变了：%s" % head[:17])
    body = x.iloc[8:]
    body = body[pd.to_numeric(body[0], errors="coerce").notna()]
    d = body[0].astype(float)
    year = d.astype(int)
    month = ((d - year) * 100).round().astype(int)   # 2026.1 是十月，2026.01 是一月
    idx = pd.to_datetime(dict(year=year, month=month, day=1)) + pd.offsets.MonthEnd(0)
    df = pd.DataFrame({
        "P": pd.to_numeric(body[1], errors="coerce").values,
        "CAPE": pd.to_numeric(body[12], errors="coerce").values,
        "ECY": pd.to_numeric(body[16], errors="coerce").values,
        "GS10": pd.to_numeric(body[6], errors="coerce").values,
    }, index=pd.DatetimeIndex(idx, name="date"))
    if df["CAPE"].dropna().shape[0] < 1500:
        raise ValueError("席勒表 CAPE 行数太少")
    return df


# ---------------------------------------------------------------- 每个序列的来源顺序

_FRED = [fred_api, fred_graph, alfred_graph]
CHAINS = {
    "NCBEILQ027S": _FRED, "GDP": _FRED, "GS10": _FRED, "TB3MS": _FRED, "SAHMREALTIME": _FRED,
    "BAA10Y": _FRED, "DEXUSAL": _FRED, "DEXJPUS": _FRED,
    "T10Y3M": [fred_api, fred_graph, treasury_10y3m, alfred_graph],
    "DGS10": [fred_api, fred_graph, treasury_10y, alfred_graph],
    # 芝加哥联储自己的 CSV（nfci-data-series-csv.csv）2026-04 起就不更新了，新地址藏在网页脚本里，所以只靠 FRED
    "NFCI": _FRED,
    "^GSPC": [yahoo1, yahoo2, fred_sp500],
    "^VIX": [yahoo1, yahoo2, cboe_vix],
    "AUDJPY=X": [yahoo1, yahoo2, ecb_audjpy],
    "shiller": [shiller],
}
# 只给近几年的备用来源：必须和缓存合并才能用
PARTIAL = {treasury_10y3m, treasury_10y, fred_sp500}
# 口径略有不同的备用来源（欧洲央行是午盘定盘价，不是收盘价）：只接在缓存后面，不改写历史
APPEND_ONLY = {ecb_audjpy}


# ---------------------------------------------------------------- 缓存

def _cache_path(name):
    return os.path.join(CACHE, re.sub(r"[^A-Za-z0-9_.-]", "_", name) + ".csv")


def _read_cache(name):
    path = _cache_path(name)
    if not os.path.exists(path):
        # 2026-10-22 之前的缓存叫 fred_NFCI.csv / yahoo__GSPC.csv，云端缓存里还是旧名字，接着用
        legacy = [p for p in (_cache_path("fred:" + name), _cache_path("yahoo:" + name)) if os.path.exists(p)]
        if not legacy:
            return None
        path = legacy[0]
    if name == "shiller":
        return pd.read_csv(path, parse_dates=["date"]).set_index("date")
    df = pd.read_csv(path, parse_dates=["date"])
    return pd.Series(df["value"].values, index=pd.DatetimeIndex(df["date"]))


def _write_cache(name, data):
    path = _cache_path(name)
    tmp = path + ".tmp"
    if name == "shiller":
        data.reset_index().assign(date=lambda f: f["date"].dt.strftime("%Y-%m-%d")).to_csv(tmp, index=False)
    else:
        pd.DataFrame({"date": data.index.strftime("%Y-%m-%d"), "value": data.values}).to_csv(tmp, index=False)
    os.replace(tmp, path)          # 先写临时文件再改名，写到一半断掉也不会弄坏缓存


def _merge(new, old):
    if old is None or len(old) == 0:
        return new
    out = new.combine_first(old)   # 同一天以新数据为准；缓存补上新来源没有的日子
    return out[~out.index.duplicated(keep="last")].sort_index()


def _age_days(name, data):
    last = data.index[-1]
    if name == "shiller":            # 席勒的当月行标在月底（未来日期），按月份算
        last = min(last, pd.Timestamp.today().normalize())
    return int((pd.Timestamp.today().normalize() - last.normalize()).days)


def _load_one(name, force):
    cached = _read_cache(name)
    path = _cache_path(name)
    if cached is not None and not force and time.time() - os.path.getmtime(path) < MAX_AGE:
        return name, cached, {"via": "缓存"}
    errors = []
    for fn in CHAINS[name]:
        try:
            new = fn(name)
            if new is None or len(new) == 0:
                raise ValueError("空数据")
            if fn in PARTIAL and (cached is None or len(cached) < 100):
                raise ValueError("只有近几年，又没有缓存可以合并")
            if fn not in PARTIAL and len(new) < 50:
                raise ValueError("只有 %d 行" % len(new))
            if fn in APPEND_ONLY and cached is not None and len(cached):
                new = new[new.index > cached.index[-1]]
            data = _merge(new, cached)
            _write_cache(name, data)
            return name, data, {"via": fn.__name__, "errors": errors}
        except Exception as e:
            errors.append("%s: %s" % (fn.__name__, str(e)[:120]))
    return name, cached, {"via": "缓存" if cached is not None else None, "errors": errors}


def fetch_all(force=True):
    """并行下载全部数据源。返回 (data, status)；status 里 stale=True 表示数据日期已经太旧。"""
    os.makedirs(CACHE, exist_ok=True)
    _fails.clear()
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda n: _load_one(n, force), CHAINS))
    data, status = {}, {}
    for name, d, st in results:
        data[name] = d
        if d is not None and len(d):
            st["last"] = d.index[-1].strftime("%Y-%m-%d")
            st["age_days"] = _age_days(name, d)
            st["stale"] = st["age_days"] > MAX_DAYS[name]
        else:
            st["stale"] = True
        status[name] = st
    return data, status
