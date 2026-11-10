# HPCA real CPU clock counterbalance — pre-execution freeze

**Gate: HOLD_NO_GO / DENY_ALL, research only.** An exploratory real CPU
training run on the previously exposed fixture, not independent future
evaluation. Does not verify owner signatures, external evaluator, real
ACT/CTRL effects, NDU 2x2, or deployment rights.

## Source and inputs frozen before execution

- Parent PR #5861 commit a1f3b596f433aa8420785f71cf9f5791fb071719,
  itself stacked on research PR #5739 commit
  15daf24ef21e9d038919fef53b82e3a6fb70358d.
- Execution script real_cpu_clock_counterbalance.py, frozen SHA-256
  d4fafebc2024040f87092efa4465f7bbc519a94c25ef82489eaf9fc81603d495.
- Model SmolLM2-135M-Instruct FP32, frozen backbone, rank-4 q_proj LoRA.
  Model safetensors SHA-256:
  5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c.
  Tokenizer and config are rehashed by the run.
- Previously exposed training fixture experiment-plan.json SHA-256
  01ec1a644f37b9fc7a4c6616f589768df97f8eed7a289b5de86afadaa7ce6165.
- Seeds 11,17,23,29; 12 optimizer steps per arm; 4 CPU threads;
  seeded row stream identical per seed across all four arms.
- Arms: uniform 01 repeated x6 (group counts 6/6);
  heterogeneous 0001 x3 (9/3);
  inverse 1110 x3 (3/9);
  phase shift 1000 x3 (9/3).
  Groups are frozen first 15 / last 15 layers with identical
  LoRA parameter count. Per-arm information and update-element budget
  are fixed; the group-level label exposure necessarily differs.
- Question: do differences depend on which layers receive extra
  updates or on their temporal order? Inverse and phase are fixed
  negative controls, not post-hoc optimized candidates.
- Report all arms and seeds, B/C accuracy and per-question
  probabilities, paired log loss/Brier, regressions, source IDs,
  step logs, adapters, cold reload, CPU/I/O/wall and missing-cost
  fields. No selection based only on mean improvement.
- B is exposed and C operator-written and reused. Neither is
  independent future evaluation. No inferential efficacy test,
  performance promotion, production owner operation, deployment,
  or changes to weights/permissions are authorized.
