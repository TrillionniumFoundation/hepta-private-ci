# learning.plasticity production operating profile

This is the concrete host profile for the authenticated plasticity proposal adapter.
The numbers below are operational stop/alert thresholds, not measured performance
claims. A deployment may be stricter but must not silently relax them.

## Authority and ownership

The product-workspace adapter entrypoint is
`codex-rs/hepta-intelligence::propose_authenticated_parameter_plasticity_v1`.
It can construct and persist a proposal only. It has no selection, training,
installation, runtime-topology, promotion or release authority. No selected production
host callsite is currently claimed; a host must explicitly invoke this adapter before
product execution can be asserted.

The selected host owns three independent facts: current learning-evidence trust state,
current artifact/evidence frontier witness, and the proposal-registry anchor/fence. The
proposal registry file MUST NOT be the only copy of its acknowledged anchor. Writer
fence issuance and anchor persistence MUST be serialized by the host.

An adapter append is acknowledged only after `PlasticityAnchorCommitterV1` durably
persists the resulting current registry anchor in that independent rollback domain.
If the anchor commit fails after the registry append, the adapter writer is poisoned,
returns `AnchorPersistenceFailed`, and MUST NOT perform another operation until an
anchored reopen reconciles the durable file with previously acknowledged history.

## Required events

A selected host MUST emit one bounded event for: `proposal_attempt`,
`generator_rejected`, `evidence_rejected`, `evaluation_rejected`, `registry_conflict`,
`registry_busy`, `registry_indeterminate`, `registry_poisoned`, `anchor_commit_failed`,
`anchor_mismatch`, `acknowledged_history_missing`, and `proposal_appended`.

Events contain digests/IDs and numeric counts only. Raw model parameters, signatures,
credentials, dataset records and payload bytes are prohibited from logs.

## SLO and stop thresholds

- **Integrity:** any `anchor_mismatch`, `acknowledged_history_missing`, corrupt frame,
  authority-granted condition, signature/trust-context mismatch, or failed external
  anchor commit is an immediate stop and page. No automatic fallback to unanchored
  open is permitted.
- **Indeterminate durability:** any write/sync `Indeterminate` or poisoned writer is an
  immediate stop for that handle. Reopen only after reconciling an independently
  retained anchor. Blind retry is prohibited.
- **Capacity:** warn at `>=80%` configured proposal-record capacity; stop admission at
  `>=95%` until retention/rollover is explicitly authorized. Capacity exhaustion is
  never handled by deleting history in place.
- **Conflict:** alert when semantic conflicts exceed 1% of proposal attempts in a
  rolling 15-minute window or any single proposal ID/slot produces repeated drift.
- **Authentication:** page on any accepted request whose authenticated generator and
  evaluator identities do not satisfy the existing signed-role separation checks;
  the implementation is expected to make this state unreachable.
- **Latency target:** host p99 for authenticated generation + evidence/evaluation
  admission + durable append + external anchor commit should remain below 2 seconds
  for the bounded profile. Exceeding this for 15 minutes disables new plasticity
  attempts but does not affect the currently selected runtime artifact.

These thresholds are the required operating profile for a future selected host. They
are not measured SLO evidence until a real host callsite and telemetry stream exist.

## Recovery runbook

1. Freeze new plasticity attempts; do not modify the selected runtime artifact.
2. Retain the suspect registry bytes, last externally acknowledged anchor, writer
   fence, trust snapshot and artifact/evidence frontier receipts.
3. On `Indeterminate`, `Poisoned` or `AnchorPersistenceFailed`, discard the in-process
   writer handle. Do not convert a failed anchor commit into success based only on the
   registry file.
4. Reopen only with `AnchoredPlasticityWriterV1::reopen_anchored` and the independently
   retained last acknowledged anchor. A valid file may contain later unacknowledged
   frames; reconciliation may inspect them because `open_anchored` proves the trusted
   prefix before any repair. Anchor mismatch or missing acknowledged history requires
   operator recovery; never truncate first.
5. Reverify current trust/revocation and artifact/evidence frontiers before retrying
   proposal construction.
6. An identical proposal retry may return the original record. Semantic drift in an
   occupied artifact/window slot remains a conflict.
7. Resume only after the new current anchor is durably retained outside the registry
   rollback domain. A same-domain copy does not satisfy the external commit.

## Canary and qualification

A production activation claim requires an actual selected-host callsite plus an
exact-head and synthetic-merge run covering: V3 deterministic generation, trust-region
rejection, signature expiry/revocation, generator/evaluator controller collision,
missing evaluation, stale/frontier witness, anchored reopen, failed external-anchor
commit and poisoned-writer behavior, old-prefix rollback, incomplete-tail recovery,
writer-fence mismatch, and topology self-activation denial. Until those receipts
exist, product execution, activation and release remain false even when source
compilation/tests pass.
