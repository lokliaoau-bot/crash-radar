# -*- coding: utf-8 -*-
"""两种输出：
  snapshot(rep)  → export/股灾雷达-快照.html  单文件，放云盘双击就能看（只读）
  site(rep)      → site/  手机网页 App（GitHub Pages 用），刷新按钮拉取云端最新结果
"""
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
SNAPSHOT = os.path.join(ROOT, "export", "股灾雷达-快照.html")
SITE = os.path.join(ROOT, "site")
STATIC = ["app.js", "style.css", "manifest.webmanifest", "sw.js", "icon-192.png", "icon-512.png"]


def _read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return f.read()


def snapshot(rep, path=SNAPSHOT):
    html = _read("index.html")
    data = json.dumps(rep, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="style.css">', "<style>\n%s\n</style>" % _read("style.css"))
    html = html.replace('<link rel="manifest" href="manifest.webmanifest">\n', "")
    html = html.replace('<link rel="icon" href="icon-192.png">\n', "")
    html = html.replace('<link rel="apple-touch-icon" href="icon-192.png">\n', "")
    html = html.replace("<!--REPORT-->", "<script>window.__REPORT__=%s;</script>" % data)
    html = html.replace('<script src="app.js"></script>', "<script>\n%s\n</script>" % _read("app.js"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def site(rep, out=SITE):
    os.makedirs(out, exist_ok=True)
    for name in STATIC:
        shutil.copy2(os.path.join(WEB, name), os.path.join(out, name))
    html = _read("index.html").replace("<!--REPORT-->", '<script>window.__MODE__="site";</script>')
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(out, "data.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False)
    return out
