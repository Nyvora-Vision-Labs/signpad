// SignPad page: polls the local agent session and shows the right view.
(() => {
  'use strict';
  const token = new URLSearchParams(location.search).get('t') || '';
  const $ = (id) => document.getElementById(id);
  const views = { wait: $('waitView'), sign: $('signView'), review: $('reviewView') };
  let state = { seq: -1 };

  // ------------------------------------------------------------- server I/O
  async function api(path, body) {
    const opts = body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-SignPad-Token': token },
      body: JSON.stringify(body),
    };
    const r = await fetch(path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(token), opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  function say(msg, err) { $('status').textContent = msg || ''; $('status').className = 'status' + (err ? ' err' : ''); }

  async function poll() {
    try {
      const s = await api('/api/state');
      if (s.seq !== state.seq || s.phase !== state.phase) render(s);
    } catch (e) {
      if (state.phase !== 'closed') {
        render({ phase: 'closed', message: 'The agent session has ended. You can close this tab.' });
      }
      return;
    }
    setTimeout(poll, 700);
  }

  function show(name) {
    Object.entries(views).forEach(([k, el]) => { el.hidden = k !== name; });
  }

  function render(s) {
    state = s;
    $('phaseTag').textContent = { sign: 'signature needed', review: 'review', closed: 'finished' }[s.phase] || 'working';
    say('');
    if (s.phase === 'sign') {
      $('signer').textContent = s.signer || 'you';
      $('purpose').textContent = s.purpose || '';
      show('sign');
      strokes = []; resize(); redraw();
    } else if (s.phase === 'review') {
      $('summary').textContent = s.summary || '';
      $('files').innerHTML = '';
      (s.files || []).forEach((f) => { const li = document.createElement('li'); li.textContent = f; $('files').appendChild(li); });
      $('comment').value = '';
      $('preview').hidden = !s.has_preview;
      $('noPreview').hidden = !!s.has_preview;
      if (s.has_preview) $('preview').src = '/preview.pdf?t=' + encodeURIComponent(token) + '&s=' + s.seq;
      show('review');
    } else {
      $('waitMsg').textContent = s.message || '';
      $('spinner').hidden = s.phase === 'closed';
      show('wait');
    }
  }

  async function submit(body) {
    try { await api('/api/submit', { ...body, seq: state.seq }); say('Sent.'); }
    catch (e) { say('Could not send: ' + e.message, true); }
  }

  // ------------------------------------------------------------- drawing
  const cv = $('pad'), ctx = cv.getContext('2d'), hint = $('hint');
  let strokes = [], cur = null, color = '#0b2a8a', baseW = 3;

  function resize() {
    const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    if (!r.width) return;
    cv.width = r.width * d; cv.height = r.height * d;
    ctx.setTransform(d, 0, 0, d, 0, 0); redraw();
  }
  function seg(c2d, p0, p1, p2, w, col) {
    c2d.strokeStyle = col; c2d.lineWidth = w; c2d.lineCap = 'round'; c2d.lineJoin = 'round';
    c2d.beginPath();
    c2d.moveTo((p0.x + p1.x) / 2, (p0.y + p1.y) / 2);
    c2d.quadraticCurveTo(p1.x, p1.y, (p1.x + p2.x) / 2, (p1.y + p2.y) / 2);
    c2d.stroke();
  }
  function drawStroke(c2d, s) {
    const p = s.pts;
    if (p.length === 1) { c2d.fillStyle = s.c; c2d.beginPath(); c2d.arc(p[0].x, p[0].y, s.w * 0.6, 0, 7); c2d.fill(); return; }
    for (let i = 0; i < p.length - 1; i++) seg(c2d, p[Math.max(i - 1, 0)], p[i], p[i + 1], p[i + 1].w, s.c);
    const l = p[p.length - 1], m = p[p.length - 2];
    c2d.beginPath(); c2d.moveTo((m.x + l.x) / 2, (m.y + l.y) / 2); c2d.lineTo(l.x, l.y); c2d.stroke();
  }
  function redraw() {
    ctx.clearRect(0, 0, cv.width, cv.height);
    strokes.forEach((s) => drawStroke(ctx, s));
    hint.style.display = strokes.length ? 'none' : 'flex';
    $('useSig').disabled = !strokes.length;
  }
  function pt(e) {
    const r = cv.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top, t: performance.now() };
  }
  function beginStroke(e, mode) {
    const p = pt(e); p.w = baseW;
    cur = { c: color, w: baseW, pts: [p], mode }; strokes.push(cur);
    hint.style.display = 'none';
  }
  function addPoints(e) {
    const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    for (const ev of evs) {
      const p = pt(ev), last = cur.pts[cur.pts.length - 1];
      const dist = Math.hypot(p.x - last.x, p.y - last.y);
      if (dist < 0.8) continue;
      const v = dist / Math.max(p.t - last.t, 1);
      const pressure = ev.pointerType === 'pen' && ev.pressure ? ev.pressure * 1.6 : 1;
      const target = baseW * pressure * Math.max(0.45, Math.min(1.25, 1.3 - v * 0.35));
      p.w = last.w * 0.7 + target * 0.3;
      cur.pts.push(p);
      const n = cur.pts.length;
      seg(ctx, cur.pts[Math.max(n - 3, 0)], cur.pts[n - 2], cur.pts[n - 1], p.w, cur.c);
    }
  }
  function endStroke() { if (cur) { cur = null; redraw(); } }

  // click-and-drag drawing
  cv.addEventListener('pointerdown', (e) => {
    if (mode !== 'idle') return;
    cv.setPointerCapture(e.pointerId); beginStroke(e, 'drag'); redraw();
  });
  cv.addEventListener('pointermove', (e) => { if (mode === 'idle' && cur) addPoints(e); });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach((t) =>
    cv.addEventListener(t, () => { if (mode === 'idle') endStroke(); }));

  // hover drawing: Start -> 3 s countdown -> moving the pointer draws
  let mode = 'idle', penDown = true, timer = null, finishedAt = 0;
  const wrap = $('wrap'), countEl = $('count'), liveEl = $('live'), pen = $('pen'), startBtn = $('start');
  const inside = (e) => {
    const r = cv.getBoundingClientRect();
    return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
  };
  function showLive() {
    liveEl.hidden = false;
    liveEl.className = 'live' + (penDown ? '' : ' up');
    liveEl.innerHTML = '<span class="dot"></span>' + (penDown
      ? 'Writing. Space = lift pen, click / Enter = done'
      : 'Pen lifted. Space = write again, click / Enter = done');
  }
  function finish() {
    if (mode === 'countdown') clearInterval(timer);
    mode = 'idle'; endStroke();
    strokes = strokes.filter((s) => s.mode !== 'hover' || s.pts.length > 2);
    countEl.hidden = true; liveEl.hidden = true; pen.hidden = true;
    wrap.classList.remove('hovering'); startBtn.textContent = 'Start'; redraw();
  }
  window.addEventListener('pointermove', (e) => {
    if (mode !== 'drawing') return;
    const r = cv.getBoundingClientRect();
    pen.hidden = !inside(e);
    pen.style.left = (e.clientX - r.left) + 'px'; pen.style.top = (e.clientY - r.top) + 'px';
    if (!penDown || !inside(e)) { endStroke(); return; }
    if (!cur) { beginStroke(e, 'hover'); return; }
    addPoints(e);
  });
  window.addEventListener('keydown', (e) => {
    if (mode === 'idle') return;
    if (e.code === 'Space') {
      e.preventDefault();
      if (mode === 'drawing') { penDown = !penDown; endStroke(); showLive(); }
    } else if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); finish(); }
  }, true);
  window.addEventListener('pointerdown', (e) => {
    if (mode === 'drawing') { e.preventDefault(); e.stopPropagation(); finish(); finishedAt = performance.now(); }
  }, true);
  startBtn.onclick = () => {
    startBtn.blur();
    if (performance.now() - finishedAt < 600) return;
    if (mode !== 'idle') { finish(); return; }
    mode = 'countdown'; penDown = true; startBtn.textContent = 'Cancel';
    let n = 3; countEl.textContent = n; countEl.hidden = false;
    liveEl.hidden = false; liveEl.className = 'live up';
    liveEl.innerHTML = '<span class="dot"></span>Move the pointer to where you want to start';
    timer = setInterval(() => {
      n -= 1;
      if (n > 0) { countEl.textContent = n; return; }
      clearInterval(timer); countEl.hidden = true;
      mode = 'drawing'; wrap.classList.add('hovering'); showLive();
    }, 1000);
  };

  // tools
  $('undo').onclick = () => { strokes.pop(); redraw(); };
  $('clear').onclick = () => { strokes = []; redraw(); };
  $('width').oninput = (e) => { baseW = +e.target.value; };
  document.querySelectorAll('.swatch').forEach((b) => { b.onclick = () => {
    document.querySelectorAll('.swatch').forEach((x) => x.classList.remove('on'));
    b.classList.add('on'); color = b.dataset.c;
    strokes.forEach((s) => { s.c = color; }); redraw();
  }; });
  window.addEventListener('resize', resize);

  // Crop to the ink at 4x resolution on a transparent background.
  function exportPNG() {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    strokes.forEach((s) => s.pts.forEach((p) => {
      x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y);
    }));
    const pad = 8, S = 4;
    x0 -= pad; y0 -= pad; x1 += pad; y1 += pad;
    const out = document.createElement('canvas');
    out.width = Math.ceil((x1 - x0) * S); out.height = Math.ceil((y1 - y0) * S);
    const o = out.getContext('2d');
    o.setTransform(S, 0, 0, S, -x0 * S, -y0 * S);
    strokes.forEach((s) => drawStroke(o, s));
    return out.toDataURL('image/png');
  }

  $('useSig').onclick = () => { if (strokes.length) submit({ action: 'signed', png: exportPNG() }); };
  $('decline').onclick = () => submit({ action: 'declined' });
  $('approve').onclick = () => submit({ approved: true, comment: $('comment').value });
  $('reject').onclick = () => {
    if (!$('comment').value.trim()) { say('Say what should change, so the agent can fix it.', true); $('comment').focus(); return; }
    submit({ approved: false, comment: $('comment').value });
  };

  poll();
})();
