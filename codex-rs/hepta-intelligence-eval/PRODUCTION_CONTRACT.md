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
| `evaluate_registered_temporal_comparison` | **Authenticated host execution ingress** | Rechecks the Generator plan and independent custody Observer's exact durable registration before consulting the provider or consuming holdout |
| `LockedFileProductEvidenceSinkV1` | **Single-host evidence adapter** | Preserves the full original signed request and exact native decision; fsync before ACK, exact replay, independent ACK rollback detection |
| `inspect_fixed_product_evaluation` (`fixed-eval-host`) | **Preflight only** | Reads protected masked source, the existing custody inspection and independent calibration result; publishes pending prerequisites without registration, gold release or qualification |
| `FencedFinalHoldoutOwnerV1` + `FinalHoldoutCasStoreV1` | **Production-required when multiple writers/hosts can contend** | Linearizable CAS, monotonic writer fencing and accepted-or-unknown reconciliation |
| `DurableFinalHoldoutJournalV1` | Single-host/cooperative-owner only | Local file durability when the host can guarantee exclusive namespace ownership |
| `trusted_inprocess::decide_independently{,_v2}` | **Trusted-only** | Explicit compatibility/test feature; never external qualification ingress |
| `trusted_inprocess::evaluate_legacy_inprocess_v1` | **Deprecated / trusted-only** | Legacy deterministic comparator; cannot be used as production qualification |

The `trusted_inprocess` module is absent from default builds and is available
only with the explicit `trusted-inprocess-eval` feature.

## Signed admission

For ordinary qualification:

1. freeze the V2 plan and metric roles before holdout observation;
2. authenticate the generator's frozen plan and the independent custody Observer's exact durable registration with current trust before holdout consumption;
3. durably consume the exact frozen plan through the authoritative holdout owner;
4. authenticate the evaluator's signature over the exact V2 evaluation payload;
5. verify current host-owned trust, scope, objective, authority epoch, lifetime and revocation; generator, evaluator and longitudinal observer must be pairwise distinct by principal, credential chain, signing key and controller;
6. run the bound statistical, support, safety and claim-scope checks;
7. persist the decision together with trust/authentication digests.

A `SystemLongitudinal` claim additionally requires V3 signed observer/time
evidence. Synthetic future IDs or virtual timestamps are never future-calendar
efficacy evidence.

## Archived machine-task input lineage

Statistical `principal_lineage` names a dependency component; it is
not restricted to humans and is separate from authenticated signing principals.
`FrozenTaskSourceLineageV1` freezes a label-free source graph with exact archive,
file, original row and record digests. Repeated tasks and transitively shared
dependencies stay in one principal/cluster, including unscored bridge tasks.
Source custody must authenticate the complete graph and bind its digest into the
frozen source/assumptions contract. A subset graph cannot replace that contract.
Graph separation does not prove causal exchangeability or eliminate undeclared
dependence; those remain independently reviewed assumptions of the frozen plan.

`bind_prediction` maps original native decision/receipt/run identities and actual
Unix-microsecond execution events into targets, training rows and clusters. The
task episode persists across reruns; recovery timestamps do not create new
samples. Archive publication time is never an execution timestamp. These pure
adapters issue no signatures, qualification, selections or longitudinal evidence.
An archived benchmark remains limited to its preregistered task/population and
does not establish pretraining disjointness or future online generalization.
The existing fenced holdout, independence, support and primary-superiority gates
apply unchanged through `ProductEvaluationRunnerV1`.

The fixed masked-source adapter freezes the complete **calibration batch**
dependency graph, including unscored bridge tasks and the original scored pair
digests. Its masked dependency-node digests are explicitly distinct from the
original gold claim's content digest. It does not register a product plan or
provide the complete training-plus-final graph needed by such a plan.

The behavior-policy estimator profile supports IPS, SNIPS and DR on a common
logged behavior/outcome cut. Separate classifier outputs and confidence values
cannot manufacture behavior probabilities. The distinct native
`PairedSupervisedPlanV1` profile handles fully observed paired benchmark tasks;
it does not reinterpret `OpeRow`, temporal receipts or existing signing domains.
The fixed host's existing inspection path still reports
`pending_supported_behavior_cut`: adding a library profile does not register
or consume its real holdout, supply missing execution evidence, or refresh an
expired independent calibration signature. Actual future execution of an
archived task can support its explicitly frozen benchmark population, without
establishing a system-longitudinal claim.

### Paired supervised benchmark V1

