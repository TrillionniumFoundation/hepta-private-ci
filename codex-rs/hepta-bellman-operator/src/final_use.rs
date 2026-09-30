//! Opaque single-use final-use capabilities for learning.operator.
//!
//! Admission and fitting both bind the current durable ledger, authority epoch,
//! dataset frontier, model generation, stop epoch, absolute deadline, canonical
//! profile and cooperative cancellation token. Currentness is checked before
//! fitting, after fitting, and again when an independently selected candidate is
//! pinned for read-only use.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::OperatorDatasetBindingError;
use crate::OperatorProfileErrorV1;
use crate::OperatorResourceBudgetV1;
use crate::TABULAR_ARTIFACT_SCHEMA_V1;
use crate::TABULAR_PAYLOAD_SCHEMA_V1;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularOperatorSampleV1;
use crate::TabularPayloadError;
use crate::TabularPayloadPinV2;
use crate::TrainingProfileV1;
use crate::WorkControlV1;
use crate::WorldModelProfileV1;
use crate::WorldModelSampleV1;
use crate::encode_tabular_payload_v1;
use crate::tabular_v2::BudgetedTabularFitErrorV2;
use crate::tabular_v2::fit_tabular_operator_bounded_v2;
use crate::verify_tabular_operator_plan_v3;
use crate::verify_world_model_dataset_v3;
use crate::with_work_control_v1;
use crate::world_model_training_signing_payload_v2;
use crate::world_model_v2::WorldModelArtifactV2;
use crate::world_model_v2::WorldModelPlanV2;
use crate::world_model_v2::WorldModelUsePinV2;
use crate::world_model_v2::WorldModelV2Error;
use crate::world_model_v2::fit_world_model_v2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FinalUseFenceV1 {
    expected_ledger_head_digest: Digest32,
    expected_dataset_generation: u64,
    expected_generation: Generation,
    expected_authority_epoch: u64,
    expected_stop_epoch: u64,
    absolute_deadline_unix_micros: u64,
}

impl FinalUseFenceV1 {
    pub fn new(
        expected_ledger_head_digest: Digest32,
        expected_dataset_generation: u64,
        expected_generation: Generation,
        expected_authority_epoch: u64,
        expected_stop_epoch: u64,
        absolute_deadline_unix_micros: u64,
    ) -> Result<Self, FinalUseErrorV1> {
        if expected_ledger_head_digest.is_zero()
            || expected_dataset_generation == 0
            || expected_authority_epoch == 0
            || expected_stop_epoch == 0
            || absolute_deadline_unix_micros == 0
        {
            return Err(FinalUseErrorV1::Binding("invalid final-use fence"));
        }
        Ok(Self {
            expected_ledger_head_digest,
            expected_dataset_generation,
            expected_generation,
            expected_authority_epoch,
            expected_stop_epoch,
            absolute_deadline_unix_micros,
        })
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.expected_generation
    }

    #[must_use]
    pub const fn deadline(&self) -> u64 {
        self.absolute_deadline_unix_micros
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FinalUseWitnessV1 {
    observed_at_unix_micros: u64,
    ledger_head_digest: Digest32,
    dataset_generation: u64,
    generation: Generation,
    authority_epoch: u64,
    stop_epoch: u64,
    stop_requested: bool,
}

impl FinalUseWitnessV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        observed_at_unix_micros: u64,
        ledger_head_digest: Digest32,
        dataset_generation: u64,
        generation: Generation,
        authority_epoch: u64,
        stop_epoch: u64,
        stop_requested: bool,
    ) -> Result<Self, FinalUseErrorV1> {
        if observed_at_unix_micros == 0
            || ledger_head_digest.is_zero()
            || dataset_generation == 0
            || authority_epoch == 0
            || stop_epoch == 0
        {
            return Err(FinalUseErrorV1::Binding("invalid final-use witness"));
        }
        Ok(Self {
            observed_at_unix_micros,
            ledger_head_digest,
            dataset_generation,
            generation,
            authority_epoch,
            stop_epoch,
            stop_requested,
        })
    }

