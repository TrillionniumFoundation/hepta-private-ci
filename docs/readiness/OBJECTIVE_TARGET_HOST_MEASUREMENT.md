# objective.compiler selected target-host measurement

**Normative execution contract:** `docs/modules/objective.compiler/NORMATIVE_EXECUTION.md`  
**Evidence procedure:** `docs/modules/objective.compiler/DELIVERY_EVIDENCE.md`

This document specifies how to measure `objective.compiler` on a selected host.
It does not select a host, approve resource/storage policy, activate a deployment
or issue release authority.

## 1. Trust and runner requirements

The workflow definition used for an authoritative selected-host run must come from
protected `main` at an immutable workflow SHA. Candidate code and trusted-control
code use separate workspaces.

Candidate execution is routed only to a runner with labels:

```text
self-hosted
objective-target-host
ephemeral
```

The target infrastructure owner must independently establish that the runner:

- was provisioned for one workflow job;
- had no prior candidate workspace or writable shared cache;
- received no reusable repository or deployment credential;
- used job-local `CARGO_HOME` and `CARGO_TARGET_DIR`;
- exposed the registered host profile and storage namespace;
- was destroyed or cryptographically reset after the job.

Labels are routing metadata, not lifecycle attestation. A persistent runner with
an `ephemeral` label does not satisfy this contract.

## 2. Candidate binding

Before build or measurement, record and verify:

```text
candidate commit
candidate tree
protected trusted-control workflow commit/tree
host profile identifier
workflow run id and attempt
runner name and environment
filesystem and storage profile identifiers
Rust and Cargo versions
```

The candidate checkout must be clean and credential-free. The complete commit and
tree must match the candidate admitted by exact source-head and deterministic
synthetic-merge evidence. A short SHA, moving branch name or nearby parent is not
acceptable.

## 3. Product path under measurement

The ordinary product fixture follows:

```text
ObjectiveRuntimeHost::open
-> one ValidatedAdmissionProfileV1 construction
-> signed AuthBus ObjectiveStart
-> request-local authenticated ObjectiveAdmissionContextV1
-> compile_authoritative_objective_v1
-> ProofBearingObjectiveCompileV1
-> encode_proof_bearing_objective_function_v1
-> compile_and_publish_validated_objective_run_v1
-> destination-owned RunStart V3 append or conflict V2 append
-> external checkpoint CAS
-> Agentd final trust/deadline/generation/fence checks
-> canonical handoff or explicit abstain
```

The measurement must not substitute raw-profile admission, the compatibility
encoder, qualification-only legacy compile or a fake journal for the ordinary
product fixture.

## 4. Workloads

### 4.1 Cold profile validation

Measure bounded JSON decode, complete profile validation, profile digest,
source-index construction and semantic-collision proofs for a fresh
`ValidatedAdmissionProfileV1`.

### 4.2 Warm authenticated admission

Reuse only the immutable validated profile. Every sample constructs a fresh
source and authenticated context and rechecks source identity, scope,
intent/schema/normalization, locale, freshness, exact deadline and selected
profile.

### 4.3 Native deterministic compile

Measure source lowering, generated resource/risk rows, feasibility and native
semantic/conflict digest materialization. Do not include build or executable
discovery.

### 4.4 Protocol projection

Measure proof-bound canonical `ObjectiveFunctionV1` encode plus strict decode.
The native semantic digest and protocol digest must both be retained and must not
be conflated.

### 4.5 Maximum conflict extraction

Use the registered 256-atom/257-call boundary. Retain the actual oracle-call count,
conflict identity and inclusion-minimality checks. Exhaustion must not be relabelled
as infeasibility.

### 4.6 Signed product ingress

Exercise real signed Agentd ingress, owner clock sampling, destination append,
checkpoint publication and handoff. Durable append/checkpoint/handoff remain one
observable atomic phase unless the implementation exposes separately committed
facts.

### 4.7 Physical execution fixture

Run only when the selected host is enrolled for the downstream execution owner.
Retain durable dispatch, exactly one physical send, terminal or indeterminate
observation and exact retry without resend. A mock provider can prove process
wiring and idempotency, not real provider quality or deployment acceptance.

