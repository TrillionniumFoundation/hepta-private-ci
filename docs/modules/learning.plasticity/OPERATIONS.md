# learning.plasticity production operating profile

This is the concrete host profile for the authenticated plasticity proposal adapter.
The numbers below are operational stop/alert thresholds, not measured performance
claims. A deployment may be stricter but must not silently relax them.

## Explicit bootstrap and admission prerequisites

The Agentd binary accepts the pair `--plasticity-bootstrap-descriptor` and
`--plasticity-bootstrap-descriptor-digest`. Supplying only one is rejected.
The descriptor is a bounded JSON record with schema
`hepta.agentd.plasticity-bootstrap.v1`, exact Agentd ID/spawn generation, absolute
owner-store paths, expected independent recovery witnesses, selected signer/owner
policy and bounded queue/registry configuration. Its digest must come from the
host-selected configuration; hashing an untrusted descriptor and accepting its
own trust keys does not establish an independent trust root. Absence of the
explicit descriptor leaves plasticity disabled.

`load_plasticity_process_bootstrap_v1` checks descriptor bytes and identity, checks
path separation, reconstructs each store through its native recovery API and
rejects unknown fields. Native registry opens use one of `bootstrap_new`,
`resume_unacknowledged` or `reopen_anchored`; a failed reopen/resume must not be
retried as fresh bootstrap. File/path separation checks prevent aliases, but do
not prove physically independent rollback domains. Deployment supplies that
separate evidence.

The recovered ArtifactRegistry, learning ledger, NDU/neuron state and verifier are
the owner handles selected for this generation. Re-reading their current heads
does not prove synchronization with an external owner's later updates. The
bootstrap is not a hot-refresh or revocation-subscription implementation. Before
admitting changed selected-artifact, source, objective, trust/revocation or owner
state, the selected host must provide explicit current-owner integration or
reconstruct a generation from fresh independent witnesses. Expired/unavailable
evidence disables new proposals; it never permits retaining opaque digests as
substitute evidence.

The source runtime owner samples its Unix-millisecond clock after dequeue and
before host admission. The historical `now` argument on the submission handle is
retained for API compatibility and ignored for verification time. Failure of this
initial clock sample returns `ClockUnavailable`; a receipt's `observed_at` remains
evidence provenance, not the current clock. Every successful clock sample updates
the owner's lifetime high-water mark, including samples from requests later
rejected for expiry, revocation or another admission failure. A subsequent sample
below that mark rejects instead of reviving old evidence. This covers successive
requests and both sampling phases; it is not a durable time floor across owner
restart. The queue capacity is configured within `1..64`. A bounded queue is a
memory limit, not an expiry or timeout guarantee, and queue delay never extends a
signature's validity window.

The composed host path performs candidate generation, independent evaluation and
proposal preparation, then the registry completes its applicable full-history
scan, semantic preflight and frame encoding. Only after that expensive work does
the guarded append callback sample the clock again and recheck signatures,
principal validity, scheduled revocation and trust context; parameter admission
also checks the intersection of the initially authenticated owner receipts'
validity intervals. The callback runs before the writer enters its poison/write
transition, before physical append and before an identical retry receives a
positive result. An expired, revoked or unavailable final-time check rejects
without changing the writer or durable registry. This temporal revalidation does
not refresh external owner or trust snapshots for the generation.

Failure of the second clock sample is a parameter/topology product binding error
with `host clock unavailable`. Clock regression follows the same phase-specific
rejection path. The `ClockUnavailable` runtime variant specifically describes
failure or regression at the initial sample; neither phase clears the retained
time high-water mark.

The owner is pinned to the process's exact `spawn_generation + 1` Running
generation, with overflow rejected. It checks that generation and readiness at
dequeue and final admission instead of adopting whichever generation a request
refreshes. Draining is a monotonic process latch. Late readiness probes and stale
Running observations cannot reopen admission after local or supervisor-driven
drain; recovery requires a newly composed lifetime.

At that final registry callback, admission samples the clock and rechecks
cancellation, exact generation and current readiness. It then retains the local
runtime mutex guard through the synchronous durable transaction, post-write
integrity confirmation and independent anchor commit. Local lifecycle updates
wait for that transaction to finish.
Cancellation already observed before this gate rejects. Cancellation, signature
expiry or an external supervisor publication after the gate does not undo an
already admitted transaction. A missing response requires durable reconciliation
using the original proposal identity. The operation is bounded by the configured
history and input sizes; it has no hard wall-clock completion guarantee and no
distributed atomicity with supervisor publication or external owner changes.
Evidence is admitted at that final gate, not resampled at every physical byte
write. Subsequent expiry does not turn completed durable work into a rollback.

