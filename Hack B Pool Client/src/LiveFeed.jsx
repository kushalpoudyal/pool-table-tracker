import React, { useEffect, useRef, useState } from 'react';

// Polls the latest JPEG the phone pushed for a match and paints it into an <img>.
export function useLiveFrame(matchId, interval=250) {
  const image=useRef(null);
  const [status,setStatus]=useState('Waiting for camera...');
  useEffect(()=>{
    let disposed=false, timer, url;
    const controller=new AbortController();
    async function frame() {
      try {
        const response=await fetch(`/api/matches/${matchId}/frame`,{
          cache:'no-store',signal:controller.signal,
        });
        if(response.status===204) {
          if(url) {URL.revokeObjectURL(url);url=null;}
          image.current?.removeAttribute('src');
          setStatus('Waiting for camera or reconnecting...');
        } else {
          if(!response.ok) throw new Error(`Server returned ${response.status}`);
          const blob=await response.blob();
          if(disposed) return;
          const next=URL.createObjectURL(blob);
          if(image.current) image.current.src=next;
          if(url) URL.revokeObjectURL(url);
          url=next; setStatus('Live preview · video recording on server');
        }
      } catch(e) {
        if(!disposed) {
          image.current?.removeAttribute('src');
          setStatus(`Feed interrupted: ${e.message}. Reconnecting...`);
        }
      } finally {if(!disposed) timer=setTimeout(frame,interval);}
    }
    frame();
    return ()=>{disposed=true;clearTimeout(timer);controller.abort();if(url) URL.revokeObjectURL(url);};
  },[matchId,interval]);
  return [image,status];
}

export default function LiveFeed({match, players}) {
  const [image,status]=useLiveFrame(match.id);
  const name=id=>players.find(p=>p.id===id)?.name;
  return <section className="panel live-panel" id={`game-${match.id}`}>
    <header><span className="badge recording">{match.live?'LIVE':'GAME STARTED'}</span>
      <h2>{name(match.a)} <em>vs</em> {name(match.b)}</h2>
      <p role="status">{status}</p></header>
    <div className="live-screen"><img ref={image} alt={`Live pool table: ${name(match.a)} versus ${name(match.b)}`}/></div>
  </section>;
}