    #[must_use]
    pub const fn observed_at(&self) -> u64 {
        self.observed_at_unix_micros
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectionCurrentnessV1 {
    artifact_digest: Digest32,
    selection_digest: Digest32,
    runtime_profile_digest: Digest32,
    trust_digest: Digest32,
    registry_head_digest: Digest32,
    ledger_head_digest: Digest32,
    generation: Generation,
    authority_epoch: u64,
    stop_epoch: u64,
    observed_at_unix_micros: u64,
    expires_at_unix_micros: u64,
    stop_requested: bool,
}

impl SelectionCurrentnessV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        artifact_digest: Digest32,
        selection_digest: Digest32,
        runtime_profile_digest: Digest32,
        trust_digest: Digest32,
        registry_head_digest: Digest32,
        ledger_head_digest: Digest32,
        generation: Generation,
        authority_epoch: u64,
        stop_epoch: u64,
        observed_at_unix_micros: u64,
        expires_at_unix_micros: u64,
        stop_requested: bool,
    ) -> Result<Self, FinalUseErrorV1> {
        if [
            artifact_digest,
            selection_digest,
            runtime_profile_digest,
            trust_digest,
            registry_head_digest,
            ledger_head_digest,
        ]
        .into_iter()
        .any(Digest32::is_zero)
            || authority_epoch == 0
            || stop_epoch == 0
            || observed_at_unix_micros == 0
            || observed_at_unix_micros >= expires_at_unix_micros
        {
            return Err(FinalUseErrorV1::SelectionBinding(
                "invalid selection currentness",
            ));
        }
        Ok(Self {
            artifact_digest,
            selection_digest,
            runtime_profile_digest,
            trust_digest,
            registry_head_digest,
            ledger_head_digest,
            generation,
            authority_epoch,
            stop_epoch,
            observed_at_unix_micros,
            expires_at_unix_micros,
            stop_requested,
        })
    }

    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }
}

#[derive(Debug)]
pub enum FinalUseErrorV1 {
    Profile(OperatorProfileErrorV1),
    Source(OperatorDatasetBindingError),
    Tabular(BudgetedTabularFitErrorV2),
    WorldModel(WorldModelV2Error),
    Payload(TabularPayloadError),
    OwnerState(String),
    Binding(&'static str),
    SelectionBinding(&'static str),
    ClockRegression,
    DeadlineExceeded,
    Stopped,
}

impl fmt::Display for FinalUseErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FinalUseErrorV1 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Profile(error) => Some(error),
            Self::Source(error) => Some(error),
            Self::Tabular(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::Payload(error) => Some(error),
            Self::OwnerState(_)
            | Self::Binding(_)
            | Self::SelectionBinding(_)
            | Self::ClockRegression
            | Self::DeadlineExceeded
            | Self::Stopped => None,
        }
    }
}

impl From<OperatorProfileErrorV1> for FinalUseErrorV1 {
    fn from(value: OperatorProfileErrorV1) -> Self {
        Self::Profile(value)
    }
}

impl From<OperatorDatasetBindingError> for FinalUseErrorV1 {
    fn from(value: OperatorDatasetBindingError) -> Self {
        Self::Source(value)
    }
}

impl From<BudgetedTabularFitErrorV2> for FinalUseErrorV1 {
    fn from(value: BudgetedTabularFitErrorV2) -> Self {
        Self::Tabular(value)
    }
}

impl From<WorldModelV2Error> for FinalUseErrorV1 {
    fn from(value: WorldModelV2Error) -> Self {
        Self::WorldModel(value)
    }
}

impl From<TabularPayloadError> for FinalUseErrorV1 {
    fn from(value: TabularPayloadError) -> Self {
        Self::Payload(value)
    }
}

#[derive(Debug)]
pub struct TabularTrainingRequestV1 {
    artifact_id: StableId,
    producer_id: StableId,
    generation: Generation,
    profile: TrainingProfileV1,
    sensor_ids: Vec<StableId>,
    action_ids: Vec<StableId>,
    samples: Vec<TabularOperatorSampleV1>,
}

impl TabularTrainingRequestV1 {
    pub fn new(
        artifact_id: StableId,
        producer_id: StableId,
        generation: Generation,
        profile: TrainingProfileV1,
        sensor_ids: Vec<StableId>,
        action_ids: Vec<StableId>,
        samples: Vec<TabularOperatorSampleV1>,
    ) -> Result<Self, FinalUseErrorV1> {
        if sensor_ids.is_empty() || action_ids.is_empty() || samples.is_empty() {
            return Err(FinalUseErrorV1::Binding(
                "tabular request requires a nonempty complete grid",
            ));
        }
        Ok(Self {
            artifact_id,
            producer_id,
            generation,
            profile,
            sensor_ids,
            action_ids,
            samples,
        })
    }