The remaining upstream product trigger is a separately composed self-iteration
coordinator. It must consume a frozen envelope and independently signed
parameter/topology request with exact source, objective, grammar, budget and
next-generation bindings, and submit through the existing producer. The current
internal state methods and producer façade do not by themselves prove that such
a coordinator exists or runs. It must not construct its own evaluation,
acceptance, writer or execution grant.

## Authority and ownership

The product-workspace adapter entrypoint is
`codex-rs/hepta-intelligence::propose_authenticated_parameter_plasticity_v1`.
It can construct and persist a proposal only. It has no selection, training,
installation, runtime-topology, promotion or release authority. `codex-rs/hepta-agentd::propose_agentd_plasticity_v1` is now called by the long-lived
`PlasticityRuntimeOwnerV1` supervised from the real Agentd `runtime.rs` task set. The state-held `AgentdLearningPlasticityProducerV1` is the named non-test producer for both parameter and topology submissions; it owns only the bounded handle. The owner recomputes the current artifact and durable learning-ledger frontiers
and requires context-bound owner evidence for dataset, update-rule, modulator,
modulator-broadcast, eligibility, mutation-policy and per-parameter signals before
invoking the adapter. Every owner query binds the live artifact/ledger heads; parameter signals additionally bind the exact eligibility, modulator, learning-rate and bound values used by deterministic generation. `DatasetSnapshotReceiptV3` and immutable Policy artifacts have concrete owner adapters; NDU projection state supplies the current modulator, the immutable broadcast-policy artifact binds projection weights, neuron.runtime supplies the anchored eligibility checkpoint, and exact ParameterSignal receipts recompute the consumed numeric values. All of these paths fail closed on stale, rolled-back, unavailable, wrong-owner or value-substituted state. A complete evidence-kind→owner allowlist is enforced
separately from resolver authentication, so a valid receipt from the wrong owner
cannot satisfy admission. The owner is attached explicitly through `AgentdConfig`, uses a bounded in-process
queue and is fenced by the current Running/ready Agentd generation. No public plasticity
wire method or fallback writer is created. `AgentdState::submit_parameter_plasticity_v1`
and `submit_topology_plasticity_v1` are driven by the named non-test producer; the
lifetime E2E proves first write, daemon restart, anchored reopen and idempotent replay
for both proposal registries. This source composition is not evidence that a deployed
target host executed or accepted it, so product execution remains unproved.

The selected host owns four independent facts: current learning-evidence trust state,
current artifact/evidence frontier witness, authoritative owner-evidence resolution,
and the proposal-registry anchor/fence.
Agentd now provides parameter and topology anchor/fence stores through a shared
append-only checksum-framed journal implementation. Deployment must place each
journal in a rollback domain independent from its registry file. A complete invalid journal frame is
corruption and is never silently discarded; only an incomplete final crash tail may
be truncated after all complete predecessors validate. The proposal registry file
MUST NOT be the only copy of its acknowledged anchor. Writer-fence issuance, registry
generation rollover and anchor persistence are serialized by the journal.

Before writer-fence issuance and anchor persistence, `AdaptiveAnchorJournalV1`
verifies the complete current journal against its retained 72-byte header, trusted
digests for every 81-byte frame and exact expected EOF. This includes an identical
anchor acknowledgement that would otherwise return from cached state. After a
successful physical write and synchronization, it repeats the verification before
clearing poison and acknowledging success. Journal corruption or I/O uncertainty
poisons the handle, including a sync error after frame bytes may have reached
durable storage. That handle rejects both anchor commits and writer-fence issuance
until explicit reopen/reconciliation; the caller cannot retry to overwrite or
acknowledge an uncertain frame. New zero-length journal initialization resets its
file cursor before the header write.

The journal limit is 1,000,000 frames, with a maximum physical size of 81,000,072
bytes including the header. Full verification uses a fixed 32 KiB read buffer,
72-byte/81-byte scratch and retained trusted digests with `O(frames)` metadata memory and
`O(history bytes)` I/O. Include this cost, as well as proposal-registry scans, in
the target-host latency and capacity profile. Cached fence, anchor,
previous-anchor and journal-state snapshots are not a live byte-integrity check
and must not be treated as a new acknowledgement. The same immutable enrollment
and cooperative exclusive file-description contract applies to the journal.

