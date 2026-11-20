import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, post } from './api';
import Controller from './Controller';
import LiveFeed from './LiveFeed';
import RemoteFeed from './RemoteFeed';
import Leaderboard, { Celebration, useCelebration } from './Leaderboard';
import PoolTable from './PoolTable';
import PlayerDrawer from './PlayerDrawer';
import { highlights, standingsWithInsights } from './insights';
import { reducedMotion, usePointerEffects, useReveal } from './effects';
import { CountUp, Form, RankChip, Streak } from './shared';
import Ball3D from './Ball3D';
import './styles.css';

export function PlayerEntry({onAdded}) {
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const p = await post('players', {name: name.trim()});
      onAdded(p); setName(''); setNote(`${p.name} joined the roster.`);
    } catch (e) { setNote(e.message); }
    finally { setBusy(false); }
  }
  return <form onSubmit={submit}>
    <label htmlFor="player-name">Player name</label>
    <input id="player-name" value={name} onChange={e=>setName(e.target.value)} placeholder="e.g. Alex Morgan" required maxLength={48}/>
    <button className="btn primary wide" disabled={busy || !name.trim()}>{busy ? 'Adding...' : '+ Add player'}</button>
    <small role="status">{note}</small>
  </form>;
}

// Scrolling club ticker built from the same talking points as the big-screen highlights.
function Ticker({items}) {
  if (!items.length) return null;
  const run = [...items, ...items];
  return <section className="ticker" aria-label="Club highlights" style={{'--dur': `${Math.max(24, items.length * 9)}s`}}>
    <div className="ticker-track">
      {run.map((h, i) => <span className="ticker-item" key={`${h.key}-${i}`} aria-hidden={i >= items.length || undefined}>
        <Ball3D n={h.ball} size={22} spin={5}/><b>{h.kicker}</b>{h.title}
      </span>)}
    </div>
  </section>;
}

// The table camera's final score for its games: each player's group and balls, and the game log.
function MatchDetails({d}) {
  return <div className="match-details">
    <p>{d.players.map(p=>`${p.name}: ${p.group||'open table'}, ${p.potted.length?`potted ${p.potted.join(', ')}`:'nothing potted'}`).join(' · ')}</p>
    {d.events?.length>0 && <details><summary>Game log ({d.events.length} moments)</summary>
      <ol>{[...d.events].reverse().map((e,i)=><li key={i}><time>{e.time}</time> {e.summary}{e.notes.length>0 && <em> · {e.notes.join('; ')}</em>}</li>)}</ol></details>}
  </div>;
}

// On desktop the standings scroll inside their card (CSS caps the height). This tracks whether
// rows are hidden below, so the bottom edge fades only when there is more to see.
function useScrollFade() {
  const [el,setEl] = useState(null);
  const [more,setMore] = useState(false);
  useEffect(()=>{
    if (!el) return;
    const update=()=>setMore(el.scrollHeight - el.clientHeight - el.scrollTop > 2);
    update();
    el.addEventListener('scroll',update,{passive:true});
    const resize=new ResizeObserver(update);
    resize.observe(el); if (el.firstElementChild) resize.observe(el.firstElementChild);
    return ()=>{el.removeEventListener('scroll',update);resize.disconnect();};
  },[el]);
  return [setEl,more];
}

