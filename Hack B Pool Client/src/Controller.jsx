import React, { useEffect, useRef, useState } from 'react';
import { api, post } from './api';
import { Score } from './RemoteFeed';
import { commentaryPlayer } from './commentary';

function closeMatch(game, outcome) {
  return api(`matches/${game.id}/close?outcome=${outcome}`,{method:'POST',headers:{'X-Recorder-Key':game.token}});
}

export default function Controller({board, add, refresh, PlayerEntry}) {
  const [a,A]=useState(''), [b,B]=useState('');
  const [stage,setStage]=useState('select'), [error,setError]=useState('');
  const [seconds,setSeconds]=useState(0), [gameId,setGameId]=useState(null);
  const [liveError,setLiveError]=useState('');
  // external: the stream server's table camera is configured. It films and scores the game, so this page
  // skips the browser camera: it starts the game there, shows its feed and score, and records its winner.
  const [external,setExternal]=useState(false), [score,setScore]=useState(null);
  const [correcting,setCorrecting]=useState(false);
  const canRecord=window.isSecureContext && !!navigator.mediaDevices?.getUserMedia && !!window.MediaRecorder;
  const liveCameraUrl=import.meta.env.VITE_LIVE_CAMERA_URL;
  const stream=useRef(null), video=useRef(null), recorder=useRef(null), current=useRef(null);
  const stopCamera=()=>stream.current?.getTracks().forEach(t=>t.stop());
  const name=id=>board.players.find(p=>p.id===Number(id))?.name;
  const active=['permission','starting','record','saving'].includes(stage);
  useEffect(()=>{
    if (video.current) video.current.srcObject=stream.current;
  },[stage]);
  useEffect(()=>{
    if(stage!=='record') return;
    const start=Date.now(); setSeconds(0);
    const timer=setInterval(()=>setSeconds(Math.floor((Date.now()-start)/1000)),500);
    return ()=>clearInterval(timer);
  },[stage]);
  useEffect(()=>{
    if(!active) return;
    const guard=e=>{e.preventDefault();e.returnValue='';};
    window.addEventListener('beforeunload',guard);
    return ()=>window.removeEventListener('beforeunload',guard);
  },[active]);
  useEffect(()=>()=>stopCamera(),[]);
  useEffect(()=>{api('stream-server/status').then(s=>setExternal(!!s.configured)).catch(()=>{});},[]);
  useEffect(()=>{
    if(stage!=='record' || !external) return;
    let disposed=false, timer;
    async function poll() {
      try { const g=await api('stream-server/game'); if(!disposed) setScore(g); } catch { /* shown on the next poll */ }
      finally {if(!disposed) timer=setTimeout(poll,2000);}
    }
    poll();
    return ()=>{disposed=true;clearTimeout(timer);};
  },[stage,external]);
  useEffect(()=>{  // the table camera ended the game itself (or Stop came second): show the recorded result
    const m=board.matches.find(x=>x.id===gameId);
    if(current.current?.external && ['record','retry'].includes(stage) && m && m.status!=='recording') {setError('');setStage('done');}
  },[board,stage,gameId]);
  useEffect(()=>{
    if(stage!=='record' || external) return;
    let disposed=false, timer;
    const abort=new AbortController();
    const canvas=document.createElement('canvas');
    const context=canvas.getContext('2d');
    async function transmit() {
      try {
        const source=video.current;
        if(!context) throw new Error('Live preview is unavailable in this browser.');
        if(source?.videoWidth && source.readyState>=2) {
          canvas.width=Math.min(640,source.videoWidth);
          canvas.height=Math.round(source.videoHeight*canvas.width/source.videoWidth);
          context.drawImage(source,0,0,canvas.width,canvas.height);
          const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',0.65));
          if(!blob) throw new Error('Could not encode the live preview.');
          if(disposed) return;
          await api(`matches/${gameId}/frame`,{method:'PUT',body:blob,headers:{'X-Recorder-Key':current.current.token},signal:abort.signal});
          setLiveError('');
        }
      } catch(e) {if(!disposed) setLiveError(`Leaderboard preview interrupted: ${e.message} Retrying...`);}
      finally {if(!disposed) timer=setTimeout(transmit,250);}
    }
    setLiveError(''); transmit();
    return ()=>{disposed=true;clearTimeout(timer);abort.abort();};
  },[stage,gameId,external]);

  async function startExternal() {
    commentaryPlayer().unlock();   // inside the Start tap: lets the phone play the commentary from here on
    setStage('starting'); setError(''); setScore(null);
    try {
      const game=await post('stream-server/game',{a:Number(a),b:Number(b)});
      current.current={...game,external:true}; setGameId(game.id); setStage('record'); refresh();
    } catch(e) {setError(e.message);setStage('select');}
  }
  async function stopExternal() {
    setStage('saving');
    try {
      const g=current.current;
      await api(`stream-server/game/${g.id}/end`,{method:'POST',headers:{'X-Recorder-Key':g.token}});
      refresh(); setError(''); setStage('done');
    } catch(e) {setError(`Could not record the game: ${e.message}`);setStage('retry');}
  }
  async function correctWinner(id) {  // the camera or the analyzer got the result wrong: this device fixes it
    setCorrecting(true);
    try {
      await api(`matches/${gameId}/winner`,{method:'POST',body:JSON.stringify({winner:id}),
        headers:{'Content-Type':'application/json','X-Recorder-Key':current.current.token}});
      refresh(); setError('');
    } catch(e) {setError(`Could not correct the result: ${e.message}`);}
    finally {setCorrecting(false);}
  }
  async function start() {
    if(external) return startExternal();
    setStage('permission'); setError('');
    let game;
    try {
      if(!canRecord)
        throw new Error(window.isSecureContext
          ? 'This browser does not support live camera recording. Use a current Safari or Chrome browser.'
          : 'This HTTP page can reach the server, but the browser blocks live camera access here. Open the live-camera address below to stream.');
      const mime=['video/webm','video/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
      if(!mime) throw new Error('This browser cannot record MP4 or WebM.');
      stream.current=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280},height:{ideal:720}},audio:false});
      setStage('starting');
      const rec=new MediaRecorder(stream.current,{mimeType:mime,videoBitsPerSecond:1500000});
      game=await post('matches',{a:Number(a),b:Number(b),mime});
      current.current=game; setGameId(game.id);
      let queue=Promise.resolve(), seq=0, failed='', backlog=0;
      function stopWithError(message) {
        failed=message;
        if(rec.state==='recording') {setStage('saving');rec.stop();}
      }
      rec.ondataavailable=({data})=>{
        if(!data.size || failed) return;
        if(backlog>=12) {stopWithError('The network could not keep up with the video.');return;}
        const index=seq++; backlog++;
        queue=queue.then(async()=>{
          if(!failed) await api(`matches/${game.id}/chunks/${index}`,{method:'PUT',body:data,headers:{'X-Recorder-Key':game.token},signal:AbortSignal.timeout(30000)});
        }).catch(e=>stopWithError(e.message)).finally(()=>backlog--);
      };
      rec.onerror=()=>stopWithError('The camera stopped unexpectedly.');
      stream.current.getVideoTracks()[0].onended=()=>stopWithError('The camera disconnected.');
      rec.onstop=async()=>{
        setStage('saving'); stopCamera(); await queue;
        const outcome=failed || !seq?'discard':'finish';
        current.current={...game,outcome};
        try {
          await closeMatch(game,outcome); refresh();
          setError(failed || (!seq?'No video was captured.':''));
          setStage(outcome==='finish'?'done':'select');
        } catch(e) {setError(`Could not close the game: ${e.message}`);setStage('retry');}
      };
      recorder.current=rec; rec.start(1500); setStage('record'); refresh();
    } catch(e) {
      stopCamera(); setError(e.message); setStage('select');
      if(game) {
        current.current={...game,outcome:'discard'};
        try {await closeMatch(game,'discard');} catch(err) {setError(err.message);setStage('retry');}
      }
    }
  }
  const finished=board.matches.find(m=>m.id===gameId);
  const step=['select','permission'].includes(stage)?0:stage==='done'?2:1;
  return <><div className="phone-title">
    <p className="kicker ornament">Courtside controls</p><h1>Table <span className="gold-text">remote</span><span className="dot">.</span></h1><p>Pick the players. Start the game. Stream from your phone.</p></div>
    <ol className="steps">{['Matchup','Live','Result'].map((s,i)=><li className={step===i?'current':step>i?'done':''} aria-current={step===i?'step':undefined} key={s}><span aria-hidden="true">{step>i?'✓':i+1}</span>{s}</li>)}</ol>
    {error && <p className="alert" role="alert">{error}</p>}
    <section className="panel remote">
    {step===0?<><h2>Who's playing?</h2><p>Choose two different players from the club roster.</p>
      {[[a,A,b,'Player A'],[b,B,a,'Player B']].map(([v,set,other,label])=><label key={label}>{label}<select value={v} disabled={stage==='permission'} onChange={e=>set(e.target.value)}><option value="">Select a player</option>{board.players.map(p=><option key={p.id} value={p.id} disabled={String(p.id)===other}>{p.name}</option>)}</select></label>)}
      <details><summary>New to the roster? Add a player</summary><PlayerEntry onAdded={add}/></details>
      <p>Point your phone at the table before starting. Both players must agree to be recorded. Starting turns on the camera and makes the game visible to everyone in Watch games. No audio is sent.</p>
      <button className="btn primary wide" disabled={!a || !b || a===b || stage==='permission'} onClick={start}>{stage==='permission'?'Opening camera...':external?'Start game':'Start game & stream'}</button>
      {!canRecord && !external && <><p role="status">Live camera access is blocked or unsupported at this address. The game will start only after camera access succeeds.</p>
        {liveCameraUrl && !window.isSecureContext && <a className="btn primary wide" href={liveCameraUrl}>Open live camera</a>}</>}
    </>:stage==='done'?<><p className="kicker">GAME {gameId} &nbsp; / &nbsp; CAPTURE COMPLETE</p>
      <h2>{finished?.winner?`${name(finished.winner)} won`:current.current?.external?'No winner recorded':'Awaiting analysis'}</h2><p>{finished?.winner?'The standings have been updated.':current.current?.external?'The table camera did not see the game finish, so it was not counted.':'The server has the video. The winner will appear here and on the scoreboard when the analyzer returns a result.'}</p>
      {finished && ['complete','interrupted'].includes(finished.status) && current.current?.token && <div className="correct-result">
        <small>Wrong result? Set the winner:</small>
        {[finished.a,finished.b].map(id=><button key={id} className="btn ghost" disabled={correcting || finished.winner===id} onClick={()=>correctWinner(id)}>{name(id)} won</button>)}
      </div>}
      <a className="btn primary wide" href="/">View scoreboard</a><button className="text-btn" onClick={()=>{A('');B('');setStage('select');}}>Set up another game</button>
    </>:<><p className="kicker">{stage==='record'?'LIVE STREAMING':'MATCH CAPTURE'}</p><h2>{name(a)} <em>vs</em> {name(b)}</h2>
      {['record','starting'].includes(stage)&&<div className="camera">{external?<img src="/api/stream-server/video" alt="Live table camera"/>:<video ref={video} playsInline muted autoPlay/>}<div className="camera-guides" aria-hidden="true"><span/><span/><span/><span/></div>{stage==='record'&&<span className="rec">LIVE {Math.floor(seconds/60)}:{String(seconds%60).padStart(2,'0')}</span>}</div>}
      {stage==='record'&&<><p>{external?'Game started. The table camera keeps the score. Anyone can watch this game in the Watch games tab.':'Game started. Sending video to the local Python server. Anyone can watch this game in the Watch games tab. Keep this page open and your phone unlocked.'}</p>
        {external&&<Score game={score} speakExisting/>}
        <p>Viewer link: <a href={`/watch#game-${gameId}`} target="_blank" rel="noreferrer">Watch game {gameId}</a></p>
        {liveError&&<p className="alert" role="alert">{liveError}</p>}
        <button className="btn stop wide" onClick={()=>{if(external) return stopExternal();setStage('saving');recorder.current.stop();}}>■ &nbsp; Stop game &amp; submit</button></>}
      {stage==='starting'&&<p role="status">Starting match...</p>}{stage==='saving'&&<p role="status">Finishing upload. Keep this page open.</p>}
      {stage==='retry'&&<button className="btn primary wide" onClick={async()=>{if(current.current?.external) return stopExternal();setStage('saving');try{const g=current.current;await closeMatch(g,g.outcome);refresh();setError(g.outcome==='discard'?'Recording interrupted. Start a new game.':'');setStage(g.outcome==='discard'?'select':'done');}catch(e){setError(e.message);setStage('retry');}}}>Retry submission</button>}
    </>}
    </section></>;
}