    fn plan(&self, receipt: &DatasetSnapshotReceiptV3) -> TabularOperatorPlanV1 {
        TabularOperatorPlanV1 {
            artifact_id: self.artifact_id.clone(),
            producer_id: self.producer_id.clone(),
            generation: self.generation,
            objective_digest: receipt.snapshot.objective_digest,
            dataset_digest: receipt.snapshot.dataset_digest,
            sensor_core_digest: self.profile.sensor_core_digest(),
            training_profile_digest: self.profile.digest(),
            minimum_samples_per_cell: self.profile.minimum_samples_per_cell(),
            sensor_ids: self.sensor_ids.clone(),
            action_ids: self.action_ids.clone(),
            samples: self.samples.clone(),
        }
    }
}

#[derive(Debug)]
pub struct WorldModelTrainingRequestV1 {
    model_id: StableId,
    generation: Generation,
    profile: WorldModelProfileV1,
    trust_digest: Digest32,
    registry_head_digest: Digest32,
    train_window_digest: Digest32,
    holdout_window_digest: Digest32,
    future_window_digest: Digest32,
    predecessor_model_digest: Option<Digest32>,
    one_step_calibration_error: FixedQ32,
    multistep_calibration_error: FixedQ32,
    ood_false_acceptance: ProbabilityQ32,
    drift_score: FixedQ32,
    change_point_digest: Digest32,
    retained_until: u64,
    expires_at: u64,
    samples: Vec<WorldModelSampleV1>,
}

impl WorldModelTrainingRequestV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        model_id: StableId,
        generation: Generation,
        profile: WorldModelProfileV1,
        trust_digest: Digest32,
        registry_head_digest: Digest32,
        train_window_digest: Digest32,
        holdout_window_digest: Digest32,
        future_window_digest: Digest32,
        predecessor_model_digest: Option<Digest32>,
        one_step_calibration_error: FixedQ32,
        multistep_calibration_error: FixedQ32,
        ood_false_acceptance: ProbabilityQ32,
        drift_score: FixedQ32,
        change_point_digest: Digest32,
        retained_until: u64,
        expires_at: u64,
        samples: Vec<WorldModelSampleV1>,
    ) -> Result<Self, FinalUseErrorV1> {
        if [
            trust_digest,
            registry_head_digest,
            train_window_digest,
            holdout_window_digest,
            future_window_digest,
            change_point_digest,
        ]
        .into_iter()
        .any(Digest32::is_zero)
            || predecessor_model_digest.is_some_and(Digest32::is_zero)
            || retained_until == 0
            || retained_until > expires_at
            || samples.is_empty()
        {
            return Err(FinalUseErrorV1::Binding("invalid world-model request"));
        }
        if one_step_calibration_error > profile.maximum_one_step_calibration_error()
            || multistep_calibration_error > profile.maximum_multistep_calibration_error()
            || ood_false_acceptance > profile.maximum_ood_false_acceptance()
            || drift_score > profile.maximum_drift_score()
        {
            return Err(FinalUseErrorV1::Binding(
                "world-model measurements exceed canonical profile",
            ));
        }
        Ok(Self {
            model_id,
            generation,
            profile,
            trust_digest,
            registry_head_digest,
            train_window_digest,
            holdout_window_digest,
            future_window_digest,
            predecessor_model_digest,
            one_step_calibration_error,
            multistep_calibration_error,
            ood_false_acceptance,
            drift_score,
            change_point_digest,
            retained_until,
            expires_at,
            samples,
        })
    }

    fn plan(
        &self,
        receipt: &DatasetSnapshotReceiptV3,
        row_commitment_root: Digest32,
        authority_epoch: u64,
    ) -> WorldModelPlanV2 {
        WorldModelPlanV2 {
            model_id: self.model_id.clone(),
            generation: self.generation,
            objective_digest: receipt.snapshot.objective_digest,
            dataset_digest: receipt.snapshot.dataset_digest,
            training_profile_digest: self.profile.digest(),
            runtime_profile_digest: self.profile.runtime_profile_digest(),
            trust_digest: self.trust_digest,
            registry_head_digest: self.registry_head_digest,
            row_commitment_root,
            train_window_digest: self.train_window_digest,
            holdout_window_digest: self.holdout_window_digest,
            future_window_digest: self.future_window_digest,
            predecessor_model_digest: self.predecessor_model_digest,
            authority_epoch,
            minimum_support: self.profile.minimum_support(),
            one_step_calibration_error: self.one_step_calibration_error,
            multistep_calibration_error: self.multistep_calibration_error,
            ood_false_acceptance: self.ood_false_acceptance,
            drift_score: self.drift_score,
            change_point_digest: self.change_point_digest,
            retained_until: self.retained_until,
            expires_at: self.expires_at,
            samples: self.samples.clone(),
        }
    }
}

