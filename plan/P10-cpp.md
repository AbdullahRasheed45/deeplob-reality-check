# P10 (optional): C++ feature engine and latency benchmark

**Goal:** show systems skill by moving the hot path (snapshot parsing into the ring buffer, FI-order features, normalisation, book walking) to C++, with proof that it gives identical numbers and lower latency. This is curriculum Week 10. It does not change the live service during the pre-registered period.

## Scope
- `cpp/` folder, C++20, CMake, `pybind11` module `lobrc_fast` exposing:
  - `SnapshotRing(T, levels)`: `push(recv_ns, last_update_id, bid_px[10], bid_sz[10], ask_px[10], ask_sz[10]) -> bool ready`, `window_fi(out float32[T*40])`, same segmentation rules as P2.
  - `normalize_stationary(window, mean[40], std[40], out)`.
  - `walk_book(px[10], sz[10], qty) -> (vwap, levels_used, exhausted)`.
  - `parse_depth_json(str) -> arrays` using `simdjson` (vendored via CMake `FetchContent`, pinned version).
- Memory rules on the hot path: no heap allocation after construction (preallocated ring as a flat array indexed modulo T), no exceptions, no `std::string` copies.

## Equivalence tests (`tests/test_cpp_equivalence.py`, skipped if the module is not built)
For 100,000 synthetic snapshots: ring readiness, segment flags, FI windows, normalised windows and book walks match the Python versions exactly (integers) or to 1e-6 relative (floats).

## Benchmark
`cpp/bench/` with Google Benchmark (pinned via FetchContent) and a Python script that runs the same steps with the pure-Python implementation. Report p50 and p99 per snapshot for: JSON parse, ring push and window extraction, normalisation. Save `results/cpp/bench.md` with a latency table and histogram PNG, the machine description and compiler flags (`-O3 -march=native` locally; plain `-O3` for portable builds).

## Acceptance criteria
- Equivalence tests pass in CI (add a CI job that builds the module).
- `results/cpp/bench.md` shows the measured speed-up with p50 and p99, and a paragraph explaining where the time went (allocation, parsing, cache behaviour) using `perf stat` numbers if available.
