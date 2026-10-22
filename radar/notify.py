# -*- coding: utf-8 -*-
"""红灯变多时推送到手机（ntfy，免费、不用注册；手机装 ntfy App 订阅同一个主题即可）。

规则：
  - 红灯个数比上一轮多，且多出来的灯 3 天内没推过，才推（VIX 在 30 上下来回跳不会刷屏）
  - 某个灯这轮没数据（灰），当它保持上一轮的状态，不算变化
  - 第一次运行只记下现状，不推
主题名放在 GitHub 的仓库机密 NTFY_TOPIC 里（知道主题名的人都能收到/发消息，所以不写进公开代码）。
"""
import json
import os

import pandas as pd
import requests

from .fetch import CACHE

STATE = os.path.join(CACHE, "alert_state.json")
COOLDOWN = pd.Timedelta(days=3)
SITE = "https://lokliaoau-bot.github.io/crash-radar/"


def _topic():
    return os.environ.get("NTFY_TOPIC", "").strip()


def send(title, message, priority=4, tags=("rotating_light",), topic=None):
    topic = topic or _topic()
    if not topic:
        return False
    r = requests.post("https://ntfy.sh/", timeout=20, data=json.dumps({
        "topic": topic, "title": title, "message": message,
        "priority": priority, "tags": list(tags), "click": SITE,
    }, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return True


def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save(state):
    os.makedirs(CACHE, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def check(rep, now=None, push=True):
    """比较这一轮和上一轮的红灯。返回要推的 (title, message) 或 None。"""
    now = now or pd.Timestamp.now(tz="UTC")
    cards = {c["key"]: c for c in rep["indicators"]}
    state = _load()
    reds_now = {k for k, c in cards.items() if c["light"] == "red"}
    if state is None:
        _save({"reds": sorted(reds_now), "notified": {}, "updated": now.isoformat()})
        return None
    prev = set(state.get("reds", []))
    reds_now |= {k for k in prev if cards.get(k, {}).get("light") == "gray"}     # 没数据 = 维持原状
    notified = {k: pd.Timestamp(t) for k, t in state.get("notified", {}).items()}
    new = [k for k in cards if k in reds_now - prev and not (k in notified and now - notified[k] < COOLDOWN)]

    msg = None
    if len(reds_now) > len(prev) and new:
        title = "股灾雷达：红灯 %d → %d" % (len(prev), len(reds_now))
        lines = ["新亮红灯：" + "、".join("%s %s（%s）" % (cards[k]["name"], cards[k]["display"], cards[k]["sub"])
                                       for k in new),
                 "现在红灯：" + "、".join(cards[k]["name"] for k in cards if k in reds_now),
                 rep["summary"]["text"]]
        msg = (title, "\n".join(lines))
        stress_new = any(cards[k]["group"] == "stress" for k in new)
        if push:
            send(title, msg[1], priority=5 if stress_new else 4)
        for k in new:
            notified[k] = now
    _save({"reds": sorted(reds_now), "notified": {k: t.isoformat() for k, t in notified.items()},
           "updated": now.isoformat()})
    return msg
