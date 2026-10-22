# -*- coding: utf-8 -*-
"""股灾雷达 — 启动入口。

    python run.py              启动网页（http://127.0.0.1:8860），点「刷新」抓最新数据重算
    python run.py --cli        只在终端打印
    python run.py --export     生成云盘单文件 export/股灾雷达-快照.html 后退出
    python run.py --publish    生成手机网页 App 的 site/ 目录后退出（GitHub Actions 用）
    python run.py --publish --log   另外把当天的灯记进 log/YYYY-MM-DD.json（每天第一次才写）
    python run.py --notify     红灯比上一轮多时推送到手机（需要环境变量 NTFY_TOPIC）
    python run.py --test-push  发一条测试推送
"""
import argparse
import sys


def main():
    ap = argparse.ArgumentParser(description="股灾雷达")
    ap.add_argument("--port", type=int, default=8860)
    ap.add_argument("--cli", action="store_true")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--log", action="store_true", help="把当天的灯记进 log/（留作以后检验）")
    ap.add_argument("--notify", action="store_true", help="红灯变多时推送（需要 NTFY_TOPIC）")
    ap.add_argument("--test-push", action="store_true", help="发一条测试推送")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if a.test_push:
        from radar import engine, notify
        rep = engine.load() or engine.run(force=True)
        s = rep["summary"]
        ok = notify.send("股灾雷达：推送测试", "收到这条就说明推送通了。红灯变多时会这样提醒你。
现在 %d 红 %d 黄 %d 绿：%s"
                         % (s["red"], s["yellow"], s["green"], s["text"]), priority=3, tags=("white_check_mark",))
        print("测试推送已发出" if ok else "没有设置 NTFY_TOPIC，没发")
        return

    if a.cli or a.export or a.publish or a.notify:
        from radar import engine, export
        rep = engine.run(force=True)
        engine.save(rep)
        print("云盘单文件：", export.snapshot(rep))
        if a.publish:
            print("手机网页：", export.site(rep))
        if a.log:
            print("当日记录：", engine.log_day(rep) or "今天已经记过")
        if a.notify:
            from radar import notify
            try:
                m = notify.check(rep, push=bool(notify._topic()))
                print("推送：", m[0] if m else "红灯没有变多，不推")
            except Exception as e:   # 推送失败不影响网页更新；状态没存，下一轮会再试
                print("推送失败：", e)
        if a.cli:
            s = rep["summary"]
            print("\n%d 红 %d 黄 %d 绿 —— %s" % (s["red"], s["yellow"], s["green"], s["text"]))
            for c in rep["indicators"]:
                print("  %-4s %-8s %8s  %s" % ({"red": "红", "yellow": "黄", "green": "绿"}.get(c["light"], "—"),
                                              c["name"], c["display"], c.get("sub", "")))
        print("数据来源：", ", ".join("%s←%s" % (k, v["via"]) for k, v in rep["sources"].items()))
        if rep["stale"]:
            print("注意，这些数据已经偏旧：", ", ".join("%s(截至 %s)" % (k, v.get("last")) for k, v in rep["stale"].items()))
        return

    from radar.server import serve
    serve(port=a.port, open_browser=not a.no_browser)


if __name__ == "__main__":
    main()
