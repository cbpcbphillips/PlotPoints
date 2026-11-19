/* Shared behaviour for the 08 Neutral + Red mock-ups: header, theme toggle, layout switcher, helpers. */
(function () {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;
  const PAGES = [['For you', 'mock-08-combined.html', 'for'], ['Franchises', 'mock-08-franchises.html', 'fr'], ['Streaming', 'mock-08-streaming.html', 'st'], ['Import', 'mock-08-import.html', 'im']];
  const cur = document.body.dataset.page;
  const header = document.createElement('header');
  header.className = 'top';
  header.innerHTML = '<div class="wrap bar"><a class="brand" href="mock-08-combined.html">Plot<b>Points</b></a><nav aria-label="Sections">' +
    PAGES.map(p => '<a href="' + p[1] + '"' + (p[2] === cur ? ' class="on"' : '') + '>' + p[0] + '</a>').join('') +
    '</nav><button class="btn ghost" id="theme" type="button">◐ <span id="tl"></span></button></div>';
  document.body.prepend(header);
  function sync() { $('#tl').textContent = root.dataset.theme === 'dark' ? 'Dark' : 'Light'; }
  sync();
  $('#theme').addEventListener('click', () => {
    const t = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = t; try { localStorage.setItem('pp-theme', t); } catch (e) {} sync();
  });

  const PP = window.PP = { $, $$ };
  PP.stars = n => '<span class="stars" role="img" aria-label="' + n + ' out of 5">' + [1, 2, 3, 4, 5].map(i => n >= i ? '★' : '<span class="off">★</span>').join('') + '</span>';
  PP.poster = (t, h, cls) => '<div class="poster ' + (cls || '') + '" style="--h:' + h + '" role="img" aria-label="Placeholder poster for ' + t + '"><span>' + t + '</span></div>';
  PP.gauge = pct => '<div class="gauge"><b>' + pct + '</b><small>score</small></div>';
  PP.dots = (a, b, c, show) => '<span class="dots" title="Taste ' + a + ', novelty ' + b + ', critics ' + c + '"><i style="--v:' + a / 100 + '"></i><i style="--v:' + b / 100 + '"></i><i style="--v:' + c / 100 + '"></i>' + (show === false ? '' : '<span>' + a + '</span>') + '</span>';
  PP.ov = '<div class="ov"><button class="mini" type="button">+ Watchlist</button><button class="mini" type="button">Seen it</button><button class="mini" type="button">Not interested</button></div>';

  /* Layout switcher: <div class="switch" data-group="x" data-descs='["...","..."]'> ; panels have data-group + data-layout="A|B|C" */
  PP.switcher = function (group, labels, descs, onChange) {
    const bar = document.createElement('div');
    bar.className = 'switch';
    bar.innerHTML = '<div class="wrap"><span class="label">Layout</span><div class="seg" role="group" aria-label="Layout">' +
      labels.map((l, i) => '<button type="button" data-i="' + i + '">' + String.fromCharCode(65 + i) + ' · ' + l + '</button>').join('') +
      '</div><p class="desc"></p></div>';
    $('.top').after(bar);
    function set(i) {
      $$('button', bar).forEach(b => b.setAttribute('aria-pressed', +b.dataset.i === i));
      $('.desc', bar).textContent = descs[i];
      $$('[data-group="' + group + '"]').forEach(el => el.classList.toggle('show', el.dataset.layout === String.fromCharCode(65 + i)));
      try { history.replaceState(null, '', '#' + String.fromCharCode(97 + i)); } catch (e) {}
      if (onChange) onChange(i);
    }
    $$('button', bar).forEach(b => b.addEventListener('click', () => set(+b.dataset.i)));
    const h = (location.hash || '#a').charCodeAt(1) - 97;
    set(h >= 0 && h < labels.length ? h : 0);
    return set;
  };
  PP.foot = '<footer class="foot"><div class="wrap"><p>This product uses the TMDB API but is not endorsed or certified by TMDB. Streaming data via JustWatch, US only.</p><p>PlotPoints mock-up · 08 Neutral + Red · invented sample data, no live APIs.</p></div></footer>';
  document.addEventListener('DOMContentLoaded', () => document.body.insertAdjacentHTML('beforeend', PP.foot));
  if (document.readyState !== 'loading') document.body.insertAdjacentHTML('beforeend', PP.foot);
})();
