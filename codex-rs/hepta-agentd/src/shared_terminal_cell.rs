//! Same-host shared Replay consumer for the narrow terminal-cell baseline.
//!
//! Source support is exact: every training decision must cite the granted Memory
//! owner, identity, revision and content. Source and ledger are revalidated at
//! train, load and use; equal text from a different source is not equivalent support.
//! This adapter owns no database, authority issuer, effect executor or live model
//! selection. Laya and multi-source causal training are separate profiles.

use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularOperatorArtifactV1;
use codex_hepta_bellman_operator::TabularOperatorPredictionV1;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_bellman_operator::TerminalCellError;
use codex_hepta_bellman_operator::TerminalCellProfileV1;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_terminal_cell_from_owner_v1;
use codex_hepta_bellman_operator::freeze_terminal_cell_from_owner_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::NeuronTrialLedgerSourceV1;
use codex_hepta_learning_ledger::NeuronTrialSourceError;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::FederationConsumerAccess;
use codex_hepta_memory::SharedExperiencePurposeV1;
use codex_hepta_memory::SharedExperienceUseV1;
use codex_hepta_memory::StableMemoryId;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::sync::Arc;

#[derive(Debug, thiserror::Error)]
pub enum SharedTerminalCellError {
    #[error("shared source: {0}")]
    Source(#[from] CognitiveStoreError),
    #[error("learning owner: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("terminal cell: {0}")]
    Cell(#[from] TerminalCellError),
    #[error("native Neuron ledger source: {0}")]
    NeuronSource(#[from] NeuronTrialSourceError),
    #[error("shared terminal binding: {0}")]
    Binding(&'static str),
}

/// Immutable candidate with the exact source use and dataset retained for later
/// revalidation. Exposing the artifact does not authorize adoption or an effect.
#[derive(Clone, Debug)]
pub struct SharedTerminalCandidateV1 {
    artifact: TabularOperatorArtifactV1,
    dataset: DatasetSnapshotReceiptV3,
    source: SharedExperienceUseV1,
    payload_digest: Digest32,
    payload_bytes: u64,
}

impl SharedTerminalCandidateV1 {
    pub fn artifact(&self) -> &TabularOperatorArtifactV1 {
        &self.artifact
    }
}

/// Loaded read-only baseline whose use still requires current source permission.
pub struct SharedTerminalModelV1 {
    candidate: SharedTerminalCandidateV1,
    loaded: LoadedTabularOperatorV1,
}

/// Native consumer configuration, supplied by the existing owner composition.
/// Caller identity is not inferred from Memory prose or a supplied model payload.
pub struct AgentdSharedReplayHostV1 {
    source: Arc<CognitiveStore>,
    consumer: FederationConsumerAccess,
    purpose: SharedExperiencePurposeV1,
}

/// A narrowly scoped read-only bind of a live, granted Replay source to an
/// owner-produced Ledger terminal cohort. It contains no source text or labels.
/// This is not a signed host admission or a production no-change certificate.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedReplayNeuronTrialSourceV1 {
    pub ledger_source: NeuronTrialLedgerSourceV1,
    pub replay_policy_id: Sha256Digest,
    pub replay_policy_revision: u64,
    /// Exact revision of the live Memory owner that allowed this Replay.
    pub source_memory_id: StableMemoryId,
    pub source_memory_revision: u64,
    pub source_content_digest: Digest32,
    pub source_support_digest: Digest32,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl SharedReplayNeuronTrialSourceV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.neuron-replay-ledger-source.v1\0".to_vec();
        bytes.extend_from_slice(self.ledger_source.diagnostic_digest.as_array());
        let raw = self.replay_policy_id.as_str().as_bytes();
        bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
        bytes.extend_from_slice(raw);
        bytes.extend_from_slice(&self.replay_policy_revision.to_be_bytes());
        let memory_id = self.source_memory_id.as_str().as_bytes();
        bytes.extend_from_slice(&(memory_id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(memory_id);
        bytes.extend_from_slice(&self.source_memory_revision.to_be_bytes());
        bytes.extend_from_slice(self.source_content_digest.as_array());
        bytes.extend_from_slice(self.source_support_digest.as_array());
        Digest32::of_bytes(&bytes)
    }

    /// This only detects accidental mutation or a malformed binding, not a
    /// dishonest issuer. The same owner must revalidate before final model use.
    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && self.ledger_source.validate_integrity()
            && self.replay_policy_revision > 0
            && self.source_memory_revision > 0
            && !self.source_content_digest.is_zero()
            && !self.source_support_digest.is_zero()
            && !self.ledger_source.terminal_joins.is_empty()
            && self.ledger_source.pending_episodes == 0
            && self.ledger_source.censored_episodes == 0
            && self
                .ledger_source
                .terminal_joins
                .iter()
                .all(|join| join.decision_support_digest == self.source_support_digest)
            && self.diagnostic_digest == self.computed_digest()
    }
}

impl AgentdSharedReplayHostV1 {
    pub fn new(
        source: Arc<CognitiveStore>,
        consumer: FederationConsumerAccess,
        parameter_scope: String,
        artifact_consumer: AgentId,
    ) -> Result<Self, SharedTerminalCellError> {
        if consumer.agent_id() != &artifact_consumer
            || parameter_scope.trim().is_empty()
            || parameter_scope.len() > 128
            || parameter_scope.as_bytes().contains(&0)
        {
            return Err(SharedTerminalCellError::Binding("parameter scope"));
        }
        Ok(Self {
            source,
            consumer,
            purpose: SharedExperiencePurposeV1::Replay {
                parameter_scope,
                artifact_consumer,
            },
        })
    }

    /// Recheck the real Ledger owner and the current Memory Replay grant.
    /// All admitted terminal decisions must cite the same exact Memory
    /// source revision; multi-source cohorts require a separate policy.
    ///
    /// This is cross-owner best-effort read validation, NOT an atomic two-store
    /// snapshot or authorization to deliver raw content to a model runner.
    #[allow(clippy::too_many_arguments)]
    pub async fn read_neuron_trial_shared_source_v1(
        &self,
        policy_id: &Sha256Digest,
        ledger: &LedgerWriter,
        frozen_ledger: &LedgerSnapshot,
        plan: &DatasetFreezePlanV2,
        signed_freeze: &SignedLearningEvidenceV1,
        dataset: &DatasetSnapshotReceiptV3,
        now: u64,
    ) -> Result<SharedReplayNeuronTrialSourceV1, SharedTerminalCellError> {
        // The host is constructed for Replay only. A Recall-only grant cannot
        // authorize a trial dataset, even if its Memory text is identical.
        let source = self
            .source
            .read_shared_experience(&self.consumer, policy_id, &self.purpose)
            .await?;
        let support: Digest32 = source
            .source_support_digest()
            .as_str()
            .parse()
            .map_err(|_| SharedTerminalCellError::Binding("source support identity"))?;
        let ledger_source =
            ledger.read_neuron_trial_source_v1(frozen_ledger, plan, signed_freeze, dataset, now)?;
        if ledger_source.terminal_joins.is_empty()
            || ledger_source.pending_episodes != 0
            || ledger_source.censored_episodes != 0
            || ledger_source
                .terminal_joins
                .iter()
                .any(|join| join.decision_support_digest != support)
        {
            return Err(SharedTerminalCellError::Binding(
                "Neuron trial source support mismatch",
            ));
        }
        self.source.revalidate_shared_experience(&source).await?;
        if ledger.read_neuron_trial_source_v1(frozen_ledger, plan, signed_freeze, dataset, now)?
            != ledger_source
        {
            return Err(SharedTerminalCellError::Binding(
                "Neuron trial ledger changed during source read",
            ));
        }
        let source_content_digest: Digest32 = source
            .memory()
            .content_sha256
            .as_str()
            .parse()
            .map_err(|_| SharedTerminalCellError::Binding("source content digest"))?;
        let mut binding = SharedReplayNeuronTrialSourceV1 {
            ledger_source,
            replay_policy_id: source.policy_id().clone(),
            replay_policy_revision: source.policy_revision(),
            source_memory_id: source.memory().id.memory_id.clone(),
            source_memory_revision: source.memory().id.revision,
            source_content_digest,
            source_support_digest: support,
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        binding.diagnostic_digest = binding.computed_digest();
        if !binding.validate_integrity() {
            return Err(SharedTerminalCellError::Binding(
                "Neuron source diagnostic integrity",
            ));
        }
        Ok(binding)
    }

    pub async fn train(
        &self,
        policy_id: &Sha256Digest,
        ledger: &LedgerWriter,
        dataset: &DatasetSnapshotReceiptV3,
        profile: TerminalCellProfileV1,
        now: u64,
    ) -> Result<SharedTerminalCandidateV1, SharedTerminalCellError> {
        let source = self
            .source
            .read_shared_experience(&self.consumer, policy_id, &self.purpose)
            .await?;
        let support: Digest32 = source
            .source_support_digest()
            .as_str()
            .parse()
            .map_err(|_| SharedTerminalCellError::Binding("source digest"))?;
        // Check the terminal profile's bounded dataset before materializing records.
        let frozen = freeze_terminal_cell_from_owner_v1(ledger, dataset, profile, now)?;
        let records = ledger.read_dataset_records(dataset, now)?;
        // This baseline admits one complete support root, not arbitrary mixed data
        // whose training permissions are hidden behind an aggregate digest.
        if records.iter().any(|record| {
            matches!(
                &record.event, LedgerEvent::AuthenticatedDecisionV2(value)
                    if value.support_digest != support
            )
        }) {
            return Err(SharedTerminalCellError::Binding("decision source support"));
        }
        let artifact = fit_terminal_cell_from_owner_v1(ledger, frozen, now)?;
        let bytes = encode_tabular_payload_v1(&artifact)
            .map_err(|_| SharedTerminalCellError::Binding("artifact encoding"))?;
        let candidate = SharedTerminalCandidateV1 {
            artifact,
            dataset: dataset.clone(),
            source,
            payload_digest: Digest32::of_bytes(&bytes),
            payload_bytes: bytes.len() as u64,
        };
        self.revalidate(&candidate, ledger, now).await?;
        Ok(candidate)
    }

    /// Load bytes supplied by the existing artifact resolver. Exact expected bytes,
    /// generation and source lineage are checked; this does not select a release.
    pub async fn load(
        &self,
        candidate: SharedTerminalCandidateV1,
        ledger: &LedgerWriter,
        registry: &ArtifactRegistry,
        payload: &[u8],
        now: u64,
    ) -> Result<SharedTerminalModelV1, SharedTerminalCellError> {
        self.revalidate(&candidate, ledger, now).await?;
        Self::validate_registry(&candidate, registry)?;
        let expected = encode_tabular_payload_v1(&candidate.artifact)
            .map_err(|_| SharedTerminalCellError::Binding("artifact encoding"))?;
        if payload != expected {
            return Err(SharedTerminalCellError::Binding("artifact payload"));
        }
        let artifact = &candidate.artifact;
        let pin = TabularPayloadPinV1 {
            payload_digest: Digest32::of_bytes(payload),
            artifact_digest: artifact.artifact_digest,
            objective_digest: artifact.objective_digest,
            dataset_digest: artifact.dataset_digest,
            sensor_core_digest: artifact.sensor_core_digest,
            training_profile_digest: artifact.training_profile_digest,
            generation: artifact.generation,
        };
        let loaded = LoadedTabularOperatorV1::from_pinned_payload(payload, &pin)
            .map_err(|_| SharedTerminalCellError::Binding("artifact pin"))?;
        Ok(SharedTerminalModelV1 { candidate, loaded })
    }

    pub async fn predict(
        &self,
        model: &SharedTerminalModelV1,
        ledger: &LedgerWriter,
        registry: &ArtifactRegistry,
        sensor: &StableId,
        action: &StableId,
        now: u64,
    ) -> Result<TabularOperatorPredictionV1, SharedTerminalCellError> {
        self.revalidate(&model.candidate, ledger, now).await?;
        Self::validate_registry(&model.candidate, registry)?;
        model
            .loaded
            .predict(sensor, action)
            .map_err(|_| SharedTerminalCellError::Binding("prediction cell"))
    }

    fn validate_registry(
        candidate: &SharedTerminalCandidateV1,
        registry: &ArtifactRegistry,
    ) -> Result<(), SharedTerminalCellError> {
        let artifact = &candidate.artifact;
        let manifest = registry
            .manifest(&artifact.artifact_id)
            .ok_or(SharedTerminalCellError::Binding("artifact not registered"))?;
        if !registry.is_eligible(&artifact.artifact_id)
            || manifest.kind != ArtifactKind::Policy
            || manifest.generation != artifact.generation
            || manifest.objective_digest != artifact.objective_digest
            || manifest.support_digest != artifact.dataset_digest
            || manifest.compatibility_digest != artifact.training_profile_digest
            || manifest.producer_id != artifact.producer_id
        {
            return Err(SharedTerminalCellError::Binding(
                "artifact revoked or incompatible",
            ));
        }
        if manifest.content_digest != candidate.payload_digest
            || manifest.encoded_size_bytes != candidate.payload_bytes
        {
            return Err(SharedTerminalCellError::Binding(
                "artifact manifest payload",
            ));
        }
        Ok(())
    }

    async fn revalidate(
        &self,
        candidate: &SharedTerminalCandidateV1,
        ledger: &LedgerWriter,
        now: u64,
    ) -> Result<(), SharedTerminalCellError> {
        let current = self
            .source
            .read_shared_experience(&self.consumer, candidate.source.policy_id(), &self.purpose)
            .await?;
        if current != candidate.source {
            return Err(SharedTerminalCellError::Binding("source use changed"));
        }
        ledger.revalidate_dataset_snapshot(&candidate.dataset, now)?;
        Ok(())
    }
}
