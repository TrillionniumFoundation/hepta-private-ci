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
The current ObjectiveStart caller also does not itself join formal Decision
publication, physical `run_intelligence` execution and terminal Outcome creation.
Those are repository-controlled integration obligations, not a completed product
loop inferred from two endpoint APIs.

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

Prompt portfolio receipt linkage is not yet prompt realization delivery.
Authorized realization contents, roles, permissions and the selected action
must still produce the actual context and physical request. This remains an
explicit semantic gap; a linear receipt chain cannot establish an absent
input dependency or justify fabricated content.

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
also requires the independent ledger witness; catch-up/acknowledgement of a
ledger-present but unwitnessed event remains an acceptance gap.

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

Each computation retains a slot through actual completion. A worker-owned
completion guard starts an independent OS-thread watchdog before the work and
joins it before releasing capacity. Dropping/aborting the request future cannot
cancel supervision. Explicit hard-timeout policy exits code 70 only after its
configured grace; Supervisor replacement and durable recovery require separate
real-process evidence.

Cognition and final currentness reads share the remaining monotonic budget.
Input factory work and synchronous learning grant/file/writer work are not yet
covered by a complete independent lifetime; they must not be called fully bounded.

Recovery walks stable `(scope_id, operation_id)` pages. It has a separate budget
from ordinary dispatch; a one-slot profile alternates. Grant-provider failure
before authorization may defer only an exact live Prepared claim. Unknown or
already-dispatching effects remain reconcile-only. See the
[restart contract](RESTART_RECONCILIATION.md) for state distinctions.

## 8. Files and currentness

Sidecar reads verify the opened regular file and cap actual bytes; immutable
publication uses no-replace hard-link installation. Signed authority manifests
are read with an actual byte cap and strict Ed25519 verification. Unix reads
compare opened device/inode and reject group/world-writable objects.

These are not a complete parent-anchored no-follow/nonblocking open protocol.
Nor does a valid signature prove that a restored old manifest is current.
An independently maintained authority rollback floor, parent-directory identity,
concurrent replacement tests and crash/orphan recovery still need qualification.

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
lanes and adds operation-owner tests. Supplementary read-only native diagnostics
may generate a formatter patch in a separate worktree; they do not alter source,
self-merge or replace mandatory checks.

## 10. Acceptance still required

Complete actual stage-to-context/request materialization and an authorized
executable host; enforce Decision-before-dispatch and terminal Outcome/witness
recovery; close factory/learning-I/O supervision and rollback-safe file access;
execute current source/merge native checks and process crash cuts; measure
latency, memory, recovery saturation and task quality against baselines; obtain
independent security/semantic and operator acceptance. None is certified by
source presence, a test function name or a queued workflow.