Online trusted frame digests are retained only by the live handle. After it is
dropped, ordinary journal reopen checks frame checksums and transition grammar
without an independent journal-head witness; it cannot alone detect a restored
header-only image or an older valid complete prefix. Reconcile independently
retained fence/anchor history and the host's attested rollback-domain conditions.
A successfully reopened journal alone does not prove that the previously
acknowledged history survived.

An adapter append is acknowledged only after `PlasticityAnchorCommitterV1` durably
persists the resulting current registry anchor in that independent rollback domain.
The repository fault fixture also holds the external acknowledgement while presenting a rolled-back header-only registry and requires reopen to fail with `AcknowledgedHistoryMissing`; this proves the reconciliation rule, not physical storage-domain independence.
If the anchor commit fails after the registry append, the adapter writer is poisoned,
returns `AnchorPersistenceFailed`, and MUST NOT perform another operation until an
anchored reopen reconciles the durable file with previously acknowledged history.
An online journal check can fail after a proposal append has already written its
bytes. The absent acknowledgement is not rollback; retain both files and
reconcile their independent histories before another attempt.

The open parameter and topology registries also verify every live file byte
against the enrolled header, trusted frame digests and exact expected EOF before
cached reads/counts or anchor results, identical retries, canary binding and new
appends. Verification checks frame lengths, prefixes, body digests and footers;
a successful append is checked again before its receipt is returned. A same-length
file edit therefore cannot be hidden by the in-memory proposal cache. Any
integrity or read-I/O failure poisons that handle, which must be discarded and
reopened through the recovery runbook.

These checks stream the history with a fixed 32 KiB scratch buffer and bounded
metadata, without cloning or decoding all proposal objects on each call. They
perform `O(history bytes)` I/O per checked operation; the host must include that
cost in capacity and latency measurements. The parameter file cap is 512 MiB and
the topology file cap is 256 MiB; record capacity does not replace these physical
limits. The preflight scan and frame encoding precede final temporal/lifecycle
admission; post-write confirmation remains part of the admitted transaction.
The verification cursor is serialized, but the host must still honor
exclusive/cooperative ownership of the open file
descriptor and immutable path/inode enrollment. Non-cooperating concurrent writes
or seeks through another shared descriptor, and distributed storage rollback,
remain outside this guarantee. Immutable scope/fence getters alone do not prove
the integrity of current file history.

The poison getter is a cached health observation rather than file authentication.
`AnchoredPlasticityWriterV1::state()` synthesizes its state with the registry's
sticky poison latch, including failures found by read-only queries. Once such a
query detects bad bytes, the writer reports `Poisoned` and rejects subsequent
operations. A `Healthy` poll or false poison latch does not itself prove current
file integrity, and these getters do not scan the history on every call.

## Outcome handling

| Outcome | Host action | Success claim |
| --- | --- | --- |
| Missing/stale/wrong-owner evidence, bad signature, role collision or semantic drift | Reject the request; obtain newly frozen independent evidence for a changed context | No proposal success |
| Host clock failure or regression | Reject admission; restore a trustworthy host clock without clearing the owner time floor | No revival of previously expired or revoked evidence |
| Draining, cancelled or mismatched generation before final admission | Reject; reconstruct the correct lifetime when explicitly selected by the supervisor | No append from an obsolete owner |
| Independently attested `NoAdmissibleUpdate` | Persist the exact no-change terminal proposal and its anchor | Durable terminal diagnosis; no installed update |
| Identical acknowledged retry | Return the original durable record after current admission and live-file integrity checks | Idempotent proposal receipt |
| Queue closure or caller timeout/cancellation | Treat the proposal outcome as unresolved until the owner/anchored registry is reconciled; use the original identity | No inference from missing response |
| Indeterminate append or failed anchor commit | Stop that writer, retain bytes/witnesses and follow the recovery runbook | No acknowledgement based only on written bytes |
| Governed topology/canary receipt | Preserve candidate, handoff, plan, observation and exact durable-history bindings for the external runtime owner | Proposal/observation only; separate FinalUse execution remains required |

## Topology proposal operations

