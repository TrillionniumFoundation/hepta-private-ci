# Full caller verification of the final common source

## Result

The single original invocation completed with exit code **0** and the verifier's full receipt status **PASS_HEPTA_CALLER_CLOSED_SET**. This was the complete `verify` command, including source enumeration, Rust code/cfg-test stripping, every boundary's closed caller set, privileged inventory, and protected-source guards. It was not an inventory-only check.

| Receipt field | Observed result |
|---|---:|
| Rust files scanned | 6,302 |
| Boundary records | 223 |
| Privileged inventory entries | 223 |
| Protected-file records | 218 |
| Distinct protected paths | 173 |
| authorityGranted | false |
| stderr | 0 B |

The protected-file count is the receipt's record count; some paths have multiple protected records. Counts are engineering-verification scope, not independent task samples or demonstrated learning gains.

## Fixed source and checkout

- HEAD: `cb0598a9099a0d828ce73aedb51e397e600e49d1`.
- Tree: `59a019b79a6b879bbc27f6a614e1222fe87581ca`.
- Checkout: `/workspace/scratch/f7c0ded86bcc/hepta-p0-learn-merge`.
- New audit branch: `codex/cell-p0-final-caller-audit-f7c0`.
- Original branch `codex/cell-p0-learn-merge-f7c0` remains at `bad9b6490469106b8c98162878fa62feb616c20f`; it was not reset or overwritten.
- Original checkout clean state was verified before fetching the exact published commit and creating the new branch.
- BEFORE and AFTER match on HEAD, tree, branch, clean status, CALLERS hash, and verifier hash.
- Both BEFORE and AFTER `git status --porcelain=v1 -z --untracked-files=all` outputs are empty. This clean scope includes tracked and non-ignored untracked files.
- CALLERS SHA-256 before and after: `e24624826d94bd7726e55c5ffb3ffc55f182819949dbe7b66c92879441e38b19`.
- Verifier SHA-256 before and after: `8899ec2b328125b2049b808cac0eeda3f57bfc6db89348512a58777101ae6dfa`.

No source was edited and no branch was switched during the scan. No other checkout was changed.

## Original invocation and measured costs

Stable local invocation key: `p0-cb0598-full-caller-scan-20261111-v1`.

```text
python3 scripts/verify_hepta_callers.py verify --root /workspace/scratch/f7c0ded86bcc/hepta-p0-learn-merge
```

- Start: 2026-11-11T02:04:06.305159+00:00.
- End: 2026-11-11T02:16:39.223603+00:00.
- Measured wall time: **752.917854263 seconds**.
- Child user CPU: **734.443381 seconds**.
- Child system CPU: **2.857495 seconds**.
- Total measured child CPU: **737.300876 seconds**.

CPU is the wrapper's `RUSAGE_CHILDREN` delta measured around only the verifier subprocess. These measurements exclude preparation, before/after Git snapshots, orchestration, communication, and external CI. Unmeasured costs remain unknown. `HEARTBEATS.jsonl` contains the original periodic liveness observations; its /proc CPU samples are progress data, not a substitute for the final measured CPU result.

The invocation ran exactly once. No native build, Rust test, model, OCR, training, business task, or CI workflow was launched for this scan.

## Exact original output

- `SCAN.stdout.json`: complete original stdout, **103,063 B**, SHA-256 `83201a799a7be1e04116ad1b089b32761ae6d37ed77de35885e12d441f825c7c`.
- `SCAN.stderr.txt`: complete original stderr, **0 B**, SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- `BEFORE.json` and `AFTER.json`: source and clean snapshots.
- `EXECUTION.json`: original command, return code, measured costs, output hashes, and parsed full-receipt fields.
- `ORIGINAL_CHECKOUT.json` and `PREPARATION.json`: original branch custody and exact fetch/new-branch preparation.
- `MANIFEST.json`: hashes every other file in this bundle.

Raw stdout/stderr bytes were not normalized or replaced with an edited summary.

## Caller boundary interpretation

The original full receipt confirms the expected Training pair boundary:

- Receipt `attest_original_completion` and `readback` have `cell_q24_training_stage.rs` as their sole product caller.
- Native `fit_or_readback` and exact Dataset/scope pair binding also have only that Stage product caller.
- Receipt create/recover remain without ordinary product callers.
- Stage constructor, execute, readback, and receipt-attestation public entry points remain without ordinary product callers.
- Root's complete `with_root_learning_stage_owners` assembly boundary remains without ordinary product callers.

This passing closed-set proof does not supply the missing host assembly, grant authority, qualify a full P0 runtime chain, or replace native/CI qualification for this exact source. It is independent evidence of the complete static caller gate for the fixed common source above.

