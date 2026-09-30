# Objective compiler execution specification

**Normative contract:** `docs/modules/objective.compiler/NORMATIVE_EXECUTION.md`  
**Machine contract:** `docs/modules/objective.compiler/NORMATIVE_EXECUTION.json`  
**Bound modules:** `objective.compiler`, `intelligence.control`, `runtime.agentd`, `learning.ledger`, `kernel.authority`  
**Source target:** `codex-rs/hepta-objective`  
**Canonical error registry:** `docs/contracts/OBJECTIVE_ERRORS.json`

This readiness document explains implementation, recovery, measurement and
qualification procedure. It does not redefine the API names, durable versions,
semantic support or authority boundary in the normative contract. Any disagreement
is a release-blocking documentation failure.

## 1. Mission and authority boundary

`objective.compiler` freezes one bounded authenticated request into an immutable
objective revision with explicit hard constraints, success predicates, legal
actions, evidence requirements, resource ceilings, risk posture and provenance.
It does not infer authority from prose, weaken a hard constraint, choose an action,
perform an external effect, own the durable RunStart store or approve its own
output. Every compiler and protocol artifact remains
`AuthorityPosture::DENY_ALL`.

The responsibility chain is deliberately split:

- Agentd authenticates the signed ingress against current AuthBus trust, samples
  the owner clock, owns generation and fence state and performs final-use checks;
- the objective crate validates and lowers the source, solves bounded feasibility,
  compiles native semantics, constructs the opaque admission proof and emits the
  canonical protocol projection;
- the intelligence facade sequences compilation and publication without opening
  or owning the store;
- `RunStartJournal` is the sole durable writer for RunStart and objective-conflict
  facts;
- runtime/effect owners independently acquire current authority before physical
  use.

Historical proof integrity is evidence about a past admission. It is never a
replacement for current trust, revocation, deadline, generation, fence or effect
authority.

## 2. Canonical product call graph

The normal product path is:

```text
signed AuthBus ObjectiveStart
-> ObjectiveRuntimeHost::submit
   -> authenticate exact signed body against current AuthBus trust
   -> decode_source_envelope_json_v1
   -> ObjectiveSourceEnvelopeV1::validate_structure
   -> acquire serialized RunStart writer boundary
   -> resample owner-trusted admission time
   -> reuse one process-generation-frozen ValidatedAdmissionProfileV1
-> compile_and_publish_validated_objective_run_v1
   -> compile_authoritative_objective_v1
      -> admit_validated_objective_v1
         -> opaque ValidatedObjectiveAdmissionV1
         -> private ObjectiveAdmissionProofV1 construction
      -> compile_validated_objective_v1
         -> bounded deterministic native compiler
         -> opaque ProofBearingObjectiveCompileV1
   -> encode_proof_bearing_objective_function_v1
      -> strict canonical ObjectiveFunctionV1 bytes
      -> protocol-wire digest distinct from native semantic digest
   -> destination-owned RunStartJournal append
      -> RunStart record V3 or objective-conflict record V2
      -> predecessor-chain update and external checkpoint CAS
-> Agentd rechecks proof/profile binding, deadline, current trust, generation and fence
-> canonical intelligence handoff or explicitly identified compatibility handoff
```

The validated profile may reuse only immutable profile validation, lookup indexes,
collision proofs and the exact profile digest/revision/compiler-contract key.
Authentication, source identity, freshness, deadline, revocation, generation,
fence and final-use decisions are request- or use-local. There is no
caller-controlled cache key or skip-validation flag.

## 3. Input grammar and exact semantic support

The bounded source grammar carries:

```text
identity: request id, principal scope, locale, trust class, observation time
success: intermediate and terminal predicates, evidence requirements
actions: legal, forbidden and confirmation-required action classes
constraints: constitutional, principal, environment and task hard constraints
preferences: soft dimensions with unit, direction and bounded weight
resources: time, token, compute, memory, network and effect ceilings
risk: risk class, abstention rule, rollback and compensation requirements
provenance: source, input-schema and normalization-profile digests
```

Free text may be upstream evidence but is never the final authority
representation. Duplicate semantic identities, unknown critical fields,
noncanonical framing, oversize collections, invalid timestamps and digest drift
fail closed.

