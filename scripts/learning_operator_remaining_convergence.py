#!/usr/bin/env python3
"""Apply the remaining learning.operator convergence atomically in CI.

The script is intentionally idempotent because an older one-shot qualification
run may complete first on the same authoritative branch.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def path(name: str) -> Path:
    return ROOT / name


def read(name: str) -> str:
    return path(name).read_text(encoding="utf-8")


def write(name: str, value: str) -> None:
    target = path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def replace_once(name: str, old: str, new: str) -> None:
    value = read(name)
    if new in value:
        return
    if old not in value:
        raise SystemExit(f"cannot patch {name}: missing marker {old[:120]!r}")
    write(name, value.replace(old, new, 1))


def replace_all(name: str, old: str, new: str) -> None:
    value = read(name)
    if old in value:
        write(name, value.replace(old, new))


def insert_after(name: str, marker: str, addition: str, guard: str) -> None:
    value = read(name)
    if guard in value:
        return
    if marker not in value:
        raise SystemExit(f"cannot patch {name}: missing insertion marker {marker!r}")
    write(name, value.replace(marker, marker + addition, 1))


def append_section(name: str, heading: str, body: str) -> None:
    value = read(name)
    if heading in value:
        return
    write(name, value.rstrip() + "\n\n" + heading + "\n\n" + body.strip() + "\n")


# ---------------------------------------------------------------------------
# Ledger V4 exports.
# ---------------------------------------------------------------------------
insert_after(
    "codex-rs/hepta-learning-ledger/src/lib.rs",
    "mod dataset_receipt_v3;\n",
    "mod dataset_receipt_v4;\n",
    "mod dataset_receipt_v4;",
)
insert_after(
    "codex-rs/hepta-learning-ledger/src/lib.rs",
    "pub use dataset_receipt_v3::verify_dataset_snapshot_receipt_v3;\n",
    """pub use dataset_receipt_v4::DATASET_SNAPSHOT_RECEIPT_SCHEMA_V4;
pub use dataset_receipt_v4::DatasetFreezePlanV4;
pub use dataset_receipt_v4::DatasetFreezeV4Error;
pub use dataset_receipt_v4::DatasetReceiptV4Error;
pub use dataset_receipt_v4::DatasetRowCommitmentV1;
pub use dataset_receipt_v4::DatasetSnapshotReceiptV4;
pub use dataset_receipt_v4::MAX_DATASET_RECEIPT_ROWS_V4;
pub use dataset_receipt_v4::dataset_freeze_signing_payload_v4;
pub use dataset_receipt_v4::dataset_snapshot_receipt_digest_v4;
pub use dataset_receipt_v4::freeze_dataset_from_ledger_v4;
pub use dataset_receipt_v4::issue_dataset_snapshot_receipt_v4;
pub use dataset_receipt_v4::verify_dataset_snapshot_receipt_against_ledger_v4;
pub use dataset_receipt_v4::verify_dataset_snapshot_receipt_v4;
""",
    "pub use dataset_receipt_v4::DatasetSnapshotReceiptV4;",
)

# ---------------------------------------------------------------------------
# Operator module/export surface and V1 feature boundary.
# ---------------------------------------------------------------------------
insert_after(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "mod authenticated;\n",
    "mod budget;\n",
    "mod budget;",
)
insert_after(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "mod dataset_bound;\n",
    "mod dataset_bound_v4;\n",
    "mod dataset_bound_v4;",
)
insert_after(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "mod reference;\n",
    "mod sensor_core_v2;\nmod tabular_v2;\n",
    "mod sensor_core_v2;",
)
insert_after(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "mod world_model;\n",
    "mod world_model_v2;\n",
    "mod world_model_v2;",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "pub use loaded::LoadedTabularOperatorV1;\n",
    """#[cfg(feature = "qualification-unverified-input")]
