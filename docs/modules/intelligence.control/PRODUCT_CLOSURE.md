# intelligence.control product composition

Parent: [TECHNICAL.md](TECHNICAL.md). This is the effective product composition
contract, not an activation or release receipt. The facade remains ephemeral;
Agentd owns orchestration, App Server owns physical execution, kernel.operations
owns intent/outbox state and learning.ledger owns authenticated learning facts.

## 1. Exact durable identity

`AgentdIntelligenceRunIdentityV1::from_run_start` derives request/run/body/artifact,
authority, deadline, generation and fence from the complete durable
`RunStartRecordV1`. The request digest binds authentication, source/profile,
objective/model/prompt/artifact identities and semantic bytes.

```text
spawn generation = physical process launch
Running generation = spawn + 1
Draining generation = spawn + 2
```

`objective_run_fence_digest_v1` is shared by publication, invocation and bound
coordinator admission. A cognition factory may not replace this identity.
Compatibility `start_run` is not canonical product admission.

## 2. Host configuration and the actual route

There are two intentionally distinct host composition APIs.

`with_canonical_intelligence_profile` atomically installs the runner and the
host-owned invocation provider. This is a prepare-only profile. The runner must
already carry both the independently retained authority rollback guard and a
nonzero process hard-timeout fence. Request bytes cannot install factories,
policy owners, model state or trust.

`AgentdCanonicalIntelligenceProductionProfileV1` is the production composition
boundary. Its constructor accepts exactly four existing owner objects:

```text
canonical runner
+ host-owned seven-owner invocation factory
+ physical execution host
+ durable learning reconciliation runtime
```

`install` either installs all four or returns no modified configuration. It also
emits `AgentdCanonicalIntelligenceCompositionReceiptV1`, whose digest binds the
full source commit, Agent identity, spawn and Running generations, capability
profile digest, execution-owner generation and learning-owner generation. The
receipt identifies the installed composition; it grants no runtime, deployment,
activation or release authority.

Agentd startup independently calls `validate_runtime_profile_shape`. It accepts
only three shapes:

```text
no canonical profile
runner + provider                 # prepare-only
runner + provider + execution + learning   # production
```

Runner/provider and execution/learning half-profiles fail closed before runtime
state or App Server tasks are created. A configured canonical product can no
longer silently become compatibility mode because one half was omitted.

The authenticated route is:

```text
signed ObjectiveStart -> durable RunStart
-> host-owned provider.build -> canonical owner preparation
-> current RunStart/Fleet check -> bound run admission -> ContextAttached
-> configured physical execution host
-> Decision acknowledgement before send
-> exact physical terminal -> independently evidenced Outcome
```

The ordinary CLI still does not supply authorized live seven-owner or evidence
objects and therefore does not claim a default production composition. An
embedding must explicitly install the atomic production profile. Source wiring
is not a real-process provider-E2E, target-host or activation receipt.

An actual embedding must obtain every input and signed evaluation from its
existing authorized owner. No sample implementation may invent live observations,
self-sign evaluator acceptance or use test-only legacy writes as the product.

## 3. Owner output flow

The canonical order remains objective, NDU, neuron, prompt, intuition, context,
evaluation. NDU evaluates the admitted candidate universe plus its required
reserved abstain entry. The actual NDU result binds the neuron tick; the actual
neuron checkpoint binds intuition's state. Nonzero conflicting precomputed
bindings are rejected, not overwritten. A zero host-template field is filled
before owner admission and does not become a new permissive wire grammar.

NDU-infeasible candidates cannot remain both legal and unvetoed in intuition.
Owner errors pass through timing measurement before rejection, so failure
latency is not silently omitted.

The physical profile consumes owner-constructed `PreparedPromptDeliveryV1`.
Its private source and admitted exercise bind materialization, serializer,
model profile and context attachment. Validation regenerates the serialization
proof from the actual byte payload, not just caller-supplied proof hashes.
The prompt stage retains this output; intuition binds both neural and prompt
state, and context uses that exact owner's attachment. Conflicting supplied
state is rejected. `physical_prompt()` accepts only this retained owner lineage.
Compatibility computation may omit delivery, but cannot then execute a physical
canonical request. Live producer quality and complete selected-action semantics
still require product conformance and independent task-quality measurements.

## 4. Mutable DTO, membership and prepared-object boundaries

`validate_canonical_outcome_v1` rebuilds the legal set and verifies run/snapshot,
nested decision, positive selected propensity and terminal variant. It rehashes
the advisory decision, context binding and every envelope dependency. Changing
to another legal member cannot retain the prior decision/envelope digest.

