# Objective compiler execution contract

**Normative status:** This document is the sole normative execution contract for
`objective.compiler`. Module guides, semantic matrices, qualification dossiers,
closeout notes and workflow descriptions may add explanation or evidence, but
they must reference this contract and must not define a competing product path.

**Bound modules:** `objective.compiler`, `intelligence.control`,
`runtime.agentd`, `learning.ledger`, `kernel.authority`

**Canonical error registry:** `docs/contracts/OBJECTIVE_ERRORS.json`

**Canonical implementation map:** `docs/modules/objective.compiler/IMPLEMENTATION_MAP.json`

## 1. Authority boundary

`objective.compiler` converts one bounded, authenticated structured request into
an immutable native objective or a typed hard conflict. It does not infer
authority from prose, relax a hard constraint, select an action, invoke a model,
dispatch a provider, execute an effect, activate a deployment, promote a
candidate or authorize release.

All compiler and publication artifacts have `AuthorityPosture::DENY_ALL`.
Authentication, current trust, revocation, generation, fence, deadline,
dispatch and final-use authority remain with their existing owners.

The compiler owns no durable objective database. The destination-owned
`RunStartJournal` is the sole durable owner of objective/run-start publication.

## 2. Canonical product path

<!-- BEGIN NORMATIVE OBJECTIVE PRODUCT PATH -->

```text
Agentd ObjectiveRuntimeHost::open
-> decode_admission_profile_json_v1
-> ValidatedAdmissionProfileV1::new
-> freeze exact profile digest, profile revision and compiler-contract digest

Agentd ObjectiveRuntimeHost::submit
-> authenticate the exact signed AuthBus body against current trust
-> decode_source_envelope_json_v1
-> construct a fresh ObjectiveAdmissionContextV1 from owner-observed time
-> compile_and_publish_validated_objective_run_v1
   -> compile_authoritative_objective_v1
      -> admit_validated_objective_v1
      -> compile_validated_objective_v1
      -> ProofBearingObjectiveCompileV1
   -> encode_proof_bearing_objective_function_v1
   -> destination-owned RunStartJournal
      -> RunStart record V3, or
      -> objective-conflict record V2
-> external monotonic checkpoint acknowledgement
-> current trust/deadline/generation/fence recheck
-> canonical intelligence handoff or explicit abstain
```

<!-- END NORMATIVE OBJECTIVE PRODUCT PATH -->

The canonical Agentd product façade is
`compile_and_publish_validated_objective_run_v1`. The raw-profile façade and
lower-level admission functions are compatibility or owner-internal surfaces;
they are not alternate production entrypoints.

One request performs one authoritative admission and one native compile.
Protocol projection must consume the proof-bearing result and must not solve the
same objective a second time. Independent recompilation is permitted only as a
qualification/differential reference.

## 3. Static profile reuse and request-local checks

`ValidatedAdmissionProfileV1` is immutable for one process generation. It owns:

- the validated raw profile;
- exact profile digest and revision;
- compiler-contract digest;
- indexes for constraints, predicates, actions, soft dimensions and evidence
  requirements;
- global semantic-identity collision proofs.

Only these static facts may be reused. The reuse key must not contain or cache:

- source authentication;
- owner-observed time;
- freshness or deadline decisions;
- current issuer trust or revocation;
- runtime generation or fence;
- final-use or effect authority.

Each submission must independently check the complete source identity,
principal scope, source trust class, schema, normalization profile, intent,
locale, freshness, deadline and selected profile. A profile label, caller-built
`ObjectiveAdmissionContextV1` or historical proof is not authentication.

Changing the profile requires a new process generation; the frozen profile is
never mutated in place.

## 4. Input and semantic contract

Ingress is bounded and versioned. Unknown critical fields, duplicate JSON keys,
oversize text or arrays, invalid identifiers, noncanonical timestamps and
unregistered semantics fail closed.

Source V1 numeric comparison uses exact signed Q32 values. Its lossless
end-to-end operators are:

- constraint: `eq`, `lte`, `gte`;
- success and terminal predicates: `eq`, `lte`, `gte`.