## 5. Native artifact selection V2

The recorder performs Cargo build/discovery before resource sampling:

1. run `cargo test --no-run` with JSON compiler-artifact output;
2. identify exactly one package target/executable for the named fixture;
3. reject missing, duplicate, ambiguous or symlinked candidates;
4. retain executable size and SHA-256 plus build transcript digest;
5. run the exact executable with `--list` and resolve exactly one test name;
6. hash the executable again before direct `--exact` execution;
7. hash it again after execution;
8. reject any artifact or source-tree drift.

Target-folder glob selection and caller-supplied success flags are prohibited.
Build, listing, hashing and discovery are excluded from fixture resource samples
but retained as provenance.

## 6. Samples and order

The selected host authority chooses sample counts before execution. Defaults in
the workflow are development starting points, not acceptance thresholds:

```text
ordinary authenticated samples: 1000
maximum-conflict samples: 64
signed product samples: 32
physical execution samples: 4
```

Fixture order must be deterministic and retained. Warmup samples, if any, are
identified separately and excluded consistently. Failed and timed-out samples are
retained rather than discarded from percentiles.

## 7. Resource observations

Each fixture executes under a fresh helper process. Record:

- wall duration;
- user and system CPU;
- OS-reported waited-child peak RSS;
- page faults;
- voluntary and involuntary context switches;
- exit status and output digest.

Peak RSS is a high-water observation for the waited process tree. It is not the
sum of simultaneously live descendant RSS and not a per-phase allocator profile.
Internal phase timings may be reported separately but cannot be represented as
independent commits or resource owners where the product has one atomic boundary.

## 8. Storage observations

The measurement envelope records filesystem and checkpoint identities, segment
sizes, append growth and compaction observations. It does not by itself establish
storage durability.

The storage authority must separately perform destructive cases including:

- storage-full and sync failure;
- crash before/after checkpoint CAS;
- acknowledgement loss;
- active-tail tear;
- sealed-segment removal or rewrite;
- checkpoint rollback/ahead state;
- competing writer during rotation/compaction;
- long-running growth and backpressure.

The independently issued storage qualification digest is required by the target
host release receipt.

## 9. Raw execution and trusted verification

The ephemeral candidate job produces raw measurement bytes with no acceptance
claim. A separate GitHub-hosted job:

- checks out trusted control from the protected workflow SHA;
- checks out the candidate as read-only data;
- downloads the exact raw artifact from the same run/attempt;
- verifies candidate commit/tree, workload identities, executable hashes and raw
  receipt integrity using trusted-control code;
- produces the evidence projection and measurement envelope;
- retains a bundle digest and trusted-control identity.

Candidate-owned projector or release-verifier code is not authoritative.

## 10. Provenance attestation

Where repository settings support GitHub artifact attestations, the trusted job
attests the verified bundle manifest using a pinned
`actions/attest-build-provenance` action and job-scoped `id-token: write` /
`attestations: write` permission. The candidate measurement job receives neither
permission.

The attestation proves provenance of the exact verified bytes. It does not approve
resource policy, storage durability, canary or release.

## 11. Output schema

The verified envelope binds at least:

```text
schema/version/module
candidate commit/tree
trusted-control commit/tree
host profile id
workflow run/attempt
runner identity and ephemeral-lifecycle attestation digest
workload and sample counts
build/list/execute argv and transcript digests
native executable/test identities
phase distributions
resource observations
measurement bundle digest
storage qualification status
resource-policy acceptance status
activation/release false
```

An unsigned target-host receipt template remains `accepted=false`. Only the
owning target-host and storage authorities may populate acceptance fields and
issue the dependency-bound external receipt.

## 12. Acceptance boundary

A measured run is not selected-host acceptance until all are true:

- exact source-head and synthetic-merge receipts bind the same candidate;
- trusted-control verification succeeds;
- ephemeral runner lifecycle is independently attested;
- registered host profile and workload are correct;
- resource budgets are reviewed and accepted by the owner;
- destructive storage qualification is accepted;
- no unresolved independent semantic/security finding remains.

Even then, canary, rollback, promotion and release remain later gates. Missing,
queued, cancelled, failed or previous-candidate observations remain non-passes.
