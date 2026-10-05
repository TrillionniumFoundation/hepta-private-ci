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
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::FederationConsumerAccess;
use codex_hepta_memory::SharedExperiencePurposeV1;
use codex_hepta_memory::SharedExperienceUseV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::sync::Arc;
use tokio::sync::Mutex;

#[derive(Debug, thiserror::Error)]
pub enum SharedTerminalCellError {
    #[error("shared source: {0}")]
    Source(#[from] CognitiveStoreError),
    #[error("learning owner: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("terminal cell: {0}")]
    Cell(#[from] TerminalCellError),
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
    publication: SharedTerminalPublication,
}

enum SharedTerminalPublication {
    Legacy,
    Current(Mutex<SharedTerminalFrontier>),
}

struct SharedTerminalFrontier {
    trust_digest: Digest32,
    receipt: RegistrySnapshotReceipt,
    closed: bool,
}

/// Native consumer configuration, supplied by the existing owner composition.
/// Caller identity is not inferred from Memory prose or a supplied model payload.
pub struct AgentdSharedReplayHostV1 {
    source: Arc<CognitiveStore>,
    consumer: FederationConsumerAccess,
    purpose: SharedExperiencePurposeV1,
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
        Self::load_payload(candidate, payload, SharedTerminalPublication::Legacy)
    }

    /// Load a V2 publication using the owner's authenticated CURRENT view and
    /// complete V3 admission closure. A compatibility-only view is insufficient.
    /// The host must obtain a fresh view at each load and prediction boundary.
    /// The model remains bound to this owner trust and registry history.
    pub async fn load_from_current(
        &self,
        candidate: SharedTerminalCandidateV1,
        ledger: &LedgerWriter,
        current: &VerifiedCurrentRegistryViewV1,
        payload: &[u8],
        now: u64,
    ) -> Result<SharedTerminalModelV1, SharedTerminalCellError> {
        self.revalidate(&candidate, ledger, now).await?;
        Self::validate_current(&candidate, current, now)?;
        Self::load_payload(
            candidate,
            payload,
            SharedTerminalPublication::Current(Mutex::new(SharedTerminalFrontier {
                trust_digest: current.trust_digest(),
                receipt: current.receipt(),
                closed: false,
            })),
        )
    }

    fn load_payload(
        candidate: SharedTerminalCandidateV1,
        payload: &[u8],
        publication: SharedTerminalPublication,
    ) -> Result<SharedTerminalModelV1, SharedTerminalCellError> {
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
        Ok(SharedTerminalModelV1 {
            candidate,
            loaded,
            publication,
        })
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
        if matches!(model.publication, SharedTerminalPublication::Current(_)) {
            return Err(SharedTerminalCellError::Binding(
                "current registry view required",
            ));
        }
        self.revalidate(&model.candidate, ledger, now).await?;
        Self::validate_registry(&model.candidate, registry)?;
        model
            .loaded
            .predict(sensor, action)
            .map_err(|_| SharedTerminalCellError::Binding("prediction cell"))
    }

    /// Revalidate the complete V2 publication, all its parents and dataset inputs
    /// through a fresh owner view before consuming the read-only model.
    /// A failed refresh permanently closes this model; explicit reload is required.
    pub async fn predict_from_current(
        &self,
        model: &SharedTerminalModelV1,
        ledger: &LedgerWriter,
        current: &VerifiedCurrentRegistryViewV1,
        sensor: &StableId,
        action: &StableId,
        now: u64,
    ) -> Result<TabularOperatorPredictionV1, SharedTerminalCellError> {
        let SharedTerminalPublication::Current(frontier) = &model.publication else {
            return Err(SharedTerminalCellError::Binding(
                "current registry load required",
            ));
        };
        let mut frontier = frontier.lock().await;
        if frontier.closed {
            return Err(SharedTerminalCellError::Binding(
                "current registry model unavailable",
            ));
        }
        // Keep the guard through source revalidation and prediction. Errors,
        // cancellation and panics retain the closed state rather than reviving
        // a cached model with an earlier accepted view.
        frontier.closed = true;
        if current.trust_digest() != frontier.trust_digest || !current.extends(frontier.receipt) {
            return Err(SharedTerminalCellError::Binding(
                "current registry frontier changed",
            ));
        }
        self.revalidate(&model.candidate, ledger, now).await?;
        Self::validate_current(&model.candidate, current, now)?;
        let prediction = model
            .loaded
            .predict(sensor, action)
            .map_err(|_| SharedTerminalCellError::Binding("prediction cell"))?;
        frontier.receipt = current.receipt();
        frontier.closed = false;
        Ok(prediction)
    }

    fn validate_current(
        candidate: &SharedTerminalCandidateV1,
        current: &VerifiedCurrentRegistryViewV1,
        now: u64,
    ) -> Result<(), SharedTerminalCellError> {
        if current.verified_at() != Some(now) {
            return Err(SharedTerminalCellError::Binding(
                "current registry view time",
            ));
        }
        let artifact = &candidate.artifact;
        let admission = current.full_admission(&artifact.artifact_id).ok_or(
            SharedTerminalCellError::Binding("artifact admission missing"),
        )?;
        let manifest = &admission.validated_manifest.manifest;
        if !current.is_eligible(&artifact.artifact_id)
            || manifest.artifact_id != artifact.artifact_id
            || manifest.kind != ArtifactKind::Policy
            || manifest.generation != artifact.generation
            || manifest.objective_class_digest != artifact.objective_digest
            || !manifest
                .source_dataset_digests
                .contains(&artifact.dataset_digest)
            || !manifest
                .lineage_digests
                .contains(&artifact.sensor_core_digest)
            || manifest.compatibility_digest != artifact.training_profile_digest
            || manifest.producer_id != artifact.producer_id
            || manifest.created_at > now
            || admission.admitted_at > now
            || now > manifest.expires_at
        {
            return Err(SharedTerminalCellError::Binding(
                "artifact revoked or incompatible",
            ));
        }
        if manifest.bytes_digest != candidate.payload_digest
            || manifest.encoded_size_bytes != candidate.payload_bytes
        {
            return Err(SharedTerminalCellError::Binding(
                "artifact manifest payload",
            ));
        }
        Ok(())
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
