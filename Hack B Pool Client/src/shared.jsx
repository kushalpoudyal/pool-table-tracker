import React, { useEffect, useRef, useState } from 'react';
import { reducedMotion } from './effects';

export const when = iso => new Date(iso).toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});

// Leaderboard order used everywhere: most wins, then fewest losses, then name.
export function rankPlayers(players, matches) {
  const ranks = new Map(players.map(p => [p.id, {...p, played: 0, wins: 0}]));
  for (const m of matches) {
    if (m.status !== 'complete') continue;
    const a = ranks.get(m.a), b = ranks.get(m.b), w = ranks.get(m.winner);
    if (!a || !b || !w) continue;
    a.played++; b.played++; w.wins++;
  }
  return [...ranks.values()]
    .map(p => ({...p, losses: p.played - p.wins, winRate: p.played ? Math.round(p.wins / p.played * 100) : null}))
    .sort((a, b) => b.wins - a.wins || a.losses - b.losses || a.name.localeCompare(b.name));
}

// Animates a number from its previous value to the new one. With `fromZero` the first
// render also counts up from 0; otherwise the initial value shows immediately.
export function CountUp({value, duration = 900, fromZero = false}) {
  const start0 = fromZero && typeof value === 'number' && !reducedMotion();
  const [shown, setShown] = useState(start0 ? 0 : value);
  const from = useRef(start0 ? 0 : value);
  useEffect(() => {
    if (typeof value !== 'number' || reducedMotion()) { setShown(value); from.current = value; return; }
    const start = performance.now(), a = typeof from.current === 'number' ? from.current : 0;
    let frame;
    const tick = t => {
      const k = Math.min(1, (t - start) / duration), eased = 1 - (1 - k) ** 3;
      setShown(Math.round(a + (value - a) * eased));
      if (k < 1) frame = requestAnimationFrame(tick); else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return <>{shown}</>;
}

export function Form({results}) {
  if (!results?.length) return <span className="fb-dash">–</span>;
  return <span className="fb-form" aria-label={`Last ${results.length}: ${results.join(' ')}`}>
    {results.map((r, i) => <i key={i} className={r === 'W' ? 'w' : 'l'} style={{'--i': i}}/>)}
  </span>;
}

export function Streak({streak}) {
  if (!streak || streak.n < 2 || (streak.type === 'L' && streak.n < 3)) return null;
  return <span className={`fb-streak ${streak.type === 'W' ? 'hot' : 'cold'}`} title={`${streak.n} ${streak.type === 'W' ? 'wins' : 'losses'} in a row`}>
    {streak.type}{streak.n}
  </span>;
}

// Gold / silver / bronze chip for the top three, a plain chip for everyone else.
export function RankChip({rank}) {
  const medal = ['', 'gold', 'silver', 'bronze'][rank] ?? '';
  return <span className={`rank${medal ? ` medal ${medal}` : ''}`}>{rank}</span>;
}