pub struct FinalUseTabularCapabilityV1<'a> {
    owner: &'a LedgerWriter,
    receipt: DatasetSnapshotReceiptV3,
    freeze_evidence: SignedLearningEvidenceV1,
    row_evidence: SignedLearningEvidenceV1,
    plan: TabularOperatorPlanV1,
    runtime_profile_digest: Digest32,
    budget: OperatorResourceBudgetV1,
    fence: FinalUseFenceV1,
    control: WorkControlV1,
}

impl fmt::Debug for FinalUseTabularCapabilityV1<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FinalUseTabularCapabilityV1")
            .field("artifact_id", &self.plan.artifact_id)
            .field("dataset_digest", &self.plan.dataset_digest)
            .finish_non_exhaustive()
    }
}

pub struct FinalUseWorldModelCapabilityV1<'a> {
    owner: &'a LedgerWriter,
    receipt: DatasetSnapshotReceiptV3,
    freeze_evidence: SignedLearningEvidenceV1,
    row_evidence: SignedLearningEvidenceV1,
    plan: WorldModelPlanV2,
    budget: OperatorResourceBudgetV1,
    fence: FinalUseFenceV1,
    control: WorkControlV1,
}

impl fmt::Debug for FinalUseWorldModelCapabilityV1<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FinalUseWorldModelCapabilityV1")
            .field("model_id", &self.plan.model_id)
            .field("dataset_digest", &self.plan.dataset_digest)
            .finish_non_exhaustive()
    }
}

#[allow(clippy::too_many_arguments)]
pub fn issue_tabular_final_use_capability_v1<'a>(
    owner: &'a LedgerWriter,
    receipt: &DatasetSnapshotReceiptV3,
    freeze_evidence: &SignedLearningEvidenceV1,
    row_evidence: &SignedLearningEvidenceV1,
    request: TabularTrainingRequestV1,
    fence: FinalUseFenceV1,
    control: WorkControlV1,
    witness: &FinalUseWitnessV1,
) -> Result<FinalUseTabularCapabilityV1<'a>, FinalUseErrorV1> {
    validate_profile_binding(
        request.profile.objective_digest(),
        request.profile.dataset_generation(),
        request.generation,
        receipt,
        &fence,
    )?;
    validate_current(
        owner,
        receipt,
        &fence,
        &control,
        witness,
        witness.observed_at_unix_micros,
    )?;
    let plan = request.plan(receipt);
    let verified = verify_tabular_operator_plan_v3(
        plan.clone(),
        receipt,
        owner,
        freeze_evidence,
        row_evidence,
        witness.observed_at_unix_micros,
    )?;
    let _ = verified.admission_stage();
    Ok(FinalUseTabularCapabilityV1 {
        owner,
        receipt: receipt.clone(),
        freeze_evidence: freeze_evidence.clone(),
        row_evidence: row_evidence.clone(),
        runtime_profile_digest: request.profile.runtime_profile_digest(),
        budget: request.profile.runtime_limits(),
        plan,
        fence,
        control,
    })
}

