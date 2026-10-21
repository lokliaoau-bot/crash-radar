# -*- coding: utf-8 -*-
"""数据下载：FRED（美联储圣路易斯分行）、Yahoo、席勒（shillerdata.com）。

每个序列单独缓存在 cache/。下载失败就用上次的缓存，并在报告里标明「旧数据」。
"""
import io
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")

# FRED 会拦「伪装成浏览器」的请求头（实测直接读超时）；没有 curl 时才用这个
FRED_HEADERS = {"User-Agent": "crash-radar/1.0"}
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}

FRED_IDS = [
    "NCBEILQ027S",   # 非金融企业股票市值（季度，百万美元）
    "GDP",           # 名义 GDP（季度年化，十亿美元）
    "T10Y3M",        # 10年期 − 3个月美债利差（日，1982起）
    "GS10",          # 10年期美债（月，1953起）——拼接1982年以前的收益率曲线
    "TB3MS",         # 3个月国库券（月）
    "DGS10",         # 10年期美债（日）——实时更新股债性价比
    "SAHMREALTIME",  # 萨姆规则（实时版，月）
    "BAA10Y",        # 穆迪 Baa 企业债 − 10年美债（日，1986起）
    "NFCI",          # 芝加哥联储金融状况指数（周，1971起）
    "DEXUSAL",       # 1澳元 = ? 美元（日）
    "DEXJPUS",       # 1美元 = ? 日元（日）
]
YAHOO_IDS = ["^GSPC", "^VIX", "AUDJPY=X"]
SOURCES = ["fred:" + s for s in FRED_IDS] + ["yahoo:" + s for s in YAHOO_IDS] + ["shiller"]

MAX_AGE = 6 * 3600   # 不强制刷新时，6 小时内的缓存直接用


def _cache_path(key):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    return os.path.join(CACHE, safe + ".csv")


def _series_from_csv(path):
    df = pd.read_csv(path, parse_dates=["date"])
    return pd.Series(df["value"].values, index=pd.DatetimeIndex(df["date"]), name=os.path.basename(path))


def _save_series(s, path):
    pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "value": s.values}).to_csv(path, index=False)


def _fred(sid):
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + sid
    text = None
    # 在 GitHub 云端机器上 FRED 只放行 curl（其它请求头一律读超时），本机两种都行，所以优先用 curl
    if shutil.which("curl"):
        p = subprocess.run(["curl", "-s", "-f", "-m", "30", url], capture_output=True, timeout=45)
        if p.returncode == 0 and p.stdout:
            text = p.stdout.decode("utf-8", "replace")
    if text is None:
        r = requests.get(url, headers=FRED_HEADERS, timeout=30)
        r.raise_for_status()
        text = r.text
    df = pd.read_csv(io.StringIO(text))
    v = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s = pd.Series(v.values, index=pd.to_datetime(df.iloc[:, 0])).dropna()
    if len(s) < 50:
        raise ValueError("FRED %s 只回来 %d 行" % (sid, len(s)))
    return s


def _yahoo(sym):
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/" + sym,
                     params={"period1": -1325635200, "period2": int(time.time()), "interval": "1d"},
                     headers=YAHOO_HEADERS, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    dates = pd.to_datetime([t + off for t in res["timestamp"]], unit="s").normalize()
    s = pd.Series(res["indicators"]["quote"][0]["close"], index=dates, dtype="float64").dropna()
    s = s[~s.index.duplicated(keep="last")]
    if len(s) < 500:
        raise ValueError("Yahoo %s 只回来 %d 行" % (sym, len(s)))
    return s


def _shiller_url():
    html = requests.get("https://shillerdata.com/", timeout=30).text
    m = re.search(r'href="([^"]*ie_data\.xls[^"]*)"', html)
    if not m:
        raise ValueError("shillerdata.com 首页找不到 ie_data.xls 链接")
    u = m.group(1)
    return "https:" + u if u.startswith("//") else u


def _shiller():
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


def _load_one(key, force):
    path = _cache_path(key)
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE
    if fresh and not force:
        return key, _read_cache(key, path), {"ok": True, "cached": True}
    try:
        if key.startswith("fred:"):
            data = _fred(key[5:])
            _save_series(data, path)
        elif key.startswith("yahoo:"):
            data = _yahoo(key[6:])
            _save_series(data, path)
        else:
            data = _shiller()
            data.reset_index().assign(date=lambda f: f["date"].dt.strftime("%Y-%m-%d")).to_csv(path, index=False)
        return key, data, {"ok": True, "cached": False}
    except Exception as e:  # 下载失败 → 用旧缓存
        if os.path.exists(path):
            age_h = (time.time() - os.path.getmtime(path)) / 3600
            return key, _read_cache(key, path), {"ok": False, "error": str(e)[:200], "stale_hours": round(age_h, 1)}
        return key, None, {"ok": False, "error": str(e)[:200]}


def _read_cache(key, path):
    if key == "shiller":
        return pd.read_csv(path, parse_dates=["date"]).set_index("date")
    return _series_from_csv(path)


def fetch_all(force=True):
    """并行下载全部数据源。返回 (data, status)。"""
    os.makedirs(CACHE, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda k: _load_one(k, force), SOURCES))
    data, status = {}, {}
    for key, d, st in results:
        name = key.split(":", 1)[-1]
        data[name] = d
        if d is not None and len(d):
            st["last"] = d.index[-1].strftime("%Y-%m-%d")
        status[name] = st
    return data, status
