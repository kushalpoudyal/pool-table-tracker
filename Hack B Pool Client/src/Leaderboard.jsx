import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLiveFrame } from './LiveFeed';
import Ball3D from './Ball3D';
import { CountUp, Form, RankChip, Streak, when } from './shared';
import { reducedMotion } from './effects';
import { MOVEMENT_WINDOW, headToHead, highlights, standingsWithInsights } from './insights';
import './leaderboard.css';

// The screen is laid out at a fixed design size and scaled to the viewport, so it
// always fills the window exactly and never scrolls. Landscape screens get the
// two-column layout; portrait screens (phones) get a single column.
const DESKTOP = {width: 1440, height: 860};
const MOBILE = {width: 420, height: 760};
const HIGHLIGHT_MS = 8000;
const CELEBRATE_MS = 7000;

function useFit() {
  const measure = () => {
    const vw = window.innerWidth, vh = window.innerHeight;
    const mobile = vw < 720 || vw / vh < 1;
    const base = mobile ? MOBILE : DESKTOP;
    const scale = Math.min(vw / base.width, vh / base.height);
    return {mobile, scale, width: vw / scale, height: vh / scale};
  };
  const [fit, setFit] = useState(measure);
  useEffect(() => {
    const onResize = () => setFit(measure());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return fit;
}

// How many rows of `rowHeight` fit in the element. Callback ref so it re-measures
// when the list element is swapped (e.g. after loading).
function useFitCount(rowHeight) {
  const [el, setEl] = useState(null);
  const [count, setCount] = useState(0);
  useLayoutEffect(() => {
    if (!el) return;
    const update = () => setCount(Math.max(0, Math.floor(el.clientHeight / rowHeight)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [el, rowHeight]);
  return [setEl, count];
}

// Ticks every second on its own, so the rest of the screen only re-renders on board updates.
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t); }, []);
  return <div className="fb-clock"><strong>{now.toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'})}</strong><small>{now.toLocaleDateString(undefined, {weekday: 'long', day: 'numeric', month: 'long'})}</small></div>;
}

// FLIP: when children with data-flip ids change position, slide them from the old spot.
function useFlip() {
  const [el, setEl] = useState(null);
  const last = useRef(new Map());
  useLayoutEffect(() => {
    if (!el) return;
    const next = new Map();
    for (const child of el.querySelectorAll('[data-flip]')) {
      const id = child.dataset.flip, top = child.offsetTop;
      next.set(id, top);
      const prev = last.current.get(id);
      if (prev !== undefined && prev !== top && !reducedMotion()) {
        child.animate([{transform: `translateY(${prev - top}px)`}, {transform: 'none'}], {duration: 700, easing: 'cubic-bezier(.2,.8,.2,1)'});
      }
    }
    last.current = next;
  });
  return setEl;
}

// Watches the board for games that just got a winner and announces them.
export function useCelebration(board, ready) {
  const seen = useRef(null);
  const [celebration, setCelebration] = useState(null);
  useEffect(() => {
    if (!ready) return;
    const statuses = new Map(board.matches.map(m => [m.id, m.status]));
    if (seen.current) {
      const fresh = board.matches
        .filter(m => m.status === 'complete' && seen.current.get(m.id) !== 'complete')
        .sort((x, y) => y.id - x.id)[0];
      if (fresh) setCelebration({match: fresh, at: Date.now()});
    }
    seen.current = statuses;
  }, [board, ready]);
  useEffect(() => {
    if (!celebration) return;
    const t = setTimeout(() => setCelebration(null), CELEBRATE_MS);
    return () => clearTimeout(t);
  }, [celebration]);
  return celebration;
}

function useRotation(length, ms) {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (length < 2) return;
    const t = setInterval(() => setIndex(i => (i + 1) % length), ms);
    return () => clearInterval(t);
  }, [length, ms]);
  return length ? index % length : 0;
}


function WinRate({value}) {
  if (value === null) return <span className="fb-dash">–</span>;
  return <span className="win-rate"><span aria-hidden="true" className="win-track"><span style={{width: `${value}%`}}/></span>{value}%</span>;
}

