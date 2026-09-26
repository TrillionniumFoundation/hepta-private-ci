# `learning.eval` production contract

This file is the normative public-surface, durability and ownership contract for
`learning.eval`. The architectural guide, evidence-admission notes, native
mapping, Lane E matrix and execution dossier must not weaken it. Generated source
truth is recorded in
[`docs/modules/learning.eval/CURRENT_STATUS.json`](../../docs/modules/learning.eval/CURRENT_STATUS.json).

## Authority boundary

An evaluation can establish eligibility for a later independent consumer. It
never selects, activates, promotes or releases a candidate. Every evaluation,
attempt, admission, compaction and qualification receipt remains
`AuthorityPosture::DENY_ALL`.

## API classification

| Surface | Status | Permitted use |
|---|---|---|
| `RecordedProductEvaluationRunnerV1::evaluate_temporal_comparison` | **Production evaluation ingress** | Runs the product comparison while mandating a durable attempt journal before held-out observations are released |
| `RecordedProductEvaluationRunnerV1::qualify_and_persist` | **Production qualification ingress** | Builds the exact bound bundle internally, runs signed V2/V3 verification and requires durable evidence publication |
| `freeze_product_evaluation_plan_v1` | **Production plan freeze** | Freezes V2 metric roles, metric-to-estimator mapping and candidate/baseline temporal plan identities before holdout release |
| `evaluation_signing_payload_v2` / `longitudinal_evaluation_signing_payload_v3` | **Public signer contracts** | External signers attest exactly the runner-derived bundle/timing bytes |
| `admit_signed_eligibility_v2` | **Consumer-bound, non-product admission** | Authenticates one frozen V2 evaluation and binds the authority-free result to one concrete downstream request or proposal; it cannot mint product qualification |
| `decide_with_signed_evidence_v2` / `decide_with_signed_longitudinal_evidence_v3` | **Crate-internal verification primitives** | Never external cross-crate ingress |
| `FencedFinalHoldoutOwnerV1` + `FinalHoldoutCasStoreV1` | **Production-required holdout owner** | Linearizable CAS, monotonic writer fencing and accepted-or-unknown reconciliation |
| `LockedFileFinalHoldoutCasStoreV1` | Concrete single-filesystem backend | Cross-process lock, checksummed append, fsync, anti-rollback anchor, verified copy-compaction |
| `ReconciledProductQualificationSinkV1` | **Canonical publication adapter** | Idempotent load-before-write and read-after-unknown reconciliation keyed by temporal execution digest |
| `LockedFileProductEvaluationAttemptJournalV1` | **Concrete attempt journal** | Records irreversible holdout consumption and one sealed/failed terminal transition |
| `DurableFinalHoldoutJournalV1` | Single-host/cooperative compatibility | Local durability only when the host guarantees one exclusive namespace |
| `trusted_inprocess::decide_independently{,_v2}` | **Trusted-only compatibility** | Explicit feature-gated tests and bounded migration fixtures only |
| `trusted_inprocess::evaluate_legacy_inprocess_v1` | **Deprecated / trusted-only** | Legacy deterministic comparator; never production qualification |

The `trusted_inprocess` module is absent from default builds. Compiler-enforced
negative fixtures must prove the low-level V2/V3 decision functions cannot be
imported by another crate.

## Signed admission

For ordinary product qualification:

1. freeze the V2 plan, metric roles and metric source mapping before observing
   the final holdout;
2. durably consume the exact frozen plan through the authoritative fenced owner;
3. record the consumed transition in the attempt journal before the provider can
   release observations;
4. authenticate the generator signature over the frozen plan digest;
5. authenticate the evaluator signature over the exact V2 payload;
6. verify current host-owned trust, objective, scope, authority epoch, lifetime
   and revocation, with required actor/key/credential/controller separation;
7. run the bound support, statistical, safety and claim-scope checks;
8. record a sealed or failed terminal attempt transition;
9. persist qualification evidence through an idempotent reconciled sink;
10. return a sealed product qualification receipt only after durable publication.

A `SystemLongitudinal` claim additionally requires V3 signed observer/time
evidence. Synthetic future IDs, virtual clocks and source tests are never real
future-calendar efficacy evidence.

`admit_signed_eligibility_v2` is intentionally narrower than product
qualification. The caller must supply a nonzero digest of the complete concrete
consumer context. Its sealed receipt authenticates and binds the decision but
does not consume a holdout, publish product evidence or create selection,
activation, promotion or release authority.

## Final-holdout ownership

### Single host

`DurableFinalHoldoutJournalV1` is valid only when the host supplies an authorized
regular file, exclusive namespace ownership, independently retained current
anchor and durable containing-directory semantics. Its lock coordinates
cooperating local owners; it is not a distributed lock.

### Multiple processes or hosts

A contended deployment must implement `FinalHoldoutCasStoreV1` with linearizable
compare-and-swap semantics. The authoritative record binds:

