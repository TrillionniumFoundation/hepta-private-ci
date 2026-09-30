use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::LoadedTabularOperatorV1;
use crate::StrictLearnedOperatorError;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularOperatorSampleV1;
use crate::TabularPayloadError;
use crate::TabularPayloadPinV1;
use crate::TabularWorldModelV1;
use crate::TrainingProfileV1;
use crate::WorkControlError;
use crate::WorkControlV1;
use crate::WorldModelError;
use crate::WorldModelProfileV1;
use crate::WorldModelSampleV1;
use crate::encode_tabular_payload_v1;
use crate::fit_tabular_operator_strict_controlled_v3;
use crate::fit_transition_model;

/// Caller-supplied values that are not themselves identity claims. Objective,
/// dataset, generation, profile digest, sensor-core digest and limits are all
/// derived from the canonical profile and owner receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnboundTabularOperatorPlanV3 {
    pub artifact_id: StableId,
    pub producer_id: StableId,
    pub sensor_ids: Vec<StableId>,
    pub action_ids: Vec<StableId>,
    pub samples: Vec<TabularOperatorSampleV1>,
}

/// One-shot capability. It intentionally does not implement `Clone`.
#[must_use]
pub struct VerifiedTabularOperatorPlanV3 {
    plan: TabularOperatorPlanV1,
    dataset: DatasetSnapshotReceiptV3,
    control: WorkControlV1,
}

#[must_use]
pub struct FittedTabularCandidateV3 {
    artifact: TabularOperatorArtifactV1,
    dataset: DatasetSnapshotReceiptV3,
    control: WorkControlV1,
}

#[must_use]
pub struct PublicationReadyTabularCandidateV3 {
    artifact: TabularOperatorArtifactV1,
}

#[must_use]
pub struct PreparedTabularPayloadV3 {
    bytes: Vec<u8>,
    pin: TabularPayloadPinV1,
    artifact_id: StableId,
    producer_id: StableId,
}

impl PreparedTabularPayloadV3 {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub fn pin(&self) -> &TabularPayloadPinV1 {
        &self.pin
    }

    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.artifact_id
    }

    #[must_use]
    pub fn producer_id(&self) -> &StableId {
        &self.producer_id
    }

    pub fn into_loaded(self) -> Result<LoadedTabularOperatorV1, FinalUseError> {
        Ok(LoadedTabularOperatorV1::from_pinned_payload(
            &self.bytes,
            &self.pin,
        )?)
    }
}

pub fn verify_tabular_operator_plan_v3(
    owner: &LedgerWriter,
    input: UnboundTabularOperatorPlanV3,
    profile: &TrainingProfileV1,
    dataset: DatasetSnapshotReceiptV3,
    control: WorkControlV1,
    now: u64,
) -> Result<VerifiedTabularOperatorPlanV3, FinalUseError> {
    control.checkpoint(0)?;
    owner.revalidate_dataset_snapshot(&dataset, now)?;
    if dataset.snapshot.objective_digest != profile.objective_digest() {
        return Err(FinalUseError::Binding("objective/profile"));
    }
    if dataset.snapshot.eligible_frontier != profile.dataset_frontier() {
        return Err(FinalUseError::Binding("dataset frontier/profile"));
    }
    let mut supplied_evidence = input
        .samples
        .iter()
        .map(|sample| sample.evidence_digest)
        .collect::<Vec<_>>();
    supplied_evidence.sort_unstable();
    if supplied_evidence != dataset.snapshot.source_record_digests {
        return Err(FinalUseError::Binding("dataset evidence membership"));
    }
    let plan = TabularOperatorPlanV1 {
        artifact_id: input.artifact_id,
        producer_id: input.producer_id,
        generation: profile.generation(),
        objective_digest: profile.objective_digest(),
        dataset_digest: dataset.snapshot.dataset_digest,
        sensor_core_digest: profile.sensor_core_digest(),
        training_profile_digest: profile.digest(),
        minimum_samples_per_cell: profile.minimum_samples_per_cell(),
        sensor_ids: input.sensor_ids,
        action_ids: input.action_ids,
        samples: input.samples,
    };
    Ok(VerifiedTabularOperatorPlanV3 {
        plan,
        dataset,
        control,
    })
}

