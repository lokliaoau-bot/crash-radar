/* 网络优先：有网就拿最新的，没网就用上次存下的（地铁里也能看上一次的结果） */
var CACHE = "crash-radar-v1";
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function (e) {
  if (e.request.method !== "GET") return;
  var key = e.request.url.split("?")[0];
  e.respondWith(
    fetch(e.request).then(function (r) {
      if (r.ok) { var copy = r.clone(); caches.open(CACHE).then(function (c) { c.put(key, copy); }); }
      return r;
    }).catch(function () {
      return caches.match(key);
    })
  );
});
