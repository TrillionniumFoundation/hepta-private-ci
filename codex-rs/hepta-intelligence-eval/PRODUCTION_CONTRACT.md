# learning.eval production contract

**Module:** `learning.eval`
**Normative scope:** production candidate evaluation / qualification admission
**Authority:** evidence only; every decision remains `AuthorityPosture::DENY_ALL`
**Compatibility:** trusted legacy/in-process entry points are not production admission APIs

This document is the single normative production contract for the
`codex-hepta-intelligence-eval` crate. The stable module guide, native mapping,
evidence-admission notes, readiness overlay and qualification dossier provide
design and operating context; when they describe an API differently, this file
controls production ingress.

## 1. API status

| Surface | Status | Production rule |
| --- | --- | --- |
| `decide_with_signed_evidence_v2` | **Production-required** | Use for non-longitudinal qualification with frozen V2 metric roles and current host trust. |
| `decide_with_signed_longitudinal_evidence_v3` | **Production-required** | Use for `SystemLongitudinal`; V3 observed-time evidence is mandatory. |
| `evaluation_signing_payload_v2` / longitudinal V3 signing payload | **Production-required signer contract** | Sign exactly these bytes; never reconstruct an equivalent payload ad hoc. |
| `freeze_cross_fold_plan_v2` | **Production-required for new qualification plans** | Freeze metric roles, directions, margins, safety bounds, multiplicity and final holdout before outcomes are inspected. |
| `DurableFinalHoldoutJournalV1::consume_fenced` | **Production-required for multi-process/multi-host ownership** | Use a host-owned linearizable `HoldoutAnchorAuthorityV1`. |
| `DurableFinalHoldoutJournalV1::consume_single_host_trusted` | **Trusted-only** | Permitted only when one cooperative host owns the file and independently retained anchor. |
| `trusted_inprocess::evaluate_legacy_v1` | **Deprecated / trusted-only** | Available only with the explicit `trusted-inprocess-eval` feature. It cannot establish production admissibility. |
| `trusted_inprocess::decide_v1` / `decide_v2` | **Trusted-only compatibility/test** | Available only with the explicit feature. External or production ingress must not call these functions. |
| legacy `evaluate`, `decide_independently`, `decide_independently_v2` | **Not default-public** | Internal implementation details; no default cross-crate production surface. |

The crate is `publish = false`; the feature gate exists to make compatibility
use deliberate inside this repository, not to create a second production path.

## 2. Authentication and evaluator independence

`AuthenticatedPrincipalV1` is structural identity metadata. Its fields alone
are assertions. A production decision is admissible only after
`LearningEvidenceVerifierV1` validates signed evidence against the current
host-owned trust state.

The production signed path binds:

- generator signature to the exact frozen plan digest;
- evaluator signature to the exact evaluation payload, including V2 metric roles;
- objective, scope, authority epoch, signer key and trust digest;
- distinct generator/evaluator principal, credential chain and signing key;
- observed timing evidence for longitudinal claims.

A structurally valid unsigned bundle is therefore insufficient at production
ingress. Signature verification authenticates attribution; it does not by
itself prove estimator correctness, future efficacy, raw-data provenance or
operator acceptance.

## 3. Final-holdout ownership and fencing

The semantic holdout journal prevents adaptive reuse. Production durability has
two explicitly different trust models.

### Single trusted host

`consume_single_host_trusted` relies on the file lock plus an independently
retained anchor. It is valid only when all writers are cooperative and a single
host owns the journal. A cloned handle, hostile writer, split brain or rollback
outside that trust boundary is not covered.

### Multi-process or multi-host

`consume_fenced` requires a `HoldoutAnchorAuthorityV1` implementation whose
compare-and-swap is linearizable and durably monotonic for the journal binding.

The ordering is fail-closed:

1. validate the caller's expected anchor against both the external authority and
   local journal;
2. stage the semantic holdout transition without mutating storage;
3. reserve the next semantic anchor through external compare-and-swap;
4. append and sync the local journal;
5. expose the receipt only when the local anchor equals the reserved anchor.

If step 4 becomes indeterminate after the external reservation, the local handle
is poisoned. Availability is sacrificed: the advanced external anchor prevents a
second owner from consuming the same holdout, and operator reconciliation is
required. Production adapters must not reset the external anchor from a stale
journal copy.

The host implementation of `HoldoutAnchorAuthorityV1` should additionally bind
the authority record to authenticated storage, owner/fencing identity and an
append-only audit trail. This crate deliberately does not embed a networked
database or consensus service.

## 4. Qualification semantics

New qualification plans use V2 preregistered metric roles. At least one primary
objective is required. Primary superiority, non-inferiority constraints and
absolute constraints are frozen into the metric contract digest before final
holdout consumption.

The decision path also validates frozen-plan/use receipt equality, support,
multiplicity, safety bounds, snapshot/future-window requirements, retention and
unlearning evidence as required by claim scope. Eligibility is evidence for an
independent selector; it never selects, activates, deploys, promotes, merges or
releases a candidate.

## 5. Mandatory repository evidence

The Lane E workflow must qualify both the exact source candidate and the
ordered-parent synthetic merge candidate. For `learning.eval`, both paths must
run:

- closed-world operation/test traceability verification;
- locked all-target compilation;
- owner package tests, including durable holdout recovery and fencing tests;
- the signed V2 end-to-end qualification integration fixture;
- the signed evaluated-shadow runtime consumer E2E against the production V2 ingress;
- an adversarial stress audit that repeats the signed qualification suite at least
  eight times and retains its receipt/log;
- evaluator line coverage of at least 85%, retained as machine-readable coverage
  output;
- explicit trusted-feature compatibility tests so the compatibility path cannot
  silently rot into an accidental default surface;
- cross-crate Lane E and cross-language fault regressions;
- strict Clippy and rustfmt / clean-tree checks on both exact-source and
  synthetic-merge candidates.

Each successful candidate emits
`hepta.learning-eval.ci-evidence.v1`, binding source/candidate SHA and tree,
the digest of the relevant source/docs/workflow/Cargo.lock inputs, production
contract/native mapping/traceability digests, runner and Rust build identity,
workflow/run identity, generation time and an expiry no longer than 30 days.

On `main` push, the receipt must receive a GitHub Actions OIDC artifact
attestation. A retained JSON artifact without that attestation is diagnostic
evidence for a pull request, not a production provenance assertion.

## 6. Repository governance gate

Before calling repository-controlled production closure complete, `main` must
be protected by a GitHub branch protection rule or repository ruleset that
requires the Lane E exact-source and synthetic-merge checks and restricts
bypass. Workflow existence alone is not enforcement.

The current GitHub connector used by automated source remediation may not hold
repository administration permission. Source changes and CI evidence do not
self-certify this administrative control; its live GitHub configuration is the
authority.

## 7. Closure states

- `source_implemented_ci_pending`: source exists, but the exact candidate has
  not yet produced passing exact-source + synthetic-merge retained evidence.
- `source_implemented_ci_qualified`: repository-controlled source gates passed
  for the exact candidate and the evidence receipts are retained/attested as
  required. This state still grants no runtime/product acceptance.
- External gates remain open for live authenticated product inputs, durable
  production scheduler/anchor backend, real future-calendar windows,
  retention/change-point/privacy/power observations, unlearning/non-resurrection,
  independent operator acceptance, canary, selection, promotion and release.

A source CI state must never be relabelled as proof of real-world longitudinal
efficacy or product release readiness.