- scope binding;
- writer owner identity;
- strictly positive monotonic fence generation;
- lease/fence digest;
- complete replayable journal snapshot;
- state digest.

A newer generation takes ownership only through CAS while preserving the
journal. An older writer then conflicts on its next transition. A store write
whose commit status is unknown returns `Indeterminate`; the owner poisons the
handle and requires reload and reconciliation.

The locked-file backend holds an exclusive OS lock, appends checksummed fence and
plan frames, fsyncs each committed transition, replays on recovery and requires
an independently retained `FinalHoldoutCasAnchorV1` minimum to reject backup
rollback. Cross-host use additionally requires a shared filesystem whose lock and
fsync semantics have been externally qualified as linearizable across those
hosts.

### Verified compaction

Compaction always writes a new empty target file; it never truncates the source.
It writes the current fence, replays every retained plan through the normal CAS
path and returns only when the final record and anchor equal the source. The
source remains the rollback/forensic predecessor until the host independently
persists the compaction receipt, target file and containing-directory update.
Compaction cannot erase final-holdout use history.

## Evaluation-attempt lifecycle

A production evaluation uses a stable attempt identity. The journal accepts only:

```text
HoldoutConsumed -> ComparisonSealed
HoldoutConsumed -> Failed
```

Exact retries return the existing event. A terminal event without consumption,
a different plan or holdout under the same attempt identity, a second conflicting
terminal state, a truncated frame or a concurrent second writer fails closed.
The holdout-consumed event is committed before released observations reach the
estimator. A failure after consumption therefore remains auditable and cannot be
mistaken for permission to reuse the holdout.

## Qualification publication and reconciliation

`ProductQualificationEvidenceSinkV1` implementations used in production must
provide exactly-once semantic publication. The canonical adapter uses a
`ProductQualificationPublicationStoreV1` keyed by temporal execution digest:

1. load before write;
2. return an existing record only when every bound decision/trust/authentication
   digest matches;
3. reject semantic conflicts without overwrite;
4. on `Indeterminate`, retain the pending request and load again;
5. report success only after the exact committed record is observed.

A host may implement an equivalent protocol, but a bare append sink without
idempotency and accepted-but-unknown reconciliation is not production-qualified.

## Canonical product evaluation chain

The recorded runner freezes metric-to-estimator mapping into the bound estimand,
consumes the final holdout, records consumption, and only then invokes
`FinalHoldoutProviderV1::release_after_consumption`. Candidate and baseline
intervals are derived from sealed temporal and cluster receipts over the same
cohort; a caller cannot submit replacement `MetricGateV1` intervals. The runner
builds the signed qualification bundle itself and returns success only after the
evidence sink reports a nonzero durable publication digest.

The resulting `ProductQualificationReceiptV1` has a private integrity seal and
binds candidate, evaluator, generator, objective, dataset, snapshots, claim
scope, signed decision and durable publication. The repository-controlled signed
consumer `run_evaluated_shadow_v1` accepts only that sealed receipt and rechecks
current trust, dataset, candidate and evaluator bindings. This closes the source
product spine without claiming runtime activation or release.

Agentd request admission and governed plasticity proposals use the separate
consumer-bound admission facade. Their concrete run/proposal context digest is
bound into the sealed admission receipt. Neither path is a substitute for a
product qualification receipt.

## CI closure evidence

The `Hepta Lane E gap closure` workflow must retain commit-addressed exact-head
and ordered-parent synthetic-merge evidence. At minimum it binds:

- source commit and tree;
- workflow run and build identities;
- `Cargo.lock`, this contract, native mapping and traceability digests;
- compiler-enforced negative and positive public-API fixtures;
- owner, consumer-bound admission, attempt-journal, reconciliation, compaction,
  cross-crate and cross-language tests;
- `>=85%` measured line coverage;
- storage profile and fault-injection logs;
- creation time and expiry.

The evidence manifest is provenance-attested by GitHub Actions. It proves
repository source/CI facts only.

## Target-host and external qualification

The external packet and verifier are documented in
[`TARGET_HOST_QUALIFICATION.md`](../../docs/modules/learning.eval/TARGET_HOST_QUALIFICATION.md).
The following remain independent gates:

- host authentication and durable namespace binding;
- selected-filesystem CAS, lock, fsync, directory and backup behavior;
- real future-calendar outcomes and independent snapshots;
- retention, change-point, power, subgroup/privacy and unlearning evidence;
- independent semantic/operator acceptance;
- selection, canary, promotion, activation and release authorization.

## Completion states

`source_qualified_exact_head` may be claimed only for the immutable commit whose
exact head and ordered-parent synthetic merge both pass the mandatory workflow
and produce the required attested artifacts. `targetHostQualified`, independent
acceptance, activation and release remain false unless their separate external
packet passes its verifier. No repository source or CI job may collapse those
states.
