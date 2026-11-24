# DECISIONS

Date | Phase | Decision | Reason
--- | --- | --- | ---
2026-11-24 | P0 | Ruff per-file-ignores for `collector/*` (UP041, I001, E501, E741, B905) instead of editing collector code | Collector is already written and may be recording data; style-only fixes are not worth the risk of changing it
2026-11-24 | P1 | `tests/synth.py` created now with only the array generator, `write_synthetic_day` and `write_trades_file` (no `BookData` wrappers) | P1 quality/compaction tests need synthetic days; `BookData` does not exist until P2, which will add `make_synthetic_book` on top
2026-11-24 | P1 | Added `src/lobrc/data/files.py` (list_dates, list_files, read_day) | One shared place that understands both `part-*` and `hour-*` layouts, as P1 step 5 requires of all readers
2026-11-24 | P1 | `gaps.csv` has an extra `date` column; quality CSVs are merged by (symbol, date), gaps replaced per (symbol, date) recomputed | Makes re-running `lobrc quality --date` idempotent
2026-11-24 | P1 | `expected_rows` uses the observed first-to-last span only on a symbol's first and last recorded date, 86,400 s otherwise | Spec says "less on first/last recorded day"
2026-11-24 | P1 | Compaction refuses (reports `needs-attention`) when a day has both part and hour files | Partial earlier run; guessing could lose or duplicate rows, so a human inspects it
2026-11-24 | P1 | `lobrc quality` exits 1 if any day has crossed rows | Spec says crossed rows are a bug that must be investigated
2026-11-24 | P0 | Local venv at `.venv/` on Python 3.14.0 (plan says 3.11+; CI uses 3.11) | Only interpreter installed on the owner's machine
