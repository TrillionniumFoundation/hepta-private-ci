# kernel.evidence A-D execution resumption — 2026-09-28

## Exact starting point

Continue the existing isolated integration candidate PR #1148 on
`work/kernel-evidence-ad-integration-20260928`; do not create another competing
production candidate or modify main or the retired source branches.

Observed integration head before this record:
`224b078335f7c70acc8ce6cc04dd7d4fcad4cd7a`.
Observed fixed main base: `a126987b84737dbc2ee2592442a314117bddb4a2`.
PR #1092 is closed without merge. Its source descendants are provenance, not
current qualification receipts.

## Requested completion sequence

A. Validate and repair role independence, owner-controlled verification profiles,
sealed verified trust, current signed trust generations and direct compiled
source (not source-generating scripts).
B. Validate atomic complete-provenance snapshots, monotonic trust, publication
owner fencing, durable publication state and recovery of unknown CAS outcomes.
C. Validate product paging and bounded responses, explicit modes, actual
backup/build/restore bindings, segmented history, capacity and operational
failure classifications.
D. Fix executable native regressions, synchronize source/document/status
bindings and qualify both the final source and deterministic fixed-base merge.

## Execution and authority boundary

This initial commit records scope and provenance only. No test result or A-D
completion is inferred from it. Previously implemented features will be read
and reused rather than counted as newly delivered. Every subsequent code commit
requires fresh candidate-bound verification; queued jobs are not passing jobs.

No credentials, external signer receipts, independent acceptance, deployment,
canary, promotion or release authority are manufactured by this work. External
operational gates remain false without their actual evidence.
