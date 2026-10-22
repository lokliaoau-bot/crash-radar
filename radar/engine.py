# -*- coding: utf-8 -*-
"""抓数据 → 算 10 个指标 → 检验历史 → 生成报告 JSON。"""
import json
import os
import time
import traceback

import numpy as np
import pandas as pd

from . import fetch, history
from .indicators import GROUPS, GRN, RED, SPECS, YEL

REPORT_PATH = os.path.join(fetch.CACHE, "report.json")
LIGHT_NAME = {RED: "red", YEL: "yellow", GRN: "green"}


def _spark(series, years=20):
    m = series.resample("ME").last().dropna()
    m = m[m.index >= m.index[-1] - pd.DateOffset(years=years)]
    return {"d": [t.strftime("%Y-%m") for t in m.index], "v": [float("%.4g" % v) for v in m.values]}


def _summary(cards, comp):
    by = {g: [c for c in cards if c["group"] == g] for g, _, _ in GROUPS}
    reds = lambda g: [c for c in by[g] if c["light"] == "red"]
    n = {k: sum(c["light"] == k for c in cards) for k in ("red", "yellow", "green", "gray")}
    s_red, e_red, v_red = reds("stress"), reds("economy"), reds("value")
    if n["gray"] >= 2:   # 缺了好几个灯就别下「平稳」之类的结论
        text = "有 %d 个指标这次没拿到数据，结论不完整，稍后再刷新。" % n["gray"]
    elif len(s_red) >= 2:
        text = "多个压力灯亮红，下跌可能正在发生。"
    elif s_red:
        text = "「%s」亮红，留意会不会扩散到其他压力灯。" % s_red[0]["name"]
    elif e_red:
        text = "经济灯亮红，衰退风险在上升。"
    elif len(v_red) >= 2:
        text = "股票很贵，但还没有出事的迹象。贵可以贵很久，压力灯变红才是要紧的信号。"
    elif n["yellow"]:
        text = "整体平稳，有几处要留意。"
    else:
        text = "整体平稳。"
    return dict(n, text=text, composite=comp)


def run(force=True):
    t0 = time.time()
    data, status = fetch.fetch_all(force=force)
    spx = data.get("^GSPC")
    crash = history.forward_crash(spx) if spx is not None else None
    bears = history.bear_markets(spx) if spx is not None else []

    cards, all_lights = [], {}
    for spec in SPECS:
        card = {k: spec[k] for k in ("key", "group", "name", "explain", "sectors", "tip")}
        old = [d for d in spec["deps"] if status.get(d, {}).get("stale")]
        if old:   # 数据源连不上、用的是旧数据：灯照样算，但标出来
            card["old"] = ["%s 截至 %s" % (d, status[d].get("last", "—")) for d in old]
        try:
            r = spec["fn"](data)
            all_lights[spec["key"]] = r["lights"]
            sp = _spark(r["series"])
            sp["lines"] = [[float("%.4g" % y), LIGHT_NAME[l]] for y, l in r["lines"]]
            card.update(light=LIGHT_NAME[r["light"]], display=r["display"], sub=r["sub"],
                        as_of=r["as_of"], note=r.get("note", ""), spark=sp,
                        hist=history.evaluate(r["lights"], crash, bears))
        except Exception as e:
            traceback.print_exc()
            card.update(light="gray", display="—", sub="数据缺失", error=str(e)[:200])
        cards.append(card)

    comp = None
    if len(all_lights) == len(SPECS):
        cl, reds = history.composite_lights(all_lights)
        comp = history.evaluate(cl, crash, bears)
        if comp:
            comp["need"] = 3

    stale = {k: v for k, v in status.items() if v.get("stale")}
    return {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),   # 前端按看的人的时区显示
        "seconds": round(time.time() - t0, 1),
        "groups": [{"key": k, "title": t, "hint": h} for k, t, h in GROUPS],
        "summary": _summary(cards, comp),
        "indicators": cards,
        "bears": [{"peak": p.strftime("%Y-%m"), "trough": t.strftime("%Y-%m") if t is not None else None}
                  for p, _, t in bears],
        "stale": stale,
        "sources": {k: {"via": v.get("via"), "last": v.get("last"), "stale": v.get("stale")} for k, v in status.items()},
    }


def save(rep, path=REPORT_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False)


def log_day(rep, folder=os.path.join(os.path.dirname(fetch.CACHE), "log")):
    """每天第一次运行时记一笔当天的灯（之后同一天不覆盖），攒下来就是将来检验用的「事前记录」。"""
    day = rep["generated_at"][:10]
    path = os.path.join(folder, day + ".json")
    if os.path.exists(path):
        return None
    os.makedirs(folder, exist_ok=True)
    rec = {"generated_at": rep["generated_at"],
           "summary": {k: rep["summary"][k] for k in ("red", "yellow", "green", "gray", "text")},
           "lights": {c["key"]: [c["light"], c.get("display"), c.get("as_of")] for c in rep["indicators"]}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return path


def load(path=REPORT_PATH):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
