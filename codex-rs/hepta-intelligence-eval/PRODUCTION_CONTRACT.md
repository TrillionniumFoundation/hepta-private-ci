# learning.eval production contract

This file is the normative public-surface and ownership contract for
`learning.eval`. The architectural guide, evidence-admission notes, native
mapping, Lane E matrix and execution dossier must not weaken this contract.

## Authority boundary

An evaluation can establish eligibility for a later independent selector. It
never selects, activates, promotes or releases a candidate. Every evaluation
decision remains `AuthorityPosture::DENY_ALL`.

External or production callers must enter through signature-verified admission.
Asserted `AuthenticatedPrincipalV1` values are not external authentication.

## API status

| Surface | Status | Permitted use |
|---|---|---|
| `decide_with_signed_evidence_v2` | **Production-required** | Ordinary qualification with preregistered V2 metric roles |
| `decide_with_signed_longitudinal_evidence_v3` | **Production-required for SystemLongitudinal** | Longitudinal qualification with signed observed-time evidence |
| `decide_with_signed_evidence_v1` | Compatibility signed admission | Existing non-longitudinal V1 all-superiority contracts only |
| `freeze_cross_fold_plan_v2` | Production plan freeze | Freeze metric roles before final-holdout observation |
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
5. verify current host-owned trust, role/controller separation, scope, objective,
   authority epoch, lifetime and revocation;
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

The host remains responsible for issuing fence generations/leases, authenticating
the store namespace, retention, backup/restore anti-rollback and physical
durability. A backup must not be able to manufacture a newer fence or current
authoritative state.

## Canonical product consumer

The repository's current signed consumer is
`codex-rs/hepta-intelligence/src/evaluated_shadow.rs::run_evaluated_shadow_v1`.
It calls `decide_with_signed_evidence_v2` before any host port is invoked and
retains evaluation eligibility as a deny-all input to later logic. This is a
real signed product composition path, but it does not by itself prove runtime
activation, target-host qualification or production longitudinal efficacy.

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
- coverage report digest and measured line coverage;
- repeated fenced-holdout stress result;
- signed cross-crate E2E test identity;
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