function Movement({value}) {
  if (!value) return <span className="fb-move flat" aria-label="No change">•</span>;
  const up = value > 0;
  return <span className={`fb-move ${up ? 'up' : 'down'}`} aria-label={`${up ? 'Up' : 'Down'} ${Math.abs(value)}`}>{up ? '▲' : '▼'}{Math.abs(value)}</span>;
}

function Podium({player, place, flash}) {
  if (!player) return <div className={`fb-podium-card place-${place} vacant`}><span className="rank">{place}</span><p>Open spot</p></div>;
  return <div className={`fb-podium-card place-${place}${flash ? ' flash' : ''}`}>
    <RankChip rank={place}/>
    <Ball3D n={place} size={place === 1 ? 70 : 52} spin={place === 1 ? 3.6 : 4.4} float={place === 1}/>
    <h3>{player.name}</h3>
    <p className="fb-record"><b><CountUp value={player.wins}/></b> W <span>·</span> <b><CountUp value={player.losses}/></b> L</p>
    <WinRate value={player.winRate}/>
    <div className="fb-podium-meta"><Form results={player.form}/><Streak streak={player.streak}/></div>
  </div>;
}

function Standings({board, ranked, ready, mobile, flashId}) {
  const [list, fits] = useFitCount(mobile ? 50 : 54);
  const flip = useFlip();
  const rest = ranked.slice(3, 3 + fits);
  const hidden = Math.max(0, ranked.length - 3 - rest.length);
  return <section className="panel fb-standings" aria-label="Leaderboard">
    <header className="fb-panel-head">
      <div><p className="kicker">Standings</p><h2>Leaderboard</h2><p>Ranked by wins, then fewest losses.</p></div>
      <span className="badge">{board.players.length} player{board.players.length === 1 ? '' : 's'}</span>
    </header>
    {ranked.length ? <>
      <div className="fb-podium">
        <Podium player={ranked[1]} place={2} flash={ranked[1]?.id === flashId}/>
        <Podium player={ranked[0]} place={1} flash={ranked[0]?.id === flashId}/>
        <Podium player={ranked[2]} place={3} flash={ranked[2]?.id === flashId}/>
      </div>
      <div className="fb-table-head" aria-hidden="true"><span>Rank</span><span>Player</span><span>Form</span><span>W</span><span>L</span><span>Win %</span></div>
      <div className="fb-rows-wrap" ref={list}>
        <ol className="fb-rows" ref={flip}>
          {rest.map((p, i) => <li key={p.id} data-flip={p.id} className={`fb-row${p.id === flashId ? ' flash' : ''}`} style={{'--i': i}}>
            <span className="fb-rank-cell"><RankChip rank={i + 4}/><Movement value={p.movement}/></span>
            <span className="fb-name"><strong>{p.name}</strong><Streak streak={p.streak}/></span>
            <Form results={p.form}/>
            <span>{p.wins}</span>
            <span>{p.losses}</span>
            <span><WinRate value={p.winRate}/></span>
          </li>)}
        </ol>
      </div>
      {ranked.length > 3 && <p className="fb-more">
        {hidden ? `Top ${3 + rest.length} of ${ranked.length} players · ` : `All ${ranked.length} players · `}
        arrows show movement over the last {MOVEMENT_WINDOW} games
      </p>}
    </> : <div className="empty fb-empty"><Ball3D n={1} size={44}/><h3>{ready ? 'The ladder is open' : 'Loading standings'}</h3><p>{ready ? 'Add your first player from the scoreboard to claim a spot.' : 'Connecting to the clubhouse.'}</p></div>}
  </section>;
}

