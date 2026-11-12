# Raw JSONL CLI ingress ceiling — read-only qualification

**Status: local RED → GREEN contract validation only; HOLD_NO_GO / DENY_ALL.**
This research CLI is not a model trainer, Owner, independent evaluator, or release authority.

## Exact source and defect
- Exact parent: PR #6094 head `84e895854ee3e5a0f0cc0633469e27ba4c4e0b9d`, tree `df44118723fa5af460d5524898b0b3857d5f13f4`.
- The existing `paired_evidence()` bound raw iterables to 400,000 rows, but `main()` first created an **unbounded** JSONL list. Blank-line floods and oversized lines passed the raw-input budget without independent accounting.
- New lazy JSONL reader enforces 400,000 physical lines **including blank lines**, max 65,536 Unicode characters per individual line using bounded `readline()`, and validates JSON objects as `TrialRow` before handing them to the existing 400,000-row paired contract. It never accepts a 400,001st line or silently interprets an invalid item as evidence.
- This limit is based on decoded text characters, not raw file bytes; UTF-8 byte traffic, OS file open, and the Python interpreter still cost resources and are not accounted as Owner measurements.

## Real execution on the operator host
The immutable raw logs `JSONL_INGRESS_RED.log`, `JSONL_INGRESS_GREEN.log`, `JSONL_INGRESS_FULL_SUITE.log`, `JSONL_INGRESS_RESOURCE.log` and `JSONL_INGRESS_IDENTITY.log` contain observed results and source hashes.
- Before patch: 4 adversarial tests ran, 1 passed / 1 failed / 2 errors. Over-limit blank input yielded "empty evaluation"; malformed JSON object shape or oversized line leaked a `TypeError`.
- After patch: focused 4/4 passed; entire shadow reference suite 102/102 passed. Valid 4-arm JSONL still reports 1 complete matched block with unchanged HOLD/qualification fields.
- Exact model, training, production Owner, independently held-out B, next-task C, GPU, Colab/Kaggle, and actual task outcome counts are **zero or NOT_RUN**. Fixtures are synthetic, and the source/test hashes are local consistency checks only.

## Remaining gates
No live model output quality, ACT/CTRL full-cost pairing, Q24 production candidate, Owner-attested timing, memory deletion, NoUpdate/Adopt, future B, C, cold restart, or Core×NDU 2×2 attribution is established. Even a passing path-scoped CI cannot close these gates. The new PR must remain Draft; do not merge/deploy/adopt weights.
