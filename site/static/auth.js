/* Pro4U: вход через Telegram Mini App и «Избранное».
   Сайт открывается из бота (кнопка «Подробнее на сайте» или «🌐 Сайт»): Telegram передаёт подписанные данные
   человека, сервер (Supabase, функция tg-auth) проверяет подпись и выдаёт сессию. Пароли не нужны.
   Вне Telegram сайт работает как обычный справочник, без личных функций. */
(function () {
  "use strict";
  var SB_URL = "https://igvwvlzkwhbzcrgcqlgt.supabase.co";
  var SB_KEY = "sb_publishable_hNwMVh6fap4x26Nfd-Zwsg_Qndaya0o"; // публичный (anon/publishable) ключ: доступ ограничен правилами RLS
  var KEY = "pro4u_session";
  var tg = window.Telegram && window.Telegram.WebApp;
  var session = null;      // {access_token, refresh_token, expires_at, user_id, first_name}
  var favs = null;         // Set строк "kind|slug"
  var waiters = [];

  function store(get, val) {
    try { return get ? JSON.parse(sessionStorage.getItem(KEY) || "null") : (val ? sessionStorage.setItem(KEY, JSON.stringify(val)) : sessionStorage.removeItem(KEY)); }
    catch (e) { return null; }
  }

  function api(path, opts, token) {
    opts = opts || {};
    var h = { apikey: SB_KEY, "content-type": "application/json" };
    if (token) h.authorization = "Bearer " + token;
    for (var k in (opts.headers || {})) h[k] = opts.headers[k];
    return fetch(SB_URL + path, { method: opts.method || "GET", headers: h, body: opts.body });
  }

  function login() {
    return api("/functions/v1/tg-auth", { method: "POST", body: JSON.stringify({ initData: tg.initData }) })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (d) {
        session = { access_token: d.access_token, refresh_token: d.refresh_token, user_id: d.user_id,
                    first_name: d.first_name, expires_at: Date.now() + (d.expires_in - 60) * 1000 };
        store(false, session);
        return session;
      });
  }

  function refresh() {
    return api("/auth/v1/token?grant_type=refresh_token", { method: "POST", body: JSON.stringify({ refresh_token: session.refresh_token }) })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (d) {
        session.access_token = d.access_token;
        session.refresh_token = d.refresh_token;
        session.expires_at = Date.now() + (d.expires_in - 60) * 1000;
        store(false, session);
        return session;
      })
      .catch(function () { return login(); });
  }

  function token() {
    if (!session) return Promise.resolve(null);
    return (Date.now() < session.expires_at ? Promise.resolve(session) : refresh()).then(function (s) { return s.access_token; });
  }

  function rest(path, opts) {
    return token().then(function (t) { return api("/rest/v1/" + path, opts, t); });
  }

  function loadFavs() {
    return rest("favorites?select=kind,slug&order=created_at.desc")
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (rows) {
        favs = {};
        rows.forEach(function (x) { favs[x.kind + "|" + x.slug] = 1; });
        return rows;
      });
  }

  function setFav(kind, slug, on) {
    var p = on
      ? rest("favorites", { method: "POST", headers: { prefer: "resolution=ignore-duplicates,return=minimal" },
                            body: JSON.stringify({ user_id: session.user_id, kind: kind, slug: slug }) })
      : rest("favorites?kind=eq." + encodeURIComponent(kind) + "&slug=eq." + encodeURIComponent(slug), { method: "DELETE" });
    return p.then(function (r) {
      if (!r.ok) return Promise.reject(r.status);
      if (on) favs[kind + "|" + slug] = 1; else delete favs[kind + "|" + slug];
    });
  }

  function paintButton(b) {
    var on = !!(favs && favs[b.dataset.kind + "|" + b.dataset.slug]);
    b.textContent = on ? "★ В избранном" : "☆ В избранное";
    b.setAttribute("aria-pressed", on ? "true" : "false");
  }

  function initButtons() {
    var btns = document.querySelectorAll(".fav-btn");
    btns.forEach(function (b) {
      b.hidden = false;
      paintButton(b);
      b.addEventListener("click", function () {
        var on = !(favs && favs[b.dataset.kind + "|" + b.dataset.slug]);
        b.disabled = true;
        setFav(b.dataset.kind, b.dataset.slug, on)
          .then(function () { paintButton(b); })
          .catch(function () { b.textContent = "Не получилось, попробуйте ещё раз"; })
          .then(function () { b.disabled = false; });
      });
    });
  }

  function greet() {
    var who = document.getElementById("who");
    if (who && session && session.first_name) { who.textContent = "Привет, " + session.first_name; who.hidden = false; }
  }

  function renderFavPage(rows) {
    var root = document.getElementById("fav-root");
    if (!root) return;
    var status = document.getElementById("fav-status");
    var list = document.getElementById("fav-list");
    var base = root.dataset.base || "";
    if (!rows.length) { status.textContent = "Пока пусто. Открывайте вузы и программы и нажимайте «☆ В избранное»."; return; }
    status.textContent = "Сохранено: " + rows.length;
    fetch(base + "/data/index.json").then(function (r) { return r.json(); }).then(function (idx) {
      var names = {};
      idx.unis.forEach(function (u) {
        names["university|" + u.slug] = { t: u.short + " · " + u.city, url: u.url };
        (u.programs || []).forEach(function (p) {
          var k = p.url.replace(/^vuz\//, "").replace(/\/$/, "");
          names["program|" + k] = { t: p.name + " (" + u.short + ")", url: p.url };
        });
      });
      rows.forEach(function (x) {
        var n = names[x.kind + "|" + x.slug];
        if (!n) return;
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.href = base + "/" + n.url;
        a.textContent = (x.kind === "university" ? "🏛 " : "🎓 ") + n.t;
        li.appendChild(a);
        list.appendChild(li);
      });
    });
  }

  function guest() {
    var g = document.getElementById("fav-guest");
    if (g) g.hidden = false;
    var s = document.getElementById("fav-status");
    if (s) s.hidden = true;
  }

  function start() {
    if (!tg || !tg.initData) { guest(); return; }
    try { tg.ready(); tg.expand(); } catch (e) {}
    var cached = store(true);
    var go = cached && cached.expires_at > Date.now() ? Promise.resolve((session = cached)) : login();
    go.then(function () { greet(); return loadFavs(); })
      .then(function (rows) { initButtons(); renderFavPage(rows); })
      .catch(function () {
        var s = document.getElementById("fav-status");
        if (s) s.textContent = "Не получилось войти. Откройте сайт ещё раз из бота.";
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
