// Baseline grid: put every text baseline, rule and card edge of the scrolling content on the 24px
// backdrop grid. Works on layout positions (offsetTop), so the reveal transforms never skew it.
// The page scroll rests on 24px steps (scroll-snap), so at rest the fixed grid and the content meet.
(() => {
  const U = 24, M = 120;                                            // fine grid / bright major grid
  // modules framed by the bright lines: top and bottom (last rule) on a 120px line (desktop only)
  const MAJOR = '.sec > .copy:not(.copy--center), .metrics';
  const LAST_BOX = ':scope > .specs, :scope > .parts, :scope > .timeline, :scope > .cards';
  const BLOCKS = '.hero, .sec > .copy, .metrics, .court__head, .court__cap, .outro';
  const TEXT = 'p, h1, h2, .card__k, .card__v, .card__s, .specs li, .timeline li, .parts li, .bars li';
  const BOX = '.hero__cta, .specs, .parts, .timeline, .cards, .card, .bars, .swatches, .metrics__head, .gauge';
  const touched = new Set();

  // exact (fractional) document position; reveal transforms are switched off while measuring (see .snap-measuring)
  const docTop = (el) => el.getBoundingClientRect().top + scrollY;
  const upTo = (v, step) => { const m = ((v % step) + step) % step; return m < 0.01 || step - m < 0.01 ? 0 : step - m; };
  const up = (v) => { const m = ((v % U) + U) % U; return m < 0.01 || U - m < 0.01 ? 0 : U - m; };   // px to the next grid line
  const px = (el, prop, v) => {
    if (!v) return; touched.add(el);
    const cur = el.style[prop] ? parseFloat(el.style[prop]) : parseFloat(getComputedStyle(el)[prop]) || 0;   // add to the CSS value, never replace it
    el.style[prop] = `${Math.round((cur + v) * 100) / 100}px`;
    if (prop === 'paddingTop') el.style.setProperty('--snap-pt', el.style.paddingTop);   // ::before markers follow the text
  };

  function firstBaseline(el) {
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: (t) => (t.data.trim() ? 1 : 3) });
    const t = w.nextNode(); if (!t) return null;
    const probe = document.createElement('span');
    probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline;';
    t.parentNode.insertBefore(probe, t);
    const y = docTop(probe);
    probe.remove();
    return y;
  }
  // put el's first baseline on the next grid line (relative to the block's current top), then round its height up to whole cells
  // `block` is re-measured every time: centred blocks re-centre (move) whenever something inside them grows
  function snapText(el, block) {
    const b = firstBaseline(el); if (b == null) return;
    px(el, 'paddingTop', up(b - docTop(block)));
    px(el, 'paddingBottom', up(el.offsetHeight));
  }
  function snapBox(el, block) {
    px(el, 'marginTop', up(docTop(el) - docTop(block)));
    walk(el, block);
    px(el, 'paddingBottom', up(el.offsetHeight));
  }
  function walk(parent, block) {
    for (const el of parent.children) {
      if (getComputedStyle(el).position === 'absolute' || !el.offsetParent) continue;
      if (el.matches(BOX)) snapBox(el, block);
      else if (el.matches(TEXT)) snapText(el, block);
      else walk(el, block);
    }
  }
  function snapAll() {
    document.documentElement.classList.add('snap-measuring');
    for (const el of touched) { el.style.paddingTop = el.style.paddingBottom = el.style.marginTop = el.style.transform = ''; el.style.removeProperty('--snap-pt'); }
    touched.clear();
    document.querySelectorAll(BLOCKS).forEach((block) => {
      if (!block.offsetParent) return;
      const flexRow = getComputedStyle(block).display === 'flex' && getComputedStyle(block).flexDirection.startsWith('row');
      if (flexRow && !block.matches(TEXT)) [...block.children].forEach((c) => c.matches(TEXT) && snapText(c, block));   // side-by-side items
      else if (block.matches(TEXT)) snapText(block, block);
      else walk(block, block);
      px(block, 'paddingBottom', up(block.offsetHeight));
      if (innerWidth > 860 && block.matches(MAJOR)) {
        const extra = upTo(block.getBoundingClientRect().height, M);    // multiple of 24, so the fine grid still holds
        const last = block.querySelector(LAST_BOX);
        if (last) px(last, 'marginTop', extra); else px(block, 'paddingBottom', extra);
      }
    });
    // second pass, once nothing grows any more: move each whole block onto a grid line
    // (transform: no reflow, so the scroll choreography is untouched)
    document.querySelectorAll(BLOCKS).forEach((block) => {
      if (!block.offsetParent || getComputedStyle(block).position === 'sticky') return;
      const step = innerWidth > 860 && block.matches(MAJOR) ? M : U;
      const top = docTop(block), d = Math.round((Math.round(top / step) * step - top) * 100) / 100;
      if (d) { touched.add(block); block.style.transform = `translateY(${d}px)`; }
    });
    document.documentElement.classList.remove('snap-measuring');
    buildRail();
  }
  // scroll-snap points every 24px down the page
  let rail;
  function buildRail() {
    if (!rail) { rail = document.createElement('div'); rail.className = 'snap-rail'; rail.setAttribute('aria-hidden', 'true'); document.body.appendChild(rail); }
    const h = document.documentElement.scrollHeight, n = Math.ceil(h / U) + 1;
    if (rail.childElementCount !== n) {
      const f = document.createDocumentFragment();
      for (let i = 0; i < n; i++) { const p = document.createElement('i'); p.style.top = `${i * U}px`; f.appendChild(p); }
      rail.replaceChildren(f);
    }
    rail.style.height = `${h}px`;
  }
  let t;
  const later = () => { clearTimeout(t); t = setTimeout(snapAll, 120); };
  addEventListener('resize', later);
  addEventListener('load', snapAll);
  document.fonts?.ready.then(snapAll);
  snapAll();
  window.__gridSnap = snapAll;

  // Scrolling grid (test). ?grid=fixed keeps the old fixed backdrop for comparison.
  if (new URLSearchParams(location.search).get('grid') !== 'fixed') {
    document.documentElement.classList.add('grid-scroll');
    const backdrop = document.querySelector('.backdrop');
    // scroll events already fire once per frame, right before paint: update directly so the lines never trail the text
    const move = () => backdrop.style.setProperty('--gy', `${120 - (scrollY % 120)}px`);
    addEventListener('scroll', move, { passive: true });
    move();
  }
})();
