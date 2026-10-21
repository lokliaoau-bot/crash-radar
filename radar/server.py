# -*- coding: utf-8 -*-
"""本机小服务器：网页 + 两个接口。GET /api/report 读上次结果；POST /api/refresh 重新抓数据、重算。"""
import json
import os
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import engine, export

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
_lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/report"):
            return self._json(engine.load() or {})
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/refresh"):
            return self._json({"error": "not found"}, 404)
        with _lock:   # 连点两下只算一次
            try:
                rep = engine.run(force=True)
                engine.save(rep)
                export.snapshot(rep)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
        return self._json(rep)


def serve(port=8860, open_browser=True):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    print("股灾雷达已启动：%s （关掉这个窗口就停止）" % url)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
