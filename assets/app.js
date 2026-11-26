// Nepal Ski Conditions: unit switch, top/base forecast tabs and "updated x ago".
// Metric is rendered by the server; imperial is converted here.
(function () {
  var KEY = 'nsc-units';
  var LABELS = { t: ['°C', '°F'], s: ['cm', 'in'], e: ['m', 'ft'], w: ['km/h', 'mph'] };
  function store(get, val) {
    try { return get ? localStorage.getItem(KEY) : localStorage.setItem(KEY, val); } catch (e) { return null; }
  }
  function conv(kind, v, imp) {
    if (!imp) return v;
    if (kind === 't') return v * 9 / 5 + 32;
    if (kind === 's') return v / 2.54;
    if (kind === 'e') return v * 3.28084;
    if (kind === 'w') return v * 0.621371;
    return v;
  }
  function fmt(kind, v, imp, bare) {
    var n = conv(kind, v, imp), unit = LABELS[kind] ? LABELS[kind][imp ? 1 : 0] : '';
    var suffix = bare ? '' : '<small>' + unit + '</small>';
    if (kind === 't') return String(Math.round(n)).replace('-', '−') + (bare ? '' : '°');
    if (kind === 's') return (n >= 10 || Number.isInteger(n) ? n.toFixed(0) : n.toFixed(1)) + suffix;
    if (kind === 'e') return (bare ? String(Math.round(n)) : Math.round(n).toLocaleString('en-GB')) + suffix;
    if (kind === 'w') return Math.round(n) + suffix;
    return String(v);
  }
  function apply(units) {
    var imp = units === 'imperial';
    var els = document.querySelectorAll('.u[data-k]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i], v = parseFloat(el.getAttribute('data-v'));
      if (!isNaN(v)) el.innerHTML = fmt(el.getAttribute('data-k'), v, imp, el.hasAttribute('data-b'));
    }
    var labels = document.querySelectorAll('.ul[data-k]');
    for (var j = 0; j < labels.length; j++) {
      var l = LABELS[labels[j].getAttribute('data-k')];
      if (l) labels[j].textContent = l[imp ? 1 : 0];
    }
    var btns = document.querySelectorAll('[data-units]');
    for (var k = 0; k < btns.length; k++) btns[k].setAttribute('aria-pressed', btns[k].getAttribute('data-units') === units ? 'true' : 'false');
  }
  function showElev(tab) {
    var scope = tab.closest('.bx') || document, which = tab.getAttribute('data-elev');
    var tabs = scope.querySelectorAll('.tabs [data-elev]'), panes = scope.querySelectorAll('.elev[data-elev]');
    for (var i = 0; i < tabs.length; i++) tabs[i].setAttribute('aria-selected', tabs[i] === tab ? 'true' : 'false');
    for (var j = 0; j < panes.length; j++) panes[j].classList.toggle('on', panes[j].getAttribute('data-elev') === which);
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-units]');
    if (b) { store(false, b.getAttribute('data-units')); apply(b.getAttribute('data-units')); return; }
    var tab = e.target.closest('.tabs [data-elev]');
    if (tab) showElev(tab);
  });
  if (store(true) === 'imperial') apply('imperial');

  // relative "updated" time
  var times = document.querySelectorAll('time[data-ago]');
  for (var m = 0; m < times.length; m++) {
    var when = new Date(times[m].getAttribute('datetime'));
    if (isNaN(when)) continue;
    var mins = Math.round((Date.now() - when.getTime()) / 60000);
    var rel = mins < 2 ? 'just now' : mins < 90 ? mins + ' min ago' : Math.round(mins / 60) + ' hours ago';
    times[m].title = times[m].textContent;
    times[m].textContent = times[m].textContent + ' (' + rel + ')';
  }
})();
