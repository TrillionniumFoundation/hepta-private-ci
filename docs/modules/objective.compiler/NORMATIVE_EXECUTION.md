# objective.compiler normative execution contract

This document is the sole normative description of the current `objective.compiler`
product path. `NORMATIVE_EXECUTION.json` is its machine-readable companion. Other
module, readiness, evidence and closeout documents may add rationale, operating
procedure or historical observations, but they may not redefine the product API,
durable record versions, authority boundary, semantic support or qualification
order stated here.

## 1. Authority and ownership

`objective.compiler` converts one bounded, authenticated structured source into an
immutable objective result. It does not interpret prose as authority, relax hard
constraints, select an action, authorize a provider or external effect, own a
private objective database, or promote its own output. Compile and protocol
artifacts retain `AuthorityPosture::DENY_ALL`.

The owners remain distinct:

- Agentd owns signed product ingress, the trusted clock sample, current AuthBus
  trust, runtime generation and final-use fencing.
- `objective.compiler` owns deterministic admission, lowering, feasibility,
  native compilation, proof construction and canonical protocol projection.
- the intelligence facade sequences compilation and durable publication but does
  not open or own the durable store;
- `RunStartJournal` is the sole durable RunStart and objective-conflict owner;
- runtime/effect owners independently recheck current authority before physical
  use.

Historical proof integrity is never current authorization.

## 2. Canonical product path

The only canonical product compilation/publication path is:

```text
signed AuthBus ObjectiveStart
-> ObjectiveRuntimeHost::submit
   -> authenticate exact signed body against current AuthBus trust
   -> decode ObjectiveSourceEnvelopeV1
   -> sample owner-trusted admission time after acquiring the serialized writer
   -> use process-generation-frozen ValidatedAdmissionProfileV1
-> compile_and_publish_validated_objective_run_v1
   -> compile_authoritative_objective_v1
      -> admit_validated_objective_v1
         -> opaque, non-cloneable ValidatedObjectiveAdmissionV1
         -> ObjectiveAdmissionProofV1
      -> compile_validated_objective_v1
         -> opaque, non-cloneable ProofBearingObjectiveCompileV1
   -> encode_proof_bearing_objective_function_v1
   -> destination-owned RunStartJournal append
      -> RunStart record V3 or objective-conflict record V2
      -> external checkpoint CAS
-> Agentd rechecks proof/profile binding, deadline, current trust, generation and fence
-> canonical intelligence handoff or explicitly identified compatibility handoff
```

No caller-controlled skip-validation flag, cache key or proof constructor exists.
A `ValidatedAdmissionProfileV1` may be reused only within its process generation
for immutable profile validation, lookup indexes, collision proofs and the exact
profile digest/revision/compiler-contract reuse key. Authentication, source
identity, freshness, deadline, revocation, generation, fence and final-use
checks remain request- or use-local.

## 3. Admission and proof contract

The authoritative admission proof is V1 and consists of the domain
`hepta.objective.admission-proof.v1` followed by five non-zero 32-byte identities:

1. complete Source V1 envelope proof digest;
2. validated profile digest;
3. versioned authentication-context digest;
4. compiler-contract digest;
5. admitted native source digest.

The compiler constructs the opaque proof; downstream code can inspect its frozen
canonical bytes and digest but cannot construct a compiler capability from
persisted bytes. The destination owner decodes those bytes as
`RunStartAdmissionProofV1`, verifies exact length, version domain, non-zero
identities and digest, and binds the profile and admitted-source identities to the
same immutable journal record.

RunStart V1/V2 and conflict V1 records remain byte-identical historical facts.
Recovery and compaction never synthesize a proof for them. They are inspectable
for migration and audit, but Agentd final use rejects them and requires a new
authorized revision.

## 4. Native and protocol identity

The native semantic digest and registered `ObjectiveFunctionV1` protocol digest
are different identities and both are durable:

- native semantic bytes identify the owner-local compiler result used by
  `RunStartSnapshotV1.objectiveDigest`;
- canonical `ObjectiveFunctionV1` bytes identify the registered protocol
  projection, including explicit source metadata, legal/forbidden actions,
  evidence requirements, resource endowment and the conservative deadline
  projection.

`encode_proof_bearing_objective_function_v1` accepts only the opaque authoritative
compile result and rebinds the complete source-envelope and frozen-profile
identities before invoking the strict canonical encoder/decoder. It does not
repeat admission or native solving. A conflict cannot be projected as a compiled
objective.

## 5. Semantic support

Source V1 scalar values are exact signed Q32 values. The product adapter supports
only `eq`, `lte` and `gte`. `ne`, `lt`, `gt`, `in` and `not_in` are deterministic
`OBJ-E002` rejection because Source V1 has no lossless payload for the additional
semantics. Capabilities of the direct typed feasibility API do not expand Source
V1.

The final native aggregate is bounded by:

