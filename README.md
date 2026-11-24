# DeepLOB Reality Check

**Question:** how much of a published deep-learning limit-order-book model's edge (DeepLOB, Zhang, Zohren and Roberts, 2019) survives realistic fees, latency and new data?

**Plan:** record live crypto order books, replicate the paper on its public benchmark (FI-2010), retrain on your own recorded data, build a cost-and-latency waterfall, then run the frozen model live (paper trading) for 4-8 weeks with a pre-registered hypothesis.

## Build plan

The complete implementation spec is **`PLAN.md`** plus one file per phase in `plan/` (P0 to P10). `plan/AGENT-KICKOFF.md` has the prompt for handing a phase to a coding agent.

## What is in this folder (Day 1)

| File | What it is |
| --- | --- |
| `collector/collector.py` | The recorder. Written for you so recording can start today; time is the one thing you cannot buy back. |
| `collector/test_collector.py` | Tests against a fake exchange (reconnect, gaps, no lost rows, no crossed books). |
| `collector/lob-collector.service` | systemd unit so it restarts on crash or reboot. |
| `DEPLOY.md` | Oracle setup, including a **warning about idle-instance reclamation**. Read it first. |

## Day 1 checklist (about 5 hours)

- [ ] Create the server and deploy (DEPLOY.md steps 1-7).
- [ ] Run `--probe 5`. Paste me the first two lines.
- [ ] Read `collector.py` top to bottom. You own this code now. Do not skip the `handle` and `run` functions.
- [ ] Confirm data is flowing (DEPLOY.md step 9).
- [ ] Open a `GLOSSARY.md` in your repo and define, in your own words, with an example from your probe output: bid, ask, spread, mid-price, level, size, snapshot, `lastUpdateId`, `buyer_is_maker`.

## Day 2 exercises (about 5 hours): you write these

The collector records. These three scripts make you trust the data, which is the real skill.

1. **`health.py`**: exits non-zero if no new book file appeared in the last 5 minutes or the last event is a disconnect. Run it from cron on the VM or your laptop.
2. **`quality_report.py`**: for each day and symbol, report rows per hour, number and total length of gaps (from `events.jsonl`), and any crossed books (best bid >= best ask). Plot the spread distribution for BTCUSDT. A crossed book means a bug somewhere: find out where.
3. **`compact.py`**: merge each hour's many small `part-*.parquet` files into one file per hour, verify row counts match, only then move the originals aside. Learn why many small files are slow to read.

**Done when:** `quality_report.py` runs on your first 24 hours of data and you can explain every gap it finds.

## Things you should be able to answer by the end of Day 2 (I will quiz you)

1. Why does every row store `recv_ns` and not rely on the exchange timestamp?
2. The depth stream sends a snapshot of the top 20 levels, not changes. What are the pros and cons for research versus a diff stream?
3. Why does the collector reconnect proactively before 24 hours, and what happens to your data when it does?
4. Why write to a `.tmp` file and rename?
5. Name two ways a silent bug here would make a later backtest look better than reality.

## Rules for the whole project

- **Never edit raw data.** Cleaning happens in code that reads it.
- **Pre-registration:** before the live phase, commit a one-page file with the hypothesis, the success criteria, the model version and the cost assumptions. Never change it afterwards.
- **No tuning during the live phase.** If the model is bad, report that it is bad.
- **Check the exchange's terms before publishing raw data.** Publishing derived features and results is safer than redistributing raw market data.