pub use loaded::LoadedTabularOperatorV1;
#[cfg(not(feature = "qualification-unverified-input"))]
#[allow(unused_imports)]
pub(crate) use loaded::LoadedTabularOperatorV1;
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "pub use loaded::TabularPayloadPinV1;\n",
    """#[cfg(feature = "qualification-unverified-input")]
pub use loaded::TabularPayloadPinV1;
#[cfg(not(feature = "qualification-unverified-input"))]
#[allow(unused_imports)]
pub(crate) use loaded::TabularPayloadPinV1;
""",
)
insert_after(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "pub use admission::OperatorRecoveryActionV1;\n",
    """pub use budget::OperatorResourceBudgetV1;
pub use budget::OperatorResourceKindV1;
pub use budget::OperatorWorkErrorV1;
pub use budget::OperatorWorkSnapshotV1;
pub(crate) use budget::OperatorWorkMeter;
pub(crate) use budget::checked_add;
pub(crate) use budget::checked_mul;
pub(crate) use budget::checked_u64;
pub(crate) use budget::sort_work;
""",
    "pub use budget::OperatorResourceBudgetV1;",
)
insert_after(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "pub use dataset_bound::world_model_training_signing_payload_v2;\n",
    """pub use dataset_bound_v4::VerifiedTabularOperatorPlanV4;
pub use dataset_bound_v4::VerifiedWorldModelPlanV4;
pub use dataset_bound_v4::fit_tabular_operator_verified_v4;
pub use dataset_bound_v4::fit_world_model_verified_v4;
pub use dataset_bound_v4::tabular_training_signing_payload_v4;
pub use dataset_bound_v4::verify_tabular_operator_plan_v4;
pub use dataset_bound_v4::verify_world_model_plan_v4;
pub use dataset_bound_v4::world_model_training_signing_payload_v4;
""",
    "pub use dataset_bound_v4::VerifiedTabularOperatorPlanV4;",
)
insert_after(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "pub use reference::validate_applicability_certificate;\n",
    """pub use sensor_core_v2::OperatorSensorCoreBuildReceiptV2;
pub use sensor_core_v2::SensorCoreBuildErrorV2;
pub use sensor_core_v2::SensorCoreExecutionProfileV2;
pub use sensor_core_v2::build_sensor_core_v2;
pub use tabular_v2::BudgetedTabularFitErrorV2;
pub use tabular_v2::TabularFitReceiptV2;
pub use tabular_v2::fit_tabular_operator_bounded_v2;
""",
    "pub use sensor_core_v2::build_sensor_core_v2;",
)
insert_after(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "pub(crate) use world_model::predict_transition;\n",
    """pub use world_model_v2::TransitionBranchV2;
pub use world_model_v2::TransitionEstimateV2;
pub use world_model_v2::WORLD_MODEL_ARTIFACT_SCHEMA_V2;
pub use world_model_v2::WorldModelArtifactV2;
pub use world_model_v2::WorldModelPlanV2;
pub use world_model_v2::WorldModelPredictionV2;
pub use world_model_v2::WorldModelUsePinV2;
pub use world_model_v2::WorldModelV2Error;
pub use world_model_v2::fit_world_model_v2;
pub use world_model_v2::predict_world_model_v2;
""",
    "pub use world_model_v2::WorldModelArtifactV2;",
)
replace_all(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "owner-bound V3 trainers require opaque inputs issued from an authenticated",
    "owner-bound V4 trainers require opaque inputs issued from an authenticated",
)

# Dataset helpers and unified error classification.
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "fn verify_tabular_plan_binding(\n",
    "pub(crate) fn verify_tabular_plan_binding(\n",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "fn verify_evidence_membership(\n",
    "pub(crate) fn verify_evidence_membership(\n",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "#[path = \"row_commitment.rs\"]\nmod row_commitment;\n",
    "#[path = \"row_commitment.rs\"]\npub(crate) mod row_commitment;\n",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """pub enum OwnerDatasetOperationV1 {
    FreezeDataset,
    ReadDatasetRecords,
    Snapshot,
    EncodeFreezePayload,
}
""",
    """pub enum OwnerDatasetOperationV1 {
    FreezeDataset,
    FreezeDatasetV4,
    ReadDatasetRecords,
    ReadDatasetRecordsV4,
    Snapshot,
    EncodeFreezePayload,
    EncodeFreezePayloadV4,
}
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """pub enum OperatorDatasetBindingError {
    DatasetReceipt(DatasetReceiptError),
    SignedEvidence(SignedEvidenceError),
""",
    """pub enum OperatorDatasetBindingError {
    DatasetReceipt(DatasetReceiptError),
    DatasetReceiptV4(codex_hepta_learning_ledger::DatasetReceiptV4Error),
    SignedEvidence(SignedEvidenceError),
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """    EvidenceSetMismatch,
    TrustContextMismatch,
""",
    """    EvidenceSetMismatch,
    RowCommitmentMismatch,
    TrustContextMismatch,
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """    Learned(StrictLearnedOperatorError),
    WorldModel(WorldModelError),
}
""",
    """    Learned(StrictLearnedOperatorError),
    BudgetedTabular(crate::BudgetedTabularFitErrorV2),
    WorldModel(WorldModelError),
    WorldModelV2(crate::WorldModelV2Error),
}
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """            Self::DatasetReceipt(error) => Some(error),
            Self::SignedEvidence(error) => Some(error),
""",
    """            Self::DatasetReceipt(error) => Some(error),
            Self::DatasetReceiptV4(error) => Some(error),
            Self::SignedEvidence(error) => Some(error),
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """            Self::Learned(error) => Some(error),
            Self::WorldModel(error) => Some(error),