Topology proposal construction is also source-composed through the named
`AgentdLearningPlasticityProducerV1::submit_topology` /
`AgentdState::submit_topology_plasticity_v1` boundary, then
`propose_authenticated_topology_plasticity_v1` and
`propose_agentd_topology_plasticity_v1`. Every update binds a typed
`WriterHandoffPlanV1` with distinct owners, an advancing writer fence, source-store,
migration, rollback and acknowledgement-contract digests. The complete governed
proposal is persisted in `DurableTopologyProposalRegistryV1`, with the same
lock-before-bootstrap and external-anchor posture as parameter proposals.

Several candidate alternatives may target the same module. Each change must
match its exact `WriterHandoffPlanV1` by module ID and plan digest; a handoff for a
different alternative cannot satisfy it. Canary construction resolves that same
exact plan and rollback from the stored governed proposal.

`StructuralCanaryControllerV1` remains an observation-only bounded state machine and cannot apply topology. The external `codex-hepta-runtime` owner now provides separate execution boundaries. Healthy replacement revalidates the governed proposal and exact writer handoff, requires every predecessor organ Ready, claims a single-use FinalUse grant immediately before live CNS replacement, and returns a deny-all execution receipt. Fault recovery accepts only a Stopped/Quarantined predecessor, requires the exact next generation, and claims a second grant bound to the distinct `runtime.hepta-live-shell.topology-recovery` destination. `build_structural_canary_plan_v1` accepts the durable topology
registry plus proposal/candidate IDs and reads the stored governed proposal and original
append receipt internally; `StructuralCanaryPlanV1` fields are not externally
constructible. It rejects proposal/admission/frame/candidate/handoff/rollback drift.
The plan digest uses the `hepta.plasticity.structural-canary-plan.v3` domain and
includes the durable registry scope and writer fence. A plan or Observer signature
from another scope, writer generation or older plan digest cannot be reused; the
Observer must sign the newly constructed exact plan before observations resume.
The plan binds that durable sequence/frame and candidate identity in addition to the
rollback, writer-handoff set, baseline health and thresholds. Safety violation,
lineage mismatch, excess regression or an unverified rollback causes terminal abort.
The receipt binds the complete plan and a rolling chain over every observation;
reaching the minimum successful-step threshold remains `Running` until an explicit
`finish()` transition.
`regression_count` is cumulative over the canary: it must never decrease and must
not exceed the current observation sequence. A decreasing/substituted count is
rejected before mutating the observation history; exceeding the plan's regression
budget aborts terminally. Per-observation zeroes cannot reset prior regressions.
`observe_authenticated_structural_canary_v1` is the product-facing observation boundary. A current trusted `Observer` must sign the plan digest and every observation field (health/evidence, regression count, safety violation, lineage mismatch and rollback verification) before the state machine is called. Direct caller assertions are therefore not accepted by the composed canary path. An Accepted source receipt is still not activation authority and is not evidence of a
real host canary run.

## Required events

A selected host MUST emit one bounded event for: `proposal_attempt`,
`generator_rejected`, `evidence_rejected`, `evaluation_rejected`, `registry_conflict`,
`owner_evidence_missing`, `owner_evidence_unauthorized`, `owner_evidence_stale`,
`owner_evidence_context_mismatch`, `registry_busy`, `registry_indeterminate`,
`registry_poisoned`, `anchor_commit_failed`, `anchor_mismatch`,
`acknowledged_history_missing`, `proposal_appended`,
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
- **Authentication:** page on any accepted request whose authenticated Generator,
  Observer and Evaluator do not satisfy pairwise signed-role separation, or whose
  owner-evidence receipt, including the mutation-policy receipt, cannot be resolved
  against its exact live artifact/ledger frontier, artifact/window/dataset context,
  per-signal values and evidence-kind owner allowlist;
  the implementation is expected to make these states unreachable.
- **Mutation grammar provenance:** reject a parameter mutation policy whose canonical
  `MutationGrammarManifestV1` semantic digest is zero, missing or differs from the
  manifest admitted by the selected host/control-engineering boundary.
- **Latency target:** host p99 for authenticated generation + evidence/evaluation
  admission + full-history integrity verification + durable append + external
  anchor commit should remain below 2 seconds for the bounded profile. Exceeding
  this for 15 minutes disables new plasticity attempts but does not affect the
  currently selected runtime artifact. This target does not establish a deadline
  for an in-flight synchronous transaction.

These thresholds are the required operating profile for a deployed target host. The
Agentd source callsites now exist, but the thresholds are not measured SLO evidence
until a target-host telemetry stream and exact execution receipts exist.

## Recovery runbook

