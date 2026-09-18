# learning.plasticity production operating profile

This is the concrete host profile for the authenticated plasticity proposal adapter.
The numbers below are operational stop/alert thresholds, not measured performance
claims. A deployment may be stricter but must not silently relax them.

## Authority and ownership

The product-workspace adapter entrypoint is
`codex-rs/hepta-intelligence::propose_authenticated_parameter_plasticity_v1`.
It can construct and persist a proposal only. It has no selection, training,
installation, runtime-topology, promotion or release authority. `codex-rs/hepta-agentd::propose_agentd_plasticity_v1` is now the source-level host
callsite. It recomputes the current artifact and durable learning-ledger frontiers
before invoking the adapter. This source composition is not evidence that a deployed
target host executed or accepted it, so product execution remains unproved.

The selected host owns three independent facts: current learning-evidence trust state,
current artifact/evidence frontier witness, and the proposal-registry anchor/fence.
Agentd now provides source implementations for parameter and topology anchor/fence
stores; deployment must place each anchor store in a rollback domain independent from
its registry file. The
proposal registry file MUST NOT be the only copy of its acknowledged anchor. Writer
fence issuance and anchor persistence MUST be serialized by the host.

An adapter append is acknowledged only after `PlasticityAnchorCommitterV1` durably
persists the resulting current registry anchor in that independent rollback domain.
If the anchor commit fails after the registry append, the adapter writer is poisoned,
returns `AnchorPersistenceFailed`, and MUST NOT perform another operation until an
anchored reopen reconciles the durable file with previously acknowledged history.

## Topology proposal operations

Topology proposal construction is also source-composed through
`propose_authenticated_topology_plasticity_v1` and
`propose_agentd_topology_plasticity_v1`. Every update binds a typed
`WriterHandoffPlanV1` with distinct owners, an advancing writer fence, source-store,
migration, rollback and acknowledgement-contract digests. The complete governed
proposal is persisted in `DurableTopologyProposalRegistryV1`, with the same
lock-before-bootstrap and external-anchor posture as parameter proposals.

`StructuralCanaryControllerV1` is an observation-only bounded state machine. It
cannot apply topology. Safety violation, lineage mismatch, excess regression or an
unverified rollback causes terminal abort. The receipt binds a digest of the complete
canary plan and a rolling chain over every observation; reaching the minimum
successful-step threshold remains `Running` until an explicit `finish()` transition.
An Accepted source receipt is still not activation authority and is not evidence of a
real host canary run.

## Required events

A selected host MUST emit one bounded event for: `proposal_attempt`,
`generator_rejected`, `evidence_rejected`, `evaluation_rejected`, `registry_conflict`,
`registry_busy`, `registry_indeterminate`, `registry_poisoned`, `anchor_commit_failed`,
`anchor_mismatch`, `acknowledged_history_missing`, `proposal_appended`,
`topology_proposal_attempt`, `topology_handoff_rejected`, `topology_proposal_appended`,
`topology_anchor_commit_failed`, `structural_canary_started`,
`structural_canary_aborted`, and `structural_canary_observation`.

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

These thresholds are the required operating profile for a deployed target host. The
Agentd source callsites now exist, but the thresholds are not measured SLO evidence
until a target-host telemetry stream and exact execution receipts exist.

## Recovery runbook

1. Freeze new plasticity attempts; do not modify the selected runtime artifact.
2. Retain the suspect registry bytes, last externally acknowledged anchor, writer
   fence, trust snapshot and artifact/evidence frontier receipts.
3. On `Indeterminate`, `Poisoned` or `AnchorPersistenceFailed`, discard the in-process
   writer handle. Do not convert a failed anchor commit into success based only on the
   registry file.
4. Reopen parameter state only with `AnchoredPlasticityWriterV1::reopen_anchored` and the independently
   retained last acknowledged anchor. A valid file may contain later unacknowledged
   frames; reconciliation may inspect them because `open_anchored` proves the trusted
   prefix before any repair. Anchor mismatch or missing acknowledged history requires
   operator recovery; never truncate first.
5. Reverify current trust/revocation and artifact/evidence frontiers before retrying
   proposal construction.
6. An identical proposal retry may return the original record. Semantic drift in an
   occupied artifact/window slot remains a conflict.
7. Topology proposal recovery follows the same rule through
   `DurableTopologyProposalRegistryV1::reopen_anchored` and the Agentd topology anchor
   store. Never convert a missing topology anchor into a fresh bootstrap.
8. Resume only after the new current anchor is durably retained outside the registry
   rollback domain. A same-domain copy does not satisfy the external commit.

## Canary and qualification

A production activation claim requires target-host execution evidence in addition to
the implemented Agentd source callsites, plus an exact-head and synthetic-merge run
covering: V3 deterministic generation, trust-region
rejection, signature expiry/revocation, generator/evaluator controller collision,
missing evaluation, stale/frontier witness, anchored reopen, failed external-anchor
commit and poisoned-writer behavior, old-prefix rollback, incomplete-tail recovery,
writer-fence mismatch, typed parameter-mutation-policy protected-surface denial, topology
writer-handoff validation, topology anchored reopen, topology self-activation denial,
and structural-canary abort semantics. A real bounded canary must additionally emit
host telemetry and operator evidence. Until those receipts exist, product execution,
activation and release remain false even when source compilation/tests pass.
