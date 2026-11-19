import { useEffect } from 'react';

export const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

// Page-wide pointer effects, wired once with event delegation:
// - the "table lamp" spotlight follows the cursor (--lamp-x / --lamp-y on .lamp only, so
//   moving the mouse restyles one element rather than the whole document)
// - any element with [data-tilt] leans toward the cursor and catches a glare highlight.
export function usePointerEffects() {
  useEffect(() => {
    let frame = 0, event = null, tilted = null;
    const reset = el => { el.style.removeProperty('--rx'); el.style.removeProperty('--ry'); el.classList.remove('tilting'); };
    const apply = () => {
      frame = 0;
      const e = event;
      const lamp = document.querySelector('.lamp');
      if (lamp) {
        lamp.style.setProperty('--lamp-x', `${e.clientX}px`);
        lamp.style.setProperty('--lamp-y', `${e.clientY}px`);
      }
      const el = e.target.closest?.('[data-tilt]');
      if (tilted && tilted !== el) reset(tilted);
      tilted = el;
      if (!el || reducedMotion()) return;
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      const strength = Number(el.dataset.tilt) || 6;
      el.classList.add('tilting');
      el.style.setProperty('--rx', `${((.5 - y) * strength).toFixed(2)}deg`);
      el.style.setProperty('--ry', `${((x - .5) * strength).toFixed(2)}deg`);
      el.style.setProperty('--gx', `${(x * 100).toFixed(1)}%`);
      el.style.setProperty('--gy', `${(y * 100).toFixed(1)}%`);
    };
    const onMove = e => {
      if (e.pointerType && e.pointerType !== 'mouse') return;
      event = e;
      if (!frame) frame = requestAnimationFrame(apply);
    };
    // pointerleave is not dispatched to document, so listen on <html> for leaving the window.
    const onLeave = () => { cancelAnimationFrame(frame); frame = 0; if (tilted) reset(tilted); tilted = null; };
    const root = document.documentElement;
    window.addEventListener('pointermove', onMove, {passive: true});
    root.addEventListener('pointerleave', onLeave);
    return () => {
      window.removeEventListener('pointermove', onMove);
      root.removeEventListener('pointerleave', onLeave);
      cancelAnimationFrame(frame);
    };
  }, []);
}

// Fades [data-reveal] elements in as they scroll into view. A MutationObserver picks up
// elements whenever they mount (from any component) and stops watching them on removal.
export function useReveal() {
  useEffect(() => {
    const all = root => [...(root.matches?.('[data-reveal]') ? [root] : []), ...(root.querySelectorAll?.('[data-reveal]') ?? [])];
    if (!('IntersectionObserver' in window) || !('MutationObserver' in window)) return;
    const io = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add('in');
        io.unobserve(entry.target);
      }
    }, {rootMargin: '0px 0px -6% 0px', threshold: .08});
    const watch = el => { if (!el.classList.contains('in')) io.observe(el); };
    all(document.body).forEach(watch);
    const mo = new MutationObserver(records => {
      for (const r of records) {
        r.addedNodes.forEach(n => { if (n.nodeType === 1) all(n).forEach(watch); });
        r.removedNodes.forEach(n => { if (n.nodeType === 1) all(n).forEach(el => io.unobserve(el)); });
      }
    });
    mo.observe(document.body, {childList: true, subtree: true});
    // Only hide content once something is guaranteed to reveal it again.
    document.documentElement.classList.add('reveal-ready');
    return () => { mo.disconnect(); io.disconnect(); document.documentElement.classList.remove('reveal-ready'); };
  }, []);
}
