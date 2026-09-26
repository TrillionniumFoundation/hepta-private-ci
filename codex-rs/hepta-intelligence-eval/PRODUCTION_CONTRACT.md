# learning.eval production contract

This file is the normative public-surface and ownership contract for
`learning.eval`. The architectural guide, evidence-admission notes, native
mapping, Lane E matrix and execution dossier must not weaken this contract.

## Authority boundary

An evaluation can establish eligibility for a later independent selector. It
never selects, activates, promotes or releases a candidate. Every evaluation
decision remains `AuthorityPosture::DENY_ALL`.

External or production callers enter through `ProductEvaluationRunnerV1`; the runner invokes signature-verified V2/V3 admission internally. Asserted `AuthenticatedPrincipalV1` values are not external authentication, and direct signed-decision functions are intentionally not part of the default cross-crate surface.

## API status

| Surface | Status | Permitted use |
|---|---|---|
| `ProductEvaluationRunnerV1::qualify_and_persist` | **Production ingress** | Builds the exact bound bundle internally, runs signed V2/V3 verification and requires durable evidence publication |
| `evaluation_signing_payload_v2` / `longitudinal_evaluation_signing_payload_v3` | **Public signer contracts** | External signers attest exactly the runner-derived bundle/timing bytes |
| `decide_with_signed_evidence_v2` / `decide_with_signed_longitudinal_evidence_v3` | **Crate-internal verification primitives** | Not default cross-crate APIs; only the product runner may turn them into product qualification |
| `freeze_product_evaluation_plan_v1` | **Production plan freeze** | Freezes V2 metric roles, metric-to-estimator mapping and candidate/baseline temporal plan identities before holdout release |
| `FencedFinalHoldoutOwnerV1` + `FinalHoldoutCasStoreV1` | **Production-required when multiple writers/hosts can contend** | Linearizable CAS, monotonic writer fencing and accepted-or-unknown reconciliation |
| `DurableFinalHoldoutJournalV1` | Single-host/cooperative-owner only | Local file durability when the host can guarantee exclusive namespace ownership |
| `trusted_inprocess::decide_independently{,_v2}` | **Trusted-only** | Explicit compatibility/test feature; never external qualification ingress |
| `trusted_inprocess::evaluate_legacy_inprocess_v1` | **Deprecated / trusted-only** | Legacy deterministic comparator; cannot be used as production qualification |

The `trusted_inprocess` module is absent from default builds and is available
only with the explicit `trusted-inprocess-eval` feature.

## Signed admission

For ordinary qualification:

1. freeze the V2 plan and metric roles before holdout observation;
2. durably consume the exact frozen plan through the authoritative holdout owner;
3. authenticate the generator's signature over the frozen plan digest;
4. authenticate the evaluator's signature over the exact V2 evaluation payload;
5. verify current host-owned trust, scope, objective, authority epoch, lifetime and revocation; generator, evaluator and longitudinal observer must be pairwise distinct by principal, credential chain, signing key and controller;
6. run the bound statistical, support, safety and claim-scope checks;
7. persist the decision together with trust/authentication digests.

A `SystemLongitudinal` claim additionally requires V3 signed observer/time
evidence. Synthetic future IDs or virtual timestamps are never future-calendar
efficacy evidence.

## Final-holdout ownership

### Single host

`DurableFinalHoldoutJournalV1` is valid only when the host provides an
exclusive authorized regular file, independently retained current anchor and
durable containing-directory semantics. Its file lock coordinates cooperating
local owners; it is not a distributed lock.

### Multiple processes or hosts

A multi-writer deployment must implement `FinalHoldoutCasStoreV1` with
linearizable compare-and-swap semantics. The authoritative record binds:

- scope binding;
- writer owner identity;
- strictly positive monotonic fence generation;
- lease/fence digest;
- complete replayable journal snapshot;
- state digest.

A newer generation may take ownership only through CAS while preserving the
journal. Once that CAS succeeds, an older writer's expected state is stale and
its next consume must conflict. A store write whose commit status is unknown
must return `Indeterminate`; the owner poisons the handle and requires reload
and reconciliation before any further use.

The repository provides `LockedFileFinalHoldoutCasStoreV1` as a concrete
single-filesystem CAS backend. It holds an exclusive OS lock, appends checksummed
fence/plan events, fsyncs each committed transition, replays on recovery and
requires an independently retained `FinalHoldoutCasAnchorV1` minimum to reject
backup rollback. `HoldoutFenceIssuerV1` resumes generation from that retained
anchor and binds issued leases to a host authority digest. The backend provides
cross-process semantics directly; cross-host use additionally requires a shared
filesystem whose locks and fsync are documented as linearizable across those
hosts.

The host remains responsible for authenticating the store namespace, retaining
the minimum anchor independently of the journal backup, containing-directory
durability, retention and physical storage policy. A backup must not be able to
manufacture a newer fence or current authoritative state.

## Canonical product evaluation chain

`ProductEvaluationRunnerV1` is the canonical evaluation composition. It freezes
the metric-to-estimator mapping into the bound estimand, consumes the final
holdout through `FencedFinalHoldoutOwnerV1`, and only then invokes the
`FinalHoldoutProviderV1::release_after_consumption` boundary. Candidate and
baseline metric intervals are derived from sealed `TemporalEvaluationReceipt`
and `ClusterOpeEstimate` receipts; a caller cannot submit replacement
`MetricGateV1` intervals. The runner builds the signed qualification bundle itself and returns success only after `ProductQualificationEvidenceSinkV1` returns a nonzero durable publication digest. The resulting `ProductQualificationReceiptV1` has a private integrity seal and binds the candidate, evaluator, objective, dataset, snapshot set, claim scope, signed decision and durable publication.