`ne`, `lt`, `gt`, `in` and `not_in` are deterministic `OBJ-E002` rejection in
Source V1. Generic typed feasibility support for finite enumeration,
immutable-identity equality or positive action implication does not broaden the
Source V1 wire contract.

The final native aggregate, not an individual source array, defines capacity:

- at most 246 source constraints plus six resource and four risk constraints;
- at most 256 native hard constraints;
- at most 128 combined success, terminal and evidence predicates;
- at most 128 compiled actions including intrinsic `abstain`;
- at most 127 caller legal actions in Source V1: its profile cannot map the
  reserved intrinsic `abstain` action, so the compiler always adds that action;
- at most 64 soft dimensions;
- at most 257 compatibility conflict-oracle calls.

No represented hard constraint, predicate, action, evidence requirement,
resource ceiling, risk rule, rollback rule or provenance identity may be
silently dropped or approximated.

The source and protocol structures can hold 128 action entries; that structural
limit does not authorize 128 mapped caller legal actions. The authoritative
native aggregate must still reserve one of its 128 slots for intrinsic
`abstain`.

Evidence confidence is expressed in integer ppm by Source V1. Its native lower
bound is `ceil(minimumConfidencePpm * 2^32 / 1_000_000)`, computed with checked
wide integer arithmetic. Rounding down would weaken a minimum confidence
requirement. Native lowering and both protocol encoders use this same
conservative bound while the wire retains the original ppm value.

## 5. Deterministic compilation

The semantic engine is a pure, bounded function of validated grammar, canonical
atoms and deterministic work budgets. Equal admitted inputs and budgets produce
equal native semantic bytes and digests.

Hard feasibility is lexicographic and noncompensable. Soft preferences never
offset a hard violation. An infeasible set yields a deterministic
inclusion-minimal conflict in canonical order; it does not claim minimum
cardinality.

The compatibility wall-time API observes elapsed host time only after bounded
deterministic work. It is not a hard preemption mechanism. Trusted runtime
owners implement deadline and cancellation around blocking work. Deterministic
budget exhaustion, owner cancellation and expired authorization must remain
distinct dispositions.

`abstain` is intrinsic, confirmation-free and cannot be forbidden. A legal set
containing no caller action may compile as `CompileDisposition::ExplicitAbstain`;
that is a typed non-error outcome and grants no effect authority.

## 6. Proof and protocol projection

`ObjectiveAdmissionProofV1` binds exactly five digests in this order:

1. complete source-envelope proof identity;
2. validated profile digest;
3. authenticated admission-context digest;
4. compiler-contract digest;
5. admitted native-source digest.

Its V1 canonical bytes are the domain
`hepta.objective.admission-proof.v1` followed by the five 32-byte digests. The
durable wrapper is historical integrity evidence, not a reconstructed compiler
capability and not current authorization.

`ProofBearingObjectiveCompileV1` is non-cloneable. Diagnostic preflight returns
`ObjectivePreflightReportV1`, which contains neither an admission proof nor a
publication token and cannot be promoted into authoritative publication without
a fresh owner-controlled admission.

At canonical ObjectiveStart handoff, the runner privately binds the existing
compiled RunStart record to the objective owner port. The constructor checks
the native semantic bytes and canonical protocol bytes against their stored
digests, strictly decodes the protocol revision, and rejects absent proof,
explicit abstention and authority grants. The port performs fresh frozen-profile
admission and compares exact source-envelope, profile, compiler-contract and
admitted-source identities with that publication before using its compiled
semantic identity. The fresh context revision must equal that persisted protocol
revision; changing the clock does not authorize changing objective semantics.
It does not perform another native solve or publish another
RunStart. A changed admission clock is fresh request-local evidence, not an
automatic rewrite of the historical authentication-context proof. Public
standalone preparation has no durable binding and retains diagnostic preflight.

`encode_proof_bearing_objective_function_v1` must rebind source-envelope and
frozen-profile identity, preserve native/source/receipt checks, produce exact
canonical `ObjectiveFunctionV1` bytes, decode those bytes strictly, and retain a
protocol-wire digest distinct from the native semantic digest.