Source V1 scalar values are exact signed Q32 values. The product adapter supports
only:

```text
eq
lte
gte
```

The following operators are deterministic `OBJ-E002` rejection because Source V1
does not carry the payload required for a lossless lowering:

```text
ne
lt
gt
in
not_in
```

The direct typed feasibility API can represent additional finite-domain and Horn
constraints, but that capability must not be advertised as Source V1 end-to-end
support.

## 4. Aggregate bounds

Bounds are checked against the final native aggregate, not merely each source
array:

- at most 246 caller hard constraints;
- exactly six generated resource constraints;
- exactly four generated risk/rollback/compensation/abstention constraints;
- at most 256 native hard constraints in total;
- at most 128 combined success, terminal and evidence predicates;
- at most 128 compiled legal actions including intrinsic `abstain`;
- at most 127 caller actions when `abstain` is implicit;
- at most 128 caller actions when the intrinsic action is explicitly represented,
  confirmation-free and not forbidden;
- at most 64 soft dimensions;
- at most 257 legacy conflict-oracle calls under the complete linear minimality
  budget;
- source and profile JSON are bounded before allocation and semantic work.

Input exceeding a bound is rejected or reported unavailable. It is never silently
truncated.

## 5. Hard feasibility and intrinsic abstain

Constraint precedence is non-compensable:

```text
P0 constitutional authority, truth, privacy, deletion and writer ownership
P1 explicit principal scope and forbidden effects
P2 environment and adapter safety
P3 task success and terminal conditions
P4 soft utility and resource allocation
```

Soft preferences do not participate in hard feasibility. A hard conflict yields a
typed `ObjectiveConflictReceiptV1` with a deterministic inclusion-minimal core; it
does not claim minimum cardinality.

`abstain` is compiler-intrinsic, legal, confirmation-free and impossible for a
caller to forbid. An empty caller legal-action set is valid and compiles to
`CompileDisposition::ExplicitAbstain`. The compiler never substitutes an easier
goal to avoid conflict.

## 6. Admission proof and durable versions

`ObjectiveAdmissionProofV1` is privately constructed and contains the domain
`hepta.objective.admission-proof.v1` followed by five non-zero 32-byte identities:

1. complete source-envelope proof digest;
2. validated profile digest;
3. authentication-context digest;
4. compiler-contract digest;
5. admitted native source digest.

The destination journal decodes those bytes as historical
`RunStartAdmissionProofV1`, verifies the exact length/domain/digest and binds the
profile and admitted-source identities to the same immutable record.

Current durable formats are:

```text
RunStart record version: 3
objective-conflict record version: 2
admission-proof version: 1
```

RunStart V1/V2 and conflict V1 records retain their frozen bytes and identities.
Recovery and compaction do not synthesize a proof for them. They remain available
for audit and migration inspection but are not valid for Agentd final use; an
authorized new revision is required.

The proof blob is protected by the journal record digest, predecessor chain and
external checkpoint. Persisted proof integrity does not by itself reconstruct a
current compiler capability or live authorization. Full current use still
requires the owner checks named above.

## 7. Native and protocol identity

The owner-native semantic digest and registered protocol-wire digest are distinct
and both are durable:

- native semantic bytes identify the compact compiler result referenced by
  `RunStartSnapshotV1.objectiveDigest`;
- canonical `ObjectiveFunctionV1` bytes bind the registered transport semantics,
  including source metadata, legal/forbidden actions, evidence requirements,
  resources and the conservative deadline projection.

`encode_proof_bearing_objective_function_v1` accepts the opaque authoritative
compile result and rebinds the complete source-envelope and frozen-profile
identities. It retains strict native/source/receipt validation and canonical
re-decoding without a second native solve. A conflict cannot be projected as a
compiled run.

## 8. Time model

Agentd samples admission time after entering the serialized writer boundary. The
source observation age, future skew and exact microsecond deadline are checked
against that trusted sample. Exact microseconds remain part of authenticated
admission and durable RunStart identity.

`ObjectiveFunctionV1` projects the deadline using the existing conservative
millisecond floor, and Agentd final use applies the same floor. Protocol
conversion must not extend authority.