## Terminal receipt integrity profile

The current product receipt digest domain is
`hepta.intelligence-eval.product-qualification.v4`; its private seal domain is
`hepta.intelligence-eval.product-qualification-receipt.v2`. In addition to the
execution, candidate, principals, objective, dataset, snapshots, scope and
publication, it binds the complete terminal decision: evaluation/candidate/baseline
identities, disposition, ordered failed metrics, evidence, trust, authentication
and deny-all authority. Retaining an old opaque decision digest does not permit
changing any of these fields. Consumer signing payloads incorporate the current
product digest and must reject a modified receipt before requesting a signature.

Historical v3/v1 product digests/seals are not accepted as this profile. Recovery
must use the preserved original signed inputs and authoritative publication/holdout
identity; do not bless old mutable conclusions, change plans, consume a different
holdout or turn a read-only historical result into a current-use authorization.

## Evidence publication and recovery

`ProductEvaluationRunnerV1::qualification_publication_payload` prepares exact
terminal bytes using the same signed admission as qualification. It produces no
qualification receipt. The external producer signs an existing kernel.evidence
envelope, and the host retains that original intent in its operation/outbox owner.
`qualify_and_persist` rechecks current trust/time and requires the exact publication.

`AgentdEvaluationEvidenceSinkV1` uses the ordinary Agentd evidence endpoint, AuthBus
and SQLite. It creates no database or credentials. Publication identity is derived
from the frozen evaluation ID in the Agent namespace. Changed terminal bytes are
rejected; a lost response remains indeterminate and only the original signed
intent may be retried. Success requires the expected evidence ID from the owner.
The synchronous adapter requires a multithread runtime and bounded blocking host.
It publishes causal qualification, not independent longitudinal acceptance.

The evidence host resolves its issuer after acquiring the SQLite writer lock.
Revocation while waiting is observed before authentication, including retries.
That post-lock read defines admission order relative to later trust changes.

Recovery tests use actual files, locks, synchronization and child-process exit.
The real-Agentd fixture uses the actual socket and evidence database, restart and
revocation. Its observations and identities are synthetic, not field acceptance.
The default authenticated input provider, immutable input archive, durable signing
outbox and evaluation scheduler still require named product integration. This
publication adapter must not be reported as completion of those missing owners.

## Storage recovery and measurement

Locked-file recovery now reuses one validated semantic journal for event replay,
while retaining checksums, plan integrity, one-use rules, monotonic fences and
every-prefix matching against the independent minimum anchor. The disk format
and state digests are unchanged. Full-prefix replay remains a test oracle.
`examples/fenced_holdout_probe.rs` measures isolated storage with synthetic plans
and refuses an existing directory. Record exact source, build profile, filesystem,
host load and workload alongside append percentiles, memory and recovery cost.
These measurements do not establish field or future-window efficacy.

## Canonical product consumer

The repository's current signed consumer is
`codex-rs/hepta-intelligence/src/evaluated_shadow.rs::run_evaluated_shadow_v1`. It now accepts only a sealed `ProductQualificationReceiptV1`, checks its trust digest against the current host verifier, binds its dataset/objective/snapshot set and requires the same evaluator to sign the candidate bytes against that terminal receipt. It no longer re-runs low-level V2 admission. This closes the repository-controlled product qualification spine without claiming runtime activation, target-host qualification or production longitudinal efficacy.

## CI closure evidence

Repository-controlled source qualification is the
`Hepta Lane E gap closure` workflow. For `learning.eval`, the mandatory
`learning-eval-qualification` job must retain a commit-addressed artifact that
binds at least:

- source commit and tree;
- workflow run identity and build identity;
- `Cargo.lock` digest;
- this production-contract digest;
- `NATIVE_MAPPING.md` and Lane E traceability digests;
- coverage report digest and measured line coverage, with `>=85%` line coverage enforced by CI;
- repeated fenced-holdout stress result;
- signed cross-crate E2E test identity and evaluated-shadow signed runtime-admission E2E;
- creation time and expiry.

The manifest is provenance-attested by GitHub Actions. These are repository
source/CI facts only. They cannot self-issue live outcomes, real future-calendar
observations, independent semantic/operator acceptance, canary, selection,
promotion or release evidence.

## Completion states

`source_qualified_exact_head` may be claimed only for a candidate whose exact
head and ordered-parent synthetic merge pass the Lane E workflow including the
mandatory learning-eval qualification artifact. External evidence gates remain
open independently and must not be collapsed into source qualification.

### Persisted qualification consumption

`ProductQualificationReceiptV1::verify_signed_bundle_current` only verifies an
already sealed, persisted result against its exact signed bundle and current
trust; it cannot mint a new qualification. Agentd uses request-bound
`AgentdSignedEvaluationV2`, and governed parameter proposals use
`CandidateEvaluationAdmissionV2`. Both reject a raw signed-metrics substitute.
The generic `decide_with_signed_evidence_v2` remains crate-private.
