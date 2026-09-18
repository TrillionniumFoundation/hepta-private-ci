# learning.eval production contract

This file is the normative production-ingress contract for
`codex-hepta-intelligence-eval`. The broader technical guide, native mapping,
evidence-admission notes and qualification dossier explain design and evidence,
but they do not override the API classifications below.

## Authority ceiling

Every evaluation decision is evidence only and must carry
`AuthorityPosture::DENY_ALL`. No API in this crate selects, activates, promotes,
deploys or releases a candidate.

## API status matrix

| Surface | Status | Allowed use |
|---|---|---|
| `evaluate_legacy_inprocess` | crate-private legacy | Unit/compatibility semantics only. It is not exported and cannot be production ingress. |
| `decide_independently` | trusted in-process compatibility | Pure semantic engine over asserted principal metadata. Never admit external qualification evidence directly. |
| `decide_independently_v2` | trusted in-process compatibility | Preregistered metric-role semantic engine. Never admit external qualification evidence directly. |
| `decide_with_signed_evidence_v1/v2` | authenticated compatibility | Verifies signatures, but does not require the type-level durable holdout proof. Existing trusted integrations may migrate through this surface; it is not the production-required qualification entrypoint. |
| `decide_with_signed_longitudinal_evidence_v3` | authenticated longitudinal compatibility | Adds independently signed observed-time windows, but does not require the type-level durable holdout proof. |
| `decide_with_signed_durable_evidence_v3` | **production-required: Qualification** | Requires preregistered V2 metric roles, host-owned signer trust, generator/evaluator signatures and `DurableHoldoutUseV1`. |
| `decide_with_signed_durable_longitudinal_evidence_v4` | **production-required: SystemLongitudinal** | Adds durable holdout proof and independently signed observed-time future windows. |

New external/product qualification integrations MUST use one of the two
production-required entrypoints. Compatibility surfaces MUST NOT be used to
claim production qualification. Upstream effect-bearing consumers must preserve
that boundary: the default `codex-hepta-intelligence` public surface exposes
`run_evaluated_shadow_v2`; pre-durable `run_evaluated_shadow_v1` is exported only
under the explicit `trusted-evaluated-shadow-v1` compatibility feature.

## Required production chain

A production qualification is admitted only after all of the following:

1. Freeze the full evaluation plan with `freeze_cross_fold_plan_v2`, including
   every metric role and margin before final-holdout access.
2. Persist/register the frozen plan in host-owned storage before collecting or
   revealing confirmatory holdout outcomes.
3. Consume the final holdout through `DurableFinalHoldoutJournalV1::consume_proven`.
   The returned `DurableHoldoutUseV1` has private fields and cannot be directly
   constructed from an in-memory `FinalHoldoutRegistry` receipt. This is an
   adapter-origin proof, not independent proof that the supplied file is the
   deployment's authoritative storage namespace.
4. Build `LearningEvidenceVerifierV1` only from host-owned current trust state.
   Remote evidence may not choose its verifier, authority epoch, controller map
   or trusted keys.
5. Require distinct generator and evaluator principals, credentials, signing
   keys and controller identities. Verify signatures over the exact production
   signing payload.
6. For `SystemLongitudinal`, additionally verify an observer that is independent
   of **both** the generator and evaluator, plus real observed-time window evidence
   through the V4 durable-longitudinal path.
7. Preserve the decision, trust digest, authentication digest, durable holdout
   proof digest and exact candidate/source identity as audit evidence.
8. Pass the evidence to a separate selector/operator/release authority. An
   eligible decision alone never authorizes an effect.

## Durable holdout trust boundary

`DurableHoldoutUseV1` closes the API-level bypass in which an in-memory registry
receipt could be presented as production durability. It does **not** claim that
a local filesystem lock is a distributed consensus primitive.

A single-host deployment must provide exclusive file ownership, independently
retained current anchors, containing-directory durability, backup rollback
protection and crash recovery. A multi-host deployment MUST additionally provide
transactional compare-and-swap or equivalent linearizable ownership plus fencing
tokens/leases that prevent a stale owner from committing a second consumption.
Those guarantees belong to the host/storage service and require external
exact-candidate evidence; repository source cannot self-certify them.

## Evidence provenance

Repository CI evidence MUST bind, at minimum:

- exact source commit SHA and source tree SHA;
- pull-request base SHA where applicable;
- workflow identity, run ID and run attempt;
- locked Rust toolchain/build identity;
- hashes of `Cargo.lock`, this contract, the Lane E implementation matrix,
  traceability registry and production E2E source;
- exact-head or ordered-parent synthetic-merge identity;
- UTC generation time and an explicit evidence expiry/revalidation policy.

The JSON receipt is deliberately self-unsigned and keeps its signer/signature
fields null. Same-repository Lane E runs separately attest the receipt and its
coverage/stress/E2E subjects with GitHub's Sigstore-backed artifact attestation
service. That external attestation is the verifiable signer/provenance layer;
never copy an unverifiable identity into the receipt itself. Fork pull-request
runs cannot be treated as exact-candidate signed provenance until the candidate
is rerun in an authorized same-repository context.

## External gates that remain non-self-certifiable

The repository cannot prove live outcome honesty, organizational independence,
real future-calendar efficacy, production multi-host storage semantics,
subgroup/privacy review, backup non-resurrection, operator acceptance, canary,
selection, promotion or release. Those gates remain open until the responsible
external owner issues immutable evidence for the exact candidate.

## Change rule

Any change that adds a weaker externally callable eligibility path, removes the
durable proof from the production signing payload, weakens role/controller
separation, makes a final holdout reusable, grants evaluation effect authority,
or lets repository source mark an external gate closed is a production-contract
regression and must fail Lane E qualification.
