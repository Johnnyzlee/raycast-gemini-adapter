# Contributing

Start with the [architecture](docs/ARCHITECTURE.md), [data boundaries](docs/DATA.md) and [validation notes](docs/VALIDATION.md). Keep changes focused on a reproducible behavior.

1. Create a Python 3.11+ virtual environment and install `requirements.txt`.
2. Run `python -m unittest -q` from the checkout. Offline tests use fake APIs and synthetic material.
3. Add a regression around changed protocol, state, provenance, security or installer behavior.
4. For optional real API checks, use `test_video_live.py` and its isolated port/state. These calls are billable. Keep generated/raw results in ignored paths.
5. Update both READMEs when installation, user-visible behavior or limits change.
6. Run `git diff --check` and `python scripts/audit_publication.py` after staging explicit paths.

Issue reports should include versions, model/tool names, a short synthetic reproduction and the readable error. Do not attach keys, provider files, raw state databases, private documents or original chat logs. Changes that affect Google pricing should update `usage_cost.py`, its tests and `docs/COSTS.md` together.