function HeadToHead({match, board, ranked, name}) {
  const h = headToHead(match.a, match.b, board.matches);
  const form = id => ranked.find(p => p.id === id)?.form ?? [];
  const share = h.total ? Math.round(h.aWins / h.total * 100) : 50;
  return <div className="fb-h2h">
    <div className="fb-h2h-names">
      <span><strong>{name(match.a)}</strong><Form results={form(match.a)}/></span>
      <span className="fb-h2h-score">{h.total ? <><b>{h.aWins}</b>–<b>{h.bWins}</b></> : 'First meeting'}</span>
      <span><strong>{name(match.b)}</strong><Form results={form(match.b)}/></span>
    </div>
    <div className="fb-h2h-bar" aria-hidden="true"><span style={{width: `${share}%`}}/></div>
    <small>{h.total ? `Head to head · ${h.total} game${h.total === 1 ? '' : 's'}` : 'No previous games between these two'}</small>
  </div>;
}

function LiveGame({match, board, ranked, name}) {
  // An external match is filmed by the stream server's table camera, not by a phone browser.
  const [image, status] = useLiveFrame(match.external ? null : match.id, 500);
  return <>
    <div className="fb-live-title"><span className="badge recording fb-pulse">{match.live ? 'LIVE' : 'GAME STARTED'}</span><small>Started {when(match.started)}</small></div>
    <HeadToHead match={match} board={board} ranked={ranked} name={name}/>
    <div className="live-screen fb-screen"><img ref={match.external ? undefined : image} src={match.external ? '/api/stream-server/video' : undefined}
      alt={`Live pool table: ${name(match.a)} versus ${name(match.b)}`}/></div>
    <p className="fb-live-status" role="status">{match.external ? 'Live from the table camera' : status}</p>
  </>;
}

function TableCard({board, ranked, name}) {
  const live = board.matches.filter(m => m.status === 'recording');
  if (!live.length) return <section className="panel fb-free" aria-label="At the table">
    <span className="fb-free-ball"><Ball3D n={8} size={46} spin={4}/></span>
    <div><p className="kicker">At the table now</p><h2>Table is free</h2><p>Start a game from the Controller to stream it here.</p></div>
  </section>;
  return <section className="panel fb-now" aria-label="At the table">
    <header className="fb-panel-head compact">
      <div><p className="kicker">At the table now</p><h2>Game in progress</h2></div>
      {live.length > 1 && <span className="badge recording">{live.length} games</span>}
    </header>
    <div className="fb-now-body"><LiveGame match={live[0]} board={board} ranked={ranked} name={name}/></div>
  </section>;
}

function Highlights({items, compact}) {
  const index = useRotation(items.length, HIGHLIGHT_MS);
  if (!items.length) return null;
  const h = items[index];
  if (compact) return <section className="panel fb-ticker" aria-live="polite">
    <div key={h.key} className="fb-ticker-item"><span className="kicker">{h.kicker}</span><strong>{h.title}</strong></div>
  </section>;
  return <section className="panel fb-highlights" aria-live="polite" aria-label="Highlights">
    <div key={h.key} className="fb-highlight">
      <Ball3D n={h.ball} size={58} float/>
      <div><p className="kicker">{h.kicker}</p><h3>{h.title}</h3><p>{h.detail}</p></div>
    </div>
    {items.length > 1 && <div className="fb-dots" aria-hidden="true">{items.map((x, i) => <i key={x.key} className={i === index ? 'on' : ''}/>)}</div>}
  </section>;
}

function RecentGames({board, name}) {
  const games = board.matches.filter(m => m.status === 'complete' || m.status === 'pending');
  const [list, fits] = useFitCount(66);
  return <section className="panel fb-recent" aria-label="Recent games">
    <header className="fb-panel-head compact"><div><p className="kicker">Match history</p><h2>Recent games</h2></div></header>
    <ol className="fb-games" ref={list}>
      {games.slice(0, fits).map((m, i) => <li key={m.id} className="fb-game" style={{'--i': i}}>
        <div><small>GAME {String(m.id).padStart(3, '0')} &middot; {when(m.started)}</small><h3>{name(m.a)} <em>vs</em> {name(m.b)}</h3></div>
        <span className={`badge ${m.status}`}>{m.status === 'complete' ? `${name(m.winner)} won` : 'In review'}</span>
      </li>)}
      {!games.length && <li className="fb-none">No finished games yet.</li>}
    </ol>
  </section>;
}

