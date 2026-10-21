# -*- coding: utf-8 -*-
"""股灾雷达 — 启动入口。

    python run.py              启动网页（http://127.0.0.1:8860），点「刷新」抓最新数据重算
    python run.py --cli        只在终端打印
    python run.py --export     生成云盘单文件 export/股灾雷达-快照.html 后退出
    python run.py --publish    生成手机网页 App 的 site/ 目录后退出（GitHub Actions 用）
    python run.py --publish --log   另外把当天的灯记进 log/YYYY-MM-DD.json（每天第一次才写）
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
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if a.cli or a.export or a.publish:
        from radar import engine, export
        rep = engine.run(force=True)
        engine.save(rep)
        print("云盘单文件：", export.snapshot(rep))
        if a.publish:
            print("手机网页：", export.site(rep))
        if a.log:
            print("当日记录：", engine.log_day(rep) or "今天已经记过")
        if a.cli:
            s = rep["summary"]
            print("\n%d 红 %d 黄 %d 绿 —— %s" % (s["red"], s["yellow"], s["green"], s["text"]))
            for c in rep["indicators"]:
                print("  %-4s %-8s %8s  %s" % ({"red": "红", "yellow": "黄", "green": "绿"}.get(c["light"], "—"),
                                              c["name"], c["display"], c.get("sub", "")))
        if rep["stale"]:
            print("注意，这些数据源没抓到、用了旧缓存：", ", ".join(rep["stale"]))
        return

    from radar.server import serve
    serve(port=a.port, open_browser=not a.no_browser)


if __name__ == "__main__":
    main()