1. Freeze new plasticity attempts; do not modify the selected runtime artifact.
2. Retain the suspect registry bytes, last externally acknowledged anchor, writer
   fence, trust snapshot and artifact/evidence frontier receipts.
3. On `Indeterminate`, `Poisoned` or `AnchorPersistenceFailed`, discard the in-process
   writer handle and any journal handle poisoned by integrity or I/O failure.
   Do not convert a failed anchor commit into success based only on the registry file, or issue
   another fence through an uncertain journal handle.
4. Reopen parameter state only with `AnchoredPlasticityWriterV1::reopen_anchored`
   and the independently retained last acknowledged anchor. The Agentd anchor journal
   must also replay cleanly. It may trim only an incomplete last journal frame; a
   complete checksum/sequence/fence violation is an incident and must remain intact
   for recovery. Clean journal replay alone cannot detect an older valid prefix;
   compare independently retained fence/anchor history and verified rollback-domain
   conditions before accepting its state. A valid proposal file may contain later unacknowledged frames;
   reconciliation may inspect them because `open_anchored` proves the trusted prefix
   before any proposal-file repair. Anchor mismatch or missing acknowledged history
   requires operator recovery; never truncate a complete invalid frame first.
5. Reverify current trust/revocation, artifact/evidence frontiers and every typed
   owner-evidence receipt before retrying proposal construction. Do not replace an
   unavailable owner resolver with opaque-digest acceptance.
6. An identical proposal retry may return the original record. Semantic drift in an
   occupied artifact/window slot remains a conflict.
7. Registry rollover uses the explicit Agentd rollover entrypoint with the exact
   previously acknowledged anchor. If a crash occurs after a new fence is journaled,
   resume that pending fence through the restricted unacknowledged-bootstrap API.
   Empty files, exact header-only state and an incomplete first-frame crash tail are
   recoverable. Any complete unacknowledged proposal frame is preserved and rejected
   as `UnacknowledgedHistoryPresent`; reconcile it explicitly before proceeding.
   Never issue another fence to skip the interrupted generation.
8. Topology proposal recovery follows the same rule through
   `DurableTopologyProposalRegistryV1::reopen_anchored` and the Agentd topology anchor
   journal. Never convert a missing topology anchor into a fresh bootstrap.
9. Resume only after the new current anchor is durably retained outside the registry
   rollback domain. A same-domain copy does not satisfy the external commit.

## Canary and qualification

Read-only live-file tamper regressions alone do not establish post-write read or
sync failure coverage. Qualification must retain actual fault-injection results
for those phases rather than infer them from the poison latch or successful
append path.

A production activation claim requires target-host execution evidence in addition to
the implemented Agentd source callsites, plus an exact-head and synthetic-merge run
covering: V3 deterministic generation, trust-region
rejection, signature expiry/revocation, generator/evaluator and observer/evaluator
controller collisions, owner-lifetime clock rollback across rejected attempts,
exact spawn-to-Running generation binding, final cancellation/drain/fence rejection,
late-readiness drain resurrection denial, missing evaluation,
independently-attested durable no-update terminal behavior,
owner-evidence missing/stale/context or signal-value substitution,
concrete dataset/policy live-frontier rollback rejection, stale/frontier witness,
anchored reopen, failed external-anchor
commit and poisoned-writer behavior, live header/frame/footer tampering and
same-length byte substitution across cached reads, retries, canary binding and
appends, post-write integrity verification, old-prefix rollback, incomplete-tail recovery,
writer-fence mismatch, append-only anchor-journal crash-tail recovery and complete-frame
corruption rejection, online journal byte verification before fence issuance and
new or identical anchor acknowledgement, post-write journal verification,
zero-complete-frame bootstrap recovery plus complete-unacknowledged
history rejection, monotonic generation rollover, canonical mutation-grammar digest
binding, evidence-kind wrong-owner denial, typed parameter-mutation-policy
protected-surface denial, topology writer-handoff validation, topology anchored reopen and append/ack registry-only rollback rejection,
topology self-activation denial, authenticated structural-canary observation binding,
and structural-canary abort semantics. Repository qualification additionally performs an actual live CNS cutover, forces the serving host into a stopped/faulted state, executes a separately FinalUse-authorized stopped-generation recovery as the next generation, verifies serving recovery, and only then signs the canary observation through the independent Observer boundary. This proves repository source composition, not deployment. The selected target host must repeat the path with production telemetry, physically independent rollback domains and operator evidence. Until those receipts exist, product execution, independent acceptance, activation and release remain false even when source compilation/tests pass.