pub fn fit_tabular_operator_verified_v3(
    owner: &LedgerWriter,
    verified: VerifiedTabularOperatorPlanV3,
    now: u64,
) -> Result<FittedTabularCandidateV3, FinalUseError> {
    let VerifiedTabularOperatorPlanV3 {
        plan,
        dataset,
        control,
    } = verified;
    control.checkpoint(0)?;
    owner.revalidate_dataset_snapshot(&dataset, now)?;
    let operations = u64::try_from(plan.samples.len()).map_err(|_| FinalUseError::Arithmetic)?;
    let artifact = fit_tabular_operator_strict_controlled_v3(plan, &control)?;
    control.checkpoint(operations)?;
    Ok(FittedTabularCandidateV3 {
        artifact,
        dataset,
        control,
    })
}

/// Final publication/selection fence. A correction, revocation, unlearning,
/// cancellation or expired deadline between fit and handoff rejects the value.
pub fn revalidate_tabular_candidate_for_publication_v3(
    owner: &LedgerWriter,
    fitted: FittedTabularCandidateV3,
    now: u64,
) -> Result<PublicationReadyTabularCandidateV3, FinalUseError> {
    fitted.control.checkpoint(0)?;
    owner.revalidate_dataset_snapshot(&fitted.dataset, now)?;
    if fitted.artifact.authority != AuthorityPosture::DENY_ALL {
        return Err(FinalUseError::Binding("candidate authority"));
    }
    Ok(PublicationReadyTabularCandidateV3 {
        artifact: fitted.artifact,
    })
}

