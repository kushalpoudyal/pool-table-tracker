import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, post } from './api';
import Controller from './Controller';
import LiveFeed from './LiveFeed';
import './styles.css';

function Ball({n = 8}) {
  return <span aria-hidden="true" className={`ball ball-${n}`}><i>{n}</i></span>;
}

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

function Dashboard({board, add, ready}) {
  const {players,matches} = board;
  const finished = matches.filter(m=>m.status === 'complete');
  const ranks = new Map(players.map(p=>[p.id,{...p,played:0,wins:0}]));
  for (const m of finished) {
    ranks.get(m.a).played++; ranks.get(m.b).played++; ranks.get(m.winner).wins++;
  }
  const sorted = [...ranks.values()].sort((a,b)=>b.wins-a.wins || (a.played-a.wins)-(b.played-b.wins) || a.name.localeCompare(b.name));
  const [filter,setFilter] = useState('all');
  const history = matches.filter(m=>filter==='all' || m.status===filter);
  return <>
    <section className="hero"><div>
      <h1>The score room<span>.</span></h1><p>Your pool club's standings, players and match results.</p>
      <a className="btn primary" href="/play">Start a game <span aria-hidden="true">↗</span></a></div>
    </section>
    <div className="stats">
      {[[players.length,'Players','On the roster'],[finished.length,'Games scored','Confirmed results'],[matches.filter(m=>m.status==='pending').length,'In review','Awaiting a winner']].map(([value,label,sub])=><div className="stat" key={label}><p>{label}</p><strong>{ready ? value : '–'}</strong><small>{sub}</small></div>)}
    </div>
    {matches.some(m=>m.status==='recording') && <section className="panel watch-banner"><div><p className="kicker">AT THE TABLE NOW</p><h2>Game in progress</h2><p>Open Watch games to see the live feed from the phone.</p></div><a className="btn primary" href="/watch">Watch games &rarr;</a></section>}
    <div className="columns"><section className="panel" id="standings"><header><h2>Leaderboard</h2><p>Ranked by wins, then fewest losses.</p></header>
      {sorted.length > 0 && <table><thead><tr>{['Rank','Player','W','L','Win %'].map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>
        {sorted.map((p,i)=>{
          const winRate = p.played ? Math.round(p.wins / p.played * 100) : null;
          return <tr key={p.id}><td><span className={i === 0 ? 'rank first' : 'rank'}>{i+1}</span></td><th scope="row">{p.name}</th><td>{p.wins}</td><td>{p.played-p.wins}</td><td>
            {winRate === null ? '–' : <span className="win-rate"><span aria-hidden="true" className="win-track"><span style={{width: `${winRate}%`}}/></span>{winRate}%</span>}
          </td></tr>;
        })}
      </tbody></table>}
      {!sorted.length && <div className="empty"><Ball n={1}/><h3>{ready?'The ladder is open':'Loading standings'}</h3><p>{ready?'Add your first player to claim a spot on the board.':'Connecting to the clubhouse.'}</p></div>}
    </section>
    <aside className="panel entry"><h2>Add a player</h2><p>New players can be selected in the controller.</p><PlayerEntry onAdded={add}/></aside></div>
    <section className="panel history" id="history"><header><h2>Match history</h2>
      <select aria-label="Filter match history" value={filter} onChange={e=>setFilter(e.target.value)}>{Object.entries({all:'All matches',recording:'Recording',pending:'In review',complete:'Scored',interrupted:'Interrupted'}).map(([v,s])=><option key={v} value={v}>{s}</option>)}</select></header>
      {history.map(m=><article className="match" key={m.id}><div><small>GAME {String(m.id).padStart(3,'0')} &middot; {new Date(m.started).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</small><h3>{ranks.get(m.a).name} <em>vs</em> {ranks.get(m.b).name}</h3></div><span className={`badge ${m.status}`}>{m.status==='complete'?`${ranks.get(m.winner).name} won`:({recording:'Recording',pending:'Awaiting analysis',interrupted:'Interrupted'})[m.status]}</span></article>)}
      {!history.length && <p className="history-empty">{!ready?'Connecting to the match log...':matches.length?'No matches with this status.':'No matches yet. Start a game from the phone controller.'}</p>}
    </section>
  </>;
}

function WatchGames({board, ready}) {
  const games=board.matches.filter(m=>m.status==='recording');
  return <><section className="watch-title"><p className="kicker">THE CLUBHOUSE &nbsp; / &nbsp; LIVE FROM THE TABLE</p>
    <h1>Watch games<span>.</span></h1><p>Choose a game below. Anyone on the club network can watch, no sign-in needed.</p>
    <p className="kicker">{ready?`${games.length} GAME${games.length===1?'':'S'} IN PROGRESS`:'CONNECTING...'}</p></section>
    {games.map(m=><LiveFeed key={m.id} match={m} players={board.players}/>)}
    {ready && !games.length && <section className="panel empty watch-empty"><Ball/><h2>No games in progress</h2><p>When someone starts a game on their phone, the live feed will appear here automatically.</p><a className="btn primary" href="/play">Start a game</a></section>}
  </>;
}

function App() {
  const route=location.pathname.replace(/\/$/,'') || '/';
  const phone=route==='/play', watch=route==='/watch';
  const [board,setBoard] = useState({players:[],matches:[]});
  const liveCount=board.matches.filter(m=>m.status==='recording').length;
  const [ready,setReady] = useState(false);
  const [error,setError] = useState('');
  const version = useRef(0);
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
  return <><header className="top"><div className="top-inner"><a className="brand" href="/"><Ball/> Rackroom</a>
    <nav aria-label="Main navigation"><a href="/" aria-current={!phone&&!watch?'page':undefined}>Scoreboard</a><a href="/watch" aria-current={watch?'page':undefined}>Watch games{liveCount>0?` (${liveCount})`:''}</a><a href="/play" aria-current={phone?'page':undefined}>Controller</a></nav>
    <span className={ready && !error ? 'connection online' : 'connection'}>{error ? 'Reconnecting' : ready ? 'Board online' : 'Connecting'}</span></div></header>
    <main className={phone?'shell phone':'shell'}>{error && <p className="alert" role="alert">{error}</p>}
    {phone?<Controller board={board} add={add} refresh={refresh} PlayerEntry={PlayerEntry}/>:watch?<WatchGames board={board} ready={ready}/>:<Dashboard board={board} ready={ready} add={add}/>}</main></>;
}
createRoot(document.getElementById('root')).render(<App/>);
