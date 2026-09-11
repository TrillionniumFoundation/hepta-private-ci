# `learning.operator` native implementation mapping

This file separates deterministic target construction, applicability, sensor geometry, Bellman reference evaluation, strict simplest-sufficient learning and world-model estimation. No symbol is an online policy, selector or production writer.

## Compatibility and naming

`train(TrainingRequest)` is retained but delegates to `build_targets`; both are bounded target builders. V1 complete-grid tabular fit/predict remains readable. New qualification uses the strict V2 wrapper, which rejects relabelled duplicate source evidence and performs canonical indexed lookup.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| deterministic Bellman targets | `build_targets` (`train` alias) | `src/lib.rs` | implemented |
| smooth-axis applicability | `validate_applicability_certificate` | `src/reference.rs` | implemented |
| fixed sensor core | `build_sensor_core` | `src/reference.rs` | implemented |
| complete Bellman reference | `evaluate_bellman_reference` | `src/reference.rs` | implemented |
| regularity/error admission | `admit_operator_regularity` | `src/reference.rs` | implemented |
| action-conditioned dynamics fit | `fit_transition_model` | `src/world_model.rs` | implemented |
| supported dynamics prediction | `predict_transition` | `src/world_model.rs` | implemented |
| V1 complete-grid tabular fit | `fit_tabular_operator` | `src/learned.rs` | retained |
| V1 supported-cell prediction | `predict_tabular_operator` | `src/learned.rs` | retained |
| strict unique-evidence fit | `fit_tabular_operator_strict_v2` | `src/learned_strict.rs` | implemented |
| canonical indexed prediction | `predict_tabular_operator_indexed_v2` | `src/learned_strict.rs` | implemented |

## Applicability, learning and lookup

The applicability certificate binds axes, domain, actions, regularity profiles, ellipticity, control interval, independent evaluator, fallback and expiry. Sensor construction is deterministic and rejects duplicate identities, mixed dimensions and out-of-domain coordinates. Bellman reference requires the complete sensor/action Cartesian product and deterministic tie breaking.

The tabular artifact stores per-cell mean, minimum, maximum, sample count and evidence digest. Strict V2 first rejects duplicate evidence digests across all samples, preventing one underlying observation from being counted repeatedly under different sample IDs. Artifact cells are canonical by `(sensor_id, action_id)`; strict prediction rejects noncanonical artifacts and uses binary search. Unknown cells are OOD. Every prediction is learned/synthetic and deny-all.

The regularity gate intersects rank, reconstruction gain, monotonicity, positivity, Hölder/Lipschitz residuals, OOD false acceptance and every nonnegative error component. Unmeasured components cannot be omitted. Neural or low-rank candidates require a new immutable profile and independent comparison against deterministic and strict-tabular baselines.

## Host and external obligations

Product integration supplies authenticated applicability/regularity evidence, immutable dataset/artifact lineage, training code/profile/precision/device/runtime identity, target-host resource measurements, held-out calibration/change-point/OOD evidence, future-time retention/rollback evidence and a separate selector/process loader.

## Qualification mapping

Focused tests live in `src/lib_tests.rs`, `src/reference_tests.rs`, `src/world_model_tests.rs`, `src/learned_tests.rs` and `src/learned_strict.rs`. Cross-crate composition and public API linkage are compiled by `hepta-shadow-qualification`. Exact mappings are in `../../qualification/lane-e/TEST_TRACEABILITY.json`.
