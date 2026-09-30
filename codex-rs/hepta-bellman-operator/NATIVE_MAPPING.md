# `learning.operator` native implementation mapping

This file separates deterministic target construction, applicability admission,
sensor geometry, Bellman reference evaluation, simplest-sufficient tabular
learning and world-model estimation. No symbol in this crate is an online
policy, artifact selector or production writer.

## Compatibility and naming

The historical `train(TrainingRequest)` alias is retained under the non-default
`qualification-unverified-input` feature and delegates to `build_targets`. Its actual behavior is a
bounded deterministic Bellman-target builder over caller-supplied continuation
values. It does not fit a neural network or prove a complete Bellman operator.

The complete regularity gate uses `OperatorRegularityAssessmentV1`; the legacy
`RegularityProfile` contains only target-builder diagnostics and must not be
interpreted as the Hölder/operator qualification profile.

The native structs are owner-local candidate profiles. Sharing a name with a
registered V1 protocol does not establish canonical-JSON wire parity: the native
applicability certificate commits profile digests, and the sensor manifest
contains selected points, while the canonical schemas include additional
profile, horizon, construction and lifecycle fields. No canonical wire adapter
or wire round-trip proof is implemented here. `HEPTTB01` is a separate native
tabular payload, not `BellmanOperatorArtifactV1` canonical JSON.

The sensor manifest, Bellman-reference receipt, legacy target-artifact and
tabular training commitments now use V2 digest domains. They bind the full
canonical candidate design/input cells or minimum-sample training threshold;
target arithmetic uses signed nearest/ties-to-even. Public V1 struct names and
the `train` alias remain. New fits/rebuilt references have new exact identities
requiring independent admission; do not reinterpret a V1 commitment as V2.
The native payload magic remains `HEPTTB01`, and existing correctly pinned
tabular bytes remain readable under current selection and revocation checks.

## Default public surface

Cargo uses `src/authoritative_lib.rs`, whose explicit allowlist wraps the legacy
`src/lib.rs` implementation. Raw structural fitters, raw prediction helpers and
direct V3 owner verification/fitting are exported only under the non-default
`qualification-unverified-input` feature, in `compatibility`. Internal V3
primitives support the default single-use final-use capabilities.

Default read-only exports retain V1 pins/loaders for existing owner-bound
adapters. Those values validate immutable payload identity, not current selection
or live owner state. The evaluated Agentd ranker uses V2 pins and refreshes its
configured authority and registry witnesses at each read.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| classify admission stage and recovery action | `OperatorAdmissionStageV1` / `ClassifyOperatorAdmissionFailure::disposition` | `src/admission.rs` | implemented; no new authority |
| build deterministic Bellman targets | `build_targets` (`train` compatibility alias) | `src/lib.rs` | implemented |
| validate structural smooth-axis applicability | `validate_applicability_certificate` | `src/reference.rs` | compatibility implemented |
| authenticate applicability for qualification | `validate_applicability_with_signed_evidence_v2` | `src/authenticated.rs` | implemented |
| build fixed sensor core | `build_sensor_core` | `src/reference.rs` | implemented |
| execute tabular Bellman reference | `evaluate_bellman_reference` | `src/reference.rs` | implemented |
| fit complete simplest-sufficient operator | `fit_tabular_operator` | `src/learned.rs` | compatibility only; evidence uniqueness canonical |
| bind frozen dataset to tabular training | `verify_tabular_operator_plan_v3` / `fit_tabular_operator_verified_v3` | `src/dataset_bound.rs` | internal final-use primitive; direct export compatibility only |
| predict only a fitted sensor/action cell | `predict_tabular_operator` | `src/learned.rs` | compatibility only |
| predict a validated public tabular artifact by index | `predict_tabular_operator_indexed_v2` | `src/learned_strict.rs` | compatibility only; validates before lookup |
| encode and load an independently pinned tabular payload | `encode_tabular_payload_v1` / `LoadedTabularOperatorV1::from_pinned_payload` | `src/loaded.rs` | implemented; native payload only |
| validate rank/gain/shape/OOD/error budget | `admit_operator_regularity` | `src/reference.rs` | compatibility implemented |
| authenticate regularity for qualification | `admit_operator_regularity_with_signed_evidence_v2` | `src/authenticated.rs` | implemented |
| fit action-conditioned tabular dynamics | `fit_transition_model` | `src/world_model.rs` | compatibility only; evidence uniqueness canonical |
| bind frozen dataset to world-model training | `verify_world_model_dataset_v3` / `fit_transition_model_verified_v3` | `src/dataset_bound.rs` | internal final-use primitive; direct export compatibility only |
| predict supported transition distribution | `predict_transition` | `src/world_model.rs` | compatibility only |
| freeze terminal targets from current ledger-owner facts | `freeze_terminal_cell_from_owner_v1` | `src/owner_terminal.rs` | implemented; constant-state terminal profile |
| fit the frozen owner-derived terminal table | `fit_terminal_cell_from_owner_v1` | `src/owner_terminal.rs` | implemented; revalidates dataset at fit |
| derive canonical training/runtime identities | `TrainingProfileV1` / `WorldModelProfileV1` | `src/profiles.rs` | default implemented |
| issue/consume tabular final-use capability | `issue_tabular_final_use_capability_v1` / `fit_tabular_final_use_v1` | `src/final_use_hardening.rs` | default implemented; opaque single-use |
| issue/consume world-model final-use capability | `issue_world_model_final_use_capability_v1` / `fit_world_model_final_use_v1` | `src/final_use_hardening.rs` | default implemented; opaque single-use |
| build exact/reduced semantic sensor receipt | `build_sensor_core_qualified_v1` | `src/sensor_core_qualification.rs` | default implemented; finite-design geometry |
| load a complete immutable tabular pin | `LoadedTabularOperatorV2::from_pinned_payload_v2` | `src/loaded.rs` | default implemented; one-time identity validation |
| predict under the retained selection window | `SelectedTabularOperatorV1` / `OpaquePinnedWorldModelV1` | `src/final_use_selected.rs` | default selected wrappers; live owner refresh remains host-owned |
| sequence shadow stages | `coordinate_learning_operator_shadow_v1` | `../hepta-agentd/src/learning_operator_coordinator.rs` | generic coordinator implemented; actual owner ports/runtime caller absent |