- at most 246 caller source constraints plus six resource and four risk-related
  generated constraints, for at most 256 native hard constraints;
- at most 128 combined success, terminal and evidence predicates;
- at most 128 compiled legal actions including intrinsic `abstain`;
- at most 127 caller legal actions when `abstain` is implicit;
- at most 128 caller legal actions when the canonical intrinsic action is
  represented explicitly and remains confirmation-free and not forbidden.

Hard constraints are non-compensable. Soft dimensions never rescue hard
infeasibility. Conflict extraction returns a deterministic inclusion-minimal core,
not a minimum-cardinality claim. Empty caller action sets produce the immutable
`ExplicitAbstain` disposition rather than goal substitution.

## 6. Time and availability

Admission time is sampled from the Agentd owner after entering the serialized
publication boundary. The source observation age, future skew and exact
microsecond deadline are checked against that sample. Exact microseconds remain
in admission and durable identity. `ObjectiveFunctionV1` and final-use checks use
the same conservative millisecond floor; protocol projection cannot extend
permission.

The deterministic feasibility engine reads no clock and is bounded by explicit
call, work-unit and cache budgets. The compatibility `check_feasibility_v1`
wrapper records elapsed host time only after deterministic execution; its
wall-time parameter is an observed availability threshold, not hard preemption.
Hard cancellation belongs to the runtime owner around the bounded call.

## 7. Compatibility surfaces

The following surfaces are compatibility or qualification tools, not the normal
Agentd product path:

- `compile_and_publish_objective_run_v1`, which validates one raw profile before
  delegating to the validated-profile facade;
- `admit_objective_v1` and `compile_admitted_objective_v1`;
- `encode_authenticated_objective_function_v1`, which independently repeats
  authenticated admission and native compilation for callers holding separate
  historical receipts;
- `compile_prevalidated_legacy_objective_v1`, available only under the explicit
  `qualification-legacy-compile` Cargo feature.

Production crates must not enable the legacy feature or call the legacy compile
entrypoint. Compatibility tests and lint run separately from the default product
build and cannot qualify the product path by themselves.

## 8. Durable recovery and handoff

The destination journal publishes authentication, admission/proof, native bytes,
protocol bytes and `RunStartSnapshotV1` atomically with its checkpointed chain.
Exact replay is idempotent. Reusing a run identity with changed authentication,
proof, native semantics, protocol semantics or predecessor is a conflict.
Unknown provider or handoff outcomes are never blindly replayed.

A durable RunStart that predates completion of the canonical multi-owner handoff
must be visible as an explicit recovery state. It may not silently enter a
compatibility execution path. Recovery must either complete the exact idempotent
handoff from durable evidence or retain `AwaitingAuthenticatedRetry` with an
operator-visible count, age and action code. Client retry is not permission to
create a second physical execution.

## 9. Stable errors

The canonical error registry is `docs/contracts/OBJECTIVE_ERRORS.json`. The
stable families are `OBJ-E001` through `OBJ-E009`. `OBJ-E007` is not blanket
retry advice; retryability is variant-specific. `ObjectiveConflictReceiptV1` and
`ExplicitAbstain` are typed non-error outcomes. No adapter may assign a local
alternate meaning to an error code.

## 10. Source identity and evidence

Every qualification claim binds one immutable full commit and tree. The
implementation map binds every relevant source, caller, test and guide path to
its Git object and current observation. A nearby parent, old branch run, queued
workflow, cancelled job, source file, test definition or recorder self-test is
not a pass for a newer head.

Candidate-owned verification code may produce untrusted authoring diagnostics,
but it cannot qualify itself. Protected release and selected-host decisions use
a verifier checked out from protected `main`, keep candidate bytes in a separate
workspace and verify retained command logs and artifacts by digest. Candidate
code executes only on an unprivileged GitHub-hosted runner or an externally
provisioned ephemeral target runner with no reusable credential or writable cache.

The required order is:

```text
exact source head
-> deterministic synthetic merge
-> selected target-host measurement
-> storage durability acceptance
-> independent semantic and security review
-> canary observation
-> rollback drill and rollback authority
-> promotion approval
-> release authority
```

No source commit, CI artifact, author or single issuer may advance the external
acceptance states alone.

## 11. Static truth and change control

Until the complete receipt chain is independently issued, the checked-in static
truth remains:

```text
productionImplementation = false
accepted = false
activated = false
released = false
```

A change to any product API name, proof framing, durable version, Source V1
semantic support, legacy feature, error family or qualification ordering must
update `NORMATIVE_EXECUTION.json`, this document and the consistency test in the
same candidate. `TECHNICAL.md`, `SEMANTIC_SUPPORT.md`, `DELIVERY_EVIDENCE.md`,
`OBJECTIVE_COMPILER_EXECUTION.md`, the implementation map and the PR description
must link here rather than independently redefining the canonical flow.