""",
    """            Self::Learned(error) => Some(error),
            Self::BudgetedTabular(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::WorldModelV2(error) => Some(error),
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """            | Self::EvidenceSetMismatch
            | Self::TrustContextMismatch
""",
    """            | Self::EvidenceSetMismatch
            | Self::RowCommitmentMismatch
            | Self::TrustContextMismatch
""",
)
insert_after(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """impl From<DatasetReceiptError> for OperatorDatasetBindingError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::DatasetReceipt(value)
    }
}
""",
    """impl From<codex_hepta_learning_ledger::DatasetReceiptV4Error>
    for OperatorDatasetBindingError
{
    fn from(value: codex_hepta_learning_ledger::DatasetReceiptV4Error) -> Self {
        Self::DatasetReceiptV4(value)
    }
}
""",
    "impl From<codex_hepta_learning_ledger::DatasetReceiptV4Error>",
)

# Canonical row schema IDs and V4 access to canonicalizers.
replace_once(
    "codex-rs/hepta-bellman-operator/src/row_commitment.rs",
    "pub(super) fn canonical_tabular_row_semantics_v1(\n",
    "pub(crate) fn canonical_tabular_row_semantics_v1(\n",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/row_commitment.rs",
    "pub(super) fn canonical_world_model_row_semantics_v1(\n",
    "pub(crate) fn canonical_world_model_row_semantics_v1(\n",
)
insert_after(
    "codex-rs/hepta-bellman-operator/src/row_commitment.rs",
    "type BindingError = OperatorDatasetBindingError;\n",
    """

#[must_use]
pub(crate) fn tabular_row_schema_digest_v1() -> Digest32 {
    Digest32::of_bytes(b"hepta.operator.tabular-row-schema.v1")
}

#[must_use]
pub(crate) fn world_model_row_schema_digest_v1() -> Digest32 {
    Digest32::of_bytes(b"hepta.operator.world-model-row-schema.v1")
}
""",
    "pub(crate) fn tabular_row_schema_digest_v1()",
)

