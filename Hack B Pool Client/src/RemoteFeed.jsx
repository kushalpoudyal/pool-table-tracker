import React, { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { commentaryPlayer, createLineTracker } from './commentary';

// The commentator: plays each new line once (streamed audio, or the browser's voice), with a mute switch
// and the tap that browsers need before a page may make sound. speakExisting: the page started this game
// (Controller), so its first lines are new too; otherwise the lines already there on load stay quiet.
function Commentary({lines, speakExisting}) {
  const player=commentaryPlayer();
  const tracker=useRef(null);
  if(!tracker.current) tracker.current=createLineTracker({speakExisting});
  const [, redraw]=useState(0);
  useEffect(()=>player.subscribe(()=>redraw(n=>n+1)),[player]);
  useEffect(()=>{ for(const line of tracker.current.fresh(lines)) player.say(line); },[lines,player]);
  if(!lines) return null;   // an older stream server: no commentary
  return <div className="commentary">
    <div className="commentary-controls">
      {!player.unlocked && !player.muted && <button className="btn primary" onClick={()=>player.unlock()}>🔊 Tap to turn on commentary</button>}
      <button className="text-btn" aria-pressed={player.muted} onClick={()=>player.setMuted(!player.muted)}>
        {player.muted?'Commentary muted · unmute':'Mute commentary'}</button>
    </div>
    {lines.length>0 && <ol className="commentary-lines" aria-live="polite">{lines.slice(-3).map(l=>
      <li key={l.id} className={l.priority}>{l.text}</li>)}</ol>}
  </div>;
}

export function Score({game, speakExisting=false}) {
  if(!game?.configured || !game.players?.length) return null;
  return <div className="remote-score" aria-live="polite">
    {game.winner && <p className="remote-winner">{game.winner} wins</p>}
    <ul>{game.players.map(p=><li key={p.name} className={p.at_table?'at-table':''}>
      <strong>{p.name}</strong>{p.at_table && <span className="badge pending">At the table</span>}
      <span>{p.group?`${p.group} · ${p.left} left`:'Open table'}</span>
      <span className="potted">{p.potted.length?`Potted ${p.potted.join(', ')}`:'Nothing potted'}</span>
    </li>)}</ul>
    <Commentary lines={game.lines} speakExisting={speakExisting}/>
    {game.events.length>0 && <ol className="remote-events">{game.events.slice(0,4).map((e,i)=><li key={i}>
      {e.summary}{e.notes.length>0 && <em> · {e.notes.join('; ')}</em>}</li>)}</ol>}
  </div>;
}

export default function RemoteFeed() {
  const [camera,setCamera]=useState(null), [error,setError]=useState('');
  const [attempt,setAttempt]=useState(0), [loaded,setLoaded]=useState(false);
  const [game,setGame]=useState(null);
  const failed=useRef(false);
  useEffect(()=>{
    let disposed=false, timer;
    async function check() {
      try {
        const status=await api('stream-server/status');
        if(disposed) return;
        if(status.configured && status.connected && failed.current) {
          failed.current=false;setAttempt(n=>n+1);setLoaded(false);
        }
        setCamera(status);setError('');
      } catch(e) {if(!disposed) setError(`External camera unavailable: ${e.message}`);}
      finally {if(!disposed) timer=setTimeout(check,3000);}
    }
    check();
    return ()=>{disposed=true;clearTimeout(timer);};
  },[]);
  useEffect(()=>{
    let disposed=false, timer;
    async function score() {
      try { const g=await api('stream-server/game'); if(!disposed) setGame(g); }
      catch { /* The camera status above already reports an unreachable stream server. */ }
      finally {if(!disposed) timer=setTimeout(score,2000);}
    }
    score();
    return ()=>{disposed=true;clearTimeout(timer);};
  },[]);
  if(!camera?.configured && !error) return null;
  const connected=camera?.connected && !error;
  return <section className="panel live-panel" id="external-camera">
    <header><span className="badge recording">{connected&&loaded?'LIVE':'EXTERNAL CAMERA'}</span>
      <h2>Table camera</h2><p role="status">{error || (connected
        ? `${camera.width} × ${camera.height} · ${camera.fps} fps · ${loaded?'Live from stream server':'Connecting to video...'}`
        : 'Waiting for the phone to connect to the stream server.')}</p>
      <small>The stream server keeps this game's score; it is separate from locally scored matches.</small></header>
    {connected && <div className="live-screen"><img key={attempt}
      src={`/api/stream-server/video?attempt=${attempt}`} alt="Live table camera from stream server"
      onLoad={()=>setLoaded(true)} onError={()=>{failed.current=true;setLoaded(false);setError('External camera video interrupted. Reconnecting...');}}/></div>}
    <Score game={game}/>
  </section>;
}