## Applicability and sensor core

`OperatorApplicabilityCertificateV1` binds the axis partition, domain, action
space, Hölder/Lipschitz profiles, ellipticity lower bound, control interval,
independent evaluator credential, fallback, expiry and decision. Non-positive
ellipticity, expired certificates and unsupported control intervals fail before
operator evaluation.

`build_sensor_core` uses deterministic farthest-point insertion over a bounded,
canonical candidate design. It rejects duplicate identities, duplicate
coordinates, mixed dimensions and coordinates outside normalized `[0,1]`.
The manifest records selected points, finite-design fill distance, separation
radius, mesh ratio and a point-set commitment named `hull_digest`. Fill distance
is the maximum nearest-sensor distance over the supplied finite candidates; it
does not certify the supremum over a continuous domain in
`docs/learning/HOLDER_BELLMAN_SPEC.md`. Selecting every candidate gives zero
finite-design fill distance even if the continuous domain has holes. The hull
digest does not construct or test a geometric hull. A zero separation radius or
mesh ratio above the pilot bound fails. Continuous coverage, reconstruction and
hull-based OOD require a separate qualified profile; the tabular predictors only
test exact fitted sensor/action identity membership.
Fill distance and mesh ratio round upward and separation radius rounds downward
so fixed-point rounding does not understate finite-design coverage or mesh ratio.
The manifest additionally commits the full canonical candidate design, including
unselected points; a supplied design label alone is not the geometry commitment.

## Bellman reference, learned baseline and regularity

`evaluate_bellman_reference` requires the complete Cartesian product of the
registered sensor and action identities. Missing or duplicate cells fail. It
computes Q32 targets, deterministic greedy actions and action gaps; ties break by
canonical action ID. This reference is the oracle for any later learned model.

`fit_tabular_operator` is the first source-complete trainable operator profile. Duplicate underlying `evidence_digest` values are rejected by the canonical fit itself, so relabelling one observation cannot increase a cell count. `fit_tabular_operator_strict_v2` remains an additive compatibility/error surface rather than a stronger hidden trust boundary.

`verify_tabular_operator_plan_v3` is an internal qualification primitive: it borrows the actual durable `LedgerWriter`, verifies the `DatasetSnapshotReceiptV3`, requires objective/dataset identity equality and the exact frozen source-record set, authenticates canonical row semantics, and returns a single-use opaque value. `fit_tabular_operator_verified_v3` repeats current-owner, expiry, revocation, and signer checks immediately before fitting. Default external callers use final-use capability issue/consumption; direct V3
exports and V2 structural wrappers are compatibility inputs.

