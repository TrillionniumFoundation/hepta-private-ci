# learning.eval production contract

This file is the normative public-surface and ownership contract for
`learning.eval`. The architectural guide, evidence-admission notes, native
mapping, Lane E matrix and execution dossier must not weaken this contract.

## Authority boundary

An evaluation can establish eligibility for a later independent selector. It
never selects, activates, promotes or releases a candidate. Every evaluation
decision remains `AuthorityPosture::DENY_ALL`.

External or production qualification callers enter through `ProductEvaluationRunnerV1`; the runner invokes signature-verified V2/V3 admission internally. Asserted `AuthenticatedPrincipalV1` values are not external authentication, and direct signed-decision functions are intentionally not part of the default cross-crate surface.

## API status

| Surface | Status | Permitted use |
|---|---|---|
| `ProductEvaluationRunnerV1::qualify_and_persist` | **Production ingress** | Builds the exact bound bundle internally, runs signed V2/V3 verification and requires durable evidence publication |
| `prepare_self_evolution_product_selection_v1` | **Canonical selection preparation** | Requires the runner's sealed, durably published qualification and the same evaluator's signature binding exact candidate/predecessor bytes; retains the original independent selector boundary |
| `prepare_self_evolution_selection_v1` | **Compatibility preparation** | Verifies a signed caller-supplied metric bundle; does not establish product qualification and cannot enter published Agentd installation |
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

## Canonical product consumer

The signed shadow consumer is
`codex-rs/hepta-intelligence/src/evaluated_shadow.rs::run_evaluated_shadow_v1`.
It accepts only a sealed `ProductQualificationReceiptV1`, checks its trust
digest against the current host verifier, binds its dataset/objective/snapshot
set and requires the same evaluator to sign the candidate bytes against that
terminal receipt. It does not re-run low-level V2 admission.

The published Agentd installation consumer is
`prepare_self_evolution_product_selection_v1` followed by
`admit_self_evolution_selection_v1`,
`PinnedCognitiveRanker::load_evaluated_published` and
`AgentdConfig::with_evaluated_cognitive_bootstrap`. The preparation compares the
original signed bundle against the sealed runner decision and requires an
additional signature from that same evaluator over the exact candidate and
predecessor bytes, generations and qualification publication. The independent
selector signs this product binding in the versioned selection payload. Both
selection admission and later inference recheck the retained role lifetimes.
The ranker additionally verifies the named artifact owner's full V2 manifest,
signed CURRENT and exact parent lineage before exposing a permutation.

The ordinary process profile `published_product_qualification_v1` reconstructs
qualification through the original runner, exact fenced-holdout recovery and a
real immutable file evidence sink. It never deserializes a qualification seal.
An exact consumed plan may be replayed only with its independently retained CAS
anchor, complete retained inputs and the original durable publication; the
release provider remains downstream of native consume. A compatibility signed
metric bundle cannot substitute for these inputs. The legacy
`prepare_self_evolution_selection_v1` and V1 dataset-in-support ranker profile
remain explicitly bounded compatibility APIs, not product qualification.

These consumers preserve independent selection, explicit host installation and
the existing runtime FinalUse/effect fences. Source composition does not
establish target-host qualification, independent operator acceptance, real
future-calendar efficacy or general model quality.

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
