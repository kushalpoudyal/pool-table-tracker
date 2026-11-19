# Pool Table Tracker

Hackathon project. Three parts share this repo: Rackroom (`Hack B Pool API/`, `Hack B Pool Client/`)
and the camera / detection / LLM side (`Hack B Pool Vision Backend/`). See `README.md`.

- The team's agreed product spec is `docs/SPEC.md`. Research, decisions and open questions live in
  `context/`: read `context/CONTEXT.md` before starting a task, plus `context/SPEC.md` when the task
  touches the vision backend (camera, vision, game rules, voice).
- Record every decision or progress step as a new line at the end of `context/LOG.md`
  (`- YYYY-MM-DD · <what> (<who>)`), and keep `context/CONTEXT.md` current (stack, open questions).
- New research on a tool or API goes in its own `context/<TOOL>.md`, linked from `CONTEXT.md`.
- The repo is public: never commit API keys (`.env` only), recordings of people playing
  (`recordings/`), model weights (`models/`, `*.pt`) or photos of players
  (`Hack B Pool Vision Backend/assets/players/`).

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `kushalpoudyal/pool-table-tracker`, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root (created lazily). See `docs/agents/domain.md`.