function Dashboard({board, add, ready}) {
  const {players,matches} = board;
  const finished = matches.filter(m=>m.status === 'complete');
  const sorted = useMemo(()=>standingsWithInsights(players, matches),[players,matches]);
  const items = useMemo(()=>highlights(players, matches, sorted, new Date()),[players,matches,sorted]);
  const ranks = new Map(sorted.map(p=>[p.id,p]));
  const name = id => ranks.get(id)?.name ?? 'Unknown';
  const [filter,setFilter] = useState('all');
  const [scroller,moreBelow] = useScrollFade();
  const [profile,setProfile] = useState(null);
  const closeProfile = useCallback(()=>setProfile(null),[]);
  const celebration = useCelebration(board, ready);
  const history = matches.filter(m=>filter==='all' || m.status===filter);
  const selected = profile !== null ? sorted.findIndex(p=>p.id===profile) : -1;
  return <>
    <section className="hero">
      <div className="hero-copy">
        <p className="kicker ornament">billiards club</p>
        <h1><span className="line">The <span className="gold-text">score</span></span> <span className="line">room<span className="dot">.</span></span></h1>
        <p>Your pool club's standings, players and match results, kept with care.</p>
        <div className="hero-actions">
          <a className="btn primary" href="/play">Start a game <span aria-hidden="true">↗</span></a>
          <a className="btn ghost" href="/leaderboard">Big screen <span aria-hidden="true">⤢</span></a>
        </div>
      </div>
      <div className="hero-table"><PoolTable/></div>
    </section>
    <Ticker items={items}/>
    <div className="stats">
      {[[players.length,'Players','On the roster',1],[finished.length,'Games scored','Confirmed results',9],[matches.filter(m=>m.status==='pending').length,'In review','Awaiting a winner',5]].map(([value,label,sub,n],i)=>
        <div className="stat" key={label} data-tilt="8" data-reveal style={{'--d': `${i*90}ms`}}>
          <Ball3D n={n} size={30} spin={4 + i}/>
          <p>{label}</p><strong>{ready ? <CountUp value={value} fromZero/> : '–'}</strong><small>{sub}</small>
        </div>)}
    </div>
    {matches.some(m=>m.status==='recording') && <section className="panel watch-banner" data-reveal><div><p className="kicker"><span className="live-dot"/>At the table now</p><h2>Game in progress</h2><p>Open Watch games to see the live feed from the phone.</p></div><a className="btn primary" href="/watch">Watch games &rarr;</a></section>}
    <div className="columns"><section className="panel" id="standings" data-reveal><header className="standings-head"><div><p className="kicker">Standings</p><h2><a href="/leaderboard">Leaderboard</a></h2><p>Ranked by wins, then fewest losses. Select a player for their profile.</p></div><a className="btn full-screen" href="/leaderboard">Full screen <span aria-hidden="true">⤢</span></a></header>
      {sorted.length > 0 && <div className={`standings-scroll${moreBelow?' more':''}`} ref={scroller}><table><thead><tr>{['Rank','Player','Form','W','L','Win %'].map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>
        {sorted.map((p,i)=>{
          const {winRate} = p;
          return <tr key={p.id} className={i < 3 ? `top-${i+1}` : undefined} style={{'--i': i}}><td><RankChip rank={i+1}/></td><th scope="row"><button type="button" className="player-link" onClick={()=>setProfile(p.id)}>{p.name}<Streak streak={p.streak}/></button></th><td className="form-cell"><Form results={p.form}/></td><td>{p.wins}</td><td>{p.losses}</td><td>
            {winRate === null ? '–' : <span className="win-rate"><span aria-hidden="true" className="win-track"><span style={{width: `${winRate}%`}}/></span>{winRate}%</span>}
          </td></tr>;
        })}
      </tbody></table></div>}
      {!sorted.length && <div className="empty"><Ball3D n={1} size={44} float/><h3>{ready?'The ladder is open':'Loading standings'}</h3><p>{ready?'Add your first player to claim a spot on the board.':'Connecting to the clubhouse.'}</p></div>}
    </section>
    <aside className="panel entry" data-reveal style={{'--d': '120ms'}}><p className="kicker">Membership</p><h2>Add a player</h2><p>New players can be selected in the controller.</p><PlayerEntry onAdded={add}/></aside></div>
    <section className="panel history" id="history" data-reveal><header><div><p className="kicker">The ledger</p><h2>Match history</h2></div>
      <select aria-label="Filter match history" value={filter} onChange={e=>setFilter(e.target.value)}>{Object.entries({all:'All matches',recording:'Recording',pending:'In review',complete:'Scored',interrupted:'Interrupted'}).map(([v,s])=><option key={v} value={v}>{s}</option>)}</select></header>
      {history.map((m,i)=><article className="match" key={m.id} style={{'--i': Math.min(i, 12)}}><div><small>GAME {String(m.id).padStart(3,'0')} &middot; {new Date(m.started).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</small><h3>{name(m.a)} <em>vs</em> {name(m.b)}</h3>{m.details && <MatchDetails d={m.details}/>}</div><span className={`badge ${m.status}`}>{m.status==='complete'?`${name(m.winner)} won`:({recording:'Recording',pending:'Awaiting analysis',interrupted:'Interrupted'})[m.status]}</span></article>)}
      {!history.length && <p className="history-empty">{!ready?'Connecting to the match log...':matches.length?'No matches with this status.':'No matches yet. Start a game from the phone controller.'}</p>}
    </section>
    {selected >= 0 && <PlayerDrawer player={sorted[selected]} rank={selected+1} total={sorted.length} board={board} onClose={closeProfile}/>}
    <div className="toast-layer"><Celebration celebration={celebration} name={name}/></div>
  </>;
}

// Page-load intro: a cue strikes the 8-ball, it rolls to centre with a gold burst, then the
// wordmark appears and the curtain lifts. Skipped under prefers-reduced-motion.
const SPARKS=Array.from({length:12},(_,i)=>i*30+15);
function Intro() {
  const [show,setShow] = useState(()=>!reducedMotion());
  useEffect(()=>{
    if (!show) return;
    const t=setTimeout(()=>setShow(false),2600);
    return ()=>clearTimeout(t);
  },[show]);
  if (!show) return null;
  return <div className="intro" aria-hidden="true"><div className="intro-stage">
    <div className="intro-rig">
      <span className="intro-cue"/>
      <span className="intro-hit"/>
      <span className="intro-glow"/>
      <span className="intro-ring"/><span className="intro-ring"/>
      <span className="intro-sparks">{SPARKS.map(a=><i key={a} style={{'--a':`${a}deg`}}/>)}</span>
      <span className="intro-ball"><Ball3D n={8} size={84} spin={6}/></span>
    </div>
    <span className="intro-word">Rackroom</span><i className="intro-line"/>
  </div></div>;
}

function WatchGames({board, ready}) {
  const games=board.matches.filter(m=>m.status==='recording');
  return <><section className="watch-title"><p className="kicker ornament">The clubhouse &nbsp;/&nbsp; Live from the table</p>
    <h1>Watch <span className="gold-text">games</span><span className="dot">.</span></h1><p>Choose a game below. Anyone on the club network can watch, no sign-in needed.</p>
    <p className="kicker">{ready?`${games.length} GAME${games.length===1?'':'S'} IN PROGRESS`:'CONNECTING...'}</p></section>
    <RemoteFeed/>
    {games.filter(m=>!m.external).map(m=><LiveFeed key={m.id} match={m} players={board.players}/>)}
    {ready && !games.length && <section className="panel empty watch-empty" data-reveal><Ball3D n={8} size={56} float/><h2>No scored games in progress</h2><p>Start a game on your phone to track the matchup. External camera feeds are shown separately above when configured.</p><a className="btn primary" href="/play">Start a game</a></section>}
  </>;
}

function App() {
  const route=location.pathname.replace(/\/$/,'') || '/';
  const phone=route==='/play', watch=route==='/watch', fullBoard=route==='/leaderboard';
  const [board,setBoard] = useState({players:[],matches:[]});
  const liveCount=board.matches.filter(m=>m.status==='recording').length;
  const [ready,setReady] = useState(false);
  const [error,setError] = useState('');
  const version = useRef(0);
  usePointerEffects();
  useReveal();
  async function refresh() {
    const request = ++version.current;
    try {
      const snapshot = await api('board');
      if (request===version.current) { setBoard(snapshot); setReady(true); setError(''); }
    } catch(e) { if (request===version.current) setError(`Board unavailable: ${e.message} Reconnecting...`); }
  }
  useEffect(()=>{ refresh(); const timer=setInterval(refresh,4000); return ()=>clearInterval(timer); },[]);
  function add(p) {
    ++version.current;
    setBoard(b=>({...b,players:[...b.players.filter(x=>x.id!==p.id),p]}));
  }
  if (fullBoard) return <Leaderboard board={board} ready={ready} error={error}/>;
  return <><Intro/><div className="lamp" aria-hidden="true"/><header className="top"><div className="top-inner"><a className="brand" href="/"><Ball3D n={8} size={34} spin={6}/> <span className="wordmark">Rackroom</span></a>
    <nav aria-label="Main navigation"><a href="/" aria-current={!phone&&!watch?'page':undefined}>Scoreboard</a><a href="/watch" aria-current={watch?'page':undefined}>Watch games{liveCount>0?` (${liveCount})`:''}</a><a href="/play" aria-current={phone?'page':undefined}>Controller</a></nav>
    <span className={ready && !error ? 'connection online' : 'connection'}>{error ? 'Reconnecting' : ready ? 'Board online' : 'Connecting'}</span></div></header>
    <main className={phone?'shell phone':'shell'}>{error && <p className="alert" role="alert">{error}</p>}
    {phone?<Controller board={board} add={add} refresh={refresh} PlayerEntry={PlayerEntry}/>:watch?<WatchGames board={board} ready={ready}/>:<Dashboard board={board} ready={ready} add={add}/>}</main></>;
}
createRoot(document.getElementById('root')).render(<App/>);
