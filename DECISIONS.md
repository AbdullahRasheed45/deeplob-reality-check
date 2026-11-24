# DECISIONS

Date | Phase | Decision | Reason
--- | --- | --- | ---
2026-11-24 | P0 | Ruff per-file-ignores for `collector/*` (UP041, I001, E501, E741, B905) instead of editing collector code | Collector is already written and may be recording data; style-only fixes are not worth the risk of changing it
2026-11-24 | P0 | Local venv at `.venv/` on Python 3.14.0 (plan says 3.11+; CI uses 3.11) | Only interpreter installed on the owner's machine