`freeze_paired_supervised_plan_v1` binds the complete source graph and every
training, calibration, final and unscored bridge membership. Final tasks must
exactly match the frozen eligible final fold. Clusters come from complete
source dependencies, including unscored bridges; callers cannot supply cluster
labels or change the eligible cohort after results. The fixed custody Observer
must verify these memberships against its original complete eligible manifest,
not offer an arbitrary registration or correctness-signing endpoint. Hashing a
caller-supplied graph does not establish completeness or scientific independence.
Prior fold model/prediction pins denote actual earlier training artifacts, not
invented future held-out prediction hashes.

`AuthenticatedPairedRegistrationV1` verifies the original Generator plan and
independent Observer registration, full graph, installed comparator, actual
registration time and current trust before even provider metadata access. The
same `ProductEvaluationRunnerV1` and fenced custody owner commit consumption.
Subsequent failure preserves this obligation. An idempotent retry cannot release
fresh holdout data; recovery uses the original sealed receipt and durable source
evidence. Real production holdout registration, release and immutable-program
policy remain custody-host responsibilities.

The Observer authenticates one common `PairedObservationCutV1` containing every
registered candidate/comparator request, exact inputs/runtime pins, original
native receipt digests and actual execution times. It attests correctness from
private gold; the Evaluator has no gold or Observer signing key. Terminal
ABSTAIN is an incorrect class with a frozen coverage cap. Censored executions,
unknown original monotonic cost or missing required observed metrics produce
`Incomplete`, never zero values or a post-hoc successful subset. Execution cost
is derived from original monotonic microseconds as Q32 milliseconds; replay does
not create a new measurement. Retention and unlearning metric IDs, bounds and
roles are mandatory, as are their nonzero original Observer-bound receipts.

Each metric uses task-weighted means and fixed-horizon bounded cluster
confidence intervals. Within a dependency component arbitrary dependence is
allowed; between components independence remains a preregistered, independently
reviewed assumption. For range R, component sizes n_g and N tasks, the radius
is conservatively rounded outward from
R * sqrt(log(4M/alpha) * sum(n_g^2) / (2N^2)), allocating the frozen family alpha
across both policies and M metrics. The integer logarithm upper bound and Q32
rounding reserve widen the interval; observed values outside frozen bounds are
rejected, not clipped. This follows the independent bounded-summand inequality
in [Hoeffding (1963), Theorem 2](https://repository.lib.ncsu.edu/bitstreams/d0e6ed15-3e1c-432f-8419-e55ffb6f3171/download),
applied to whole component sums. Component count alone is not an independence
proof, and an insufficient sample cannot qualify by changing the estimand later.

`paired_evaluation_signing_payload_v1` binds the original execution and distinct
profile domain. Existing V2 frozen PrimarySuperiority/noninferiority/absolute
safety gates remain unchanged; Generator, Observer and Evaluator controlling
authorities must be pairwise independent. Evaluator signatures are verified
against current trust before the existing evidence sink publishes a durable
nonzero ACK. `ProductPairedQualificationReceiptV1` is a separate sealed receipt;
it cannot be relabeled as a temporal qualification. It grants no selection,
activation or release authority. A Selector integration must explicitly verify
this profile and exact original evidence before selecting the model tuple.

The known 99 calibration rows, public development results and failed CPU
candidate are not newly registered final-holdout evidence. No native fixture
signature, library eligibility case or source-only test activates that candidate
or consumes the reserved private holdout.

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

The file evidence sink similarly requires an authority-approved regular file,
durable containing-directory creation, and an independently retained prior
publication ACK on recovery. Missing/torn/conflicting evidence is never an ACK.
It preserves every byte of the original signed request and the exact terminal
native decision; it does not authenticate arbitrary request bytes or create
eligibility itself. The host must supply the authenticated request used by the
runner. One execution has one immutable publication and a bounded record size.

## Canonical product evaluation chain

`ProductEvaluationRunnerV1` is the canonical evaluation composition. It freezes
the metric-to-estimator mapping into the bound estimand, consumes the final
holdout through `FencedFinalHoldoutOwnerV1`, and only then invokes the
`FinalHoldoutProviderV1::release_after_consumption` boundary. Candidate and
baseline metric intervals are derived from sealed `TemporalEvaluationReceipt`
and `ClusterOpeEstimate` receipts; a caller cannot submit replacement
`MetricGateV1` intervals. The runner builds the signed qualification bundle itself and returns success only after `ProductQualificationEvidenceSinkV1` returns a nonzero durable publication digest. The resulting `ProductQualificationReceiptV1` has a private integrity seal and binds the candidate, evaluator, objective, dataset, snapshot set, claim scope, signed decision and durable publication.

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
