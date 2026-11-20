"""The instant lines: fixed wording for what one look of the observer changed, no LLM.

Pure text. What a look changed goes in (its new pots, its notes, the shooter and groups before and
after, the winner), one line and its priority come out. Ported from Rackroom's ticket #9 `lines.py`,
rewritten for the observer's facts: which ball, which pocket, by whom, the foul as the observer
worded it, corrections.
"""

import re

CRITICAL, NORMAL, COLOUR = "critical", "normal", "colour"  # speech priorities, most urgent first

SCRATCH_NOTE = "cue ball potted (scratch)"
NUMBERS = {"1": "One", "2": "Two", "3": "Three", "4": "Four", "5": "Five", "6": "Six", "7": "Seven"}


def ball_name(ball, kind):
    """'the 5', 'the eight', 'the orange ball' (when the observer only knew the colour)."""
    if kind == "eight" or str(ball) == "8":
        return "the eight"
    text = str(ball).strip()
    return f"the {text}" if text.isdigit() else f"the {text} ball".replace(" ball ball", " ball")


def pocket_name(pocket):
    """'top-right' -> 'the top right'; None -> ''."""
    text = " ".join(str(pocket or "").replace("-", " ").replace("_", " ").split()).lower()
    if not text or text in ("unknown", "none", "null"):
        return ""
    text = text.removesuffix(" pocket")
    return text if text.startswith("the ") else f"the {text}"


def pot(p):
    """'Ada pots the 5 in the top right.'"""
    where = pocket_name(p.get("pocket"))
    ball = ball_name(p.get("ball"), p.get("kind"))
    said = f"{p['by']} pots {ball}" if p.get("by") else f"Down goes {ball}"
    return f"{said} in {where}." if where else f"{said}."


def sentence(text):
    """The observer's free text as one spoken sentence: capital first, full stop last."""
    text = " ".join(str(text).split()).rstrip(".!? ")
    return (text[:1].upper() + text[1:] + ".") if text else ""


def groups_line(before, after):
    """'Ada takes solids. Sam has stripes.' for the groups this look assigned; '' if none."""
    taken = [(p, g) for p, g in after.items() if g and not before.get(p)]
    if not taken:
        return ""
    first, group = taken[0]
    others = [(p, g) for p, g in after.items() if p != first and g]
    return f"{first} takes {group}." + "".join(f" {p} has {g}." for p, g in others)


def look_line(entry, before, after):
    """The line for one look: (text, priority, is_event), or ("", None, False) when nothing is worth saying.

    entry: what Observer._apply returned (potted, notes, shooting).
    before / after: {"players", "groups", "shooting", "winner"} as the commentator knew them before this
    look and as the observer's memory holds them after it.
    is_event: the look holds play (a pot, a foul, a scratch, groups, a turn change), not only a
    correction or a recognised player. Colour and the quiet spell count these.
    """
    parts, critical, event = [], False, False
    notes = entry.get("notes") or []
    for note in notes:  # recognising the players, or a Guest who turned out to be on the roster
        if note.startswith("recognised: "):
            what = note.removeprefix("recognised: ")
            if " is " in what:
                parts.append(f"That's {what.split(' is ', 1)[1]} at the table.")
            else:
                names = [n.strip() for n in what.split(",") if n.strip()]
                parts.append(f"{' and '.join(names)} {'are' if len(names) > 1 else 'is'} at the table.")
    for note in notes:
        if note.startswith("correction: "):
            parts.append("Correction. " + sentence(note.removeprefix("correction: ")))
            critical = True
        elif note.startswith("table check: ") and "gone from the table" in note:
            # "table check: 2 solids gone from the table, counted as potted"
            gone = note.removeprefix("table check: ").split(" gone from the table")[0]
            count, _, kind = gone.partition(" ")
            parts.append(f"Table check. {NUMBERS.get(count, count)} {kind} gone, counted as potted.")
        elif note.startswith("final check: ") and "still on the table" in note:
            parts.append("Correction. The eight is still on the table. The game goes on.")
            critical = True
    for p in entry.get("potted") or []:
        parts.append(pot(p))
        event = True
    foul = next((n.removeprefix("foul: ") for n in notes if n.startswith("foul: ")), None)
    if foul:
        parts.append("Foul. " + sentence(foul))
        critical = event = True
    elif SCRATCH_NOTE in notes:
        parts.append(f"Scratch{' by ' + before['shooting'] if before.get('shooting') else ''}.")
        critical = event = True
    groups = groups_line(before.get("groups") or {}, after.get("groups") or {})
    if groups:
        parts.append(groups)
        event = True
    if after.get("winner") and not before.get("winner"):
        # the final check's reason, when it decided: "final check: Sam potted the 8 with 2 solids left: Alex wins"
        why = next((n.removeprefix("final check: ").rsplit(": ", 1)[0] for n in notes
                    if n.startswith("final check: ") and n.endswith(" wins")), None)
        why = why and re.sub(r"with 0 (\w+?)s? left", r"with the \1s cleared", why.replace("the 8", "the eight"))
        reason = sentence(why) + " " if why else ""
        parts.append(f"Game over. {reason}{after['winner']} wins.")
        critical = event = True
    elif after.get("shooting") and before.get("shooting") and after["shooting"] != before["shooting"] \
            and after["shooting"] in (before.get("players") or []):
        parts.append(f"{after['shooting']} to shoot.")
        event = True
    text = " ".join(x for x in parts if x)
    return (text, CRITICAL if critical else NORMAL, event) if text else ("", None, False)


def break_line(players):
    """'New game. Ada breaks, Sam to follow.'"""
    if len(players) >= 2:
        return f"New game. {players[0]} to break against {players[1]}."
    return f"New game. {players[0]} to break." if players else ""