impl PublicationReadyTabularCandidateV3 {
    pub fn prepare_pinned_payload(self) -> Result<PreparedTabularPayloadV3, FinalUseError> {
        let bytes = encode_tabular_payload_v1(&self.artifact)?;
        let pin = TabularPayloadPinV1 {
            payload_digest: Digest32::of_bytes(&bytes),
            artifact_digest: self.artifact.artifact_digest,
            objective_digest: self.artifact.objective_digest,
            dataset_digest: self.artifact.dataset_digest,
            sensor_core_digest: self.artifact.sensor_core_digest,
            training_profile_digest: self.artifact.training_profile_digest,
            generation: self.artifact.generation,
        };
        Ok(PreparedTabularPayloadV3 {
            bytes,
            pin,
            artifact_id: self.artifact.artifact_id,
            producer_id: self.artifact.producer_id,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnboundWorldModelDatasetV3 {
    pub model_id: StableId,
    pub samples: Vec<WorldModelSampleV1>,
}

#[must_use]
pub struct VerifiedWorldModelDatasetV3 {
    input: UnboundWorldModelDatasetV3,
    dataset: DatasetSnapshotReceiptV3,
    profile: WorldModelProfileV1,
    control: WorkControlV1,
}

#[must_use]
pub struct FittedWorldModelCandidateV3 {
    model: TabularWorldModelV1,
    dataset: DatasetSnapshotReceiptV3,
    profile_digest: Digest32,
    generation: Generation,
    control: WorkControlV1,
}

#[must_use]
pub struct PublicationReadyWorldModelCandidateV3 {
    model: TabularWorldModelV1,
    profile_digest: Digest32,
    generation: Generation,
}

impl PublicationReadyWorldModelCandidateV3 {
    #[must_use]
    pub fn model(&self) -> &TabularWorldModelV1 {
        &self.model
    }

    #[must_use]
    pub fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub fn generation(&self) -> Generation {
        self.generation
    }
}

pub fn verify_world_model_dataset_v3(
    owner: &LedgerWriter,
    input: UnboundWorldModelDatasetV3,
    profile: WorldModelProfileV1,
    dataset: DatasetSnapshotReceiptV3,
    control: WorkControlV1,
    now: u64,
) -> Result<VerifiedWorldModelDatasetV3, FinalUseError> {
    control.checkpoint(0)?;
    owner.revalidate_dataset_snapshot(&dataset, now)?;
    if dataset.snapshot.objective_digest != profile.objective_digest() {
        return Err(FinalUseError::Binding("world objective/profile"));
    }
    if dataset.snapshot.eligible_frontier != profile.dataset_frontier() {
        return Err(FinalUseError::Binding("world dataset frontier/profile"));
    }
    let mut supplied_evidence = input
        .samples
        .iter()
        .map(|sample| sample.evidence_digest)
        .collect::<Vec<_>>();
    supplied_evidence.sort_unstable();
    if supplied_evidence != dataset.snapshot.source_record_digests {
        return Err(FinalUseError::Binding("world dataset evidence membership"));
    }
    Ok(VerifiedWorldModelDatasetV3 {
        input,
        dataset,
        profile,
        control,
    })
}

pub fn fit_transition_model_verified_v3(
    owner: &LedgerWriter,
    verified: VerifiedWorldModelDatasetV3,
    now: u64,
) -> Result<FittedWorldModelCandidateV3, FinalUseError> {
    let VerifiedWorldModelDatasetV3 {
        input,
        dataset,
        profile,
        control,
    } = verified;
    control.checkpoint(0)?;
    owner.revalidate_dataset_snapshot(&dataset, now)?;
    let operations = u64::try_from(input.samples.len()).map_err(|_| FinalUseError::Arithmetic)?;
    let model = fit_transition_model(input.model_id, dataset.snapshot.dataset_digest, input.samples)?;
    if model.estimates.iter().any(|estimate| {
        estimate.sample_count as usize  < profile.minimum_support_per_state_action()
    }) {
        return Err(FinalUseError::Binding("world minimum support"));
    }
    control.checkpoint(operations)?;
    Ok(FittedWorldModelCandidateV3 {
        model,
        dataset,
        profile_digest: profile.digest(),
        generation: profile.generation(),
        control,
    })
}

pub fn revalidate_world_model_candidate_for_publication_v3(
    owner: &LedgerWriter,
    fitted: FittedWorldModelCandidateV3,
    now: u64,
) -> Result<PublicationReadyWorldModelCandidateV3, FinalUseError> {
    fitted.control.checkpoint(0)?;
    owner.revalidate_dataset_snapshot(&fitted.dataset, now)?;
    if fitted.model.authority != AuthorityPosture::DENY_ALL {
        return Err(FinalUseError::Binding("world candidate authority"));
    }
    Ok(PublicationReadyWorldModelCandidateV3 {
        model: fitted.model,
        profile_digest: fitted.profile_digest,
        generation: fitted.generation,
    })
}

#[derive(Debug)]
pub enum FinalUseError {
    Ledger(ProductionLedgerError),
    Learned(StrictLearnedOperatorError),
    WorldModel(WorldModelError),
    WorkControl(WorkControlError),
    Payload(TabularPayloadError),
    Binding(&'static str),
    Arithmetic,
}

impl fmt::Display for FinalUseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FinalUseError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Ledger(error) => Some(error),
            Self::Learned(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::WorkControl(error) => Some(error),
            Self::Payload(error) => Some(error),
            Self::Binding(_) | Self::Arithmetic => None,
        }
    }
}

impl From<ProductionLedgerError> for FinalUseError {
    fn from(value: ProductionLedgerError) -> Self {
        Self::Ledger(value)
    }
}

impl From<StrictLearnedOperatorError> for FinalUseError {
    fn from(value: StrictLearnedOperatorError) -> Self {
        Self::Learned(value)
    }
}

impl From<WorldModelError> for FinalUseError {
    fn from(value: WorldModelError) -> Self {
        Self::WorldModel(value)
    }
}

impl From<WorkControlError> for FinalUseError {
    fn from(value: WorkControlError) -> Self {
        Self::WorkControl(value)
    }
}

impl From<TabularPayloadError> for FinalUseError {
    fn from(value: TabularPayloadError) -> Self {
        Self::Payload(value)
    }
}