The deterministic feasibility engine reads no wall clock. It is bounded by
explicit call, work-unit and cache budgets. The compatibility availability
wrapper records elapsed host time after deterministic execution; its wall-time
parameter is an observed threshold, not hard preemption. Runtime owners provide
cancellation and isolation around the bounded call.

## 9. Compatibility surfaces

The following are migration, diagnostics or qualification surfaces, not the
normal Agentd product path:

- raw-profile publication through `compile_and_publish_objective_run_v1`;
- two-stage raw admission through `admit_objective_v1` and
  `compile_admitted_objective_v1`;
- independent authenticated revalidation through
  `encode_authenticated_objective_function_v1`;
- pre-admitted legacy compilation through
  `compile_prevalidated_legacy_objective_v1` under the explicit
  `qualification-legacy-compile` Cargo feature.

Production builds must not enable the legacy feature. Default and compatibility
builds/tests/lint run separately so compatibility code cannot hide failures in the
ordinary product surface.

## 10. Durable publication, replay and recovery

One journal transaction contains:

- signed-ingress authentication identity;
- admission receipt and V1 proof bytes/digest;
- native semantic bytes/digest;
- canonical protocol bytes/digest;
- `RunStartSnapshotV1`;
- run generation, fence, authority epoch and exact deadline;
- record and predecessor-chain identities.

Publication succeeds only after the destination owner has durably appended and
advanced its external checkpoint. Exact replay is idempotent. Reusing a run
identity with changed authentication, proof, native semantics, protocol semantics
or predecessor is a conflict.

The segmented store keeps one writer lease across open, recovery, rotation,
checkpoint publication and prefix compaction. A competing writer is rejected at
all rotation cuts. Recovery refuses missing acknowledged history, removed sealed
segments, a missing external checkpoint for existing local history, checkpoint
rollback and a checkpoint ahead of local history. Only an incomplete,
unacknowledged active tail may be truncated to the last validated frame.

Compaction may replace only a complete expired sealed prefix. It writes the
summary first, advances the checkpoint second, commits the new inventory third
and removes old segments last. Replay indexes retain enough identity to reject
resurrection and changed-semantics reuse.

## 11. Canonical handoff recovery

A durable RunStart can exist before completion of the canonical multi-owner
handoff. Such a record must not silently enter the compatibility execution path.
The recovery state is explicitly interpreted as awaiting the exact idempotent
handoff or an authenticated retry. Client retry is not permission to create a
second physical execution.

Operational closure requires a durable or reconstructible handoff identity,
operator-visible pending count and age, a stable action code and regression cases
for crash before handoff, acknowledgement loss, retry, restart, revocation and
late result. Until that source and target-host evidence is complete, the checked-in
static state remains not activated.

## 12. Product execution attachment

A compiled compatibility handoff may expose an
`ObjectiveRunExecutionBinding` copied from the exact durable record. It contains
only request/objective/body/artifact/authority/generation/fence/deadline identity;
it grants no effect authority.

The trusted execution owner must:

1. attach independently produced context to that exact run;
2. re-read current final-use authority;
3. durably commit dispatch before the physical send;
4. perform exactly one App Server turn;
5. publish the observed terminal or indeterminate state to the same run;
6. return a stored terminal observation on exact retry without a new provider
   send.

Unknown physical outcome is never treated as success and never blindly replayed.

## 13. Stable errors

`docs/contracts/OBJECTIVE_ERRORS.json` is the sole error-code registry:

| Code | Stable class | Disposition |
|---|---|---|
| `OBJ-E001` | invalid bounded structure, numeric representation or arithmetic | rejected |
| `OBJ-E002` | unknown, unsupported or unrepresentable semantics | rejected |
| `OBJ-E003` | principal, trust or authenticated scope mismatch | authority rejected |
| `OBJ-E004` | source/schema/profile/normalization/intent integrity mismatch | integrity rejected |
| `OBJ-E005` | unit, direction or semantic-profile mismatch | rejected |
| `OBJ-E006` | intrinsic abstain unavailable or confirmation-gated | rejected |
| `OBJ-E007` | time-state, deadline or feasibility availability | unavailable; variant-specific retry |
| `OBJ-E008` | terminality or durable semantic-identity conflict | conflict |
| `OBJ-E009` | untrusted evidence attempts authority escalation | security rejected |

