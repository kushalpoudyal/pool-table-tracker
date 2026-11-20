// The table camera's commentator, heard in the browser. The stream server writes the lines
// (GET /watch -> lines) and, with a voice key, makes each one into speech that is streamed here
// (/api/stream-server/commentary/{id}/audio). Without audio, or when a clip fails, the browser's own
// speechSynthesis says the line instead.
//
// Ported from Rackroom's ticket #9 speech queue and iOS unlock (tickets-integration).
//
// Lines carry a priority:
//   critical  foul, scratch, correction, winner. Cuts off a normal or colour line and goes next;
//             never cut off itself (a second critical waits right behind it).
//   normal    pots, groups, turns, the break. Spoken in order, all of them, unless they have
//             waited longer than normalMaxAgeMs (the page was asleep): then they are skipped.
//   colour    the commentator's colour. Spoken only when nothing else waits, and dropped rather than
//             spoken late.
// Two lines never overlap, and a line that was cut off is not resumed.

const PRIORITIES = ['critical', 'normal', 'colour'];

// play(line, done)   start one line; call done() when it has ended (or failed)
// stop()             stop the line being played, if any
export function createLineQueue({
  play,
  stop,
  now = () => Date.now(),
  setTimer = (run, ms) => { const timer = setTimeout(run, ms); return () => clearTimeout(timer); },
  colourMaxAgeMs = 6000,
  normalMaxAgeMs = 20000,
  timeoutMs = text => 6000 + 90 * text.length,
}) {
  const heard = new Set();
  let current = null, waiting = [], muted = false, stopTimeout = () => {};

  const stale = line => now() - line.at > (line.priority === 'colour' ? colourMaxAgeMs : line.priority === 'normal' ? normalMaxAgeMs : Infinity);

  function start(line) {
    current = line;
    const ended = () => { if (current === line) next(); };
    stopTimeout = setTimer(() => { if (current === line) { stop(); next(); } }, timeoutMs(line.text));
    play(line, ended);
  }

  function next() {
    stopTimeout();
    current = null;
    while (waiting.length) {
      const line = waiting.shift();
      if (stale(line)) continue;
      start(line);
      return;
    }
  }

  function silence() {
    stopTimeout();
    waiting = [];
    if (current) { current = null; stop(); }
  }

  return {
    // One line from the server: {id, text, priority, audio}.
    say(input = {}) {
      const { id } = input;
      if (id != null) {
        if (heard.has(id)) return;
        heard.add(id);
      }
      const line = { ...input, text: String(input.text ?? '').trim(), at: now(),
        priority: PRIORITIES.includes(input.priority) ? input.priority : 'normal' };
      if (!line.text || muted) return;
      if (line.priority === 'colour') {
        if (waiting.length) return;
      } else {
        waiting = waiting.filter(other => other.priority !== 'colour');
      }
      if (!current) start(line);
      else if (line.priority !== 'critical') waiting.push(line);
      else if (current.priority === 'critical') waiting.splice(waiting.filter(o => o.priority === 'critical').length, 0, line);
      else { stopTimeout(); stop(); start(line); }
    },
    setMuted(value) { muted = Boolean(value); if (muted) silence(); },
    clear() { silence(); heard.clear(); },
    get speaking() { return current !== null; },
    get muted() { return muted; },
  };
}

// Which of the lines in a Watch payload are new. A page that opens (or reloads) mid-game marks the lines
// already there as heard: no flood of speech. A game first seen after that (started while the page was
// open) is new from its first line. Ids keep growing on the stream server, the game key resets it.
export function createLineTracker({ speakExisting = false } = {}) {
  const highest = new Map();   // game -> highest line id seen
  let first = !speakExisting;
  return {
    fresh(lines = []) {
      const out = [];
      for (const line of lines) {
        const seen = highest.get(line.game);
        if (seen === undefined && first) { highest.set(line.game, Math.max(...lines.filter(l => l.game === line.game).map(l => l.id))); continue; }
        if (seen !== undefined && line.id <= seen) continue;
        highest.set(line.game, line.id);
        out.push(line);
      }
      if (lines.length) first = false;
      return out;
    },
  };
}

// A short silent WAV: played inside a tap, it lets iOS Safari (and Chrome's autoplay policy) play the
// same <audio> element later without one.
function silentWav() {
  const samples = 800, bytes = new Uint8Array(44 + samples);
  const view = new DataView(bytes.buffer);
  const text = (at, s) => [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + samples, true); text(8, 'WAVEfmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 8000, true); view.setUint32(28, 8000, true); view.setUint16(32, 1, true); view.setUint16(34, 8, true);
  text(36, 'data'); view.setUint32(40, samples, true); bytes.fill(128, 44);
  let binary = ''; bytes.forEach(b => { binary += String.fromCharCode(b); });
  return `data:audio/wav;base64,${btoa(binary)}`;
}

const MUTE_KEY = 'rackroom.commentary.muted';
const listeners = new Set();
let player = null;

// One player per page (one <audio> element, unlocked once), shared by every score on it.
export function commentaryPlayer() {
  if (player) return player;
  const audio = typeof Audio === 'function' ? new Audio() : null;
  const synth = globalThis.speechSynthesis, Utterance = globalThis.SpeechSynthesisUtterance;
  let unlocked = false, cancelledAt = -Infinity;

  function speak(text, done) {
    if (!synth || !Utterance) { done(); return; }
    const utterance = new Utterance(text);
    utterance.lang = /^en\b/i.test(navigator.language || '') ? navigator.language : 'en-GB';
    utterance.onend = utterance.onerror = done;
    player._utterance = utterance;   // Chrome drops the end event of an utterance nothing refers to
    const wait = cancelledAt + 80 - performance.now();   // Android Chrome swallows a line started right after cancel()
    setTimeout(() => { synth.resume(); synth.speak(utterance); }, Math.max(0, wait));
  }

  const queue = createLineQueue({
    play(line, done) {
      if (!line.audio || !audio) { speak(line.text, done); return; }
      let finished = false;
      const end = () => { if (!finished) { finished = true; done(); } };
      audio.onended = end;
      audio.onerror = () => { if (!finished) { finished = true; speak(line.text, done); } };   // no clip: say it
      audio.src = `/api/stream-server/commentary/${line.id}/audio`;
      audio.play().catch(() => audio.onerror?.());
    },
    stop() {
      if (audio) { audio.onended = audio.onerror = null; audio.pause(); audio.removeAttribute('src'); audio.load(); }
      if (synth) { cancelledAt = performance.now(); synth.cancel(); }
    },
  });

  let muted = false;
  try { muted = localStorage.getItem(MUTE_KEY) === '1'; } catch { /* storage blocked: not remembered */ }
  queue.setMuted(muted);
  const changed = () => listeners.forEach(fn => fn());

  player = {
    say: line => { if (unlocked) queue.say(line); },
    // Call synchronously inside a tap (Start game, or the "turn on commentary" button).
    unlock() {
      if (audio) { audio.src = silentWav(); audio.play().catch(() => {}); }
      if (synth && Utterance) { const u = new Utterance(' '); u.volume = 0; synth.speak(u); }
      unlocked = true;
      changed();
    },
    setMuted(value) {
      queue.setMuted(value);
      try { localStorage.setItem(MUTE_KEY, value ? '1' : '0'); } catch { /* not remembered */ }
      changed();
    },
    get muted() { return queue.muted; },
    get unlocked() { return unlocked; },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
  return player;
}