`AgentdLegalCandidateMembershipProofV1` makes the selected-member relation a
type boundary. Its fields are private and its constructor is crate-owned. The
constructor canonicalizes the candidate IDs and rejects an empty or oversized
set, duplicate members, a selected ID outside the set, zero propensity and a
zero set digest. The proof digest binds the canonical set, selected candidate and
propensity. Candidate order is therefore presentation only; membership identity
is permutation-invariant.

`PreparedAgentdIntelligenceRunV1::validate_integrity` compares public fields
against its private frozen context attachment and run snapshot, then consumes the
membership proof. `selected_candidate_membership()` exposes the inspected proof
to downstream product code without allowing callers to manufacture one. The
formal learning adapters call the same integrity gate. The proof is not a
signature or runtime grant.

## 5. Formal learning ownership, time and unknown commit state

Default-build APIs use only `LedgerWriter`. The durable learning host preserves
an immutable schema-V2 sidecar, then publishes the existing operations intent.
Decision, Outcome and their original ledger predecessors remain separate.
Payload encoding and historical digest domains are retained after the codec
split into `intelligence_learning_payload.rs`.

Fresh learning Decision construction adds the ledger's intrinsic `abstain` to
the sorted policy action IDs before verifying completeness and signatures.
Providers sign this inclusive universe (at most 127 actions plus abstention),
while canonical/evaluation evidence continues to bind the original action set.
Reserved-ID collisions, duplicate actions and overflow fail closed. The adapter
never fills in a provider's missing completeness proof. Persisted payloads are
reconstructed exactly as stored, without adding candidates during recovery.

Historical event time is Unix milliseconds, stored unchanged in `now`. Enqueue
and each actual application use a fresh host verification clock, including
principal/evidence expiry checks. An event queued before expiry cannot be first
applied after expiry merely by reusing its historical timestamp. Clock rollback
remains unknown rather than being normalized to an earlier valid instant.

`AgentdIntelligenceCommitStateV1` projects the destination observation into four
explicit states:

```text
Applied
NotApplied
Quarantined
UnknownCommittedState
```

`UnknownCommittedState` is deliberately non-terminal. It is never interpreted as
not-started, never permits a new idempotency identity and never authorizes an
external redispatch. A second or later ambiguous reconciliation leaves the
original durable operation and its proof material unsettled; it does not erase
or downgrade the pending record.

Exact destination observation precedes requesting new write authority. Historical
observation is not active learning evidence or effect replay. Complete recovery
also requires the independent ledger witness. `LedgerWriter::reconcile_exact_event_v1`
compares the complete event and original predecessor using the owner's index.
It acknowledges a witnessed prefix or repairs only the exact unwitnessed last
record through the owner's existing idempotent commit path. It never appends a
missing event. A real file-backed test covers missing/changed events, predecessor
substitution, witnessed-prefix observation and last-record witness catch-up.
Full daemon crash-cut qualification remains separate.

## 6. Physical terminal binding

The support digest binds run identity, private context attachment, envelope,
advisory decision, selected candidate/propensity, terminal Agentd phase/revision
and provider terminal digest. The Outcome must bind the same Decision and episode.
A model return, queue acknowledgement or nonterminal observation cannot create
a terminal Outcome.

The existing `AppServerModelDriver::run_intelligence` accepts an exact Agentd
context/envelope binding and preserves durable no-redispatch semantics. The
embedding must still bind the actual delivered request to the selected context
and produce independently authenticated terminal learning evidence.

## 7. Worker and recovery bounds

Each cognition computation retains a slot through actual completion. A
worker-owned completion guard starts an independent OS-thread watchdog before
the work and joins it before releasing capacity. Dropping or aborting the request
future cannot cancel supervision. The canonical product profile requires a
nonzero cognition hard-timeout grace and exits code 70 if work survives that
grace. Compatibility-only direct preparation may omit the hard fence, but cannot
be advertised as `intelligence.canonical_v1`.

Cognition and final currentness reads share the remaining monotonic budget.
Durable operation Unix timestamps come from the injected
`DurableOperationClock` only after SQLite grants `BEGIN IMMEDIATE`; this keeps
writer ordering deterministic without clamping a real clock rollback. Typed
`RecoveryDisposition` prevents unavailable commits and provider-entered states
from being reinterpreted as immediate retry. Input factory work is inside the
same supervised bounded-worker lifetime and uses the earlier of its host budget
and durable deadline. Learning grant, payload and `LedgerWriter` work runs
outside Tokio control threads with four actual-worker permits and a 30-second
caller budget. A dropped or timed-out receiver cannot release the live worker's
permit.

