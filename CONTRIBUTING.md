# Contributing
Thanks for helping. Please read the [Code of Conduct](CODE_OF_CONDUCT.md) first.

## Dev setup
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```
Quick checks before a PR: `python -m compileall -q app` and `node --check app/static/app.js` (CI runs both).

## Code map
| File | Responsibility |
|---|---|
| `app/main.py` | REST API, validation, app lifespan (starts/stops the single scheduler) |
| `app/tg.py` | Telethon accounts, DM handler + AI flow, broadcast scheduler |
| `app/store.py` | `store.json` access (lock, atomic write, `mutate(fn)`) and the activity log in `log.json` |
| `app/llm.py` | Ollama chat + connection/model tests |
| `app/static/app.js`, `app/templates/index.html` | Admin UI (no framework) |
| `docs/images/` | Diagrams used in the README |

## Adding a feature
1. New state goes in `DEFAULT` in `store.py`; always change it through `store.mutate`.
2. Add an endpoint in `main.py` that validates input and returns clear 400s.
3. Add UI in `index.html` / `app.js`; escape any Telegram-sourced text with `esc()`.
4. Update the README if behavior changes.

## Rules
- Keep it simple: no new framework, database or heavy dependency without discussion in an issue.
- One broadcast delay: do not add per-group schedules.
- No features that evade Telegram rate limits, FloodWait, moderation or detection (proxy/account rotation, human-behavior faking, auto-joining).
- Never log or expose secrets. Do not commit `.env`, sessions, `store.json` or `log.json`.
- Keep PRs small; describe what changed and how you tested it.
- Contributions are licensed under the project's MIT license.