Persisted proof verification currently establishes exact historical bytes,
digest integrity, profile binding, admitted-source binding and compiler-contract
binding. It does not by itself reconstruct current source authentication,
revocation or final-use permission. Documents and receipts must not claim more.

The conservative confidence correction changes the compiler-contract digest
through the `conservative-q32-confidence` contract tag. Historical RunStart
records bound to the predecessor compiler contract remain inspectable with their
original bytes, but fail the current Agentd final-use binding check. Migration
requires a newly authorized objective revision/request under the current
contract. Recovery, compaction and retries must not automatically upgrade the
proof, overwrite historical records or reuse predecessor execution authority.

Compiler-contract recovery and profile migration are different boundaries.
When the profile digest remains unchanged, startup can reopen the existing
destination owner, retain predecessor compiler proofs inert, and recover
current-contract records after all live checks. The mixed-proof fixture checks
this record-level filtering; manually included stale profile records do not
prove that a different configured profile can reopen the old owner.

The actual Agentd RunStart owner and external checkpoint bind the profile
digest. Changing the configured profile therefore fails `Host::open` with a
binding mismatch; it must not reset or rewrite that checkpoint, replay history
or historical proofs. A profile change requires a separately specified and
authorized destination-owner migration that preserves anti-rollback and
consumed-message identities. That migration is not implemented by the current
record-filtering recovery path.

## 7. Durable publication versions

The authoritative durable formats are:

- RunStart record domain `hepta.run-start-record.v3`;
- objective-conflict record domain `hepta.run-start-conflict.v2`;
- chain domain `hepta.run-start-chain.v1`.

Run V3 binds authenticated ingress, admission facts, canonical proof bytes and
digest, native semantic bytes and digest, canonical protocol bytes and digest,
run snapshot, predecessor chain and external checkpoint.

Conflict V2 binds the same authenticated admission proof and run identity to the
canonical conflict receipt; it creates no runtime snapshot.

Run V1/V2 and conflict V1 remain readable for historical inspection and
bounded recovery. Recovery and compaction must preserve their original bytes
and versions. They must not synthesize an admission proof or acquire execution
authority. Agentd final use rejects records that lack the current required proof
or do not match the current frozen profile/compiler contract.

Exact replay is idempotent only for the identical durable record. Reuse of a run
identity with different source, proof, native semantics, protocol bytes,
generation, fence or bindings is a conflict.

## 8. Transaction, replay and recovery

For a new publication, the owner serializes:

```text
replay admission
-> owner-observed admission time
-> authoritative compile/protocol projection
-> durable RunStart or conflict append
-> file synchronization
-> external checkpoint compare-and-swap
-> replay-frontier update
-> release of the writer guard
```

No runtime handoff is exposed before durable append and checkpoint
acknowledgement. A partial unacknowledged tail may be truncated only to the last
complete validated frame. Missing acknowledged history, stale or ahead
checkpoints, removed sealed segments, chain drift and rewritten proof bytes fail
closed.

Compaction may replace only complete expired sealed prefixes. It retains exact
deduplication/authentication identities and never promotes a historical record
to a newer version.

A canonical intelligence handoff after durable RunStart is a separate lifecycle
boundary. If it is not durably recoverable, the owner must expose the pending
state explicitly and must never silently redispatch or enter a compatibility
execution path.

The process spawn generation and the live Fleet lifecycle generation are
distinct. On the ordinary `Starting N -> Running N+1` transition, signed
ObjectiveStart publication, invocation validation, prepared runtime/context
bindings and final-use revalidation retain the exact durable `N+1` generation
and the fence over `(agent, spawn N, lifecycle N+1)`. The frozen process
composition remains the same owner; its spawn generation must not replace the
durable lifecycle generation. The worker computation budget separately bounds
preparation and cannot replace or extend the admitted deadline.

## 9. API and compatibility policy

The default product build must expose the validated-profile authoritative path.
Legacy raw compilation remains available only under the
`qualification-legacy-compile` Cargo feature.

