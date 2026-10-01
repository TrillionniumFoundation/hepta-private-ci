# `learning.operator` native implementation mapping

This file separates deterministic target construction, applicability admission,
sensor geometry, Bellman reference evaluation, simplest-sufficient tabular
learning and world-model estimation. No symbol in this crate is an online
policy, artifact selector or production writer.

## Compatibility and naming

The original public `train(TrainingRequest)` function is retained for source
compatibility, but it delegates to `build_targets`. Its actual behavior is a
bounded deterministic Bellman-target builder over caller-supplied continuation
values. It does not fit a neural network or prove a complete Bellman operator.

The qualification regularity gate consumes `OperatorRegularityAssessmentV1`
through its signed V2 admission API; the legacy `RegularityProfile` contains only
target-builder diagnostics and must not be interpreted as the Hölder/operator
qualification profile.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| build deterministic Bellman targets | `build_targets` (`train` compatibility alias) | `src/lib.rs` | implemented |
| validate structural smooth-axis applicability | `validate_applicability_certificate` | `src/reference.rs` | compatibility implemented |
| authenticate applicability for qualification | `validate_applicability_with_signed_evidence_v2` | `src/authenticated.rs` | implemented |
| build fixed sensor core | `build_sensor_core` | `src/reference.rs` | implemented |
| execute tabular Bellman reference | `evaluate_bellman_reference` | `src/reference.rs` | implemented |
| fit complete simplest-sufficient operator | `fit_tabular_operator` | `src/learned.rs` | implemented; evidence uniqueness canonical |
| bind frozen dataset to tabular training | `verify_tabular_operator_plan_v2` / `fit_tabular_operator_verified_v2` | `src/dataset_bound.rs` | implemented |
| predict only a fitted sensor/action cell | `predict_tabular_operator` | `src/learned.rs` | implemented |
| indexed structurally validated tabular prediction | `predict_tabular_operator_indexed_v2` | `src/learned_strict.rs` | implemented |
| validate rank/gain/shape/OOD/error budget | `admit_operator_regularity` | `src/reference.rs` | compatibility implemented |
| authenticate regularity for qualification | `admit_operator_regularity_with_signed_evidence_v2` | `src/authenticated.rs` | implemented |
| fit action-conditioned tabular dynamics | `fit_transition_model` | `src/world_model.rs` | implemented; evidence uniqueness canonical |
| bind frozen dataset to world-model training | `verify_world_model_dataset_v2` / `fit_transition_model_verified_v2` | `src/dataset_bound.rs` | implemented |
| predict supported transition distribution | `predict_transition` | `src/world_model.rs` | implemented |
| freeze owner-derived terminal-value rows | `freeze_terminal_cell_from_owner_v1` | `src/owner_terminal.rs` | implemented; bounded constant-state profile |
| authenticate the exact owner freeze request | `freeze_terminal_cell_from_signed_owner_v2` | `src/owner_terminal.rs` | implemented; owner verifies signature and derives the complete current cut |
| revalidate and fit owner-derived terminal-value rows | `fit_terminal_cell_from_owner_v1` | `src/owner_terminal.rs` | implemented; candidate only |

## Applicability and sensor core

`OperatorApplicabilityCertificateV1` binds the axis partition, domain, action
space, Hölder/Lipschitz profiles, ellipticity lower bound, control interval,
evaluator credential, fallback, expiry and decision. Its validator rejects
non-positive ellipticity, expired certificates and unsupported control intervals.
Reference and fit APIs do not invoke that validator automatically; the host must
compose authenticated applicability admission before qualification use.

`build_sensor_core` uses deterministic farthest-point insertion over a bounded,
canonical candidate design. It rejects duplicate identities, duplicate
coordinates, mixed dimensions and coordinates outside normalized `[0,1]`.
The V2 digest preimage for the native `OperatorSensorCoreManifestV1` binds every
canonical candidate's identity, dimension and coordinates, as well as selected
points, fill distance, separation radius, mesh ratio and a selected-coordinate
hull digest. V2 names the digest domain revision, not a new canonical wire schema
or Rust manifest type. Coverage is measured over the finite
candidate design, not every point in a continuous domain, and the hull digest is
not a membership oracle. Fill distance and mesh ratio round conservatively upward;
separation rounds downward. A zero separation radius or mesh ratio above the pilot
bound fails.

## Bellman reference, learned baseline and regularity

`evaluate_bellman_reference` requires the complete Cartesian product of the
registered sensor and action identities. Missing or duplicate cells fail. It
computes Q32 targets, deterministic greedy actions and action gaps; ties break by
canonical action ID. This reference is the oracle for any later learned model.
The reward and continuation values are supplied by the caller; this function
does not integrate a stochastic model or interpolate state coordinates. Its
receipt binds the canonical cells' reward, continuation, evidence and outputs.

`fit_tabular_operator` is the first source-complete trainable operator profile. Duplicate underlying `evidence_digest` values are rejected by the canonical fit itself, so relabelling one observation cannot increase a cell count. `fit_tabular_operator_strict_v2` remains an additive compatibility/error surface rather than a stronger hidden trust boundary.

`verify_tabular_operator_plan_v2` verifies a self-consistent
`DatasetSnapshotReceiptV3`, requires objective/dataset identity equality, and
requires training evidence to match the frozen `source_record_digests` exactly,
including cardinality. Duplicate evidence cannot acquire an opaque verified
token. Receipt hashing and membership do not authenticate a freeze issuer,
derive caller-supplied targets or observe current revocations. General
qualification hosts must supply those owner checks and target derivation;
the terminal profile below derives its targets from current owner records.
Only the opaque `VerifiedTabularOperatorPlanV2` enters
`fit_tabular_operator_verified_v2`.

