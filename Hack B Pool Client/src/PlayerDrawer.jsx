import React, { useEffect, useRef } from 'react';
import Ball3D from './Ball3D';
import { CountUp, Form, RankChip, Streak, when } from './shared';

// Record against every opponent this player has faced, most-played first.
function rivals(id, matches) {
  const table = new Map();
  for (const m of matches) {
    if (m.status !== 'complete' || (m.a !== id && m.b !== id)) continue;
    const other = m.a === id ? m.b : m.a;
    const row = table.get(other) ?? {id: other, wins: 0, losses: 0};
    if (m.winner === id) row.wins++; else row.losses++;
    table.set(other, row);
  }
  return [...table.values()].sort((x, y) => (y.wins + y.losses) - (x.wins + x.losses) || y.wins - x.wins);
}

function Ring({value}) {
  const r = 52, c = 2 * Math.PI * r, pct = value ?? 0;
  return <div className="ring" style={{'--c': c, '--off': c * (1 - pct / 100)}}>
    <svg viewBox="0 0 120 120" aria-hidden="true">
      <defs><linearGradient id="ring-gold" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#f7e4ae"/><stop offset=".5" stopColor="#d9b56c"/><stop offset="1" stopColor="#9a7438"/>
      </linearGradient></defs>
      <circle cx="60" cy="60" r={r} className="ring-track"/>
      <circle cx="60" cy="60" r={r} className="ring-fill" strokeDasharray={c}/>
    </svg>
    <div><strong>{value === null ? '–' : <><CountUp value={value} fromZero/>%</>}</strong><small>Win rate</small></div>
  </div>;
}

export default function PlayerDrawer({player, rank, total, board, onClose}) {
  const dialog = useRef(null);
  useEffect(() => {
    const el = dialog.current;
    if (!el.open) el.showModal?.();
    const close = () => onClose();
    el.addEventListener('close', close);
    return () => el.removeEventListener('close', close);
  }, [onClose]);
  const name = id => board.players.find(p => p.id === id)?.name ?? 'Unknown';
  const history = board.matches.filter(m => m.a === player.id || m.b === player.id).slice(0, 6);
  const versus = rivals(player.id, board.matches);
  return <dialog ref={dialog} className="drawer" aria-labelledby="drawer-title"
    onClick={e => {
      // Only a click on the backdrop (left of the panel) closes; empty panel space does not.
      if (e.target === dialog.current && e.clientX < dialog.current.getBoundingClientRect().left) dialog.current.close();
    }}>
    <div className="drawer-body">
      <header className="drawer-head">
        <Ball3D n={rank <= 15 ? rank : 8} size={64} spin={3.4} float/>
        <div>
          <p className="kicker">Rank {rank} of {total}</p>
          <h2 id="drawer-title">{player.name}</h2>
          <div className="drawer-tags"><RankChip rank={rank}/><Streak streak={player.streak}/><Form results={player.form}/></div>
        </div>
        <button type="button" className="btn icon-btn" onClick={() => dialog.current.close()} aria-label="Close player profile">✕</button>
      </header>

      <section className="drawer-hero">
        <Ring value={player.winRate}/>
        <dl className="drawer-stats">
          {[['Played', player.played], ['Wins', player.wins], ['Losses', player.losses], ['Best run', player.bestStreak]].map(([label, value]) =>
            <div key={label}><dt>{label}</dt><dd><CountUp value={value} fromZero/></dd></div>)}
        </dl>
      </section>

      <section className="drawer-section">
        <h3>Head to head</h3>
        {versus.length ? <ul className="versus">
          {versus.map((v, i) => <li key={v.id} style={{'--i': i}}>
            <span>{name(v.id)}</span>
            <span className="versus-bar" aria-hidden="true"><span style={{width: `${v.wins / (v.wins + v.losses) * 100}%`}}/></span>
            <b>{v.wins}–{v.losses}</b>
          </li>)}
        </ul> : <p className="drawer-empty">No scored games yet. Rivalries start at the table.</p>}
      </section>

      <section className="drawer-section">
        <h3>Recent games</h3>
        {history.length ? <ul className="drawer-games">
          {history.map(m => {
            const won = m.status === 'complete' && m.winner === player.id;
            const label = m.status !== 'complete' ? ({recording: 'Live', pending: 'In review', interrupted: 'Interrupted'})[m.status] : won ? 'Won' : 'Lost';
            return <li key={m.id}>
              <div><small>GAME {String(m.id).padStart(3, '0')} · {when(m.started)}</small><span>vs {name(m.a === player.id ? m.b : m.a)}</span></div>
              <span className={`badge ${m.status === 'complete' ? (won ? 'complete' : 'lost') : m.status}`}>{label}</span>
            </li>;
          })}
        </ul> : <p className="drawer-empty">No games on record.</p>}
      </section>
    </div>
  </dialog>;
}
