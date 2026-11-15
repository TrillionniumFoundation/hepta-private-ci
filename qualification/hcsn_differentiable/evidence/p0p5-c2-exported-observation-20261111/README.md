# HCSN successor C2 exported native observations (HOLD)

Tested **2026-11-11** in an isolated desktop directory
`/home/qian-qi/work/hcsn-c2-native-observation-20261111-v4`.
Source base: Draft #5945 exact commit
`4823fe00edff33eb5e45097aee7f6a681cc72f33`.
Original C2 native job `1a1c74f3308-be2a-75` was **never rerun**;
none of its logs, results, or checkpoints were changed.

New `c2_native_replay.py` performs an intentionally **limited structural
cross-binding** of a frozen six-attempt roster, canonical successor durable
receipts, externally exported native-status JSON, nonempty result bytes,
resource SHA-256 and reconciled per-child `wait4` CPU fields. Absence,
unknown native terminal, contradictory exit, duplicate native job ID,
altered resource bytes or a non-`wait4` bill cannot pass structural matching.
The test suite includes both positive and negative synthetic data.

**Trust limitation:** even `6/6` structurally matched exports are **untrusted
serialized copies**. A JSON claim of `status_authoritative=true` is not a
live heptaruntime supervisor read. The program always returns
`independent_live_native_status_verified=false`,
`checkpoint_model_replay_verified=false`,
`heldout_scientific_gain_verified=false` and
`scientific_admission=HOLD_NO_GO`. No controller/runner has been integrated
and this PR does not solve the original missing two fit terminals.

Native desktop test: job `1a1ca4e3379-2564-56d`, exit 0;
**10/10 PASS** with `python3 -m unittest -v test_c2_native_replay`.
The source and tests had `py_compile` success; local SHA-256 respectively
`e92f4dba2cd220f697fd4cf676a69f095d1c3c7f8ffad1c754066017943adeef`
and `5022a4a28ace79ac9abba76f81b91fad91162985cfc680710209c21273455b60`.
These are fixture-only structural tests, **not** a native C2 training run.

Original fixed audit: **4/6** producer `result.json`,
two zero-length `interrupted.pt`, 16 complete `commands.jsonl` rows and
a truncated seventeenth, and missing controller `RESULT.json`.
See #5945 independent inventory and #5927 durable prototype.

Next: bind this to newly wired successor controller/runner with genuine
heptaruntime status reads and `wait4` cost, tests for crash injection and
checkpoint semantic replay, run all six new fits with full matched controls,
then independent P1 numerics and P2–P5 science before Go.