#[allow(clippy::too_many_arguments)]
pub fn issue_world_model_final_use_capability_v1<'a>(
    owner: &'a LedgerWriter,
    receipt: &DatasetSnapshotReceiptV3,
    freeze_evidence: &SignedLearningEvidenceV1,
    row_evidence: &SignedLearningEvidenceV1,
    request: WorldModelTrainingRequestV1,
    fence: FinalUseFenceV1,
    control: WorkControlV1,
    witness: &FinalUseWitnessV1,
) -> Result<FinalUseWorldModelCapabilityV1<'a>, FinalUseErrorV1> {
    validate_profile_binding(
        request.profile.objective_digest(),
        request.profile.dataset_generation(),
        request.generation,
        receipt,
        &fence,
    )?;
    validate_current(
        owner,
        receipt,
        &fence,
        &control,
        witness,
        witness.observed_at_unix_micros,
    )?;
    if request.trust_digest != owner.verifier().trust_digest() {
        return Err(FinalUseErrorV1::Binding(
            "world-model request does not name the training owner's trust",
        ));
    }
    let row_payload = world_model_training_signing_payload_v2(
        &request.model_id,
        &request.samples,
        receipt,
        owner,
    )?;
    let row_commitment_root = Digest32::of_bytes(&row_payload);
    let plan = request.plan(receipt, row_commitment_root, fence.expected_authority_epoch);
    let verified = verify_world_model_dataset_v3(
        plan.model_id.clone(),
        plan.samples.clone(),
        receipt,
        owner,
        freeze_evidence,
        row_evidence,
        witness.observed_at_unix_micros,
    )?;
    let _ = verified.admission_stage();
    Ok(FinalUseWorldModelCapabilityV1 {
        owner,
        receipt: receipt.clone(),
        freeze_evidence: freeze_evidence.clone(),
        row_evidence: row_evidence.clone(),
        budget: request.profile.runtime_limits(),
        plan,
        fence,
        control,
    })
}

#[derive(Debug)]
pub struct FinalUseTabularCandidateV1 {
    artifact: TabularOperatorArtifactV1,
    payload: Arc<[u8]>,
    runtime_profile_digest: Digest32,
    trust_digest: Digest32,
    ledger_head_digest: Digest32,
    authority_epoch: u64,
    stop_epoch: u64,
    fit_receipt_digest: Digest32,
    published_at_unix_micros: u64,
}

impl FinalUseTabularCandidateV1 {
    #[must_use]
    pub const fn artifact_digest(&self) -> Digest32 {
        self.artifact.artifact_digest
    }

    #[must_use]
    pub fn payload_digest(&self) -> Digest32 {
        Digest32::of_bytes(self.payload.as_ref())
    }

    #[must_use]
    pub const fn fit_receipt_digest(&self) -> Digest32 {
        self.fit_receipt_digest
    }

    pub fn pin_for_selection(
        self,
        selection: SelectionCurrentnessV1,
    ) -> Result<OpaquePinnedTabularArtifactV1, FinalUseErrorV1> {
        validate_selection(
            self.artifact.artifact_digest,
            self.artifact.generation,
            self.runtime_profile_digest,
            self.ledger_head_digest,
            self.authority_epoch,
            self.stop_epoch,
            self.published_at_unix_micros,
            &selection,
        )?;
        if self.trust_digest != selection.trust_digest {
            return Err(FinalUseErrorV1::SelectionBinding(
                "tabular training trust changed; refit required",
            ));
        }
        let pin = TabularPayloadPinV2 {
            artifact_id: self.artifact.artifact_id.clone(),
            producer_id: self.artifact.producer_id.clone(),
            artifact_schema_version: TABULAR_ARTIFACT_SCHEMA_V1,
            payload_schema_version: TABULAR_PAYLOAD_SCHEMA_V1,
            payload_digest: Digest32::of_bytes(self.payload.as_ref()),
            artifact_digest: self.artifact.artifact_digest,
            objective_digest: self.artifact.objective_digest,
            dataset_digest: self.artifact.dataset_digest,
            sensor_core_digest: self.artifact.sensor_core_digest,
            training_profile_digest: self.artifact.training_profile_digest,
            runtime_profile_digest: self.runtime_profile_digest,
            trust_digest: selection.trust_digest,
            registry_head_digest: selection.registry_head_digest,
            authority_epoch: selection.authority_epoch,
            generation: self.artifact.generation,
        };
        Ok(OpaquePinnedTabularArtifactV1 {
            payload: self.payload,
            pin,
            selection_digest: selection.selection_digest,
            selected_at_unix_micros: selection.observed_at_unix_micros,
            expires_at_unix_micros: selection.expires_at_unix_micros,
        })
    }
}

