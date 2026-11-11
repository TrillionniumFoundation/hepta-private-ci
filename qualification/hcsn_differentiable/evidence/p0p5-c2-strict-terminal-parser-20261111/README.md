# HCSN C2 successor — strict real terminal-result admission (HOLD)

## Precise scope and source

This **unadopted** successor hardening candidate stacks on Draft PR #5993
exact head f00975420c07ab69cc1e4c6cfb6a63edd5994e39, whose base is
94b9501cfc82d97411cedce0cacf997bd3c1a51d (Draft #5987).
All changes are confined to a newly created independent worktree and this
GitHub branch; the old C2 job, its result files and other worktrees were not
opened for writing, restarted or adopted.

The predecessor successor terminal_result_gate used ordinary json.loads
to read result.json and the frozen parent report. It could report
terminal_evidence_complete=True for digest-bound data containing duplicate
keys, NaN or exponent overflow (1e999). A digest identifies bytes; it
does not by itself establish unambiguous finite JSON semantics.

This patch adds bounded descriptor-based, no-follow, duplicate-key rejecting,
finite-only JSON-object parsing and applies it to **both** result and frozen
parent in the actual new C2 controller gate. It also rechecks parent identity
after parsing. It does not alter the original C2 producer or treat failing
nonzero-exit reports as successful model training.

## Native, non-training RED/GREEN

Host: heptaruntime desktop; Python 3.12.3; PyTorch 2.8.0+cu128;
existing precise venv:
/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python.

- RED job 1a1cb63fad1-2564-b2f, RED.native.log and RED.exit: 7 tests,
  **6 failures**, 1 valid negative-terminal control success, exit 1.
  Malicious result/parent JSON was incorrectly accepted by the predecessor.
- GREEN job 1a1cb651414-2564-b32, GREEN.native.log and GREEN.exit:
  **13/13 passed**, no failures/skips, exit 0 (six predecessor native
  wiring tests plus seven new ingestion tests).
- FINAL-GREEN job 1a1cb674316-2564-b39,
  FINAL-GREEN.native.log and FINAL-GREEN.exit: reproduces the
  exact CI unittest-discovery pattern test_successor_*.py; 13/13 pass,
  exit 0. The original workflow's single-file discovery was extended to
  include both test modules.

The positive negative-exit control remains admitted as a producer-terminal
observation, not as a scientific success. All six adversarial cases now
fail-closed; no model was trained, resumed or independently evaluated.
Git blob SHA identities can be audited against this PR's exact source.

## Scientific / product gates

Original desktop job 1a1c74f3308-be2a-75 remains **finalizing, outcome
unknown**, with no confirmed terminal publication. Prior independently
retained evidence remains 4/6 producer reports, two zero-byte interrupted
checkpoints, and **0/6 independent model replays**; this patch does not
re-establish or increase those denominators. Any claim about independent
C2 scientific gain, P1 full accessed-state numerical precision, matched
P2 baselines, P3 QVI net value, P4 multimodal effects or P5 production
qualification stays **HOLD_NO_GO**.

This scope closes only the newly reproduced parsing ambiguity in the
*successor* controller, not the broader runner lifecycle or six-fit gate.
