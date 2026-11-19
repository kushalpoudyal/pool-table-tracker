import React from 'react';

export function Ball({n = 8}) {
  return <span aria-hidden="true" className={`ball ball-${n}`}><i>{n}</i></span>;
}

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
