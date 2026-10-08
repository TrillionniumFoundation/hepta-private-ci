//! Memory tensor candidates through the existing cognitive and learning owners.
//! Source read, train purpose and artifact consumer are checked independently of
//! parameter quality. No method here registers, selects or installs a candidate.
use std::fmt;

use codex_hepta_bellman_operator::FrozenMemoryTrainingV1;
use codex_hepta_bellman_operator::MemoryTensorCandidateV1;
use codex_hepta_bellman_operator::MemoryTrainingError;
use codex_hepta_bellman_operator::MemoryTrainingObservationV1;
use codex_hepta_bellman_operator::MemoryTrainingProfileV1;
use codex_hepta_bellman_operator::MemoryTrainingSourceV1;
use codex_hepta_bellman_operator::finish_memory_training_from_owner_v1;
use codex_hepta_bellman_operator::freeze_memory_training_from_owner_v1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::LoadedPinnedCandidate;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_memory::SharedExperiencePurposeV1;
use codex_hepta_memory::SharedExperienceUseV1;
use codex_hepta_types::Digest32;

use crate::shared_terminal_cell::AgentdSharedReplayHostV1;
use crate::shared_terminal_cell::SharedTerminalCellError;

#[derive(Debug)]
pub enum SharedMemoryTrainingError {
    Source(SharedTerminalCellError),
    Training(MemoryTrainingError),
    Invalid(&'static str),
}
impl fmt::Display for SharedMemoryTrainingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for SharedMemoryTrainingError {}
impl From<SharedTerminalCellError> for SharedMemoryTrainingError {
    fn from(value: SharedTerminalCellError) -> Self {
        Self::Source(value)
    }
}
impl From<MemoryTrainingError> for SharedMemoryTrainingError {
    fn from(value: MemoryTrainingError) -> Self {
        Self::Training(value)
    }
}

/// Opaque source-admitted job. Its source receipt cannot be supplied by a trainer.
#[derive(Clone)]
pub struct SharedMemoryTrainingV1 {
    frozen: FrozenMemoryTrainingV1,
    source: SharedExperienceUseV1,
}
impl SharedMemoryTrainingV1 {
    pub fn frozen(&self) -> &FrozenMemoryTrainingV1 {
        &self.frozen
    }
}

/// Immutable bytes awaiting the existing independent artifact admission path.
pub struct SharedMemoryTensorCandidateV1 {
    candidate: MemoryTensorCandidateV1,
    source: SharedExperienceUseV1,
    payload: Vec<u8>,
}
impl SharedMemoryTensorCandidateV1 {
    pub fn candidate(&self) -> &MemoryTensorCandidateV1 {
        &self.candidate
    }
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }
}

/// A loaded candidate still requires current source and registry checks at use.
pub struct SharedMemoryTensorModelV1 {
    candidate: MemoryTensorCandidateV1,
    source: SharedExperienceUseV1,
    pinned: RevalidatingCandidate,
}

impl AgentdSharedReplayHostV1 {
    async fn revalidate_memory_source(
        &self,
        source: &SharedExperienceUseV1,
        ledger: &LedgerWriter,
        dataset: &DatasetSnapshotReceiptV3,
        now: u64,
    ) -> Result<(), SharedMemoryTrainingError> {
        let current = self
            .source
            .read_shared_experience(&self.consumer, source.policy_id(), &self.purpose)
            .await
            .map_err(SharedTerminalCellError::Source)?;
        if &current != source {
            return Err(SharedMemoryTrainingError::Invalid("source use changed"));
        }
        ledger
            .revalidate_dataset_snapshot(dataset, now)
            .map_err(SharedTerminalCellError::Ledger)?;
        Ok(())
    }

