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

`with_canonical_intelligence_profile` atomically installs runner and host-owned
invocation provider. Request bytes cannot install factories, policy owners,
model state or trust. Runner-only configuration advertises no canonical profile.

The current daemon route is:

```text
signed ObjectiveStart -> durable RunStart
-> host-owned provider.build -> canonical owner preparation
-> current RunStart/Fleet check -> bound run admission -> ContextAttached
```

The ordinary CLI does not supply an authorized executable seven-owner factory.
An embedding can now install `AgentdIntelligenceExecutionHostV1` with
`with_intelligence_execution_host` after the guarded canonical profile. The
normal authenticated ObjectiveStart invokes that host after ContextAttached.
`NativeIntelligenceProductEmbeddingV1` is the concrete adapter over the existing
native journal, App Server driver and learning host. It acknowledges the exact
Decision (including its witness) before send, obtains the same run's physical
terminal and asks existing independent evidence owners for the Outcome.
The ordinary CLI installs none of these authority-bearing owner objects.
Source wiring is not a real-process provider-E2E or activation receipt.

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

## 4. Mutable DTO and prepared-object boundaries

`validate_canonical_outcome_v1` rebuilds the legal set and verifies run/snapshot,
nested decision, positive selected propensity and terminal variant. It rehashes
the advisory decision, context binding and every envelope dependency. Changing
to another legal member cannot retain the prior decision/envelope digest.

`PreparedAgentdIntelligenceRunV1::validate_integrity` additionally compares public
fields against its private frozen context attachment and run snapshot. The
formal learning adapters call this gate. It is not a signature or runtime grant.

## 5. Formal learning ownership and time

Default-build APIs use only `LedgerWriter`. The durable learning host preserves
an immutable schema-V2 sidecar, then publishes the existing operations intent.
Decision, Outcome and their original ledger predecessors remain separate.
Payload encoding and historical digest domains are retained after the codec
split into `intelligence_learning_payload.rs`.

Historical event time is Unix milliseconds, stored unchanged in `now`. Enqueue
and each actual application use a fresh host verification clock, including
principal/evidence expiry checks. An event queued before expiry cannot be first
applied after expiry merely by reusing its historical timestamp. Clock rollback
remains indeterminate rather than being normalized to an earlier valid instant.

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
future cannot cancel supervision. Explicit cognition hard-timeout policy exits
code 70 only after its configured grace.

Cognition and final currentness reads share the remaining monotonic budget.
Durable operation Unix timestamps come from the injected
`DurableOperationClock` only after SQLite grants `BEGIN IMMEDIATE`; this keeps
writer ordering deterministic without clamping a real clock rollback. Typed
`RecoveryDisposition` prevents unavailable commits and provider-entered states
from being reinterpreted as immediate retry.
Input factory work is inside the same supervised bounded-worker lifetime and
uses the earlier of its host budget and durable deadline. Learning grant,
payload and `LedgerWriter` work runs outside Tokio control threads with four
actual-worker permits and a 30-second caller budget. A dropped or timed-out
receiver cannot release the live worker's permit.

Every learning-I/O worker now also owns an independent OS-thread watchdog.
Returning `IoIndeterminate` at the 30-second caller budget does not release the
worker or infer destination failure. If that exact worker is still alive after
the additional 30-second hard-timeout grace, the watchdog exits the fenced
Agentd process with code 70. The durable operation remains unsettled; only the
successor Supervisor generation may adopt it and perform destination-first exact
reconciliation. A child-process regression proves that a real non-returning
worker reaches the exit boundary. Target-host Supervisor replacement and
generation-adoption measurements remain separate execution evidence.

The concrete native embedding serializes its one existing execution journal and
bounds independent evidence workers; Busy preserves the original run identity.

Recovery walks stable `(scope_id, operation_id)` pages. It has a separate budget
from ordinary dispatch; a one-slot profile alternates. Grant-provider failure
before authorization may defer only an exact live Prepared claim. Unknown or
already-dispatching effects remain reconcile-only. See the
[restart contract](RESTART_RECONCILIATION.md) for state distinctions.

## 8. Files and currentness