It canonicalizes a frozen sensor-by-action grid, validates every sample and
requires a configurable positive minimum sample count for every grid cell. The
artifact stores each cell's mean, minimum, maximum, sample count and evidence
digest. Caller order cannot change the result. `predict_tabular_operator`
returns only an explicitly fitted cell; an unknown sensor or action is OOD. Its
output is marked both learned and synthetic and retains `DENY_ALL` authority.

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

The structural V1 API accepts a nonempty component list and checks its supplied
values; it cannot establish that omitted measurements were performed. Signed V2
qualification admission requires exactly model, sensor, reconstruction, network,
optimization, statistical and rollout components. A non-applicable component is
an explicit zero with evidence. A learned implementation must publish every
required component under a separately reviewed model/runtime profile.

## World-model baseline

`verify_world_model_dataset_v2` applies the same frozen-receipt and exact evidence-set rule to world-model rows. The compatibility `fit_transition_model` also rejects duplicate evidence globally, so a relabelled observation cannot alter transition counts, probabilities or mean outcome.

`fit_transition_model` builds a deterministic action-conditioned tabular model
from an immutable dataset. For every supported `(state, action)` it records the
mean bounded outcome and a branch distribution whose Q32 probabilities sum
exactly to one. `predict_transition` rejects unsupported pairs rather than
extrapolating and marks every prediction synthetic with deny-all authority.
Synthetic predictions cannot become independent factual outcomes.

The retained-model digest uses a V2 binary preimage while the native record type
remains `TabularWorldModelV1`. It binds model/dataset identity, every state/action
estimate, sample count, mean, canonical branch counts/probabilities and estimate
digest. Prediction structurally validates the mutable model and recomputes this
digest. Retained statistics cannot reconstruct the original sample-bound
estimate digest, and digest self-consistency does not authenticate provenance.

## Authenticated qualification admission

The V1 applicability and regularity functions are deterministic structural validators. They do not authenticate the caller merely because an evaluator ID or credential digest is non-zero. Qualification uses `validate_applicability_with_signed_evidence_v2` and `admit_operator_regularity_with_signed_evidence_v2`, which reuse the ledger-owned `LearningEvidenceVerifierV1`. The host supplies immutable trust state; both generator and evaluator sign the exact structural digest; principal/credential identity and controller separation are checked. The signature proves who attested exact bytes, not that the mathematical or empirical conclusion is scientifically correct.

## Host and external obligations

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
- `src/world_model_tests.rs`.

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
ceiling is 64 MiB, the grid is at most 262,144 cells and the existing sensor,
action and sample bounds apply. Unknown versions, trailing/truncated bytes,
noncanonical or incomplete grids and invalid statistics reject.

A host-selected `TabularPayloadPinV1` binds payload, original training-artifact,
objective, dataset, sensor, training-profile and generation identities.
`LoadedTabularOperatorV1::from_pinned_payload` checks that independent pin and
validates once; its private immutable state permits O(log n) repeated prediction.
Both public mutable-artifact predictors validate bounds, deny-all authority,
nonzero identities, complete canonical grids and attainable statistics on every
call before lookup. Validation uses bounded ordered collections and costs
`O(c log c + c log(s+a))` for `c` cells, `s` sensors and `a` actions, including
the duplicate-evidence set. It cannot reconstruct
sample-bound digests from sufficient statistics or authenticate a mutable
artifact. Independent payload pins and immutable loaded state supply that
different trust boundary and the repeated `O(log c)` prediction cost.

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

## Actual owner and product consumers

The compatible `freeze_terminal_cell_from_owner_v1` path requires trusted
receipt provenance. Its self-consistent V3 receipt cannot prove a historical
freeze issuer or inclusion policy. `freeze_terminal_cell_from_signed_owner_v2`
calls the real LedgerWriter owner to authenticate the exact signed freeze
request and derive its complete current source cut before terminal target
derivation. Both paths revalidate records at fit, including correction,
withdrawal, owner trust identity and time monotonicity. The signed-owner V2
frozen input retains its original attested payload and signature; fitting also
rechecks their expiry, credential validity and scheduled revocation at the fit
time. A later owner head is not substituted for the signed frozen cut.

`../hepta-agentd/src/cognitive_ranker.rs` composes a host-selected operator at the
cognitive read boundary, checks registry/payload identity and producer, and
revalidates authenticated CURRENT lineage before each read. An unsupported query
or any unsupported candidate causes whole-ranking abstention. The table has at
most 128 actions; the read API's larger input ceiling is not learned support.

`../hepta-agentd/src/shared_terminal_cell.rs` exposes
`AgentdSharedReplayHostV1::train/load/predict` for the narrow owner-derived terminal
profile and the additive `train_signed_owner_v2` entrypoint. The latter passes the
same signed-owner frozen input through a private shared source/fit helper;
compatibility `train` retains the trusted-receipt V1 boundary. Both revalidate
shared-source grants, exact Memory identity/revision/content support, ledger
corrections/revocations and registry lineage at their boundaries. The updated
async integration test is a source mapping, not an execution receipt here.
Neither explicit consumer composes the default freeze/train/independent-evaluate/
select/new-process-load learning loop. The generic simulator, continuous-domain
coverage and optional neural/tensor backend remain separate implementation work.