/// An immutable selected payload. The host must revalidate current owner
/// lineage, registry and stop state before each final-use operation.
pub struct OpaquePinnedTabularArtifactV1 {
    payload: Arc<[u8]>,
    pin: TabularPayloadPinV2,
    selection_digest: Digest32,
    selected_at_unix_micros: u64,
    expires_at_unix_micros: u64,
}

impl fmt::Debug for OpaquePinnedTabularArtifactV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("OpaquePinnedTabularArtifactV1")
            .field("artifact_id", &self.pin.artifact_id)
            .field("selection_digest", &self.selection_digest)
            .finish_non_exhaustive()
    }
}

#[derive(Debug)]
pub struct FinalUseWorldModelCandidateV1 {
    artifact: WorldModelArtifactV2,
    ledger_head_digest: Digest32,
    stop_epoch: u64,
    published_at_unix_micros: u64,
}

impl FinalUseWorldModelCandidateV1 {
    #[must_use]
    pub const fn artifact_digest(&self) -> Digest32 {
        self.artifact.model_digest
    }

    pub fn pin_for_selection(
        self,
        selection: SelectionCurrentnessV1,
    ) -> Result<OpaquePinnedWorldModelV1, FinalUseErrorV1> {
        validate_selection(
            self.artifact.model_digest,
            self.artifact.generation,
            self.artifact.runtime_profile_digest,
            self.ledger_head_digest,
            self.artifact.authority_epoch,
            self.stop_epoch,
            self.published_at_unix_micros,
            &selection,
        )?;
        if self.artifact.trust_digest != selection.trust_digest
            || self.artifact.registry_head_digest != selection.registry_head_digest
        {
            return Err(FinalUseErrorV1::SelectionBinding(
                "world-model trust or registry changed; refit/reload required",
            ));
        }
        let pin = WorldModelUsePinV2 {
            runtime_profile_digest: self.artifact.runtime_profile_digest,
            trust_digest: selection.trust_digest,
            registry_head_digest: selection.registry_head_digest,
            minimum_authority_epoch: selection.authority_epoch,
            expected_predecessor_model_digest: self.artifact.predecessor_model_digest,
        };
        Ok(OpaquePinnedWorldModelV1 {
            artifact: self.artifact,
            pin,
            selection_digest: selection.selection_digest,
            selected_at_unix_micros: selection.observed_at_unix_micros,
            expires_at_unix_micros: selection.expires_at_unix_micros,
        })
    }
}

pub struct OpaquePinnedWorldModelV1 {
    artifact: WorldModelArtifactV2,
    pin: WorldModelUsePinV2,
    selection_digest: Digest32,
    selected_at_unix_micros: u64,
    expires_at_unix_micros: u64,
}

impl fmt::Debug for OpaquePinnedWorldModelV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("OpaquePinnedWorldModelV1")
            .field("model_id", &self.artifact.model_id)
            .field("selection_digest", &self.selection_digest)
            .finish_non_exhaustive()
    }
}