Compatibility admission/projection APIs must be explicitly identified as
compatibility surfaces, covered by the same strict lint/test gates, and must not
be used by ordinary product callers. New production callers must enter through
Agentd and the validated publication façade.

The crate-internal raw compiler and opaque compiler-proof/result constructors
must not be constructible by downstream crates. A versioned historical
`RunStartAdmissionProofV1::from_canonical_bytes` decoder remains public: it
reconstructs historical integrity evidence, never an opaque compiler capability
or current authorization. A trusted journal owner can assemble self-consistent
historical bytes; that fact alone is not independent authenticated provenance.
The library's admission context is a trusted-caller boundary. Product ingress
must enter the signed Agentd route with current trust, its private frozen profile
and checkpoint ownership rather than treating a caller-built context as source
authentication. Public API changes require an additive versioned contract or an
explicit migration and retirement plan.

## 10. Error contract

`docs/contracts/OBJECTIVE_ERRORS.json` is the sole canonical error registry.
The required stable families are `OBJ-E001`, `OBJ-E002`, `OBJ-E003`, `OBJ-E004`,
`OBJ-E005`, `OBJ-E006`, `OBJ-E007`, `OBJ-E008` and `OBJ-E009`.

`OBJ-E007` is a family with variant-specific retry policy, not a blanket retry
instruction. A typed `ObjectiveConflictReceiptV1` and
`CompileDisposition::ExplicitAbstain` are non-error outcomes.

Rust variants, documentation and adapters must not assign local alternate
meanings to a registered code.

## 11. Qualification and trust separation

Source authoring, execution observation, independent acceptance, activation and
release are separate claims.

Exact-source and deterministic synthetic-merge qualification must:

- bind one immutable source commit/tree and one fixed merge base;
- execute the same declared command inventory;
- retain real argv, exit status and log hashes;
- fail on dirty source, missing/duplicate commands, timeout or interrupted work;
- never patch source, status files or receipts during qualification.

Protected release and target-host workflows must not execute a verifier loaded
from a caller-selected candidate. Trusted verification logic is obtained from a
protected ref or immutable reviewed artifact. Candidate code executes only in an
unprivileged build environment or a disposable target runner.

A persistent self-hosted runner is not an acceptable boundary for arbitrary
candidate execution. Target-host qualification requires an ephemeral runner,
no shared writable cache, no retained repository credentials, fixed artifact
digests and retained build provenance.

Source or CI cannot self-issue independent semantic/security review, target-host
resource acceptance, operator acceptance, canary success, rollback authority,
promotion or release approval.

## 12. Evidence chain and release order

The only valid order is:

```text
exact head
-> deterministic synthetic merge
-> selected target host
-> storage durability acceptance
-> independent semantic/security review
-> canary observation
-> rollback drill and authority
-> promotion approval
-> release authority
```

Every receipt is bound to the same immutable candidate commit/tree and to the
release-policy digest. Required distinct issuers remain distinct. Missing,
queued, cancelled, skipped, failed, historical or unsigned template material is
not a passing receipt.

Receipt hashes, predecessor links and distinct issuer labels establish
consistency only. The current repository verifier reports
`receiptAuthenticityVerified: false` and `externalAuthorityVerification: required`
even for a consistent chain, and keeps `releaseGranted` and release truth false.
Externally verifiable issuer/provenance authentication remains required before
an authority can rely on independent acceptance or release approval.

`CURRENT_STATE.json` remains static and fail-closed. Dynamic observations exist
only in the receipt-bound evidence projection. Until the complete authorized
receipt chain exists:

```text
productionImplementation = false
accepted = false
activated = false
released = false
```

## 13. Normative consistency gate

`scripts/hepta-objective-contract-consistency.py` validates this contract against
the current source tree. It checks:

- canonical API names and the production façade;
- RunStart V3 and conflict V2 domains;
- compatibility feature names;
- error families `OBJ-E001` through `OBJ-E009`;
- implementation-map pointers;
- static fail-closed state;
- the exact checkout commit/tree supplied by CI.

Any source, document or workflow change that alters one of these facts must
update this contract and the corresponding implementation in the same
candidate. A prose closeout or historical receipt cannot override this gate.
