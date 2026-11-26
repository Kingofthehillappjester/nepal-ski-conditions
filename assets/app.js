// Nepal Ski Conditions: unit switch and "updated x ago". Metric is rendered by the server.
(function () {
  var KEY = 'nsc-units';
  function store(get, val) {
    try { return get ? localStorage.getItem(KEY) : localStorage.setItem(KEY, val); } catch (e) { return null; }
  }
  function fmt(kind, v, imperial) {
    if (kind === 't') {
      var c = imperial ? v * 9 / 5 + 32 : v;
      return String(Math.round(c)).replace('-', '−') + '°';
    }
    if (kind === 's') {
      var s = imperial ? v / 2.54 : v;
      var txt = s >= 10 || s === 0 ? s.toFixed(0) : s.toFixed(1);
      return txt + '<small>' + (imperial ? 'in' : 'cm') + '</small>';
    }
    if (kind === 'e') {
      var e = imperial ? v * 3.28084 : v;
      return Math.round(e).toLocaleString('en-GB') + '<small>' + (imperial ? 'ft' : 'm') + '</small>';
    }
    if (kind === 'w') {
      var w = imperial ? v * 0.621371 : v;
      return Math.round(w) + '<small>' + (imperial ? 'mph' : 'km/h') + '</small>';
    }
    return v;
  }
  function apply(units) {
    var imperial = units === 'imperial';
    var els = document.querySelectorAll('.u[data-k]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i], v = parseFloat(el.getAttribute('data-v'));
      if (!isNaN(v)) el.innerHTML = fmt(el.getAttribute('data-k'), v, imperial);
    }
    var btns = document.querySelectorAll('[data-units]');
    for (var j = 0; j < btns.length; j++) btns[j].setAttribute('aria-pressed', btns[j].getAttribute('data-units') === units ? 'true' : 'false');
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-units]');
    if (!b) return;
    var units = b.getAttribute('data-units');
    store(false, units);
    apply(units);
  });
  var saved = store(true);
  if (saved === 'imperial') apply('imperial');

  // relative "updated" time
  var times = document.querySelectorAll('time[data-ago]');
  for (var k = 0; k < times.length; k++) {
    var when = new Date(times[k].getAttribute('datetime'));
    if (isNaN(when)) continue;
    var mins = Math.round((Date.now() - when.getTime()) / 60000);
    var rel = mins < 2 ? 'just now' : mins < 90 ? mins + ' min ago' : Math.round(mins / 60) + ' hours ago';
    times[k].title = times[k].textContent;
    times[k].textContent = rel + ' · ' + times[k].textContent;
  }
})();