pub fn fit_tabular_final_use_v1(
    capability: FinalUseTabularCapabilityV1<'_>,
    use_witness: &FinalUseWitnessV1,
    publish_witness: &FinalUseWitnessV1,
    effective_now: impl Fn(u64) -> Result<u64, FinalUseErrorV1>,
) -> Result<FinalUseTabularCandidateV1, FinalUseErrorV1> {
    if publish_witness.observed_at_unix_micros < use_witness.observed_at_unix_micros {
        return Err(FinalUseErrorV1::ClockRegression);
    }
    let use_now = effective_now(use_witness.observed_at_unix_micros)?;
    validate_current(
        capability.owner,
        &capability.receipt,
        &capability.fence,
        &capability.control,
        use_witness,
        use_now,
    )?;
    let verified_at_use = verify_tabular_operator_plan_v3(
        capability.plan.clone(),
        &capability.receipt,
        capability.owner,
        &capability.freeze_evidence,
        &capability.row_evidence,
        use_now,
    )?;
    let fit = with_work_control_v1(&capability.control, || {
        fit_tabular_operator_bounded_v2(capability.plan.clone(), capability.plan_budget())
    })?;
    let _ = verified_at_use.admission_stage();
    if fit.artifact.training_profile_digest != capability.plan.training_profile_digest
        || fit.artifact.generation != capability.fence.expected_generation
    {
        return Err(FinalUseErrorV1::Binding(
            "tabular fit escaped the canonical final-use identity",
        ));
    }
    let payload = encode_tabular_payload_v1(&fit.artifact)?;
    let publish_now = effective_now(publish_witness.observed_at_unix_micros)?;
    validate_current(
        capability.owner,
        &capability.receipt,
        &capability.fence,
        &capability.control,
        publish_witness,
        publish_now,
    )?;
    let verified_at_publish = verify_tabular_operator_plan_v3(
        capability.plan.clone(),
        &capability.receipt,
        capability.owner,
        &capability.freeze_evidence,
        &capability.row_evidence,
        publish_now,
    )?;
    let _ = verified_at_publish.admission_stage();
    Ok(FinalUseTabularCandidateV1 {
        artifact: fit.artifact,
        payload: payload.into(),
        runtime_profile_digest: capability.runtime_profile_digest,
        trust_digest: capability.owner.verifier().trust_digest(),
        ledger_head_digest: capability.fence.expected_ledger_head_digest,
        authority_epoch: capability.fence.expected_authority_epoch,
        stop_epoch: capability.fence.expected_stop_epoch,
        fit_receipt_digest: fit.receipt_digest,
        published_at_unix_micros: publish_now,
    })
}

pub fn fit_world_model_final_use_v1(
    capability: FinalUseWorldModelCapabilityV1<'_>,
    use_witness: &FinalUseWitnessV1,
    publish_witness: &FinalUseWitnessV1,
    effective_now: impl Fn(u64) -> Result<u64, FinalUseErrorV1>,
) -> Result<FinalUseWorldModelCandidateV1, FinalUseErrorV1> {
    if publish_witness.observed_at_unix_micros < use_witness.observed_at_unix_micros {
        return Err(FinalUseErrorV1::ClockRegression);
    }
    let use_now = effective_now(use_witness.observed_at_unix_micros)?;
    validate_current(
        capability.owner,
        &capability.receipt,
        &capability.fence,
        &capability.control,
        use_witness,
        use_now,
    )?;
    validate_world_row_commitment(&capability)?;
    let verified_at_use = verify_world_model_dataset_v3(
        capability.plan.model_id.clone(),
        capability.plan.samples.clone(),
        &capability.receipt,
        capability.owner,
        &capability.freeze_evidence,
        &capability.row_evidence,
        use_now,
    )?;
    let fit = with_work_control_v1(&capability.control, || {
        fit_world_model_v2(capability.plan.clone(), capability.plan_budget())
    })?;
    let _ = verified_at_use.admission_stage();
    let publish_now = effective_now(publish_witness.observed_at_unix_micros)?;
    validate_current(
        capability.owner,
        &capability.receipt,
        &capability.fence,
        &capability.control,
        publish_witness,
        publish_now,
    )?;
    validate_world_row_commitment(&capability)?;
    let verified_at_publish = verify_world_model_dataset_v3(
        capability.plan.model_id.clone(),
        capability.plan.samples.clone(),
        &capability.receipt,
        capability.owner,
        &capability.freeze_evidence,
        &capability.row_evidence,
        publish_now,
    )?;
    let _ = verified_at_publish.admission_stage();
    if fit.training_profile_digest != capability.plan.training_profile_digest
        || fit.generation != capability.fence.expected_generation
    {
        return Err(FinalUseErrorV1::Binding(
            "world-model fit escaped the canonical final-use identity",
        ));
    }
    Ok(FinalUseWorldModelCandidateV1 {
        artifact: fit,
        ledger_head_digest: capability.fence.expected_ledger_head_digest,
        stop_epoch: capability.fence.expected_stop_epoch,
        published_at_unix_micros: publish_now,
    })
}

impl FinalUseTabularCapabilityV1<'_> {
    const fn plan_budget(&self) -> OperatorResourceBudgetV1 {
        self.budget
    }
}

impl FinalUseWorldModelCapabilityV1<'_> {
    const fn plan_budget(&self) -> OperatorResourceBudgetV1 {
        self.budget
    }
}

