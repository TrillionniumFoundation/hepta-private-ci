# HCSN C2 exported native evidence: strict types and accounting sanity

2026-11-11. **Draft-only P0/P2 source/evidence hygiene, HOLD_NO_GO.**

## Pinned source / independent branch

- Parent Draft #5968 immutable head: `eacc1cd2d85a89dff5e71b5de4e406e5dbea5ff4`.
- This is a fresh clone and separate branch. No existing worktree, original C2
  process, original checkpoint, controller or journal was modified or restarted.
- Scope: `recovery_v1/c2_native_replay.py` and its unit tests; this is an
  *exported observation structural checker*, not native status authentication.

## Actual red/green regression

Four new negative fixtures construct receipt-bound but invalid native-shaped
observations. They initially **failed 4/4** against the exact #5968 baseline:
fractional peak RSS (bytes), impossible zero elapsed child wall with nonzero
child CPU, numeric 0 used as a boolean truncation flag, and nested numeric 0
truncation flags. `RED.stderr.log` and `RED.exitcode` preserve the failures.
The remote heptaruntime shell wrapper returns exit 0 after **confirming** the
inner unittest exit 1; do not confuse wrapper exit with unittest outcome.

The new code insists on integer positive native RSS bytes, rejects positive
CPU with zero elapsed wall, and admits truncation only as literal builtin
`False` or exact two-key `{stdout: False, stderr: False}` booleans.

Final full `recovery_v1` unittest discovery (original 52 + new 4):
**56/56 passed, 0 failures, 0 skipped**, inner exit 0.
Interpreter: desktop original pinned
`/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python`,
Python 3.12.3, PyTorch 2.8.0+cu128. CPU fixture tests; no new training.

## Original native C2: immutable read-only observation

`ORIGINAL-READONLY.json` rehashes all six fixed fit names, distinguishes
four producer `result.json` files from two missing results, and two
zero-byte `interrupted.pt` files. The original 28,672-byte journal has
16 complete JSON objects and a torn seventeenth; original controller RESULT
is absent. Independent native process status (not producer report) remains
`finalizing / outcome=unknown / terminal_publication_confirmed=false`.
These source observations are **not** full six-fit training results, model
replay, numerical admission, or verified scientific benefit.

## Blockers not closed

P0 full E/C/U/F/G/J/M, CURRENT and complete provenance; P1 whole training
visited posterior, rare tails, reset/mass and gradients; P2 new durable
runner/controller integration and six complete independently replayed
resource-bound fits; P3 independently paid DP/QVI versus fixed and
learned thresholds; P4 real async multimodal and anti-diffusion controls;
P5 stable independent net gain before adoption. Source/test green is not
repo-wide CI, merged tree, native production or scientific GO.
