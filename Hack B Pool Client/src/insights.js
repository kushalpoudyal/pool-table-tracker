import { rankPlayers } from './shared';

// Everything here is derived from /api/board: players + matches (a, b, winner, status, started).
// Match ids increase over time, so id order is play order.

export const MOVEMENT_WINDOW = 5;

const completed = matches => matches.filter(m => m.status === 'complete').sort((x, y) => x.id - y.id);

function resultsByPlayer(games) {
  const results = new Map();
  for (const m of games) {
    for (const id of [m.a, m.b]) {
      if (!results.has(id)) results.set(id, []);
      results.get(id).push(m.winner === id ? 'W' : 'L');
    }
  }
  return results;
}

function streakOf(results) {
  if (!results.length) return null;
  const last = results[results.length - 1];
  let n = 0;
  for (let i = results.length - 1; i >= 0 && results[i] === last; i--) n++;
  return {type: last, n};
}

function bestWinStreak(results) {
  let best = 0, run = 0;
  for (const r of results) { run = r === 'W' ? run + 1 : 0; best = Math.max(best, run); }
  return best;
}

// Standings plus form, streaks and movement compared with before the last few results.
export function standingsWithInsights(players, matches) {
  const games = completed(matches);
  const results = resultsByPlayer(games);
  const ranked = rankPlayers(players, matches);
  const recentIds = new Set(games.slice(-MOVEMENT_WINDOW).map(m => m.id));
  const before = games.length > MOVEMENT_WINDOW
    ? new Map(rankPlayers(players, matches.filter(m => !recentIds.has(m.id))).map((p, i) => [p.id, i]))
    : null;
  return ranked.map((p, i) => {
    const r = results.get(p.id) ?? [];
    return {
      ...p,
      form: r.slice(-5),
      streak: streakOf(r),
      bestStreak: bestWinStreak(r),
      movement: before && before.has(p.id) ? before.get(p.id) - i : 0,
    };
  });
}

export function headToHead(a, b, matches) {
  let aWins = 0, bWins = 0;
  for (const m of completed(matches)) {
    if (!((m.a === a && m.b === b) || (m.a === b && m.b === a))) continue;
    if (m.winner === a) aWins++; else if (m.winner === b) bWins++;
  }
  return {aWins, bWins, total: aWins + bWins};
}

const sameDay = (iso, now) => {
  const d = new Date(iso);
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
};

// Short, rotating talking points for the big screen. Only facts we can compute.
export function highlights(players, matches, standings, now = new Date()) {
  const name = id => players.find(p => p.id === id)?.name;
  const games = completed(matches);
  const out = [];
  if (!games.length) return out;

  const hot = standings.filter(p => p.streak?.type === 'W' && p.streak.n >= 2).sort((x, y) => y.streak.n - x.streak.n)[0];
  if (hot) out.push({key: 'hot', kicker: 'On fire', title: `${hot.name} has won ${hot.streak.n} in a row`, detail: 'The longest active winning streak in the club.', ball: 1});

  const record = [...standings].sort((x, y) => y.bestStreak - x.bestStreak)[0];
  if (record?.bestStreak >= 3) out.push({key: 'record', kicker: 'Club record', title: `${record.name}: ${record.bestStreak} straight wins`, detail: 'The best winning run anyone has put together.', ball: 9});

  const [first, second] = standings;
  if (first && second && first.wins > second.wins) {
    const gap = first.wins - second.wins;
    out.push({key: 'lead', kicker: 'Top of the table', title: `${first.name} leads by ${gap} win${gap === 1 ? '' : 's'}`, detail: `${second.name} is the closest challenger.`, ball: 1});
  }

  const pairs = new Map();
  for (const m of games) {
    const [lo, hi] = m.a < m.b ? [m.a, m.b] : [m.b, m.a];
    const key = `${lo}-${hi}`;
    const pair = pairs.get(key) ?? {lo, hi, n: 0, lo_w: 0};
    pair.n++; if (m.winner === lo) pair.lo_w++;
    pairs.set(key, pair);
  }
  const rivalry = [...pairs.values()].sort((x, y) => y.n - x.n)[0];
  if (rivalry?.n >= 3) out.push({key: 'rivalry', kicker: 'Biggest rivalry', title: `${name(rivalry.lo)} vs ${name(rivalry.hi)}`, detail: `${rivalry.n} games so far · ${rivalry.lo_w}–${rivalry.n - rivalry.lo_w}.`, ball: 8});

  const busiest = [...standings].sort((x, y) => y.played - x.played)[0];
  if (busiest?.played) out.push({key: 'busy', kicker: 'Most games played', title: `${busiest.name} · ${busiest.played} games`, detail: 'Nobody has spent more time at the table.', ball: 4});

  const today = games.filter(m => sameDay(m.started, now)).length;
  if (today) out.push({key: 'today', kicker: 'Today', title: `${today} game${today === 1 ? '' : 's'} played today`, detail: 'Every confirmed result counts toward the board.', ball: 2});

  return out;
}