function Stats({board, ready}) {
  const {players, matches} = board;
  const items = [
    [players.length, 'Players'],
    [matches.filter(m => m.status === 'complete').length, 'Games scored'],
    [matches.filter(m => m.status === 'pending').length, 'In review'],
  ];
  return <div className="fb-stats">
    {items.map(([value, label]) => <div className="stat fb-stat" key={label}><p>{label}</p><strong>{ready ? <CountUp value={value}/> : '–'}</strong></div>)}
  </div>;
}

export function Celebration({celebration, name}) {
  if (!celebration) return null;
  const {match} = celebration;
  const loser = match.winner === match.a ? match.b : match.a;
  return <div className="fb-celebrate" role="status" key={celebration.at}>
    <div className="fb-confetti" aria-hidden="true">{Array.from({length: 18}, (_, i) => <i key={i} style={{'--i': i}}/>)}</div>
    <Ball3D n={1} size={48} spin={0.9}/>
    <div><p className="kicker">Result in · Game {String(match.id).padStart(3, '0')}</p><h2>{name(match.winner)} <em>beats</em> {name(loser)}</h2></div>
  </div>;
}

export default function Leaderboard({board, ready, error}) {
  const fit = useFit();
  const name = id => board.players.find(p => p.id === id)?.name ?? 'Unknown';
  const live = board.matches.find(m => m.status === 'recording');
  const celebration = useCelebration(board, ready);
  // Computed once per board refresh and shared by every panel.
  const ranked = useMemo(() => standingsWithInsights(board.players, board.matches), [board]);
  const items = useMemo(() => highlights(board.players, board.matches, ranked, new Date()), [board, ranked]);

  useEffect(() => {
    const prev = document.title;
    document.title = 'Leaderboard | Rackroom';
    const onKey = e => { if (e.key === 'Escape' && !document.fullscreenElement) location.href = '/'; };
    window.addEventListener('keydown', onKey);
    return () => { document.title = prev; window.removeEventListener('keydown', onKey); };
  }, []);
  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else document.documentElement.requestFullscreen?.()?.catch?.(() => {});
  };
  const flashId = celebration?.match.winner;

  return <div className="fb-viewport">
    <div className={`fb-stage${fit.mobile ? ' mobile' : ''}`}
      style={{width: fit.width, height: fit.height, transform: `scale(${fit.scale})`}}>
      <header className="fb-top">
        <a className="brand" href="/" title="Back to the scoreboard"><Ball3D n={8} size={34} spin={6}/> <span className="wordmark">Rackroom</span></a>
        {!fit.mobile && <span className={ready && !error ? 'connection online' : 'connection'}>{error ? 'Reconnecting' : ready ? 'Board online · updates live' : 'Connecting'}</span>}
        <div className="fb-tools">
          <Clock/>
          {!fit.mobile && <button className="btn fb-icon-btn" onClick={toggleFullscreen} title="Toggle full screen" aria-label="Toggle full screen">⤢</button>}
          <a className="btn fb-icon-btn" href="/" title="Exit (Esc)" aria-label="Exit full screen leaderboard">✕</a>
        </div>
      </header>
      {error && <p className="alert fb-alert" role="alert">{error}</p>}
      <main className="fb-main">
        {fit.mobile ? <>
          {live ? <a className="panel fb-live-strip" href="/watch"><span className="badge recording fb-pulse">LIVE</span><strong>{name(live.a)} <em>vs</em> {name(live.b)}</strong><span aria-hidden="true">&rarr;</span></a>
            : <Highlights items={items} compact/>}
          <Standings board={board} ranked={ranked} ready={ready} mobile flashId={flashId}/>
        </> : <>
          <Standings board={board} ranked={ranked} ready={ready} flashId={flashId}/>
          <div className="fb-side">
            <Stats board={board} ready={ready}/>
            <TableCard board={board} ranked={ranked} name={name}/>
            {!live && <Highlights items={items}/>}
            <RecentGames board={board} name={name}/>
          </div>
        </>}
      </main>
      <Celebration celebration={celebration} name={name}/>
    </div>
  </div>;
}
