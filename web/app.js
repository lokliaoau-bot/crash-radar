/* 股灾雷达前端。三种模式：
 *   本地（python run.py）：刷新 = 让本机服务器重新抓数据、重算
 *   云端（GitHub Pages）：刷新 = 拉取云端最新算好的结果（云端定时重算）
 *   快照（单文件 HTML）：只读
 */
(function () {
  "use strict";
  var MODE = window.__REPORT__ ? "snapshot" : (window.__MODE__ || "local");
  var LIGHT = { red: "红灯", yellow: "黄灯", green: "绿灯", gray: "无数据" };
  var CHAIN_FIRST = ["fred_api", "fred_graph", "yahoo1", "shiller"];   // 各序列的首选来源
  var app = document.getElementById("app");
  var btn = document.getElementById("refresh");
  var pop = document.getElementById("pop");
  var report = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function fmtTime(iso) {
    var t = new Date(iso);
    if (isNaN(t)) return iso;
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return t.getFullYear() + "-" + p(t.getMonth() + 1) + "-" + p(t.getDate()) + " " + p(t.getHours()) + ":" + p(t.getMinutes());
  }

  function ago(iso) {
    var m = (Date.now() - new Date(iso).getTime()) / 60000;
    if (!(m >= 0)) return "";
    if (m < 60) return Math.max(1, Math.round(m)) + " 分钟前";
    if (m < 48 * 60) return Math.round(m / 60) + " 小时前";
    return Math.round(m / 1440) + " 天前";
  }

  /* ---------- 渲染 ---------- */

  function render(rep) {
    report = rep;
    var s = rep.summary, h = [];
    document.getElementById("stamp").textContent =
      "更新于 " + fmtTime(rep.generated_at) + "（" + ago(rep.generated_at) + "）" + (MODE === "snapshot" ? " · 快照" : "");

    var olds = rep.indicators.filter(function (x) { return x.old; });
    if (olds.length) h.push('<div class="banner">' + olds.length + " 个指标的数据源暂时连不上，用的是旧数据：" +
      esc(olds.map(function (x) { return x.name; }).join("、")) + "</div>");

    h.push('<section class="sum"><div class="tally">' +
      chip("red", s.red, "红") + chip("yellow", s.yellow, "黄") + chip("green", s.green, "绿") +
      (s.gray ? chip("gray", s.gray, "缺") : "") +
      '</div><div class="text">' + esc(s.text) + "</div>");
    var c = s.composite;
    if (c && c.p_red != null) {
      h.push('<div class="comp">历史上同时亮 ≥' + c.need + " 个红灯：一年内暴跌机会 " + c.p_red + "%（平时 " + c.base +
        "%）· 现在 " + s.red + " 个</div>");
    }
    h.push("</section>");

    rep.groups.forEach(function (g) {
      h.push('<div class="group"><h2>' + esc(g.title) + '</h2><span class="hint">' + esc(g.hint) + '</span></div><div class="grid">');
      rep.indicators.filter(function (x) { return x.group === g.key; }).forEach(function (x) { h.push(card(x)); });
      h.push("</div>");
    });

    var src = rep.sources || {}, names = Object.keys(src);
    var fresh = names.filter(function (k) { return !src[k].stale; }).length;
    var backup = names.filter(function (k) { return src[k].via && CHAIN_FIRST.indexOf(src[k].via) < 0; }).length;
    h.push('<div class="foot">「暴跌」＝标普 500 在一年内跌 20% 以上。历史数字只能参考：股灾次数少、月份前后重叠。' +
      "红黄灯门槛都是事先定好的常用标准，没有拿历史去凑。点 ⓘ 看算法和数据日期。<br>" +
      "数据：美联储 FRED、Yahoo、席勒；备用：美国财政部、CBOE。" +
      (names.length ? "本次 " + fresh + "/" + names.length + " 个数据源是最新的" + (backup ? "（" + backup + " 个用了备用来源或缓存）" : "") + "。" : "") +
      "不构成投资建议。</div>");
    app.innerHTML = h.join("");
    drawSparks();
  }

  function chip(cls, n, word) {
    return '<span class="' + cls + '"><i class="dot ' + cls + '"></i>' + n + " " + word + "</span>";
  }

  function card(x) {
    var hs = x.hist;
    var histLine = "";
    if (hs) {
      histLine = hs.p_red == null
        ? "历史上没亮过红灯"
        : '历史 <span class="v">' + esc(hs.verdict) + "</span> · 红灯后一年内暴跌 " + hs.p_red + "%（平时 " + hs.base + "%）";
    }
    return '<article class="card ' + x.light + '">' +
      '<div class="row1"><div><button class="name info" type="button" data-k="' + x.key + '">' + esc(x.name) +
      '<span class="i" aria-label="说明">ⓘ</span></button>' +
      '<div class="light"><i class="dot ' + x.light + '"></i>' + LIGHT[x.light] +
      (x.old ? '<span class="old">· 数据偏旧</span>' : "") + "</div></div>" +
      '<div class="val"><b>' + esc(x.display) + '</b><div class="sub">' + esc(x.sub) + "</div></div></div>" +
      '<div class="explain">' + esc(x.explain) + "</div>" +
      '<div class="sectors">影响：' + esc(x.sectors) + "</div>" +
      (x.spark ? '<div class="spark" data-k="' + x.key + '"><span class="rd"></span><svg></svg></div>' : "") +
      (histLine ? '<div class="hist">' + histLine + "</div>" : "") +
      "</article>";
  }

  function tipText(x) {
    var t = [x.tip];
    if (x.spark) t.push("小图：近 20 年走势，虚线是黄灯 / 红灯门槛；手指划过看数值。");
    if (x.as_of) t.push("数据截至 " + x.as_of + (x.note ? "（" + x.note + "）" : ""));
    var hs = x.hist;
    if (hs) {
      t.push(hs.since + " 年以来 " + hs.bears + " 次熊市，" + hs.caught + " 次在跌满 10% 之前亮过红灯；" +
        "亮红灯的月份共 " + hs.red_months + " 个。");
    }
    if (x.old) t.push("数据偏旧：" + x.old.join("；") + "。数据源暂时连不上，恢复后会自动更新。");
    if (x.error) t.push("这次没算出来：" + x.error);
    return t.join("\n\n");
  }

  /* ---------- 小走势图（近 20 年，月度） ---------- */

  var NS = "http://www.w3.org/2000/svg";
  function drawSparks() {
    var els = app.querySelectorAll(".spark");
    for (var i = 0; i < els.length; i++) drawSpark(els[i]);
  }

  function drawSpark(el) {
    var x = find(el.getAttribute("data-k"));
    var sp = x.spark, v = sp.v, n = v.length;
    var svg = el.querySelector("svg"), rd = el.querySelector(".rd");
    var W = el.clientWidth || 280, H = 38, pad = 3;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.innerHTML = "";
    var lo = Math.min.apply(null, v), hi = Math.max.apply(null, v);
    sp.lines.forEach(function (l) { lo = Math.min(lo, l[0]); hi = Math.max(hi, l[0]); });
    if (hi === lo) { hi += 1; lo -= 1; }
    var X = function (i) { return pad + (W - 2 * pad) * i / Math.max(1, n - 1); };
    var Y = function (y) { return pad + (H - 2 * pad) * (1 - (y - lo) / (hi - lo)); };

    sp.lines.forEach(function (l) {
      var ln = mk("line", { x1: 0, x2: W, y1: Y(l[0]), y2: Y(l[0]), stroke: "var(--" + l[1] + ")", "stroke-width": 1, "stroke-dasharray": "3 3", opacity: 0.8 });
      svg.appendChild(ln);
    });
    var d = "";
    for (var i = 0; i < n; i++) d += (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(v[i]).toFixed(1);
    svg.appendChild(mk("path", { d: d, fill: "none", stroke: "var(--spark)", "stroke-width": 1.5, "stroke-linejoin": "round" }));
    svg.appendChild(mk("circle", { cx: X(n - 1), cy: Y(v[n - 1]), r: 3.5, fill: "var(--" + x.light + ")", stroke: "var(--card)", "stroke-width": 2 }));
    var cross = mk("line", { y1: 0, y2: H, stroke: "var(--muted)", "stroke-width": 1, visibility: "hidden" });
    var hit = mk("rect", { x: 0, y: -10, width: W, height: H + 20, fill: "transparent" });
    svg.appendChild(cross);
    svg.appendChild(hit);
    rd.textContent = "";
    function show(ev) {
      var r = svg.getBoundingClientRect();
      var i = Math.round((ev.clientX - r.left - pad) / (r.width - 2 * pad) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i));
      cross.setAttribute("visibility", "visible");
      rd.textContent = sp.d[i] + "：" + v[i];
    }
    function hide() { cross.setAttribute("visibility", "hidden"); rd.textContent = ""; }
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", hide);
  }

  function mk(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function find(k) {
    for (var i = 0; i < report.indicators.length; i++) if (report.indicators[i].key === k) return report.indicators[i];
  }

  /* ---------- ⓘ 说明气泡（电脑悬停、手机点按） ---------- */

  function openPop(b) {
    pop.textContent = tipText(find(b.getAttribute("data-k")));
    pop.hidden = false;
    var r = b.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight;
    var left = Math.min(Math.max(16, r.left - 20), window.innerWidth - pw - 16);
    var top = r.bottom + 8;
    if (top + ph > window.innerHeight - 10) top = Math.max(10, r.top - ph - 8);
    pop.style.left = left + "px"; pop.style.top = top + "px";
    pop._owner = b;
    pop._y = window.scrollY;
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".info");
    if (b) { if (!pop.hidden && pop._owner === b) pop.hidden = true; else openPop(b); return; }
    if (!pop.contains(e.target)) pop.hidden = true;
  });
  document.addEventListener("mouseover", function (e) {
    var b = e.target.closest && e.target.closest(".info");
    if (b && matchMedia("(hover: hover)").matches) openPop(b);
  });
  document.addEventListener("mouseout", function (e) {
    var b = e.target.closest && e.target.closest(".info");
    if (b && matchMedia("(hover: hover)").matches) pop.hidden = true;
  });
  window.addEventListener("scroll", function () {   // 点按时页面会抖一下，滚远了才关
    if (!pop.hidden && Math.abs(window.scrollY - pop._y) > 40) pop.hidden = true;
  }, { passive: true });
  var rt;
  window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(function () { if (report) drawSparks(); }, 150); });

  /* ---------- 加载与刷新 ---------- */

  function toast(msg) {
    var t = document.createElement("div");
    t.className = "toast"; t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2600);
  }

  function getJSON(url, opts) {
    return fetch(url, opts).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function busy(on) {
    btn.disabled = on;
    btn.classList.toggle("busy", on);
    btn.querySelector(".lbl").textContent = on ? "抓取中" : "刷新";
  }

  function refresh() {
    busy(true);
    var p = MODE === "site"
      ? getJSON("data.json?t=" + Date.now(), { cache: "no-store" })
      : getJSON("api/refresh", { method: "POST" });
    p.then(function (rep) {
      render(rep);
      toast(MODE === "site" ? "已是云端最新：" + ago(rep.generated_at) + "算的" : "已更新，用时 " + rep.seconds + " 秒");
    }).catch(function (e) {
      toast("刷新失败：" + e.message);
    }).then(function () { busy(false); });
  }

  if (MODE === "snapshot") {
    btn.style.display = "none";
    render(window.__REPORT__);
  } else {
    btn.addEventListener("click", refresh);
    var first = MODE === "site" ? getJSON("data.json?t=" + Date.now(), { cache: "no-store" }) : getJSON("api/report");
    first.then(function (rep) {
      if (rep && rep.indicators) render(rep); else refresh();
    }).catch(function () {
      if (MODE === "local") refresh(); else app.innerHTML = '<div class="empty">没连上网络，稍后再试</div>';
    });
  }

  if (MODE === "site" && "serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(function () {});
  }
})();