It canonicalizes a frozen sensor-by-action grid, validates every sample and
requires a configurable positive minimum sample count for every grid cell. The
artifact stores each cell's mean, minimum, maximum, sample count and evidence
digest. Caller order cannot change the result. `predict_tabular_operator`
returns only an explicitly fitted cell; an unknown sensor or action is OOD. Its
output is marked both learned and synthetic and retains `DENY_ALL` authority.
Raw, indexed and persisted inference share the same bounded artifact validation,
including complete rectangular support, unique cell evidence, positive counts,
ordered/attainable summary statistics and nonzero identity digests. This is
structural validation; an independent payload pin establishes expected bytes.

This profile deliberately implements the simplest sufficient learner. A neural
or low-rank tensor candidate is not required merely because the architecture
permits one. Such a candidate needs a new immutable training/runtime profile and
must independently justify itself against the deterministic and tabular
baselines.

`admit_operator_regularity` intersects:

- measured rank `1..64`;
- reconstruction gain at most `1.02`;
- zero required monotonicity and positivity violations;
- bounded Hölder and action-Lipschitz residuals;
- OOD false acceptance below `0.5%`;
- explicit non-negative error components with total normalized error at most
  `0.05`;
- independent approval when one component consumes more than half of the total.

Unmeasured components are not silently omitted. A learned implementation must
publish every required component under a separately reviewed model/runtime
profile.

## World-model baseline

`verify_world_model_dataset_v3` applies the owner-bound frozen-receipt, exact evidence-set, signed-row, and final-use revalidation rules to world-model rows. The compatibility `fit_transition_model` also rejects duplicate evidence globally, so a relabelled observation cannot alter transition counts, probabilities or mean outcome.

`fit_transition_model` builds a deterministic action-conditioned tabular model
from an immutable dataset. For every supported `(state, action)` it records the
mean bounded outcome and a branch distribution whose Q32 probabilities sum
exactly to one. `predict_transition` rejects unsupported pairs rather than
extrapolating and marks every prediction synthetic with deny-all authority.
Synthetic predictions cannot become independent factual outcomes.

The world-model fit retains a private inference seal: changing public fitted
statistics, identities or digests makes prediction reject. Public reads and API
names remain; external struct-literal construction is no longer supported.
V2 estimate/model digests commit the complete sorted training rows as well as
derived distributions. There is no persisted world-model wire format to migrate.

## Owner-derived terminal profile

`freeze_terminal_cell_from_owner_v1` reads the exact frozen record set from
`LedgerWriter`, requires homogeneous objective/run snapshot/action support and
terminal outcomes in one unit profile, and derives labels and values from those
owner facts. `fit_terminal_cell_from_owner_v1` rechecks current dataset validity
before fitting and rejects a fit clock earlier than freeze. Freeze rejects
outcomes whose observed/finalized/latest-observable time lies in the future.
This is stronger provenance than checking that caller-supplied
targets merely name every digest in a receipt. The generic verified V2 APIs bind
dataset identity and evidence membership; they do not resolve source records or
prove that supplied numeric labels equal the source events.

Agentd's `AgentdSharedReplayHostV1` composes the terminal profile with exact
shared-source permission, ledger revalidation and the existing artifact registry.
It is a bounded candidate consumer, not a default trainer, selector or live policy.

## Authenticated qualification admission

The V1 applicability and regularity functions are deterministic structural validators. They do not authenticate the caller merely because an evaluator ID or credential digest is non-zero. Qualification uses `validate_applicability_with_signed_evidence_v2` and `admit_operator_regularity_with_signed_evidence_v2`, which reuse the ledger-owned `LearningEvidenceVerifierV1`. The host supplies immutable trust state; both generator and evaluator sign the exact structural digest; principal/credential identity and controller separation are checked. The signature proves who attested exact bytes, not that the mathematical or empirical conclusion is scientifically correct.

## Host and external obligations

Repository-controlled work still includes real owner-port adapters and a named
runtime caller for the generic shadow coordinator, plus canonical protocol wire
adapters and their bounds/round-trip tests. Fixture-port coordinator tests and
signed component E2E exercise distinct boundaries; they do not prove one composed
default loop. The canonical status keeps `defaultLoopWired=false`.

A production integration must still provide:

1. authenticated applicability and regularity evidence;
2. immutable dataset and artifact lineage;
3. actual training code, profile, precision, device and runtime tuple;
4. target-host training and inference measurements;
5. held-out one-step and multistep calibration, change-point and OOD evidence;
6. independent future-time evaluation, retention and rollback;
7. a separate selector and process loader.

The simplest qualified implementation wins. A tabular or deterministic
reference satisfying the objective is preferred over an unnecessary neural
operator.

## Qualification mapping

Focused tests live in:

- `src/lib_tests.rs`;
- `src/reference_tests.rs`;
- `src/learned_tests.rs`;
- `src/world_model_tests.rs`;
- `src/world_model_v2_tests.rs` (exact moments, retained support, metadata integrity and input memory);
- `src/final_use_tests.rs` (selection windows and training trust);
- `src/final_use_hardening.rs` tests (deadline, elapsed time and final cancellation);
- `src/owner_dataset_tests.rs` (owner-bound V3 admission and full-path profile);
- `src/loaded_tests.rs` (immutable load and process rollback).

The generic coordinator's clock, persistence, cleanup and audit scenarios live in
`../hepta-agentd/src/learning_operator_coordinator_tests.rs`; the coordinator,
validation, rollback and public types have separate implementation modules.

The current-ledger provenance path is exercised by
`../hepta-agentd/tests/terminal_cell_owner.rs`, including the shared-source consumer.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.


## Persisted tabular candidate loading

`encode_tabular_payload_v1` emits a bounded owner-local `HEPTTB01` payload for the
existing `learning.artifacts` create-only storage APIs. It does not open another
store. The format contains model identity, generation, five digests and canonical
sensor/action cells with sample counts, Q32 means/minima/maxima and evidence.
All integers are big-endian; counts are bounded before allocation. The payload
ceiling is 64 MiB, the compatibility grid is at most 262,144 cells and can
represent up to 1,000,000 samples. Owner-authenticated V3 admission is separately
bounded to 4,096 signed rows and requires `sensors × actions × minimum_samples_per_cell ≤ 4096`. Unknown versions, trailing/truncated bytes,
noncanonical or incomplete grids and invalid statistics reject.

A host-selected `TabularPayloadPinV1` binds payload, original training-artifact,
objective, dataset, sensor, training-profile and generation identities.
`LoadedTabularOperatorV1::from_pinned_payload` checks that independent pin and
validates once; its private immutable state permits O(log n) repeated prediction.
The original indexed V2 function validates the public mutable artifact in O(n)
on every call, before its binary search. These are different cost profiles.

The original training digest includes samples not retained in these sufficient
statistics; it is retained rather than falsely reconstructed. The artifact owner
must first establish current selection, compatible manifests and non-revoked
lineage. A hash computed from received bytes is not independent admission.
`src/loaded_tests.rs` fits actual tabular targets and observes baseline, changed
candidate and the same predecessor payload in three separate processes. That is
an engineering reload/rollback test, not a production learning or future-gain
claim. Scientific evaluation and actual host wiring remain separate gates.

The existing `hepta-shadow-qualification` durable-learning integration target now
also composes the strict tabular learner with the existing `learning.artifacts`
create-only payload/snapshot APIs and `load_pinned_candidate`, then the private
loaded predictor. `tests/support/tabular_reload.rs` checks separate-process
baseline/candidate/original-predecessor predictions and refuses both a revoked
predecessor and its descendant under the current registry witness. The parent
holds expected payload/manifest/registry pins outside the files being inspected;
no extra artifact store or production selection is introduced. This is executable
cross-owner engineering qualification, not an authenticated external operator
acceptance, future-window efficacy result or live C1 deployment.

## Selection time and owner-currentness boundary

`LoadedTabularOperatorV2` is an immutable once-validated predictor. The opaque
selected tabular load produces `SelectedTabularOperatorV1`, which checks
`selection_observed_at <= now < selection_expires_at` on load and prediction.
The selected world model checks the same window. Tabular selection also binds
the trust digest retained at training; a later unrelated trust snapshot cannot
be attached to those bytes as if it had authorized the fit.

These static wrappers cannot discover subsequent source withdrawal, registry
movement, trust revocation or stop changes. The host refreshes actual owner
witnesses immediately before every final use, and the evaluated Agentd ranker
revalidates its currentness providers for every read. A timestamp-valid static
token alone does not establish current owner permission.

The final-use hardening layer retains one monotonic fit context from issuance.
It checks the issuance timestamp plus actual elapsed work against the exclusive
absolute deadline and checks cancellation before returning a completed candidate.
Stale caller timestamps cannot extend the deadline or hide final cancellation.
World-model admission also binds the request trust digest to the current owner
verifier rather than attaching an unrelated trust identity.

The bounded V2 world-model profile computes conditional variance from the exact
integer moments and retains confidence precision before rounding the variance.
Input-memory preflight counts owned identifier text and retained input capacity.
Private fitted statistics, branch storage and full prediction metadata are checked
against fit-owned integrity commitments before inference. These are bounded
source correctness properties, not external calibration or efficacy evidence.