# Admission stage and actionable failure mapping.
replace_once(
    "codex-rs/hepta-bellman-operator/src/admission.rs",
    """    IndependentlyEvaluated,
    SelectedReadOnly,
}
""",
    """    IndependentlyEvaluated,
    SelectedOrRollbackAuthorized,
    LoadedReadOnly,
    /// Compatibility name retained for serialized diagnostics only.
    SelectedReadOnly,
}
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/admission.rs",
    """            Self::DatasetReceipt(_) | Self::TrustContextMismatch => OperatorFailureDispositionV1 {
""",
    """            Self::DatasetReceipt(_)
            | Self::DatasetReceiptV4(_)
            | Self::TrustContextMismatch => OperatorFailureDispositionV1 {
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/admission.rs",
    """            Self::Learned(_) | Self::WorldModel(_) => OperatorFailureDispositionV1 {
""",
    """            Self::Learned(_)
            | Self::WorldModel(_)
            | Self::WorldModelV2(_) => OperatorFailureDispositionV1 {
""",
)
replace_once(
    "codex-rs/hepta-bellman-operator/src/admission.rs",
    """            Self::DatasetDigestMismatch
            | Self::ObjectiveDigestMismatch
""",
    """            Self::DatasetDigestMismatch
            | Self::ObjectiveDigestMismatch
            | Self::RowCommitmentMismatch
            | Self::BudgetedTabular(_)
""",
)

# Cross-target deterministic digest encoding for sensor profile limits.
replace_all(
    "codex-rs/hepta-bellman-operator/src/sensor_core_v2.rs",
    "receipt_bytes.extend_from_slice(&profile.exact_candidate_limit.to_be_bytes());",
    "receipt_bytes.extend_from_slice(&u64::try_from(profile.exact_candidate_limit).map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?.to_be_bytes());",
)
replace_all(
    "codex-rs/hepta-bellman-operator/src/sensor_core_v2.rs",
    "receipt_bytes.extend_from_slice(&profile.maximum_working_candidates.to_be_bytes());",
    "receipt_bytes.extend_from_slice(&u64::try_from(profile.maximum_working_candidates).map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?.to_be_bytes());",
)

# ---------------------------------------------------------------------------
# Concurrent immutable artifact use and Agentd RCU/telemetry.
# ---------------------------------------------------------------------------
insert_after(
    "codex-rs/hepta-learning-artifacts/src/lib.rs",
    "mod pinned;\n",
    "mod pinned_concurrent;\n",
    "mod pinned_concurrent;",
)
insert_after(
    "codex-rs/hepta-learning-artifacts/src/lib.rs",
    "pub use pinned::load_pinned_candidate;\n",
    "pub use pinned_concurrent::ConcurrentRevalidatingCandidate;\n",
    "pub use pinned_concurrent::ConcurrentRevalidatingCandidate;",
)
replace_once(
    "codex-rs/hepta-agentd/Cargo.toml",
    "[dependencies]\nanyhow = { workspace = true }\n",
    "[dependencies]\nanyhow = { workspace = true }\narc-swap = { workspace = true }\n",
)

ranker = "codex-rs/hepta-agentd/src/cognitive_ranker.rs"
replace_once(ranker, "use std::sync::Mutex;\n", "use std::time::Instant;\n")
replace_once(
    ranker,
    "use codex_hepta_learning_artifacts::RevalidatingCandidate;\n",
    "use codex_hepta_learning_artifacts::ConcurrentRevalidatingCandidate;\n",
)
replace_once(
    ranker,
    """#[path = "cognitive_ranker_cache.rs"]
mod candidate_cache;
use candidate_cache::with_exclusive_candidate;
""",
    """#[path = "cognitive_ranker_metrics.rs"]
mod metrics;
pub use metrics::CognitiveRankerMetricsSnapshotV1;
use metrics::CognitiveRankerMetrics;
#[path = "cognitive_ranker_reload.rs"]
mod reload;
pub use reload::ReloadableCognitiveRanker;
""",
)
replace_once(
    ranker,
    """    current: Arc<dyn CurrentCognitiveRegistry>,
    cache: Mutex<Option<RevalidatingCandidate>>,
}
""",
    """    current: Arc<dyn CurrentCognitiveRegistry>,
    candidate: ConcurrentRevalidatingCandidate,
    metrics: CognitiveRankerMetrics,
}
""",
)
replace_once(
    ranker,
    """            current,
            cache: Mutex::new(Some(RevalidatingCandidate::new(candidate))),
        };
""",
    """            current,
            candidate: ConcurrentRevalidatingCandidate::new(candidate),
            metrics: CognitiveRankerMetrics::default(),
        };
""",
)
replace_once(
    ranker,
    """        if self.admission.is_some() {
            OperatorAdmissionStageV1::SelectedReadOnly
        } else {
""",
    """        if self.admission.is_some() {
            OperatorAdmissionStageV1::LoadedReadOnly
        } else {
""",
)
insert_after(
    ranker,
    """    pub fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        if self.admission.is_some() {
            OperatorAdmissionStageV1::LoadedReadOnly
        } else {
            OperatorAdmissionStageV1::StructurallyValidated
        }
    }
""",
    """

    #[must_use]
    pub fn metrics(&self) -> CognitiveRankerMetricsSnapshotV1 {
        self.metrics.snapshot()
    }
""",
    "pub fn metrics(&self) -> CognitiveRankerMetricsSnapshotV1",
)
replace_once(
    ranker,
    """    fn with_current<T>(&self, consume: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
        with_exclusive_candidate(&self.cache, |candidate| {
            // The provider cannot inject a bare file/receipt: the artifact
            // authority must first issue an opaque verified CURRENT view.
            // Both owner I/O and immutable model lookups run outside the mutex.
            let current = self.current.current()?;
            if let Some(admission) = &self.admission {
                admission.revalidate(&current)?;
            }
            candidate
                .with_current(current, |_| consume())
                .map_err(|error| error.to_string())?
        })
    }
""",
    """    fn with_current<T>(&self, consume: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
        let started = Instant::now();
        // whole_batch_abstains are recorded by rank(); trust/currentness failures
        // close this immutable candidate and require an explicit admitted reload.
        let current = match self.current.current() {
            Ok(current) => current,
            Err(error) => {
                self.candidate.close();
                self.metrics.terminal_close();
                self.metrics.revalidated(started.elapsed());
                return Err(error);
            }
        };
        if let Some(admission) = &self.admission {
            if let Err(error) = admission.revalidate(&current) {
                self.candidate.close();
                self.metrics.terminal_close();
                self.metrics.revalidated(started.elapsed());
                return Err(error);
            }
        }
        let result = self
            .candidate
            .with_current(current, |_| consume())
            .map_err(|error| error.to_string());
        self.metrics.revalidated(started.elapsed());
        match result {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(error)) => {
                self.candidate.close();
                self.metrics.terminal_close();
                Err(error)
            }
            Err(error) => {
                self.metrics.terminal_close();
                Err(error)
            }
        }
    }
""",
)
replace_once(
    ranker,
    """        let sensor = cognitive_sensor_id(query)?;
        self.with_current(|| {
""",
    """        self.metrics.begin_rank(items.len());
        let sensor = cognitive_sensor_id(query)?;
        self.with_current(|| {
""",
)
replace_once(
    ranker,
    """                    Ok(prediction) => scored.push((index, prediction.value.raw())),
""",
    """                    Ok(prediction) => {
                        self.metrics.supported_item();
                        scored.push((index, prediction.value.raw()));
                    }
""",
)
replace_once(
    ranker,
    """                    Err(TabularPayloadError::UnsupportedCell) => {
                        return Ok(CognitiveRankObservation {
""",
    """                    Err(TabularPayloadError::UnsupportedCell) => {
                        self.metrics.abstained(item.revision > 1);
                        return Ok(CognitiveRankObservation {
""",
)
replace_once(
    ranker,
    """            Ok(CognitiveRankObservation {
                policy_digest: self.policy_digest,
""",
    """            self.metrics.applied();
            Ok(CognitiveRankObservation {
                policy_digest: self.policy_digest,
""",
)

admission = "codex-rs/hepta-agentd/src/cognitive_ranker_admission.rs"
replace_once(admission, "use std::sync::Mutex;\n", "")
insert_after(
    admission,
    "use codex_hepta_learning_artifacts::ArtifactKind;\n",
    "use codex_hepta_learning_artifacts::ConcurrentRevalidatingCandidate;\n",
    "use codex_hepta_learning_artifacts::ConcurrentRevalidatingCandidate;",
)
insert_after(
    admission,
    "use super::PinnedCognitiveRanker;\n",
    "use super::CognitiveRankerMetrics;\n",
    "use super::CognitiveRankerMetrics;",
)
replace_once(
    admission,
    """            current,
            cache: Mutex::new(Some(RevalidatingCandidate::new(candidate))),
            admission: Some(EvaluatedUse {
""",
    """            current,
            candidate: ConcurrentRevalidatingCandidate::new(candidate),
            metrics: CognitiveRankerMetrics::default(),
            admission: Some(EvaluatedUse {
""",
)

# Export the new telemetry/RCU surfaces.
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    """pub use cognitive_ranker::CurrentCognitiveRegistry;
pub use cognitive_ranker::PinnedCognitiveRanker;
""",
    """pub use cognitive_ranker::CognitiveRankerMetricsSnapshotV1;
pub use cognitive_ranker::CurrentCognitiveRegistry;
pub use cognitive_ranker::PinnedCognitiveRanker;
pub use cognitive_ranker::ReloadableCognitiveRanker;
""",
)

# Migrate the non-test Agentd terminal consumer off the incomplete V1 pin.
terminal = "codex-rs/hepta-agentd/src/shared_terminal_cell.rs"
replace_once(
    terminal,
    "use codex_hepta_bellman_operator::LoadedTabularOperatorV1;\n",
    "use codex_hepta_bellman_operator::LoadedTabularOperatorV2;\n",
)
replace_once(
    terminal,
    "use codex_hepta_bellman_operator::TabularPayloadPinV1;\n",
    """use codex_hepta_bellman_operator::TABULAR_ARTIFACT_SCHEMA_V1;
use codex_hepta_bellman_operator::TABULAR_PAYLOAD_SCHEMA_V1;
use codex_hepta_bellman_operator::TabularPayloadPinV2;
""",
)
replace_once(
    terminal,
    "loaded: LoadedTabularOperatorV1,\n",
    "loaded: LoadedTabularOperatorV2,\n",
)
replace_once(
    terminal,
    """        let pin = TabularPayloadPinV1 {
            payload_digest: Digest32::of_bytes(payload),
            artifact_digest: artifact.artifact_digest,
            objective_digest: artifact.objective_digest,
            dataset_digest: artifact.dataset_digest,
            sensor_core_digest: artifact.sensor_core_digest,
            training_profile_digest: artifact.training_profile_digest,
            generation: artifact.generation,
        };
        let loaded = LoadedTabularOperatorV1::from_pinned_payload(payload, &pin)
""",
    """        let pin = TabularPayloadPinV2 {
            artifact_id: artifact.artifact_id.clone(),
            producer_id: artifact.producer_id.clone(),
            artifact_schema_version: TABULAR_ARTIFACT_SCHEMA_V1,
            payload_schema_version: TABULAR_PAYLOAD_SCHEMA_V1,
            payload_digest: Digest32::of_bytes(payload),
            artifact_digest: artifact.artifact_digest,
            objective_digest: artifact.objective_digest,
            dataset_digest: artifact.dataset_digest,
            sensor_core_digest: artifact.sensor_core_digest,
            training_profile_digest: artifact.training_profile_digest,
            runtime_profile_digest: registry
                .manifest(&artifact.artifact_id)
                .ok_or(SharedTerminalCellError::Binding("artifact not registered"))?
                .compatibility_digest,
            trust_digest: ledger.verifier().trust_digest(),
            registry_head_digest: registry.snapshot().head_digest,
            authority_epoch: ledger.verifier().authority_epoch(),
            generation: artifact.generation,
        };
        let loaded = LoadedTabularOperatorV2::from_pinned_payload_v2(payload, &pin)
""",
)

# Exercise legal concurrent reads and exported telemetry on the real ranker path.
append_section(
    "codex-rs/hepta-agentd/src/cognitive_ranker_tests.rs",
    "#[test]\nfn immutable_candidate_supports_concurrent_current_reads_and_metrics()",
    r'''{
    let original = vec![item("one"), item("two")];
    let fixture = fixture(&original, &[0, 10]);
    let ranker = Arc::clone(&fixture.ranker);
    let mut workers = Vec::new();
    for _ in 0..8 {
        let ranker = Arc::clone(&ranker);
        let values = original.clone();
        workers.push(std::thread::spawn(move || {
            let mut values = values;
            ranker.rank(&owner(), 1, "lemon", &mut values).unwrap();
            values
        }));
    }
    for worker in workers {
        assert_eq!(worker.join().unwrap(), vec![original[1].clone(), original[0].clone()]);
    }
    let metrics = ranker.metrics();
    assert!(metrics.exact_query_requests >= 8);
    assert!(metrics.ranking_applied >= 8);
    assert!(metrics.registry_revalidation_count >= 8);
    assert_eq!(metrics.whole_batch_abstains, 0);
}''',
)

# ---------------------------------------------------------------------------
# Documentation: one current path, explicit migration, sequence, operations.
# ---------------------------------------------------------------------------
write(
    "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
    """# learning.operator admission contract

The production qualification path is a closed type-state chain. Callers cannot
construct or deserialize the opaque transitions:

```text
RawRows
→ StructurallyValidated
→ SourceAuthenticated
→ CurrentAtUse
→ VerifiedTrainingInput
→ ImmutableCandidate
→ IndependentlyEvaluated
→ SelectedOrRollbackAuthorized
→ LoadedReadOnly
```

## Authoritative types

| State | Owner-issued evidence/type |
|---|---|
| RawRows | untrusted caller data; no training authority |
| StructurallyValidated | bounded canonical row validation |
| SourceAuthenticated | `DatasetSnapshotReceiptV4` plus evaluator/observer signatures |
| CurrentAtUse | `LedgerWriter::freeze_dataset_v4` replay and revocation/current-owner verification |
| VerifiedTrainingInput | `VerifiedTabularOperatorPlanV4` or `VerifiedWorldModelPlanV4` |
| ImmutableCandidate | `TabularFitReceiptV2` or `WorldModelArtifactV2`, always `DENY_ALL` |
| IndependentlyEvaluated | learning.eval verified evidence, never generator self-approval |
| SelectedOrRollbackAuthorized | independently verified selection or rollback receipt |
| LoadedReadOnly | `TabularPayloadPinV2` → `LoadedTabularOperatorV2` |

`DatasetSnapshotReceiptV3`, raw fitters, `TabularPayloadPinV1`, and
`LoadedTabularOperatorV1` are compatibility/qualification-only surfaces. A
production host cannot import the V1 pin/loader without the explicit
`qualification-unverified-input` feature.

## Failure disposition

| Failure | Scope | Required action |
|---|---|---|
| malformed request, row commitment mismatch, resource budget | request | correct request; do not retry unchanged |
| expired/revoked dataset evidence | candidate | obtain a fresh owner-issued V4 receipt |
| invalid candidate bytes or evaluation | candidate | reject candidate |
| registry frontier or runtime pin changed | consumer | explicit independently admitted reload |
| unsupported cell | request decision | abstain; candidate remains eligible |
| owner corruption, clock regression, authority failure | consumer | stop consumer and page operator |

## End-to-end sequence

```mermaid
sequenceDiagram
  participant L as learning.ledger owner
  participant O as learning.operator
  participant E as learning.eval
  participant A as learning.artifacts
  participant H as Agentd host
  L->>O: DatasetSnapshotReceiptV4 + signed exact row commitment
  O->>L: final-use revalidation under current owner/revocation state
  O->>O: budgeted deterministic fit
  O->>A: immutable DENY_ALL candidate
  E->>A: independently evaluated evidence
  A->>H: selected/rollback-authorized manifest + current registry view
  H->>H: TabularPayloadPinV2 → LoadedTabularOperatorV2
  H->>A: revalidate current registry before every read
  H-->>H: read-only rank or explicit abstention
```

No step grants effect execution, activation, promotion, or release authority.
""",
)

write(
    "docs/modules/learning.operator/COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md",
    """# learning.operator compatibility, resource, and shadow policy

Machine-readable authority: `SCHEMA_COMPATIBILITY.json`.

## V1/V2/V3/V4 migration matrix

| Version | Meaning | Production status | Migration |
|---|---|---|---|
| V1 | structural/raw fit and incomplete payload pin | qualification compatibility only | re-freeze V4, evaluate, select, load V2 |
| V2 | structural dataset wrappers and complete `TabularPayloadPinV2` / `LoadedTabularOperatorV2` | payload identity usable; rows not production-admitted | retain pin and replace input with V4 |
| V3 | owner-authenticated frozen source set | compatibility; lacks self-describing row envelope | issue additive V4 row schema/root/profile/window |
| V4 | `DatasetSnapshotReceiptV4` plus opaque verified input | production qualification path | no downgrade |

## Resource contract

Every V4 fit receives one `OperatorResourceBudgetV1`: maximum operations,
estimated resident bytes, and an absolute elapsed deadline. Sensor V2 uses
canonical coordinate fingerprints instead of an O(N²D) duplicate scan,
maintains separation during FPS, and records deterministic approximation for
large design sets. Tabular/world fitting preflights cell, sample, byte, and sort
work and checks the same deadline through long loops.

Source ceilings are not target-host measurements. Actual p50/p95/p99, resident
and transient peaks, compiler, target, device, and workload evidence remain an
external qualification gate and must not be invented by repository prose.

## WorldModelArtifactV2

V2 binds support threshold, conditional variance and empirical confidence,
train/holdout/future-window identities, one-step and multistep calibration, OOD
false acceptance, drift/change point, row commitment, runtime/trust/registry
pins, retention/expiry, authority epoch, and predecessor identity. Estimates
are sorted for binary lookup and branch arrays are immutable shared storage.
Predictions remain synthetic and `DENY_ALL`.

## Shadow policy and telemetry

The current safe policy keeps whole-batch abstention when any exact query/action
cell is unsupported. It is now measured rather than assumed. Required metrics:
exact-query requests, requested/supported items, whole-batch abstains,
ranking-applied count, registry revalidation latency, RCU reload count,
terminal-close count, and revised-item abstains. Future-window objective gain is
external evidence, never a repository-generated constant.
""",
)

write(
    "docs/modules/learning.operator/OPERATIONS_RUNBOOK.md",
    """# learning.operator operations runbook

## Normal admission

Resolve the exact candidate SHA, verify `DatasetSnapshotReceiptV4`, enforce the
resource profile, require independent evaluation/selection, and load only with
`TabularPayloadPinV2` / `LoadedTabularOperatorV2`. Keep the PR Draft until exact
head, current main, deterministic synthetic merge, relevant cross-platform,
security/audit, and separate-process rollback checks all pass.

## Failure actions

- **key rotation**: stop new admission; reload only after both ledger trust and
  artifact CURRENT trust are current and the authority epoch advances.
- **revocation**: invalidate the current epoch immediately; close the consumer;
  do not revive from an older registry snapshot.
- **clock regression**: stop the consumer and investigate trusted-time state;
  never clamp the clock or silently retry.
- **registry unavailable**: fail closed, increment terminal-close telemetry, and
  require an explicit independently admitted reload after recovery.
- **row/resource error**: reject the unchanged request; do not classify it as a
  transient dependency retry.
- **unsupported cell**: abstain only from that ranking decision; do not grant a
  fabricated propensity or invalidate otherwise current immutable bytes.

## Telemetry and alert thresholds

Page immediately on any authority/clock error, registry frontier fork, or
terminal close. Alert when whole-batch abstention exceeds 5% over a minimum 100
requests, p95 registry revalidation exceeds the registered host budget, or
revised-item abstention doubles over the previous accepted window. These are
operational defaults, not efficacy claims; a target-host profile may tighten
but never silently loosen them.

## Canary, rollback, promotion, emergency stop

1. **canary**: publish only an independently selected immutable candidate to a
   bounded read-only cohort; no effect authority.
2. **rollback**: use a fresh independently authorized rollback receipt and the
   immutable predecessor bytes under current revocations; RCU-publish the new
   loaded generation.
3. **promotion**: requires external operator acceptance and future-window
   evidence bound to the same source/workflow/lock/target tuple.
4. **emergency stop**: revoke/quarantine the artifact, advance the current
   registry epoch, close all consumers, and preserve diagnostics. Never repair
   by restoring an old snapshot.

## Qualification evidence

The generated index is
`qualification/lane-e/learning-operator-qualification-manifest.json`. It binds
source SHA/tree, workflow blob, Cargo.lock digest, compiler/target evidence,
deterministic synthetic merge SHA/tree, and test-artifact digest. The field
`independentAcceptanceIdentity` remains null until an external owner signs it.
""",
)

for document in [
    "docs/modules/learning.operator/TECHNICAL.md",
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
]:
    append_section(
        document,
        "## Current V4/V2 production qualification amendment",
        """The authoritative production qualification path is now
`DatasetSnapshotReceiptV4` → opaque V4 verified training input → budgeted
immutable candidate → independent evaluation/selection or rollback →
`TabularPayloadPinV2` → `LoadedTabularOperatorV2`. V3 receipt/training and V1
pin/loader paths remain explicit compatibility surfaces only. Sensor-core V2,
budgeted tabular V2, and `WorldModelArtifactV2` implement bounded termination,
row commitment, runtime/trust/registry identity, retention, and shared immutable
lookup. Agentd uses concurrent final-use revalidation and exposes an ArcSwap RCU
reload surface plus actionable coverage/abstention/currentness telemetry.

Repository evidence does not self-issue independent scientific acceptance,
target-host benchmark, future-window efficacy, operator acceptance, canary,
promotion, activation, or release. See `docs/modules/learning.operator/ADMISSION_CONTRACT.md`,
`COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md`, and `OPERATIONS_RUNBOOK.md`.
""",
    )

# Keep prominent old prose honest without erasing historical compatibility detail.
replace_all(
    "docs/modules/learning.operator/TECHNICAL.md",
    "Qualification training first verifies a self-describing `DatasetSnapshotReceiptV3`",
    "Production qualification training first verifies a self-describing `DatasetSnapshotReceiptV4`",
)
replace_all(
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    "An explicit Agentd `PinnedCognitiveRanker` already composes a selected, pinned `LoadedTabularOperatorV1`",
    "An explicit Agentd `PinnedCognitiveRanker` composes a selected, fully pinned `LoadedTabularOperatorV2`",
)

# Implementation map additions; exact SHA/tree are rebound after the source commit.
map_path = "docs/modules/learning.operator/IMPLEMENTATION_MAP.json"
implementation = json.loads(read(map_path))
new_operations = [
    ("build_sensor_core_v2", "build_sensor_core_v2", "codex-rs/hepta-bellman-operator/src/sensor_core_v2.rs"),
    ("verify_tabular_operator_plan_v4", "verify_tabular_operator_plan_v4", "codex-rs/hepta-bellman-operator/src/dataset_bound_v4.rs"),
    ("fit_tabular_operator_verified_v4", "fit_tabular_operator_verified_v4", "codex-rs/hepta-bellman-operator/src/dataset_bound_v4.rs"),
    ("verify_world_model_plan_v4", "verify_world_model_plan_v4", "codex-rs/hepta-bellman-operator/src/dataset_bound_v4.rs"),
    ("fit_world_model_verified_v4", "fit_world_model_verified_v4", "codex-rs/hepta-bellman-operator/src/dataset_bound_v4.rs"),
    ("load_pinned_tabular_operator_v2", "LoadedTabularOperatorV2::from_pinned_payload_v2", "codex-rs/hepta-bellman-operator/src/loaded.rs"),
    ("concurrent_current_candidate_use", "ConcurrentRevalidatingCandidate::with_current", "codex-rs/hepta-learning-artifacts/src/pinned_concurrent.rs"),
]
known = {row["operation"] for row in implementation["operations"]}
for operation, symbol, source in new_operations:
    if operation not in known:
        implementation["operations"].append(
            {
                "operation": operation,
                "designOperation": operation,
                "nativeSymbol": symbol,
                "sourcePath": source,
                "mappingClass": "owner_native",
                "delegatedCallees": [],
                "tests": [],
                "state": "source_implemented_requires_exact_candidate_evidence",
                "authority": "none",
                "sourcePathExists": True,
            }
        )
implementation["productCallerState"] = (
    "explicit_concurrent_v2_read_consumer_composed_default_learning_loop_absent"
)
implementation["repositoryControlledGaps"] = [
    "Complete all exact-head/current-main/synthetic-merge/cross-platform/security checks on one frozen source SHA.",
    "Compose the default dataset freeze -> V4 verified training -> independent evaluation -> selection -> new-process load shadow loop.",
    "Retain immutable qualification evidence while external acceptance and target-host efficacy remain unissued.",
]
implementation["claimBoundary"].update(
    {
        "productionImplementation": False,
        "productExecutionProved": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
        "explicitReadConsumerComposed": True,
        "defaultProductLoopWired": False,
    }
)
implementation["productCallers"] = [
    {
        "sourcePath": "codex-rs/hepta-agentd/src/cognitive_ranker.rs",
        "nativeSymbol": "PinnedCognitiveRanker",
        "state": "explicit_concurrent_loaded_v2_read_consumer_not_training_loop",
    }
]
write(map_path, json.dumps(implementation, indent=2) + "\n")

print("learning.operator remaining convergence applied")
