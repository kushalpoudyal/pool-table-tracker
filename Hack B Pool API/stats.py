"""Two players' records for the stream server's commentator, from Rackroom's own matches.

The same definitions as the client's leaderboard insights (src/insights.js): counted (complete) games
only, in id order (= play order); the current streak is the run of equal results at the end; the best
streak is the longest run of wins. Interrupted games never count. Average balls potted comes from the
final scores the stream server sent (match_details), for the games where the player's name appears.
"""
import json


def _streak(results):
    if not results:
        return None
    last, n = results[-1], 0
    for r in reversed(results):
        if r != last:
            break
        n += 1
    return {"type": last, "n": n}


def _best_win_streak(results):
    best = run = 0
    for r in results:
        run = run + 1 if r == "W" else 0
        best = max(best, run)
    return best


def for_game(c, a, b):
    """{"<name a>": {...}, "<name b>": {...}, "head_to_head": {"played", "wins": {"<name>": n}}}.

    Each player: played, won, streak ({"type": "W"|"L", "n"} or None), best_streak, avg_potted (None
    without a stored final score), last_played (when their last counted game started, or None)."""
    names = dict(c.execute("SELECT id,name FROM players WHERE id IN (?,?)", (a, b)).fetchall())
    games = c.execute("SELECT m.id,m.a,m.b,m.winner,m.started,d.details FROM matches m "
                      "LEFT JOIN match_details d ON d.match_id=m.id WHERE m.status='complete' ORDER BY m.id").fetchall()
    out = {}
    for pid in (a, b):
        mine = [g for g in games if pid in (g["a"], g["b"])]
        results = ["W" if g["winner"] == pid else "L" for g in mine]
        potted = []
        for g in mine:
            try:
                final = json.loads(g["details"]) if g["details"] else {}
            except ValueError:
                continue
            for p in final.get("players") or []:
                if isinstance(p, dict) and str(p.get("name", "")).casefold() == names[pid].casefold():
                    potted.append(len(p.get("potted") or []))
        out[names[pid]] = {
            "played": len(results), "won": results.count("W"), "streak": _streak(results),
            "best_streak": _best_win_streak(results),
            "avg_potted": round(sum(potted) / len(potted), 1) if potted else None,
            "last_played": mine[-1]["started"] if mine else None,
        }
    both = [g for g in games if {g["a"], g["b"]} == {a, b}]
    out["head_to_head"] = {"played": len(both),
                           "wins": {names[pid]: sum(g["winner"] == pid for g in both) for pid in (a, b)}}
    return out