Authority and sidecar reads walk every absolute-path component through
no-follow directory handles. The leaf is opened no-follow and nonblocking before
same-handle type, mode, link-count and byte-bound checks; parent/leaf symlinks,
hard links and oversized inputs are rejected. Non-Unix profiles without this
handle contract fail closed. Immutable payload publication remains no-replace.
The entire seven-owner manifest is validated and strictly signature-verified
before advancing the independently retained rollback floor. Signature alone
is not currentness. Privileged replacement of the separately retained host root,
write-side crash/orphan cleanup and target-host restore cuts remain acceptance
requirements, not inferred from read-side unit tests.

## 9. Observability and exact qualification

The profile digest uses `hepta.agentd.intelligence-capability-profile.v2`,
length-prefixed variable fields and full timeout precision. It binds a
configuration, not deployment authority. Telemetry includes actual worker,
timeout, stage, currentness, advisory and run-dwell measurements; target-host
latency/RSS and task-quality evidence remain absent until measured.

The tracked implementation/test JSON files are reviewed declarations with
`CI_EXACT_HEAD` and `pending`, not mutable cached CI facts. The status script
validates their source/test references. An exact passing projection requires
all command records, checkout identity, matching raw log hashes, successful exit
codes and the mapped tests observed passing in their correct package/profile.
Qualification-only tests remain separate. Native command failures stay failures.

The independent Linux workflow preserves source-head and deterministic merge
lanes and adds operation-owner tests. `scripts/hepta-intelligence-acceptance.py`
groups the reviewed declarations into the five A-D acceptance objectives and
admits an `ACCEPTANCE_RECEIPT.json` only after the same exact command records
have passed and the two new learning-I/O containment tests are observed in the
default Agentd log. Supplementary read-only native diagnostics may generate a
formatter patch in a separate worktree; they do not alter source, self-merge or
replace mandatory checks.

## 10. Acceptance still required

Supply and qualify the real embedding's authenticated owner/evidence sources.
Execute the normal ObjectiveStart-to-provider-to-Outcome path across every
process-loss and acknowledgement boundary on the exact candidate. Measure the
Supervisor replacement and successor-generation adoption that follow exit 70,
write-side root replacement/backup/orphan behavior, target-host latency, RSS,
saturation and task-quality baselines. Independent semantic/security and
operator acceptance remain separate. No missing observation is invented to
satisfy these gates, and source/test presence is not execution evidence.

## 11. Independent authority-manifest rollback floor

The canonical runner requires a host-owned
`IntelligenceAuthorityRollbackGuardV1` before runner/provider composition can be
advertised or executed. The witness is retained outside the Agent home and run
roots, holds a single-process lock, and durably records the greatest admitted
authority epoch together with the exact signed-manifest digest. Lower epochs and
same-epoch byte substitution fail closed after reopen. Signature verification
still occurs on every use; the rollback record grants no authority and cannot
replace current owner, key, epoch, or revocation checks.

This closes the repository-owned signed-backup replay primitive. Target-host
backup separation, privileged host-root replacement, process-crash injection,
independent security review and activation remain separate evidence gates.

## 12. Embedding assembly and outcome semantics

The authorized application composes existing objects, in this order:

```rust,ignore
let config = config.with_canonical_intelligence_profile(runner, authorized_factory)?;
let product = NativeIntelligenceProductHostV1::new(driver, agentd_client, learning_host);
let completion = NativeIntelligenceProductEmbeddingV1::new(
    product, existing_native_journal, independent_evidence_source,
    running_generation, cancellation,
)?;
let config = config.with_intelligence_execution_host(Arc::new(completion))?;
```

`runner` already carries the independently supplied evaluation trust and separate
rollback guard. `authorized_factory` reads the actual seven owners;
`independent_evidence_source` supplies signed Decision/Outcome support from the
existing evidence owners. This example does not create keys or synthetic facts.
The existing Agentd startup then owns this configuration; the facade owns no
new store, execution kernel or source of learning truth.

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
HEAD, lane, command/log digests, the observed mapped tests and the two direct
learning-I/O watchdog tests. It deliberately keeps real-provider E2E,
target-host qualification, independent acceptance, activation and release
false. Those facts require their own immutable external evidence.