Every learning-I/O worker also owns an independent OS-thread watchdog. Returning
`IoIndeterminate` at the caller budget does not release the worker or infer
destination failure. If that exact worker is still alive after the additional
hard-timeout grace, the watchdog exits the fenced Agentd process with code 70.
The durable operation remains unsettled; only the successor Supervisor generation
may adopt it and perform destination-first exact reconciliation. A child-process
regression proves that a real non-returning worker reaches the exit boundary.
Target-host Supervisor replacement and generation-adoption measurements remain
separate execution evidence.

The concrete native embedding serializes its one existing execution journal and
bounds independent evidence workers; Busy preserves the original run identity.

Recovery walks stable `(scope_id, operation_id)` pages. It has a separate budget
from ordinary dispatch; a one-slot profile alternates. Grant-provider failure
before authorization may defer only an exact live Prepared claim. Unknown or
already-dispatching effects remain reconcile-only. See the
[restart contract](RESTART_RECONCILIATION.md) for state distinctions.

## 8. Files and fence-scoped currentness

Authority and sidecar reads walk every absolute-path component through no-follow
directory handles. The leaf is opened no-follow and nonblocking before same-handle
type, mode, link-count and byte-bound checks; parent/leaf symlinks, hard links and
oversized inputs are rejected. Non-Unix profiles without this handle contract
fail closed. Immutable payload publication remains no-replace.

`CanonicalFreshnessOracleV1::refresh_snapshot` defines one currentness fence.
The file-backed oracle performs one bounded open/read/parse, one strict Ed25519
verification, one complete seven-owner-universe validation and one durable
anti-rollback admission. All owner lookups within that fence read the resulting
immutable map. The next fence forces a new file read and signature check.

This optimization does not turn currentness into a run-long cache. Every owner
still has a distinct pre-call and post-call fence, and the final product handoff
uses another aggregate fence. A generation, implementation, key, authority epoch
or revocation-frontier change between those boundaries therefore still fails
closed, while the seven-owner final fence no longer repeats the same complete
manifest work seven times.

The independently retained rollback floor records the greatest admitted authority
epoch together with the exact signed-manifest digest. Lower epochs and same-epoch
byte substitution fail closed after reopen. Signature verification still occurs
at every fence; the rollback record grants no authority and cannot replace
current owner, key, epoch or revocation checks.

Privileged replacement of the separately retained host root, write-side
crash/orphan cleanup and target-host restore cuts remain acceptance requirements,
not inferred from read-side unit tests.

## 9. Observability and exact qualification

The profile digest uses `hepta.agentd.intelligence-capability-profile.v2`,
length-prefixed variable fields, rollback identity and full timeout precision.
The production composition receipt additionally binds source commit, agent/process
generation and both physical owner generations. Neither digest grants deployment
authority.

Telemetry includes actual worker, timeout, stage, currentness, advisory and
run-dwell measurements. The operational metric set includes owner-stage wall
time, queue wait, permit hold, timed-out-but-still-running workers, authority
manifest observations, pending ambiguous append age, reconciliation attempts,
candidate cardinality and abstain/slow-path counts. Target-host latency, RSS, CPU,
signature cost, hard-kill time and task-quality evidence remain absent until
measured on the named host and exact candidate.

The tracked implementation/test JSON files are reviewed declarations with
`CI_EXACT_HEAD` and `pending`, not mutable cached CI facts. The status script
validates their source/test references. An exact passing projection requires all
command records, checkout identity, matching raw log hashes, successful exit
codes and the mapped tests observed passing in their correct package/profile.
Qualification-only tests remain separate. Native command failures stay failures.

The independent Linux workflow preserves source-head and deterministic merge
lanes and adds operation-owner tests. `scripts/hepta-intelligence-acceptance.py`
groups the reviewed declarations into the five A-D acceptance objectives and
admits an `ACCEPTANCE_RECEIPT.json` only after the same exact command records
have passed. Supplementary diagnostics may produce artifacts in a separate
worktree; they do not alter source, self-merge or replace mandatory checks.

## 10. Acceptance still required

Supply and qualify the real embedding's authenticated owner/evidence sources.
Execute the normal ObjectiveStart-to-provider-to-Outcome path across every
process-loss and acknowledgement boundary on the exact candidate. Measure the
Supervisor replacement and successor-generation adoption that follow exit 70,
write-side root replacement/backup/orphan behavior, target-host latency, RSS,
CPU, signature verification cost, saturation, recovery, hard-kill time and task
quality. Independent semantic/security and operator acceptance remain separate.
No missing observation is invented to satisfy these gates, and source/test
presence is not execution evidence.

## 11. Independent authority-manifest rollback floor

