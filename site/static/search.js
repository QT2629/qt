/* Pro4U: поиск и фильтры на главной. Vanilla JS, без зависимостей. */
(function (root) {
  'use strict';

  var PAGE = 30;
  var PREVIEW = 5;

  /* ---------- чистая логика (тестируется в Node/jsc) ---------- */

  function normalize(s) {
    return String(s == null ? '' : s)
      .toLowerCase()
      .replace(/ё/g, 'е')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /* Синонимы запроса. Ключ — слово запроса (в нижнем регистре, ё=е), значение — альтернативы: подходит ЛЮБАЯ
     (подстрока в названии вуза/программы/группы). Само слово запроса тоже остаётся вариантом.
     Чтобы добавить синоним, допишите строку: 'слово': ['вариант 1', 'вариант 2'].
     Варианты пишите в нижнем регистре; учитывайте падежи («информационной безопасности»). */
  var SYNONYMS = {
    'кибербезопасность': ['информационная безопасность', 'информационной безопасности', 'защита информации', 'cyber'],
    'кибербезопасности': ['информационная безопасность', 'информационной безопасности', 'защита информации', 'cyber'],
    'кибер': ['информационная безопасность', 'информационной безопасности', 'защита информации', 'cyber'],
    'айти': ['информационные технологии', 'информационные системы', 'программ'],
    'it': ['информационные технологии', 'информационные системы', 'программ'],
    'ит': ['информационные технологии', 'информационные системы', 'программ'],
    'юрист': ['право', 'юрисп'],
    'юриспруденция': ['право', 'юрисп'],
    'медицина': ['медицина', 'лечебное дело', 'общая медицина'],
    'врач': ['медицина', 'лечебное дело', 'общая медицина'],
    'педагог': ['подготовка учителей', 'педагог'],
    'учитель': ['подготовка учителей', 'педагог'],
    'психолог': ['психолог'],
    'экономист': ['экономика']
  };

  // Варианты для одного слова запроса: [слово] + синонимы.
  function expand(w) {
    var alts = [w];
    var syn = Object.prototype.hasOwnProperty.call(SYNONYMS, w) ? SYNONYMS[w] : null;
    if (syn) syn.forEach(function (a) { alts.push(normalize(a)); });
    return alts;
  }

  // Короткое слово-синоним («ит», «it») ищем только целым словом: иначе «ит» находит «литература», «политология».
  function wholeWord(t, w) {
    var re = new RegExp('(^|[^0-9a-zа-яәғқңөұүһі])' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '($|[^0-9a-zа-яәғқңөұүһі])');
    return re.test(t);
  }

  // Слово (с синонимами) встречается в нормализованном тексте t?
  function hit(t, w) {
    var alts = expand(w);
    var shortKey = w.length <= 3 && Object.prototype.hasOwnProperty.call(SYNONYMS, w);
    for (var i = 0; i < alts.length; i++) {
      if (i === 0 && shortKey) { if (wholeWord(t, w)) return true; continue; }
      if (t.indexOf(alts[i]) !== -1) return true;
    }
    return false;
  }

  function words(q) {
    var n = normalize(q);
    return n ? n.split(' ') : [];
  }

  // Подготовка данных: поисковые строки считаются один раз, вузы по алфавиту short.
  function prepare(data) {
    var unis = (data && data.unis ? data.unis : []).slice();
    unis.sort(function (a, b) {
      return String(a.short || '').localeCompare(String(b.short || ''), 'ru');
    });
    unis.forEach(function (u) {
      u._t = normalize([u.short, u.name, u.city].join(' '));
      (u.programs || []).forEach(function (p) {
        p._t = normalize([p.name, p.code, p.gop_name].join(' '));
      });
    });
    return unis;
  }

  // state: {q, city, ent, gop, special}
  // Возвращает {items: [{uni, progs, listed}], programs: M}
  function filterUnis(unis, state) {
    var ws = words(state.q);
    var progFilter = !!(state.ent || state.gop);
    var items = [];
    var total = 0;
    unis.forEach(function (u) {
      if (state.city && u.city !== state.city) return;
      if (state.special && !u.special) return;
      var uniWords = ws.filter(function (w) { return hit(u._t, w); });
      var restWords = ws.filter(function (w) { return !hit(u._t, w); });
      var progs = (u.programs || []).filter(function (p) {
        if (state.ent && p.ent !== state.ent) return false;
        if (state.gop && p.gop !== state.gop) return false;
        for (var i = 0; i < restWords.length; i++) {
          if (!hit(p._t, restWords[i])) return false;
        }
        return true;
      });
      if (progs.length === 0) {
        // вуз без подходящих программ показываем, только если фильтры по программам не заданы
        // и запрос целиком совпал с самим вузом
        if (progFilter || restWords.length) return;
        if (ws.length && uniWords.length !== ws.length) return;
      }
      // программы перечисляем, если запрос/фильтр что-то сужает на уровне программ
      var listed = progFilter || restWords.length > 0;
      items.push({ uni: u, progs: progs, listed: listed });
      total += progs.length;
    });
    return { items: items, programs: total };
  }

  function plural(n, one, few, many) {
    var m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
    return many;
  }

  function options(unis) {
    var cities = {}, ents = {}, gops = {};
    unis.forEach(function (u) {
      if (u.city) cities[u.city] = 1;
      (u.programs || []).forEach(function (p) {
        if (p.ent) ents[p.ent] = 1;
        if (p.gop) gops[p.gop] = p.gop_name || '';
      });
    });
    var cmp = function (a, b) { return a.localeCompare(b, 'ru'); };
    return {
      cities: Object.keys(cities).sort(cmp),
      ents: Object.keys(ents).sort(cmp),
      gops: Object.keys(gops).sort().map(function (g) {
        return { value: g, label: gops[g] ? g + ' — ' + gops[g] : g };
      })
    };
  }

  function parseSearch(search) {
    var st = { q: '', city: '', ent: '', gop: '', special: false };
    String(search || '').replace(/^\?/, '').split('&').forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf('=');
      var k = i < 0 ? kv : kv.slice(0, i);
      var v = i < 0 ? '' : kv.slice(i + 1);
      try { v = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (e) { return; }
      if (k === 'q' || k === 'city' || k === 'ent' || k === 'gop') st[k] = v;
      else if (k === 'special') st.special = v === '1';
    });
    return st;
  }

  function buildSearch(st) {
    var parts = [];
    ['q', 'city', 'ent', 'gop'].forEach(function (k) {
      if (st[k]) parts.push(k + '=' + encodeURIComponent(st[k]));
    });
    if (st.special) parts.push('special=1');
    return parts.length ? '?' + parts.join('&') : '';
  }

  var api = {
    normalize: normalize, words: words, expand: expand, hit: hit, SYNONYMS: SYNONYMS, prepare: prepare, filterUnis: filterUnis,
    plural: plural, options: options, parseSearch: parseSearch, buildSearch: buildSearch
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  /* ---------- интерфейс (только в браузере) ---------- */

  if (typeof document === 'undefined') return;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function field(labelText, control, id) {
    var wrap = el('div', 'srch-field');
    var lab = el('label', 'srch-label', labelText);
    control.id = id;
    lab.htmlFor = id;
    wrap.appendChild(lab);
    wrap.appendChild(control);
    return wrap;
  }

  function init() {
    var rootEl = document.getElementById('search-root');
    if (!rootEl) return;
    var url;
    try { url = new URL('data/index.json', document.baseURI); } catch (e) { return; }

    fetch(url.href)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data || !Array.isArray(data.unis)) throw new Error('bad data');
        start(rootEl, data);
      })
      .catch(function () { /* статический список остаётся как есть */ });
  }

  function start(rootEl, data) {
    var unis = prepare(data);
    var opt = options(unis);
    var state = parseSearch(location.search);
    var shown = PAGE;
    var lastResult = null;

    var form = el('form', 'srch-form');
    form.setAttribute('role', 'search');
    form.addEventListener('submit', function (e) { e.preventDefault(); });

    var q = el('input', 'srch-input');
    q.type = 'search';
    q.placeholder = 'Вуз, город, программа или код';
    q.autocomplete = 'off';
    q.setAttribute('enterkeyhint', 'search');
    var qField = field('Поиск по вузам и программам', q, 'srch-q');
    qField.className += ' srch-field-wide';

    function select(first, items) {
      var s = el('select', 'srch-select');
      var o = el('option', null, first);
      o.value = '';
      s.appendChild(o);
      items.forEach(function (it) {
        var op = el('option', null, typeof it === 'string' ? it : it.label);
        op.value = typeof it === 'string' ? it : it.value;
        s.appendChild(op);
      });
      return s;
    }
    var city = select('Все города', opt.cities);
    var ent = select('Любые предметы', opt.ents);
    var gop = select('Все группы программ', opt.gops);

    var spec = el('input');
    spec.type = 'checkbox';
    spec.id = 'srch-special';
    var specWrap = el('div', 'srch-check');
    var specLab = el('label', null, ' Только особый порядок поступления');
    specLab.htmlFor = 'srch-special';
    specLab.insertBefore(spec, specLab.firstChild);
    specWrap.appendChild(specLab);

    var reset = el('button', 'srch-btn srch-btn-ghost', 'Сбросить');
    reset.type = 'button';

    var filters = el('div', 'srch-filters');
    filters.appendChild(field('Город', city, 'srch-city'));
    filters.appendChild(field('Предметы ЕНТ', ent, 'srch-ent'));
    filters.appendChild(field('Группа программ', gop, 'srch-gop'));

    var actions = el('div', 'srch-actions');
    actions.appendChild(specWrap);
    actions.appendChild(reset);

    form.appendChild(qField);
    form.appendChild(filters);
    form.appendChild(actions);

    var counter = el('p', 'srch-count');
    counter.setAttribute('role', 'status');
    counter.setAttribute('aria-live', 'polite');
    var list = el('div', 'srch-list');
    var moreWrap = el('div', 'srch-more');
    var more = el('button', 'srch-btn', 'Показать ещё');
    more.type = 'button';
    moreWrap.appendChild(more);

    rootEl.textContent = '';
    rootEl.appendChild(form);
    rootEl.appendChild(counter);
    rootEl.appendChild(list);
    rootEl.appendChild(moreWrap);

    // восстановление состояния из адреса (значения вне списков игнорируются)
    q.value = state.q;
    city.value = state.city; if (city.value !== state.city) state.city = '';
    ent.value = state.ent; if (ent.value !== state.ent) state.ent = '';
    gop.value = state.gop; if (gop.value !== state.gop) state.gop = '';
    spec.checked = state.special;

    function programLink(p) {
      var li = el('li', 'srch-prog');
      var a = el('a', null, p.name || p.code);
      a.href = p.url;
      li.appendChild(a);
      if (p.gop) li.appendChild(el('span', 'srch-prog-gop', ' ' + p.gop));
      return li;
    }

    function card(item) {
      var u = item.uni;
      var c = el('article', 'srch-card');
      var h = el('h3', 'srch-title');
      var a = el('a', null, u.short || u.name);
      a.href = u.url;
      h.appendChild(a);
      c.appendChild(h);
      if (u.name && u.name !== u.short) c.appendChild(el('p', 'srch-name', u.name));
      var meta = el('p', 'srch-meta');
      if (u.city) meta.appendChild(el('span', null, u.city));
      if (u.special) meta.appendChild(el('span', 'srch-badge', 'особый приём'));
      var n = item.progs.length;
      meta.appendChild(el('span', 'srch-num',
        (item.listed ? 'Подходит: ' : 'Программ: ') + n));
      c.appendChild(meta);
      if (item.listed && n) {
        var ul = el('ul', 'srch-progs');
        item.progs.slice(0, PREVIEW).forEach(function (p) { ul.appendChild(programLink(p)); });
        c.appendChild(ul);
      }
      var all = el('a', 'srch-all', 'все программы вуза →');
      all.href = u.url;
      c.appendChild(all);
      return c;
    }

    function renderList(append) {
      if (!append) list.textContent = '';
      var items = lastResult.items;
      var from = append ? list.childNodes.length : 0;
      var frag = document.createDocumentFragment();
      for (var i = from; i < Math.min(shown, items.length); i++) frag.appendChild(card(items[i]));
      list.appendChild(frag);
      var left = items.length - list.childNodes.length;
      moreWrap.hidden = left <= 0;
      more.textContent = 'Показать ещё (' + left + ')';
      if (!items.length && !append) {
        list.appendChild(el('p', 'srch-empty', 'Ничего не найдено. Попробуйте изменить запрос или сбросить фильтры.'));
      }
    }

    function update() {
      state.q = q.value;
      state.city = city.value;
      state.ent = ent.value;
      state.gop = gop.value;
      state.special = spec.checked;
      try {
        history.replaceState(null, '', location.pathname + buildSearch(state) + location.hash);
      } catch (e) { /* ignore */ }
      shown = PAGE;
      lastResult = filterUnis(unis, state);
      var nu = lastResult.items.length, np = lastResult.programs;
      counter.textContent = 'Найдено ' + nu + ' ' + plural(nu, 'вуз', 'вуза', 'вузов') +
        ', ' + np + ' ' + plural(np, 'программа', 'программы', 'программ');
      renderList(false);
    }

    var timer = null;
    q.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(update, 150);
    });
    [city, ent, gop, spec].forEach(function (c) { c.addEventListener('change', update); });
    more.addEventListener('click', function () {
      var before = list.childNodes.length;
      shown += PAGE;
      renderList(true);
      var first = list.childNodes[before];
      var link = first && first.querySelector('a');
      if (link) link.focus();
    });
    reset.addEventListener('click', function () {
      q.value = ''; city.value = ''; ent.value = ''; gop.value = ''; spec.checked = false;
      update();
      q.focus();
    });

    update();
    var stat = document.getElementById('static-list');
    if (stat) stat.hidden = true, stat.style.display = 'none';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(typeof window !== 'undefined' ? window : this);
