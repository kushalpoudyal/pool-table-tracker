import React, { useEffect, useRef, useState } from 'react';
import { reducedMotion } from './effects';

// A small playable pool table. Drag back from the cue ball and release to shoot.
// Units are "table units": the playing surface is W×H, framed by RAIL on each side.
const W = 200, H = 100, RAIL = 11, R = 2.7;
const TOTAL_W = W + RAIL * 2, TOTAL_H = H + RAIL * 2;
const MAX_SPEED = 10.5, FRICTION = .989, ROLL_DRAG = .005, SUBSTEPS = 4;
const POCKETS = [
  {x: -.6, y: -.6, r: 5.6}, {x: W / 2, y: -2.2, r: 4.9}, {x: W + .6, y: -.6, r: 5.6},
  {x: -.6, y: H + .6, r: 5.6}, {x: W / 2, y: H + 2.2, r: 4.9}, {x: W + .6, y: H + .6, r: 5.6},
];
const COLORS = {1: '#e8b923', 2: '#2552c4', 3: '#cf352c', 4: '#5c2d91', 5: '#ec6d1f', 6: '#1c8050', 7: '#86222f', 8: '#121014'};
const RACK_ORDER = [1, 10, 2, 3, 8, 11, 12, 4, 13, 5, 6, 14, 7, 15, 9];
const CUE_SPOT = {x: W * .25, y: H / 2};

function rack() {
  const balls = [{n: 0, x: CUE_SPOT.x, y: CUE_SPOT.y}];
  const apex = W * .7, gap = .08;
  let i = 0;
  for (let row = 0; row < 5; row++)
    for (let j = 0; j <= row; j++)
      balls.push({n: RACK_ORDER[i++], x: apex + row * (2 * R + gap) * .866, y: H / 2 + (j - row / 2) * (2 * R + gap)});
  return balls.map(b => ({...b, vx: 0, vy: 0, dx: 1, dy: 0, phase: 0, sunk: false, sinking: 0, px: 0, py: 0}));
}

function step(balls, onPocket) {
  for (let s = 0; s < SUBSTEPS; s++) {
    for (const b of balls) {
      if (b.sunk) continue;
      b.x += b.vx / SUBSTEPS; b.y += b.vy / SUBSTEPS;
      const speed = Math.hypot(b.vx, b.vy);
      if (speed > .001) { b.dx = b.vx / speed; b.dy = b.vy / speed; b.phase += speed / SUBSTEPS / R; }
      const pocket = POCKETS.find(p => Math.hypot(b.x - p.x, b.y - p.y) < p.r);
      if (pocket) { b.sunk = true; b.sinking = 1; b.px = pocket.x; b.py = pocket.y; b.vx = b.vy = 0; onPocket(b); continue; }
      const nearPocket = POCKETS.some(p => Math.hypot(b.x - p.x, b.y - p.y) < p.r + R * 1.6);
      if (!nearPocket) {
        if (b.x < R) { b.x = R; b.vx = Math.abs(b.vx) * .78; }
        if (b.x > W - R) { b.x = W - R; b.vx = -Math.abs(b.vx) * .78; }
        if (b.y < R) { b.y = R; b.vy = Math.abs(b.vy) * .78; }
        if (b.y > H - R) { b.y = H - R; b.vy = -Math.abs(b.vy) * .78; }
      } else {
        // Inside a pocket mouth the ball can still clip the jaw a little further out.
        b.x = Math.min(W + R, Math.max(-R, b.x));
        b.y = Math.min(H + R, Math.max(-R, b.y));
      }
    }
    for (let i = 0; i < balls.length; i++) {
      const a = balls[i];
      if (a.sunk) continue;
      for (let j = i + 1; j < balls.length; j++) {
        const b = balls[j];
        if (b.sunk) continue;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
        if (d >= 2 * R || d === 0) continue;
        const nx = dx / d, ny = dy / d, overlap = (2 * R - d) / 2;
        a.x -= nx * overlap; a.y -= ny * overlap; b.x += nx * overlap; b.y += ny * overlap;
        const rel = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny;
        if (rel <= 0) continue;
        const k = rel * .97;
        a.vx -= k * nx; a.vy -= k * ny; b.vx += k * nx; b.vy += k * ny;
      }
    }
  }
  let moving = false;
  for (const b of balls) {
    if (b.sunk) { if (b.sinking > 0) { b.sinking = Math.max(0, b.sinking - .07); moving = true; } continue; }
    const speed = Math.hypot(b.vx, b.vy);
    const next = Math.max(0, speed * FRICTION - ROLL_DRAG);
    if (next < .01) { b.vx = b.vy = 0; continue; }
    b.vx *= next / speed; b.vy *= next / speed;
    moving = true;
  }
  return moving;
}