The canonical runner requires both a host-owned
`IntelligenceAuthorityRollbackGuardV1` and a process hard-timeout fence before
runner/provider composition can be advertised or executed. The witness is
retained outside the Agent home and run roots, holds a single-process lock and
durably records the greatest admitted authority epoch together with the exact
signed-manifest digest. Lower epochs and same-epoch byte substitution fail closed
after reopen.

This closes the repository-owned signed-backup replay primitive and product
containment precondition in source. Target-host backup separation, privileged
host-root replacement, process-crash injection, Supervisor replacement,
independent security review and activation remain separate evidence gates.

## 12. Embedding assembly and outcome semantics

The authorized application composes existing objects through the atomic
production profile:

```rust,ignore
let runner = runner
    .with_authority_rollback_guard(rollback_guard)?
    .with_hard_timeout_process_exit(hard_timeout_grace)?;
let execution = Arc::new(NativeIntelligenceProductEmbeddingV1::new(
    NativeIntelligenceProductHostV1::new(driver, agentd_client, learning_host),
    existing_native_journal,
    independent_evidence_source,
    running_generation,
    cancellation,
)?);
let profile = AgentdCanonicalIntelligenceProductionProfileV1::new(
    runner,
    authorized_factory,
    execution,
    learning_runtime,
    exact_source_commit,
)?;
let (config, composition_receipt) = profile.install(config)?;
```

`runner` carries independently supplied evaluation trust, rollback guard and
process hard-timeout fence. `authorized_factory` reads the actual seven owners;
`independent_evidence_source` supplies signed Decision/Outcome support from the
existing evidence owners. `learning_runtime` owns restart reconciliation for the
same Running generation. The example does not create keys or synthetic facts.
The existing Agentd startup owns this configuration; the facade owns no new
store, execution kernel or source of learning truth.

`canonical_ready` means the prepared route has no execution host attached.
`canonical_executed` means a real terminal observation and an acknowledged
Outcome; it does not mean the task succeeded. A failed/interrupted terminal can
also close an episode. `canonical_reconciliation_required` preserves uncertain
execution or missing learning acknowledgement. Learning/evidence/RPC failure
following terminal observation does not erase the native journal's observation
or authorize a new run ID or another provider call.

The rollback parent directory must be explicitly provisioned private by the host.
The guard opens it without following any path component; lock creation, record
reads, temporary creation and atomic record replacement all use that same open
directory. Uncertain write/fsync failure fences the guard until reopen rather
than reusing the old in-memory epoch. This does not make a full host backup an
independent rollback witness or grant an Agent permission to reset the floor.

## 13. Five-objective A-D acceptance contract

The repository-controlled acceptance order is fixed:

1. **A1 — cross-stage semantic closure:** actual owner outputs drive the next
   request identity; substitutions, foreign candidates and receipt-only lineage
   fail closed.
2. **A2 — current-time recovery closure:** historical event time remains
   immutable while first application and replay use the current trusted clock.
3. **B — single product execution closure:** authenticated ObjectiveStart,
   Decision-before-send, the existing App Server path, exact terminal receipt
   and independently authenticated Outcome remain one run-bound chain.
4. **C — bounded recovery and file closure:** worker permits, hard containment,
   fair reconciliation, exact pre-dispatch deferral, no-follow bounded files and
   the independent rollback floor share one failure model.
5. **D — exact-candidate acceptance:** source-head and deterministic base-merge
   lanes must retain all command records and an exact acceptance receipt.

The acceptance verifier reads the reviewed implementation/test declarations; it
does not discover completion from symbol names. A passed receipt binds checkout
HEAD, lane, command/log digests and observed mapped tests. It deliberately keeps
real-provider E2E, target-host qualification, independent acceptance, activation
and release false. Those facts require their own immutable external evidence.

## 14. Completion-state taxonomy

Every status surface must keep these facts separate:

| State | Meaning in this module |
| --- | --- |
| `source_present` | Ordinary source and declarations exist in the candidate tree. |
| `repo_native_composed` | The atomic production profile can install all four host-owned components and emit a commit-bound receipt. It does not mean the default CLI is configured. |
| `physically_executed` | The exact candidate completed the real ObjectiveStart → App Server → Decision/Outcome chain with retained process evidence. |
| `independently_qualified` | Independent semantic, security and operations evaluators accepted the exact receipts. |
| `activated` | An authorized deployment owner selected the qualified candidate. |
| `released` | Release authority published the activated candidate. |

At tracked-source time only the first two may be true, and
`repo_native_composed` is limited to the explicit production-profile API. The
ordinary CLI remains uncomposed. CI may project exact-head or deterministic-merge
execution into external artifacts, but it must not overwrite the tracked source
declaration or infer independent qualification, activation or release.