`OBJ-E007` is not blanket retry advice. Rust variant-level policy distinguishes
transient availability from stale or invalid input. Conflict and explicit
abstention are typed non-error outcomes.

## 14. Verification matrix

The source candidate must execute all applicable checks on both the exact source
head and the deterministic synthetic merge:

- implementation-map verification bound to exact commit/tree;
- current-state projection verification;
- normative specification consistency;
- fail-closed release-source truth;
- default objective tests;
- compatibility-feature objective tests;
- all-target compilation;
- durable RunStart/proof/recovery tests;
- intelligence publication tests;
- Agentd admission/checkpoint/product E2E tests;
- strict Clippy for owned all-target packages;
- strict compatibility-feature Clippy;
- scoped formatting and clean-source checks.

`scripts/hepta-objective-qualify-exact.py` is not itself authority. Each command
retains argv, candidate working directory, status, exit code, elapsed time and the
SHA-256 of its actual combined log. Missing, duplicate, failed, interrupted,
timed-out or log-drifted commands fail the receipt.

## 15. Qualification trust model

Candidate-owned scripts may produce authoring diagnostics but cannot qualify the
candidate. Trusted verification is separated from candidate bytes:

```text
protected-main trusted control checkout
+ separate exact candidate checkout/data workspace
+ digest-bound raw execution artifacts
-> trusted receipt verification and evidence projection
```

Candidate code executes only on an unprivileged GitHub-hosted runner or an
externally provisioned ephemeral target runner. Protected workflows do not execute
candidate-owned release-verifier code. Target-host jobs use isolated job-local
Cargo home/target directories, no reusable credential and no reusable writable
cache, then destroy the candidate workspace.

A persistent self-hosted runner without the `ephemeral` enrollment label cannot
satisfy the selected-host gate. The label is a routing requirement, not evidence
that provisioning or destruction occurred; the owning infrastructure authority
must independently attest ephemeral lifecycle and host identity.

## 16. Measurement

The target-host recorder separates:

- cold validated-profile construction;
- warm authenticated admission;
- deterministic native compile;
- proof-bound protocol encode/decode;
- maximum conflict extraction;
- signed Agentd product ingress;
- durable append/checkpoint/handoff as one observable atomic boundary;
- physical execution fixture where explicitly enrolled.

Build/discovery/hashing happen outside fixture resource sampling. The V2 recorder
selects exactly one executable from Cargo JSON output, records artifact digests,
lists exactly one test and invokes it directly with `--exact`. Missing,
ambiguous, symlinked or changed artifacts fail closed.

RSS is the OS-reported waited-child high-water value; it is not the sum of all
simultaneously live descendant RSS and not an internal allocator profile. A
GitHub-hosted measurement is development evidence, not selected deployment-host
acceptance.

## 17. Evidence and release order

Every observation binds one immutable full commit and tree. Historical runs,
nearby parents, queued workflows, source files, test definitions and recorder
self-tests cannot qualify a newer head.

The mandatory order is:

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

Receipt issuers required to be independent by `RELEASE_POLICY.json` must remain
distinct. A source author, CI job or artifact cannot self-issue external acceptance.

Until the full independently issued chain exists, static truth remains:

```text
productionImplementation = false
accepted = false
activated = false
released = false
```

## 18. Change control

A change to the product API, proof framing, durable version, Source V1 semantics,
legacy feature, stable error family or qualification order must update in one
candidate:

- `docs/modules/objective.compiler/NORMATIVE_EXECUTION.md`;
- `docs/modules/objective.compiler/NORMATIVE_EXECUTION.json`;
- this readiness specification;
- `TECHNICAL.md` and `SEMANTIC_SUPPORT.md` references;
- implementation map and exact source objects;
- normative consistency tests;
- exact source/merge qualification inventory.

Generated projections never become sources of truth. No documentation update,
source commit or green development workflow grants activation, promotion or
release authority.
