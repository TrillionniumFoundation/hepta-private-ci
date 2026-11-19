# Frozen credit + typed MEM replay: common-cutoff and raw-budget integration

Status: **SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. This is a two-parent
reference-contract integration test, not model training, independent
evaluation, Owner time attestation, weight adoption, task effectiveness or
production approval. Do not merge/deploy this draft as an eligibility grant.

## Exact inputs, before new merge commit

- First parent: PR #6025, Git commit
  `9a5ef60be0076c5e9de97e3a396e94ebe39454da`, which bounds the frozen
  credit raw feedback scan.
- Second parent: PR #6026, Git commit
  `a4abafbcb89053bda9a8300adab13ed8a91f9456`, which integrates
  causal MEM prefix filtering and deterministic seeded kind rotation.
- Merge base: `9d90eee116002530a402ec2b8d47a1641d9f7653`.
- Source: `study.py` SHA-256
  `f7ade27d55c998525109dd54b8624c610e4b0b3ebff7e2ae44e8be87476c083b`.
- Added joint test: `test_joint_credit_mem_prefix_budget.py` SHA-256
  `857965d00c31948fe29c52f4099a654c1b6c549ca2f0ca51d3191e4151af1e01`.
- Runtime: configured HeptaRuntime `ai395`, Python 3.14.4,
  run at 2026-11-12 00:41 UTC. Neither Colab nor Kaggle availability
  was established for this small CPU-only verification.

## Frozen experiment identity

No model weights, tokenizer or training optimizer are involved. All inputs
are synthetic and constructed by the checked-in unittest code. The shared
declared cutoff is sequence 10; observed credit action sequence 1, reward
availability 4, future invalid feedback availability 15; memory kinds fact,
episode, skill and recovery have sequences 1..4, tombstone 8, later attempted
revival 12, and future invalid revision 20. Seed strings are deterministically
`trial-owner-proposed:0..127` and are **not** custodied by an independent
Owner. Credit arm is routed, decay 1, max lag 10 and one update dimension.
Memory's stratified replay budget is one object. Exact/uniform controls
remain in the inherited regression tests.

## What was independently executed

1. Full strict two-parent Git merge was clean, retaining both original
   commits and their evidence. No prior reference test was rewritten.
2. Four *new cross-mechanism tests* passed: causal suffix invariance of both
   frozen selectors for 128 declared seeds, visible deletion remains sticky
   while earlier credit is unchanged, two independent future-only raw
   iterators fail closed at precisely the 65,537th yielded record, and both
   accept a legal raw length of 65,536 without future inclusion.
3. A new full regression of the merged candidate passed **88/88**
   (prior #6026 branch 80 and #6025 addition four plus four new joint tests).

Original local logs are shipped as
`JOINT_CREDIT_MEM_FULL_SUITE.log` and
`JOINT_CREDIT_MEM_FOCUSED.log`; command/source/parent hashes are in
`JOINT_CREDIT_MEM_IDENTITY.log`. Tests use
`python3 -m unittest discover -s qualification/neuroscience-20261110 -p 'test_*.py' -q`.
The exact test suite was timed with `/usr/bin/time -v`:
full suite 0.08s wall, 0.07s user CPU, peak RSS 22,728 KiB,
exit 0; four focused tests 0.05s wall, 0.04s user CPU,
peak RSS 22,012 KiB, exit 0. These are **reference-process costs**,
not end-to-end execution/training/proof/communication or comparable
algorithm costs.

## Failure and adoption boundaries

This integration does not authenticate self-declared event timestamps,
model/data provenance or seed custody. An input exceeding the raw cap is
refused even if all later events are irrelevant; no unbounded-suffix
independence is claimed. A passing finite test does not prove all adversarial
interleavings safe. Production Q24 Owner, real dense/sparse ACT/CTRL reward
matching, actual MEM retention/deletion, A to held-out B to NoUpdate/Adopt
to different C to cold recovery, true per-arm execution costs, multi-seed
statistics and Core×NDU 2×2 attribution all remain **HOLD_NO_GO**.

GitHub CI terminal status must be independently checked against the exact
final HEAD. This report does not assert future CI or deployment success.