function drawTable(ctx) {
  // Walnut rail with a gold inlay.
  const wood = ctx.createLinearGradient(0, 0, 0, TOTAL_H);
  wood.addColorStop(0, '#3a2216'); wood.addColorStop(.5, '#24140d'); wood.addColorStop(1, '#3a2216');
  ctx.fillStyle = wood;
  roundRect(ctx, 0, 0, TOTAL_W, TOTAL_H, 7); ctx.fill();
  ctx.strokeStyle = '#d9b56c88'; ctx.lineWidth = .45;
  roundRect(ctx, 2.6, 2.6, TOTAL_W - 5.2, TOTAL_H - 5.2, 5); ctx.stroke();
  // Diamond sights.
  ctx.fillStyle = '#ecd59a';
  for (let i = 1; i < 8; i++) if (i !== 4) {
    diamond(ctx, RAIL + W * i / 8, RAIL / 2); diamond(ctx, RAIL + W * i / 8, TOTAL_H - RAIL / 2);
  }
  for (let i = 1; i < 4; i++) { diamond(ctx, RAIL / 2, RAIL + H * i / 4); diamond(ctx, TOTAL_W - RAIL / 2, RAIL + H * i / 4); }
  // Felt, lit from above.
  ctx.save();
  ctx.translate(RAIL, RAIL);
  const felt = ctx.createRadialGradient(W / 2, H / 2, 6, W / 2, H / 2, W * .62);
  felt.addColorStop(0, '#48266a'); felt.addColorStop(.55, '#30184a'); felt.addColorStop(1, '#170b24');
  ctx.fillStyle = felt;
  ctx.fillRect(-1.5, -1.5, W + 3, H + 3);
  ctx.strokeStyle = '#00000066'; ctx.lineWidth = 1.2;
  ctx.strokeRect(-.9, -.9, W + 1.8, H + 1.8);
  // Head string and foot spot.
  ctx.strokeStyle = '#ffffff10'; ctx.lineWidth = .3;
  ctx.beginPath(); ctx.moveTo(W * .25, 0); ctx.lineTo(W * .25, H); ctx.stroke();
  ctx.fillStyle = '#ffffff22';
  ctx.beginPath(); ctx.arc(W * .7, H / 2, .6, 0, Math.PI * 2); ctx.fill();
  for (const p of POCKETS) {
    const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r);
    g.addColorStop(0, '#000'); g.addColorStop(.75, '#050307'); g.addColorStop(1, '#2a1a12');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(p.x, p.y, p.r * .92, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();
}

function drawBall(ctx, b) {
  let {x, y} = b, scale = 1, alpha = 1;
  if (b.sunk) {
    if (!b.sinking) return;
    const k = b.sinking;
    x = b.px + (b.x - b.px) * k; y = b.py + (b.y - b.py) * k; scale = .55 + .45 * k; alpha = k;
  }
  const r = R * scale;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = '#00000070';
  ctx.beginPath(); ctx.ellipse(x + r * .25, y + r * .4, r * 1.02, r * .9, 0, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.save(); ctx.clip();
  const ivory = '#f6efdf';
  const stripe = b.n > 8;
  ctx.fillStyle = b.n === 0 || stripe ? ivory : COLORS[b.n];
  ctx.fillRect(x - r, y - r, r * 2, r * 2);
  if (stripe) {
    ctx.fillStyle = COLORS[b.n - 8];
    ctx.translate(x, y); ctx.rotate(Math.atan2(b.dy, b.dx) + Math.PI / 2);
    ctx.fillRect(-r, -r * .56, r * 2, r * 1.12);
  }
  ctx.restore();
  if (b.n > 0) {
    // Numbers are on both sides, so one disc is always visible, travelling with the roll.
    const wrapped = ((b.phase + Math.PI / 2) % Math.PI + Math.PI) % Math.PI - Math.PI / 2;
    const cos = Math.cos(wrapped), sin = Math.sin(wrapped), angle = Math.atan2(b.dy, b.dx);
    ctx.save();
    ctx.translate(x + b.dx * sin * r * .55, y + b.dy * sin * r * .55);
    ctx.rotate(angle); ctx.scale(Math.max(cos, .08), 1); ctx.rotate(-angle);
    ctx.fillStyle = ivory;
    ctx.beginPath(); ctx.arc(0, 0, r * .48, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#15101a';
    ctx.font = `800 ${r * .62}px Inter, system-ui, sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(String(b.n), 0, r * .04);
    ctx.restore();
  }
  const shade = ctx.createRadialGradient(x - r * .3, y - r * .35, r * .1, x, y, r);
  shade.addColorStop(0, '#ffffff00'); shade.addColorStop(.55, '#00000000'); shade.addColorStop(1, '#00000080');
  ctx.fillStyle = shade;
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  const shine = ctx.createRadialGradient(x - r * .38, y - r * .42, 0, x - r * .38, y - r * .42, r * .62);
  shine.addColorStop(0, '#ffffffe0'); shine.addColorStop(1, '#ffffff00');
  ctx.fillStyle = shine;
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}

function drawAim(ctx, cue, aim) {
  const {dx, dy, power} = aim;
  // Dotted guide in the shot direction.
  ctx.save();
  ctx.setLineDash([1.2, 2]);
  const guide = ctx.createLinearGradient(cue.x, cue.y, cue.x + dx * 70, cue.y + dy * 70);
  guide.addColorStop(0, '#f2dc9fcc'); guide.addColorStop(1, '#f2dc9f00');
  ctx.strokeStyle = guide; ctx.lineWidth = .5;
  ctx.beginPath(); ctx.moveTo(cue.x + dx * (R + 1), cue.y + dy * (R + 1)); ctx.lineTo(cue.x + dx * 70, cue.y + dy * 70); ctx.stroke();
  ctx.restore();
  // The cue stick, pulled back in proportion to power.
  const back = R + 1.5 + power * 16, length = 92;
  const sx = cue.x - dx * back, sy = cue.y - dy * back, ex = sx - dx * length, ey = sy - dy * length;
  ctx.save();
  ctx.lineCap = 'round';
  ctx.strokeStyle = '#00000055'; ctx.lineWidth = 2.2;
  ctx.beginPath(); ctx.moveTo(sx + 1, sy + 1.6); ctx.lineTo(ex + 1, ey + 1.6); ctx.stroke();
  const wood = ctx.createLinearGradient(sx, sy, ex, ey);
  wood.addColorStop(0, '#f3e6c8'); wood.addColorStop(.04, '#f3e6c8'); wood.addColorStop(.05, '#e2c48a');
  wood.addColorStop(.62, '#b07c3e'); wood.addColorStop(.64, '#d9b56c'); wood.addColorStop(.66, '#2a160c'); wood.addColorStop(1, '#140a06');
  ctx.strokeStyle = wood; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(ex, ey); ctx.stroke();
  ctx.fillStyle = '#5a7fbf';
  ctx.beginPath(); ctx.arc(sx, sy, .78, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
  // Power gauge along the bottom rail.
  ctx.save();
  ctx.translate(-RAIL, -RAIL);
  const gx = TOTAL_W / 2 - 30, gy = TOTAL_H - RAIL / 2 - .9;
  ctx.fillStyle = '#00000088'; roundRect(ctx, gx, gy, 60, 1.8, .9); ctx.fill();
  const fill = ctx.createLinearGradient(gx, 0, gx + 60, 0);
  fill.addColorStop(0, '#9a7438'); fill.addColorStop(.6, '#f2dc9f'); fill.addColorStop(1, '#ff7a5c');
  ctx.fillStyle = fill; roundRect(ctx, gx, gy, Math.max(1.8, 60 * power), 1.8, .9); ctx.fill();
  ctx.restore();
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
function diamond(ctx, x, y) {
  ctx.beginPath(); ctx.moveTo(x, y - .9); ctx.lineTo(x + .6, y); ctx.lineTo(x, y + .9); ctx.lineTo(x - .6, y); ctx.closePath(); ctx.fill();
}

export default function PoolTable() {
  const canvas = useRef(null);
  const game = useRef(null);
  const [sunk, setSunk] = useState(0);
  const [hint, setHint] = useState('Drag back from the cue ball, release to shoot');

  useEffect(() => {
    const el = canvas.current, ctx = el.getContext('2d');
    const g = game.current = {balls: rack(), aim: null, drag: null, running: false, demo: null, touched: false, scale: 1};
    let raf = 0;

    const cue = () => g.balls[0];
    const moving = () => g.balls.some(b => !b.sunk ? b.vx || b.vy : b.sinking > 0);
    const countSunk = () => g.balls.filter(b => b.n && b.sunk).length;

    function draw() {
      ctx.setTransform(g.scale, 0, 0, g.scale, 0, 0);
      ctx.clearRect(0, 0, TOTAL_W, TOTAL_H);
      drawTable(ctx);
      ctx.translate(RAIL, RAIL);
      for (const b of g.balls) drawBall(ctx, b);
      if (g.aim && !cue().sunk) drawAim(ctx, cue(), g.aim);
    }
    function frame(t) {
      raf = 0;
      if (g.demo) runDemo(t);
      const active = step(g.balls, b => { if (b.n) setSunk(countSunk()); });
      if (!active) settle();
      draw();
      if (active || g.drag || g.demo) raf = requestAnimationFrame(frame);
    }
    const kick = () => { if (!raf) raf = requestAnimationFrame(frame); };
    g.kick = kick;

    // Once everything stops: return a scratched cue ball, re-rack an empty table.
    function settle() {
      const c = cue();
      if (c.sunk) {
        // First free spot near the head spot, scanning outward but always on the felt.
        const free = (x, y) => !g.balls.some(b => b !== c && !b.sunk && Math.hypot(b.x - x, b.y - y) < 2 * R + .2);
        let spot = CUE_SPOT;
        search: for (let ring = 0; ring < 12; ring++)
          for (const [ox, oy] of [[0, 0], [-1, 0], [0, -1], [0, 1], [1, 0], [-1, -1], [-1, 1], [1, -1], [1, 1]]) {
            const x = CUE_SPOT.x + ox * ring * 2 * R, y = CUE_SPOT.y + oy * ring * 2 * R;
            if (x < R * 2 || x > W - R * 2 || y < R * 2 || y > H - R * 2) continue;
            if (free(x, y)) { spot = {x, y}; break search; }
          }
        Object.assign(c, {x: spot.x, y: spot.y, vx: 0, vy: 0, sunk: false, sinking: 0});
        setHint('Scratch! The cue ball is back on the spot');
      }
      if (countSunk() === 15) {
        g.balls = rack(); setSunk(0); setHint('Cleared the table. Racked again');
      }
    }
    function shoot(dx, dy, power) {
      const c = cue();
      c.vx = dx * power * MAX_SPEED; c.vy = dy * power * MAX_SPEED;
      g.aim = null;
      kick();
    }
    g.shoot = shoot;
    g.rerack = () => { g.balls = rack(); g.aim = null; g.demo = null; setSunk(0); setHint('Fresh rack. Break when ready'); draw(); };
    g.breakShot = () => {
      if (moving() || cue().sunk) return;
      const c = cue(), tx = W * .7 - c.x, ty = H / 2 + (Math.random() - .5) * 1.2 - c.y, d = Math.hypot(tx, ty);
      g.touched = true;
      g.demo = {start: null, dx: tx / d, dy: ty / d};
      kick();
    };
    // Scripted break: the stick draws back, pauses, then strikes.
    function runDemo(t) {
      const d = g.demo;
      d.start ??= t;
      const k = (t - d.start) / 1000;
      if (k < .9) g.aim = {dx: d.dx, dy: d.dy, power: Math.sin(Math.min(k / .9, 1) * Math.PI / 2) * .95};
      else { g.demo = null; shoot(d.dx, d.dy, 1); }
    }

    const toTable = e => {
      const r = el.getBoundingClientRect(), s = r.width / TOTAL_W;
      return {x: (e.clientX - r.left) / s - RAIL, y: (e.clientY - r.top) / s - RAIL};
    };
    const updateAim = p => {
      const c = cue(), dx = c.x - p.x, dy = c.y - p.y, d = Math.hypot(dx, dy) || 1;
      const pulled = Math.hypot(p.x - g.drag.x, p.y - g.drag.y);
      g.aim = {dx: dx / d, dy: dy / d, power: Math.min(1, pulled / 45)};
    };
    const down = e => {
      if (moving() || cue().sunk || g.demo) return;
      g.touched = true;
      try { el.setPointerCapture(e.pointerId); } catch { /* synthetic or already-released pointer */ }
      g.drag = toTable(e);
      updateAim(g.drag);
      kick();
    };
    const move = e => { if (g.drag) { updateAim(toTable(e)); kick(); } };
    // An OS-cancelled gesture (edge swipe, notification) drops the aim instead of shooting.
    const cancel = () => { if (!g.drag) return; g.drag = null; g.aim = null; draw(); };
    const up = () => {
      if (!g.drag) return;
      g.drag = null;
      const aim = g.aim;
      if (aim && aim.power > .04) { shoot(aim.dx, aim.dy, aim.power); setHint('Nice. Line up the next one'); }
      else { g.aim = null; draw(); }
    };
    el.addEventListener('pointerdown', down);
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', cancel);

    const resize = new ResizeObserver(() => {
      const width = el.clientWidth, dpr = Math.min(window.devicePixelRatio || 1, 2);
      el.width = Math.round(width * dpr); el.height = Math.round(width * TOTAL_H / TOTAL_W * dpr);
      g.scale = el.width / TOTAL_W;
      draw();
    });
    resize.observe(el);

    // Break automatically the first time the table is on screen, unless the visitor got there first.
    let timer;
    const seen = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting || reducedMotion()) return;
      seen.disconnect();
      timer = setTimeout(() => { if (!g.touched) g.breakShot(); }, 1600);
    }, {threshold: .6});
    seen.observe(el);

    return () => {
      cancelAnimationFrame(raf); clearTimeout(timer); resize.disconnect(); seen.disconnect();
      el.removeEventListener('pointerdown', down); el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', cancel);
    };
  }, []);

  return <figure className="pool-table">
    <canvas ref={canvas} role="img" aria-label="Playable pool table. Drag back from the cue ball and release to shoot."/>
    <figcaption>
      <span className="pool-hint">{hint}</span>
      <span className="pool-score"><b>{sunk}</b>/15 pocketed</span>
      <span className="pool-actions">
        <button type="button" className="chip-btn" onClick={() => game.current?.breakShot()}>Break</button>
        <button type="button" className="chip-btn" onClick={() => game.current?.rerack()}>Re-rack</button>
      </span>
    </figcaption>
  </figure>;
}
