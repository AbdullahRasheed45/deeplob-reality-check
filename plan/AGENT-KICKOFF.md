# How to hand this project to an implementing agent

Open the repository in Claude Code (or any coding agent) and paste one of these prompts. Work one phase per session to keep the context focused.

## Start of every session
```
You are implementing the DeepLOB Reality Check project. Read PLAN.md in full, then STATUS.md and DECISIONS.md, then plan/<PHASE FILE>. Implement only that phase.
Rules: follow PLAN.md sections 3 and 4 exactly; write the named tests first; never tune on test data; never place orders or use API keys; if anything is unspecified, choose the simplest option consistent with the plan and record it in DECISIONS.md.
When every acceptance criterion passes, run `ruff check .` and `pytest`, update STATUS.md, and commit with message "Phase N: <title>". Then stop and summarise what you built, the test results, and any decisions you recorded.
```

## Phase order
P0, P1 (steps 3-5; the owner does steps 1-2 on the server), P2, P3, P4, P5 (needs at least 10 recorded days), then the FI-2010 baselines from P3, P6, P8, P11 (second site in Tokyo), P7 (the owner fills in PREREGISTRATION.md; both sites start the live period together after this), P9, and optionally P10.

## What the owner does by hand
- Server setup and deployment (DEPLOY.md), the probe output, and copying data to the training machine.
- GPU training runs (Kaggle or Colab notebooks that install this package and call the `lobrc` CLI).
- Writing the pre-registration hypotheses, weekly commentary and the final write-up text.
- Reading every module the agent writes. Ask it to explain any function you can't explain yourself; that is how this project turns into interview answers.