    pub fn memory_parameter_scope_digest(&self) -> Result<Digest32, SharedMemoryTrainingError> {
        let SharedExperiencePurposeV1::Replay {
            parameter_scope,
            artifact_consumer,
        } = &self.purpose
        else {
            return Err(SharedMemoryTrainingError::Invalid(
                "training requires Replay purpose",
            ));
        };
        let mut bytes = b"hepta.memory-training.parameter-scope.v1\0".to_vec();
        for part in [
            parameter_scope.as_bytes(),
            artifact_consumer.as_str().as_bytes(),
        ] {
            bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
            bytes.extend_from_slice(part);
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    pub async fn prepare_memory_training(
        &self,
        policy_id: &Sha256Digest,
        ledger: &LedgerWriter,
        dataset: &DatasetSnapshotReceiptV3,
        profile: MemoryTrainingProfileV1,
        now: u64,
    ) -> Result<SharedMemoryTrainingV1, SharedMemoryTrainingError> {
        if profile.scope_digest != self.memory_parameter_scope_digest()? {
            return Err(SharedMemoryTrainingError::Invalid(
                "parameter scope mismatch",
            ));
        }
        let source = self
            .source
            .read_shared_experience(&self.consumer, policy_id, &self.purpose)
            .await
            .map_err(SharedTerminalCellError::Source)?;
        let support_digest = source
            .source_support_digest()
            .as_str()
            .parse()
            .map_err(|_| SharedMemoryTrainingError::Invalid("source support digest"))?;
        let content_digest = source
            .memory()
            .content_sha256
            .as_str()
            .parse()
            .map_err(|_| SharedMemoryTrainingError::Invalid("source content digest"))?;
        let frozen = freeze_memory_training_from_owner_v1(
            ledger,
            dataset,
            profile,
            MemoryTrainingSourceV1 {
                support_digest,
                content_digest,
                content: source.memory().content.clone(),
            },
            now,
        )?;
        self.revalidate_memory_source(&source, ledger, dataset, now)
            .await?;
        Ok(SharedMemoryTrainingV1 { frozen, source })
    }

    pub async fn finish_memory_training(
        &self,
        prepared: SharedMemoryTrainingV1,
        ledger: &LedgerWriter,
        observation: MemoryTrainingObservationV1,
        payload: Vec<u8>,
        now: u64,
    ) -> Result<SharedMemoryTensorCandidateV1, SharedMemoryTrainingError> {
        self.revalidate_memory_source(&prepared.source, ledger, prepared.frozen.dataset(), now)
            .await?;
        let candidate = finish_memory_training_from_owner_v1(
            ledger,
            prepared.frozen,
            observation,
            &payload,
            now,
        )?;
        self.revalidate_memory_source(&prepared.source, ledger, candidate.frozen().dataset(), now)
            .await?;
        Ok(SharedMemoryTensorCandidateV1 {
            candidate,
            source: prepared.source,
            payload,
        })
    }

    pub async fn load_memory_tensor(
        &self,
        candidate: SharedMemoryTensorCandidateV1,
        ledger: &LedgerWriter,
        loaded: LoadedPinnedCandidate,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
    ) -> Result<SharedMemoryTensorModelV1, SharedMemoryTrainingError> {
        self.revalidate_memory_source(
            &candidate.source,
            ledger,
            candidate.candidate.frozen().dataset(),
            now,
        )
        .await?;
        let profile = candidate.candidate.frozen().profile();
        let manifest = &loaded.spec().manifest;
        if manifest.artifact_id != profile.artifact_id
            || manifest.kind != ArtifactKind::Parameters
            || manifest.generation != profile.generation
            || manifest.objective_digest != profile.objective_digest
            || manifest.support_digest
                != candidate
                    .candidate
                    .frozen()
                    .dataset()
                    .snapshot
                    .dataset_digest
            || manifest.compatibility_digest != profile.base_digest
            || manifest.producer_id != profile.producer_id
            || manifest.content_digest != candidate.candidate.observation().payload_digest
            || manifest.encoded_size_bytes != candidate.payload.len() as u64
            || loaded.bytes() != candidate.payload
        {
            return Err(SharedMemoryTrainingError::Invalid(
                "loaded artifact identity/lineage mismatch",
            ));
        }
        let mut pinned = RevalidatingCandidate::new(loaded);
        pinned
            .with_current(current, |_| ())
            .map_err(|_| SharedMemoryTrainingError::Invalid("current artifact rejected"))?;
        Ok(SharedMemoryTensorModelV1 {
            candidate: candidate.candidate,
            source: candidate.source,
            pinned,
        })
    }

    /// The trusted consumer must be bounded and side-effect-free. State/effect
    /// publication stays with its owner after this result has been revalidated.
    pub async fn with_current_memory_tensor<T>(
        &self,
        model: &mut SharedMemoryTensorModelV1,
        ledger: &LedgerWriter,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, SharedMemoryTrainingError> {
        self.revalidate_memory_source(
            &model.source,
            ledger,
            model.candidate.frozen().dataset(),
            now,
        )
        .await?;
        let result = model
            .pinned
            .with_current(current, consume)
            .map_err(|_| SharedMemoryTrainingError::Invalid("current artifact rejected"))?;
        self.revalidate_memory_source(
            &model.source,
            ledger,
            model.candidate.frozen().dataset(),
            now,
        )
        .await?;
        Ok(result)
    }
}
