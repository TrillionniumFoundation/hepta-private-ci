# learning.eval production contract

This file is the normative public-surface and ownership contract for
`learning.eval`. The architectural guide, evidence-admission notes, native
mapping, Lane E matrix and execution dossier must not weaken this contract.

## Authority boundary

An evaluation can establish eligibility for a later independent selector. It
never selects, activates, promotes or releases a candidate. Every evaluation
decision remains `AuthorityPosture::DENY_ALL`.

All external or product qualification must originate from `ProductEvaluationRunnerV1`
and its sealed `ProductQualificationReceiptV1`. The runner invokes
signature-verified V2/V3 admission internally. The product consumers below now
require that sealed receipt in their source APIs. Native qualification, the
named production provider/sink integration and durable host handoff remain
separate acceptance obligations. Asserted `AuthenticatedPrincipalV1` values
are not external authentication.

## API status

| Surface | Status | Permitted use |
|---|---|---|
| `ProductEvaluationRunnerV1::qualify_and_persist` | **Production ingress** | Builds the exact bound bundle internally, runs signed V2/V3 verification and requires durable evidence publication |
| `evaluation_signing_payload_v2` / `longitudinal_evaluation_signing_payload_v3` | **Public signer contracts** | External signers attest exactly the runner-derived bundle/timing bytes |
| `revalidate_product_qualification_v1` | **Public sealed-receipt consumption check** | Validates the receipt and context, reauthenticates the exact evidence under current host trust/time, and compares the complete signed decision; does not consume a holdout or publish evidence |
| `decide_with_signed_evidence_v2` / `decide_with_signed_longitudinal_evidence_v3` | **Crate-internal verification primitives** | Invoked by the product runner and sealed-receipt revalidation; absent from the default cross-crate surface |
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

## Canonical product consumers

The sealed product consumer is
`codex-rs/hepta-intelligence/src/evaluated_shadow.rs::run_evaluated_shadow_v1`.
It accepts only a sealed `ProductQualificationReceiptV1`, checks its trust digest
against the current host verifier, binds its dataset/objective/snapshot set and
requires the same evaluator to sign the candidate bytes against that terminal
receipt. It does not re-run low-level V2 admission. It invokes the shadow ports
and owns the durable shadow `Decision` append; it does not execute dispatch or
activate an artifact.

The other three source consumers require the same sealed qualification together
with the original signed bundle and roles. They use
`revalidate_product_qualification_v1` to retain the current signature, scope,
role-separation and lifetime checks. Equality covers the entire
`SignedEvaluationDecisionV1`, including evidence, trust and authentication
digests; a newly signed bundle with the same Eligible label is insufficient.

| Current caller | Required source admission | Downstream qualification binding |
|---|---|---|
| [`AgentdEvaluationSessionV1::evaluate`](../hepta-agentd/src/intelligence_evaluation.rs) | Mandatory product receipt plus Qualification-scoped revalidation and the current-owner, request-bound evaluator attestation | `intelligence_evaluation_binding_payload_v2` and the v2 consumption digest bind both qualification evidence and publication identities into canonical preparation |
| [`propose_authenticated_parameter_plasticity_v1`](../hepta-intelligence/src/plasticity_product.rs) | Every update candidate requires a product receipt and Qualification-scoped revalidation; generator/evaluator/observer checks remain | The v2 candidate-evaluation commitment includes both qualification identities and feeds the existing governed admission, durable proposal and composition digests; returned `qualifications` retain the sealed receipts in memory |
| [`prepare_self_evolution_selection_v1`](src/self_evolution_selection.rs) | Mandatory SystemLongitudinal product receipt, original time evidence, policy and authoritative ledger/dataset checks, with current generator/evaluator/observer verification | `SelfEvolutionSelectionReceiptV1` retains both qualification identities; `selection_signing_payload_v2` binds them for the separate independent selector, and rollback remains bound to that selection digest |

`NoAdmissibleUpdate` retains its separate independent evaluator attestation,
empty candidate evaluations and original v1 commitment domain. It does not
require a fabricated candidate qualification. These source entrypoints are
not gated by `trusted-inprocess-eval`; source availability does not establish
deployed activation, real longitudinal efficacy or physical-effect authority.

The mandatory receipt fields and v2 Agentd-use/selector signing payloads require
caller migration and new signatures. There is no zero-digest default or old
signing-payload fallback. Existing proposal-registry bytes remain readable, but
an old proposal is not upgraded into a newly qualified candidate: a changed
qualification commitment cannot replay as the old proposal identity. Issuing a
new use signature does not authorize another consumption of a used final holdout.

## Remaining host and recovery obligations

The named production `FinalHoldoutProviderV1` and
`ProductQualificationEvidenceSinkV1` are not yet connected to this product
path. The concrete fenced CAS backend does not supply authenticated observations
or a production publication owner. Host integration must bind both providers to
their declared owners, current namespace and durable publication/recovery rules.

A complete persisted `ProductQualificationReceiptV1` codec and qualified
readback/handoff are still missing. The proposal registry retains a digest
commitment to qualification evidence/publication; its new `qualifications`
return field is in memory, not an additional durable record. The default
canonical Agentd host still lacks a durable seven-owner/App Server handoff and
authenticated `Decision`/`Outcome` composition through the existing
`LedgerWriter`. The optional legacy `PendingIntelligenceLedgerAppendV1` is only
an in-memory qualification carrier. The existing publication sink contract
receives temporal execution identity and a signed decision; this migration
does not turn it into a full-receipt recovery format.

The new regressions use explicitly test-only Memory CAS/publication doubles and,
for self-evolution dataset membership, synthetic facts in the ledger core.
They test source admission and commitment binding, not production durability,
real future-calendar observations or measured adaptive benefit. Independent
selection, current-owner physical-effect authorization and release evidence
remain separate requirements.

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

The listed candidate-qualification paths now require the canonical sealed receipt
in source. Acceptance of sole sealed ingress still requires actual native
regressions that reject mismatched receipts before candidate use or downstream
writes, plus the unchanged exact-head and synthetic-merge CI evidence above.
This source migration does not satisfy the remaining host provider/publication,
full-receipt recovery, durable handoff or independent release obligations.
