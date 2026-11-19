import React, { useEffect, useRef, useState } from 'react';
import { api, post } from './api';

function closeMatch(game, outcome) {
  return api(`matches/${game.id}/close?outcome=${outcome}`,{method:'POST',headers:{'X-Recorder-Key':game.token}});
}

export default function Controller({board, add, refresh, PlayerEntry}) {
  const [a,A]=useState(''), [b,B]=useState('');
  const [stage,setStage]=useState('select'), [error,setError]=useState('');
  const [seconds,setSeconds]=useState(0), [gameId,setGameId]=useState(null);
  const stream=useRef(null), video=useRef(null), recorder=useRef(null), current=useRef(null);
  const stopCamera=()=>stream.current?.getTracks().forEach(t=>t.stop());
  const name=id=>board.players.find(p=>p.id===Number(id))?.name;
  const active=['starting','record','saving'].includes(stage);
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

  async function preview() {
    setError(''); setStage('permission');
    try {
      if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
        throw new Error('Recording needs HTTPS (or localhost) and a browser with camera recording support.');
      stream.current=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280},height:{ideal:720}},audio:false});
      setStage('preview');
    } catch(e) {setError(`Camera not ready: ${e.message}`);setStage('select');}
  }
  async function start() {
    setStage('starting'); setError('');
    let game;
    try {
      const mime=['video/webm','video/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
      if(!mime) throw new Error('This browser cannot record MP4 or WebM.');
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
  return <><div className="phone-title"><p className="kicker">TABLE 01 &nbsp; / &nbsp; PHONE CONTROLLER</p>
    <h1>Table remote<span>.</span></h1><p>Set the matchup, frame the table, and record the game.</p></div>
    <ol className="steps">{['Matchup','Camera','Result'].map((s,i)=><li className={step===i?'current':''} aria-current={step===i?'step':undefined} key={s}>0{i+1} &nbsp; {s}</li>)}</ol>
    {error && <p className="alert" role="alert">{error}</p>}
    <section className="panel remote">
    {step===0?<><p className="kicker">MATCH SETUP</p><h2>Who's playing?</h2><p>Choose two different players from the club roster.</p>
      {[[a,A,b,'Player A'],[b,B,a,'Player B']].map(([v,set,other,label])=><label key={label}>{label}<select value={v} disabled={stage==='permission'} onChange={e=>set(e.target.value)}><option value="">Select a player</option>{board.players.map(p=><option key={p.id} value={p.id} disabled={String(p.id)===other}>{p.name}</option>)}</select></label>)}
      <details><summary>New to the roster? Add a player</summary><PlayerEntry onAdded={add}/></details>
      <button className="btn ink wide" disabled={!a || !b || a===b || stage==='permission'} onClick={preview}>{stage==='permission'?'Opening camera...':'Continue to camera →'}</button>
    </>:stage==='done'?<><p className="kicker">GAME {gameId} &nbsp; / &nbsp; CAPTURE COMPLETE</p>
      <h2>{finished?.winner?`${name(finished.winner)} won`:'Awaiting analysis'}</h2><p>{finished?.winner?'The standings have been updated.':'The server has the video. The winner will appear here and on the scoreboard when the analyzer returns a result.'}</p>
      <a className="btn ink wide" href="/">View scoreboard</a><button className="text-btn" onClick={()=>{A('');B('');setStage('select');}}>Set up another game</button>
    </>:<><p className="kicker">{stage==='record'?'RECORDING':stage==='preview'?'CAMERA CHECK':'MATCH CAPTURE'}</p><h2>{name(a)} <em>vs</em> {name(b)}</h2>
      {['preview','record','starting'].includes(stage)&&<div className="camera"><video ref={video} playsInline muted autoPlay/>{stage==='record'&&<span className="rec">● REC &nbsp; {Math.floor(seconds/60)}:{String(seconds%60).padStart(2,'0')}</span>}</div>}
      {stage==='preview'&&<><p>Frame the whole table. Starting uploads video without audio to the club server for analysis. Check both players are ready to be recorded.</p>
        <button className="btn ink wide" onClick={start}>Start game &amp; record</button><button className="text-btn" onClick={()=>{stopCamera();setStage('select');}}>Change players</button></>}
      {stage==='record'&&<><p>Keep this page open and your phone unlocked until the game ends.</p><button className="btn stop wide" onClick={()=>{setStage('saving');recorder.current.stop();}}>■ &nbsp; Stop game &amp; submit</button></>}
      {stage==='starting'&&<p role="status">Starting match...</p>}{stage==='saving'&&<p role="status">Finishing upload. Keep this page open.</p>}
      {stage==='retry'&&<button className="btn ink wide" onClick={async()=>{setStage('saving');try{const g=current.current;await closeMatch(g,g.outcome);refresh();setError(g.outcome==='discard'?'Recording interrupted. Start a new game.':'');setStage(g.outcome==='discard'?'select':'done');}catch(e){setError(e.message);setStage('retry');}}}>Retry submission</button>}
    </>}
    </section></>;
}
