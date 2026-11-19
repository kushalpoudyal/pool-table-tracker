import React from 'react';
import './ball3d.css';

// Pool-ball colours tuned to the Rackroom palette. 9–15 are stripes of 1–7.
const COLORS = {
  1: '#8f6af0', 2: '#9aa7c4', 3: '#d0864a', 4: '#f0a352',
  5: '#3fc79d', 6: '#e2566f', 7: '#6b4bc7', 8: '#1d1928',
};

// A CSS "3D" pool ball: the number decal travels across the sphere (squashing near the
// edges, hidden while on the far side) under a fixed highlight and shadow, so it reads as
// a ball spinning in place. `spin` is seconds per revolution; `float` adds a gentle bob.
export default function Ball3D({n = 8, size = 40, spin = 3.2, float = false, className = ''}) {
  const stripe = n > 8;
  const color = COLORS[stripe ? n - 8 : n] ?? COLORS[8];
  const style = {
    '--s': `${size}px`,
    '--c': color,
    '--spin': `${spin}s`,
    '--delay': `${-((n * 0.73) % spin).toFixed(2)}s`,
  };
  return <span aria-hidden="true" className={`b3d${stripe ? ' stripe' : ''}${float ? ' float' : ''} ${className}`} style={style}>
    <span className="b3d-surface">
      {stripe && <span className="b3d-stripe"/>}
      <span className="b3d-decal"><i>{n}</i></span>
    </span>
    <span className="b3d-shade"/>
  </span>;
}