fn validate_world_row_commitment(
    capability: &FinalUseWorldModelCapabilityV1<'_>,
) -> Result<(), FinalUseErrorV1> {
    let payload = world_model_training_signing_payload_v2(
        &capability.plan.model_id,
        &capability.plan.samples,
        &capability.receipt,
        capability.owner,
    )?;
    if Digest32::of_bytes(&payload) != capability.plan.row_commitment_root {
        return Err(FinalUseErrorV1::Binding(
            "world-model row commitment changed at final use",
        ));
    }
    Ok(())
}

fn validate_profile_binding(
    profile_objective: Digest32,
    profile_dataset_generation: u64,
    generation: Generation,
    receipt: &DatasetSnapshotReceiptV3,
    fence: &FinalUseFenceV1,
) -> Result<(), FinalUseErrorV1> {
    if profile_objective != receipt.snapshot.objective_digest
        || profile_dataset_generation != receipt.snapshot.eligible_frontier
        || profile_dataset_generation != fence.expected_dataset_generation
        || generation != fence.expected_generation
        || receipt.snapshot.ledger_head_digest != fence.expected_ledger_head_digest
        || receipt.producer.authority_epoch != fence.expected_authority_epoch
    {
        return Err(FinalUseErrorV1::Binding(
            "canonical profile, dataset, generation, or authority mismatch",
        ));
    }
    Ok(())
}

fn validate_current(
    owner: &LedgerWriter,
    receipt: &DatasetSnapshotReceiptV3,
    fence: &FinalUseFenceV1,
    control: &WorkControlV1,
    witness: &FinalUseWitnessV1,
    now: u64,
) -> Result<(), FinalUseErrorV1> {
    if witness.stop_requested || control.is_cancelled() {
        return Err(FinalUseErrorV1::Stopped);
    }
    if now < witness.observed_at_unix_micros {
        return Err(FinalUseErrorV1::ClockRegression);
    }
    if now >= fence.absolute_deadline_unix_micros {
        return Err(FinalUseErrorV1::DeadlineExceeded);
    }
    if witness.ledger_head_digest != fence.expected_ledger_head_digest
        || witness.dataset_generation != fence.expected_dataset_generation
        || witness.generation != fence.expected_generation
        || witness.authority_epoch != fence.expected_authority_epoch
        || witness.stop_epoch != fence.expected_stop_epoch
        || receipt.snapshot.ledger_head_digest != fence.expected_ledger_head_digest
        || receipt.snapshot.eligible_frontier != fence.expected_dataset_generation
    {
        return Err(FinalUseErrorV1::Binding(
            "final-use witness is stale or belongs to another generation",
        ));
    }
    owner
        .revalidate_dataset_snapshot(receipt, now)
        .map_err(|error| FinalUseErrorV1::OwnerState(error.to_string()))?;
    let snapshot = owner
        .snapshot()
        .map_err(|error| FinalUseErrorV1::OwnerState(error.to_string()))?;
    if snapshot.head_digest != fence.expected_ledger_head_digest
        || owner.verifier().authority_epoch() != fence.expected_authority_epoch
    {
        return Err(FinalUseErrorV1::Binding(
            "durable owner currentness changed at final use",
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_selection(
    artifact_digest: Digest32,
    generation: Generation,
    runtime_profile_digest: Digest32,
    ledger_head_digest: Digest32,
    authority_epoch: u64,
    stop_epoch: u64,
    published_at: u64,
    selection: &SelectionCurrentnessV1,
) -> Result<(), FinalUseErrorV1> {
    if selection.stop_requested {
        return Err(FinalUseErrorV1::Stopped);
    }
    if selection.observed_at_unix_micros < published_at
        || selection.observed_at_unix_micros >= selection.expires_at_unix_micros
        || selection.artifact_digest != artifact_digest
        || selection.generation != generation
        || selection.runtime_profile_digest != runtime_profile_digest
        || selection.ledger_head_digest != ledger_head_digest
        || selection.authority_epoch != authority_epoch
        || selection.stop_epoch != stop_epoch
    {
        return Err(FinalUseErrorV1::SelectionBinding(
            "selection is stale or bound to another candidate/currentness epoch",
        ));
    }
    Ok(())
}

#[path = "final_use_selected.rs"]
mod selected;
pub use selected::SelectedTabularOperatorV1;

#[cfg(test)]
#[path = "final_use_tests.rs"]
mod tests;
