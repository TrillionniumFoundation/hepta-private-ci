# HCSN C2: strict receipts + frozen best inspection + exported status parser hardening

2026-11-11. **DRAFT / P0-P2 engineering only / HOLD_NO_GO**.

## Exact ancestry and inherited scope

- New independent branch parent: Draft #5962 exact source commit `1865a705609027cb9e7d83613fb49d1f68ac250f`; its parent is #5957, with #5945/#5936/#5927/#5920 histories retained. No change to any of those branches.
- Imported #5965 exporter/audit verifier and 10 tests from source `d5e23a2810eb35943d7027c303c3772cd69be5ef`. Git blobs imported exactly: `c2_native_replay.py=b673255cd80206037c71046e5b992366f5cf9dd0`, `test_c2_native_replay.py=0eeb197094db3004e81faf0c9db837da9f19c49c`.
- Only changed the **new exported-observation checker** and its tests. The ancestor `c2_durable.py` strict builtin JSON receipts, read-only original best.pt verifier, and original evidence bytes are untouched.

## Newly reproduced fail-open at the resource-document boundary

The #5965 exported-status checker bound `resource.json` to a SHA-256 receipt, then parsed it with default `json.loads`. Python silently accepts **duplicate JSON object keys** (last-wins) and non-standard **NaN** constants in unrelated fields. Consequently, a producer and copied receipt could *agree on the exact malicious bytes* yet the structural checker labeled the evidence matched. This is a *semantic parser ambiguity*, not a SHA-256 collision or a claim of exploitable live supervisor forgery.

Added negative tests construct fresh isolated successor receipts bound to the *modified resource file's own digest*. The frozen imported source yields **2/2 FAIL**, native heptaruntime desktop job `1a1ca611732-2564-5c2`, authoritative exit **1**; [exact red stderr](RED.stderr.log) SHA-256 `7a947e814765cb20dbff02b93bd2b55fec5553c5a3f5b2fcf0bb46bd8e5a75d9`. These were expected test failures, not original training results.

New checker: reject duplicate JSON keys at every object depth; reject NaN/Infinity and overflowed numeric exponents even in extra fields; cap result (16 MiB) and resource (1 MiB) file sizes *before* SHA reads. Reject / preserve denominator rather than silently accepting these records. This does **not** authenticate copied native status or add a complete native resource bill.

## Fresh independent native GREEN, exact source

- Host `desktop`; originally pinned C2 interpreter `/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python`, Python 3.12.3 / Torch **2.8.0+cu128**. CPU unit tests only.
- New exact-source job `1a1ca62d34d-2564-5c7`: authoritative exit **0**, **52/52 PASS**, 0 failed, 0 skipped; complete logs and confirmed terminal.
- Four added resource attacks: duplicate keys, NaN, numerical exponent overflow, oversized file. Original ten exported checker tests still pass; the ancestor receipt + pinned-best + inventory suite also runs in the 52.
- [Full GREEN stderr/test listing](GREEN.stderr.log) SHA-256 `e356d18b6eb16b702b3f039b1a561212858da6fa39c2764ccd5e1fd0d0d8bcb6`; [stdout/python identity](GREEN.stdout.log) SHA-256 `254cdf303f9e2b0fa7c92c0e2a3b938ee6fdc48f2b9414d7b9f5b80c28048727`. Exact job [exit JSON](GREEN.exit.json) SHA-256 `9077f6cf16ae410624013118052b9864dae21b87fa944027ec2181995156fe6f`.
- Final new-source Git blobs: `c2_native_replay.py=fd6ebf4a4b705287651e793c1bc0f743a1ca316c`, `test_c2_native_replay.py=0652ce2af2339232cedc765affbf042952bf15f3`. `git diff --check` passes.
- **Final post-format exact-source native rerun** `1a1ca689255-2564-5d7`: authoritative exit **0**, **52/52 PASS**, zero skipped, new final blobs exactly `fd6ebf4a4b705287651e793c1bc0f743a1ca316c` and `0652ce2af2339232cedc765affbf042952bf15f3`; retained [complete final stderr](FINAL-GREEN.stderr.log) SHA-256 `4853c316715fde8cf7599d1535f3375e6fa48623f6e67671b6c2c32b72b008ef`, [final stdout](FINAL-GREEN.stdout.log) SHA-256 `d511c54e5f06f9a5cb05b6657bdc79bacc6f4e89cf47f5a816038b584d498018`, and [terminal JSON](FINAL-GREEN.exit.json) SHA-256 `b1141be094d85eded62eab2b87a1ad2ffe3db82db69679e8b3c9690d41779fbd`.
- A **separate environment-path preflight** `1a1ca622c24-2564-5c5` exited 1 because an older convenience venv lacked Torch; the frozen interpreter above was used for final complete suite. This is not an HCSN code failure and is not disguised as a pass.

## Frozen original C2 remains unknown / incomplete

Read-only `desktop` native job `1a1c74f3308-be2a-75` is still `finalizing/outcome=unknown`, `terminal_publication_confirmed=false`. Six original attempts: only **4/6** SHA-pinned producer `result.json` copies; `hcsn-s211-lr0.001` and `hcsn-s307-lr0.001` have no `result.json` and both `interrupted.pt` files are **zero bytes**. Frozen original `commands.jsonl`: 28,672 B, SHA-256 `1405bced8c59a294276616cd7054f2b4068e10d858ab61d78bb578b93992239f` (16 valid and a torn 17th). Original `RESULT.json` absent. Two frozen `best.pt` are merely decoded, not resumed/replayed. No original code, job, checkpoints, journal or unrelated worktree changed.

## Explicit acceptance limits / next

This is still **structural verification of exported, untrusted copied native observations**: `independent_live_native_status_verified=false`, `checkpoint_model_replay_verified=false`, `scientific_admission=HOLD_NO_GO`. Neither producer terminal copies nor 52 fixture tests establish complete scientific or production acceptance.

P0 still needs a single frozen E/C/U/F/G/J/M + CURRENT and exact source/model/data/config/log/CI identity. P1 still needs actual training-visited posterior, drift +/-/0, tail/log-risk, reset/mass/count and high-precision AD gradients. P2 still needs genuine successor **runner/controller integration**, fresh six fully terminal native fits, safe checkpoint replay, all child/gpu/energy bills and opportunity-matched GRU/CfC/SNN/event-gradient/SSM/optimized Transformer/HCSN comparisons. P3 independently paid DP/QVI vs fixed/learned thresholds; P4 real asynchronous multimodal + anti-diffusion controls; P5 only after stable independent cost-adjusted gains. New-head hosted CI and artifact must be checked separately from this native run. **No Go, merge, adopt or original C2 restart.**
