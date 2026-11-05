# Runtime convergence: recovery, evaluation, and lifecycle admission

This change advances the existing product architecture: App Server is the only
model/session/tool execution spine, Agentd is the lifecycle/composition host,
and durable facts remain with their declared domain writers. It does not add a
second executor, a new authority issuer, or an adaptive release mechanism.

## Source composition

| Source | Exact commit |
| --- | --- |
| R3 diagnosis candidate | `4e31abc907f09740d402d1ddef7a1d2fe0a366a6` |
| Published public lifecycle refusal and matching documentation | `3247636513f4cddaede6e9b45110925e9065d507` |
| Two-parent integration | `12f793efff9d701b4ea781e5990ac434067e20ff` |
| Initial combined implementation | `1d87082c0d5afd2b474a2c453ea98005fd540dea` |

The lifecycle merge retains both histories. Its six changed paths have identical
base objects on R2 and R3, and the integration retains the published blobs. The
initial combined source tree is `f6e6406653d45c8d6b19f2271183c42300f6d051`.
Subsequent formatting or validation changes must retain their own exact source
identities; initial-source results cannot silently qualify a changed tree.

## A. Product recovery: reject arithmetic failure before changing a run

The original public recovery API admits a nonzero `u64::MAX` revision. A terminal
observation then changed the phase before its checked revision increment failed.
The error response could therefore leave a closed run that released capacity,
could be removed, and could accept a repeated observation as idempotent success.

The same ordering issue affected context attachment, dispatch, cancellation,
deadline expiry, drain, and unknown-state transitions. The implementation now
checks revision, ACK-deadline, and applicable change-count arithmetic before
committing that record's fields. Unresolved records retain their capacity and
remain non-redispatchable when arithmetic is rejected.

This is record-level arithmetic rejection atomicity. Completed batch prefixes
remain committed; the failed record remains unchanged. `begin_drain` keeps
admission closed even when a later record cannot transition. Existing autonomous
expiry inside `cancel_run` is preserved, including its existing error
classification after a successful expiry transition. No all-batch rollback or
claim that every compound-operation error leaves all state unchanged is added.

Eight regressions cover public recovered uncertainty, the last valid revision,
ACK-deadline overflow and its last valid value, bounded internal revision
exhaustion, and partial batch completion. The pre-dispatch exhaustion fixtures
are explicitly internal boundary injections, not ordinary public call traces.

## B. Bounded adaptation: preserve frozen evaluation and terminal decisions

### Authenticate both complete plans before consuming holdout

The original runner compared caller-supplied digest fields with the frozen plan,
then consumed the final holdout and invoked its release callback. The lower
temporal estimator only subsequently recomputed the plan contents. Retaining an
old digest while changing a fold, OPE, or confidence field therefore spent the
holdout before rejection.

Both complete canonical digests are now checked before provider inspection,
holdout consumption, or release. The regression mutates three field classes in
each arm, checks the complete owner anchor and zero releases, then successfully
uses the unchanged plan on the same owner. These six cases are one loop-based
test, not six independent test processes.

### Seal the complete qualification decision

The original qualification seal bound the opaque decision evidence digest but
omitted public decision lineage, disposition, and failed metrics. A consumer
could therefore receive a relabelled qualification whose original seal still
validated and then read the changed eligibility label.

The qualification digest now binds every decision field, including evaluation,
candidate and baseline identity, disposition, and failed metrics. Existing trust,
authentication, publication, principals, context, and DENY_ALL bindings remain.
The qualification evidence domain advances from v3 to v4 and its receipt seal
from v1 to v2. Downstream candidate signatures bind the new evidence identity.
There is no acceptance fallback for an old, incompletely bound seal, and this
change does not authorize re-consuming an already used final holdout.

The consumer regression first obtains an actually signed Ineligible fixture,
confirms its ordinary rejection, and changes only its public disposition while
retaining signatures, failed metrics and evidence. The current implementation
must reject before any of seven shadow host ports, before a durable Decision
append, and without changing closed ledger bytes. This concerns shadow
eligibility and Decision persistence; it is not evidence of external-effect or
release authorization being bypassed in a deployed system.

## C. Governed lifecycle: preserve the mandatory public refusal

Both public topology apply and recovery enter the same mandatory admission
before grant consumption, state-adapter reads, or migration callbacks. Until the
complete Control lifecycle owner is implemented, they return the typed
`CellLifecycleAdmissionUnavailable` error. Control, Cognitive, Learning and
Evidence role labels cannot clear this hold. Recovery from a stopped fixture
host remains refused. Private process-local FinalUse, migration, generation and
canary positive controls remain separate and unchanged.

The imported implementation map and generated status now describe this actual
public DENY_ALL behavior. They do not treat private mechanism tests as public
lifecycle activation or physical-host recovery evidence.

## Qualification and remaining work

Source review, patch applicability, object hashes and merge-parent verification
are recorded separately from native execution. Native qualification requires the
repository-pinned Rust 1.96.0, the original `just test` entry, the four changed
packages, isolated negative controls, and the original platform CI. Formatting,
lint, compilation, test execution and real product qualification are distinct
results. A queued or skipped job is not a pass.

These changes do not close the following product requirements:

- A real goal-to-App-Server-to-authorized-effect-to-terminal task, including
  durable evidence and process restart on the same implementation composition.
- Persistent recovery of the Intelligence pending Decision/Outcome append and
  current trust/provider reconciliation in the actual product host.
- Complete sealed-receipt ingress across existing signed evaluation and
  self-evolution callers, followed by independently evidenced selection.
- Same-information, comparable-budget strong baselines; complete failed-candidate,
  planner, critic, training and execution costs; and independent held-out outcomes.
  A source safety fix provides no NDU/Neuron net-benefit evidence. No-update and
  the accepted predecessor remain required when efficacy admission fails.
- A single durable Control owner for addition, replacement, splitting, merging,
  retirement and rewiring: bounded candidate identity, independent qualification,
  phase authority, old-writer fencing, migration and outbox receipts, consumer
  cutover, durable CNS CAS/readback, current generation and revocation floors,
  new-writer readiness, and verified rollback/recovery. Unknown effects retain
  their original operation identity and cannot become permission to redispatch.
- Original Windows isolation and other platform failures, physical device
  qualification, independent acceptance, promotion and release.

The branch remains a reviewable draft until its actual required evidence exists.
