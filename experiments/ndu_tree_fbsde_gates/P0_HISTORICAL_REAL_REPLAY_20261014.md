# Actual public pretrained artifact P0 read-only replay — 2026-10-14

**Observation, not qualification.** This research sub-study replays the existing #1775 hosted run [38541658096](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38541658096), successful job and artifact **11886761368** at SHA256 `e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d`. Uses only its four saved per-case model-result arms, 128 fixed cross-sectional public AG News new-source rows, model reports and scorer receipts. No checkpoint reloaded in this new PR.

| Arm | correct/128 | Brier |
|---|---:|---:|
| Gemma 2 frozen Head | 49 | 0.25001948 |
| Gemma 2 trained Head | 120 | 0.24881424 |
| Gemma 2 trained and exploratory preset 1024 logit multiplier | 120 | 0.04932607 |
| Laya 421M frozen | 124 | 0.02012669 |

Paired learned Gemma vs frozen: 75 recovered, 4 lost. Learned Gemma vs Laya frozen: 1 recovered, 5 lost. Archived whole-process observations: Gemma 79.01s wall / 2,097,057,792 max RSS bytes (includes SGD); Laya 119.12s / 2,999,279,616 bytes (does not include SGD). Amortized per-row batch allocation is **not** request p99. Different lifecycle work prevents fair speedup claims.

**Replay:** download the exact GitHub Actions artifact ZIP, then `python experiments/ndu_tree_fbsde_gates/p0_historical_real_replay.py --archive /path/to/archive.zip --output /new/audit.json`. ZIP identity is pinned and mismatch fails closed; synthetic unit tests do not qualify the real model.

**Remaining:** Granite97/mmBERT missing; only Gemma/Laya, public AG News is not future-time data; no independent external source or model-origin signature, no verified physical Transformer forward count, no unified Reader cost, not four-scale physical shared-Encoder execution, no 4,096 Cell learnability, no natural System2 or nonlinear FBSDE. All flags remain `DENY_ALL`; do not auto-select models.
