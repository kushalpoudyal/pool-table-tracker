import React, { useEffect, useRef, useState } from 'react';
import { api } from './api';

export default function RemoteFeed() {
  const [camera,setCamera]=useState(null), [error,setError]=useState('');
  const [attempt,setAttempt]=useState(0), [loaded,setLoaded]=useState(false);
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
  if(!camera?.configured && !error) return null;
  const connected=camera?.connected && !error;
  return <section className="panel live-panel" id="external-camera">
    <header><span className="badge recording">{connected&&loaded?'LIVE':'EXTERNAL CAMERA'}</span>
      <h2>Table camera</h2><p role="status">{error || (connected
        ? `${camera.width} × ${camera.height} · ${camera.fps} fps · ${loaded?'Live from stream server':'Connecting to video...'}`
        : 'Waiting for the phone to connect to the stream server.')}</p>
      <small>This camera feed is separate from locally scored matches.</small></header>
    {connected && <div className="live-screen"><img key={attempt}
      src={`/api/stream-server/video?attempt=${attempt}`} alt="Live table camera from stream server"
      onLoad={()=>setLoaded(true)} onError={()=>{failed.current=true;setLoaded(false);setError('External camera video interrupted. Reconnecting...');}}/></div>}
  </section>;
}
