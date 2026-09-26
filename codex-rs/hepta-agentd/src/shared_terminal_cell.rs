//! Same-host shared Replay consumer for the narrow terminal-cell baseline.
//!
//! Source support is exact: every training decision must cite the granted Memory
//! owner, identity, revision and content. Source and ledger are revalidated at
//! train, load and use; equal text from a different source is not equivalent support.
//! This adapter owns no database, authority issuer, effect executor or live model
//! selection authority. Independent signed selection is checked through the actual
//! fenced artifact owner at load and every use. Laya remains a separate profile.

use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularOperatorArtifactV1;
use codex_hepta_bellman_operator::TabularOperatorPredictionV1;
use codex_hepta_bellman_operator::TerminalCellError;
use codex_hepta_bellman_operator::TerminalCellProfileV1;
use codex_hepta_bellman_operator::fit_terminal_cell_from_owner_v1;
use codex_hepta_bellman_operator::freeze_terminal_cell_from_owner_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerHost;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
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
use std::sync::Mutex;

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
    trust_distribution_digest: Digest32,
}

impl SharedTerminalCandidateV1 {
    /// Persist these complete bytes through the existing artifact owner. The
    /// independent selector signs their digest, including all recovery metadata.
    pub fn encode_payload(&self) -> Result<Vec<u8>, SharedTerminalCellError> {
        crate::shared_terminal_recovery::encode(
            &self.artifact,
            &self.dataset,
            &self.source,
            self.trust_distribution_digest,
        )
    }

    pub fn artifact(&self) -> &TabularOperatorArtifactV1 {
        &self.artifact
    }
}

/// Loaded read-only baseline whose use still requires current source permission.
pub struct SharedTerminalModelV1 {
    dataset: DatasetSnapshotReceiptV3,
    source: SharedExperienceUseV1,
    loaded: LoadedTabularOperatorV1,
    selection: SignedArtifactSelectionV1,
    manifest: ArtifactManifest,
    manifest_expires_at: u64,
    trust_distribution_digest: Digest32,
    closed: bool,
}

struct SharedTerminalArtifactOwner {
    owner: Arc<Mutex<LearningArtifactOwnerHost>>,
    selector: ArtifactSelectionVerifierV1,
}

/// Native consumer configuration, supplied by the existing owner composition.
/// Caller identity is not inferred from Memory prose or a supplied model payload.
pub struct AgentdSharedReplayHostV1 {
    source: Arc<CognitiveStore>,
    consumer: FederationConsumerAccess,
    purpose: SharedExperiencePurposeV1,
    artifacts: Option<SharedTerminalArtifactOwner>,
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
            artifacts: None,
            purpose: SharedExperiencePurposeV1::Replay {
                parameter_scope,
                artifact_consumer,
            },
        })
    }

    /// Bind the actual fenced artifact owner, not a replayable view provider.
    /// Hosts must share this lock with publication. Training alone is permitted
    /// without this binding; loading and consuming a model are not.
    pub fn with_artifact_owner(
        mut self,
        owner: Arc<Mutex<LearningArtifactOwnerHost>>,
        selector: ArtifactSelectionVerifierV1,
    ) -> Self {
        self.artifacts = Some(SharedTerminalArtifactOwner { owner, selector });
        self
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
        let candidate = SharedTerminalCandidateV1 {
            artifact,
            dataset: dataset.clone(),
            trust_distribution_digest: ledger.trust_distribution_digest(),
            source,
        };
        self.revalidate(
            &candidate.source,
            &candidate.dataset,
            candidate.trust_distribution_digest,
            ledger,
            now,
        )
        .await?;
        Ok(candidate)
    }

    /// Reopen the complete selected version from a durable native configuration
    /// pin. The descriptor, bundle, source and dataset are all required; no
    /// missing input is substituted by retraining or a different version.
    pub async fn restore(
        &self,
        ledger: &LedgerWriter,
        selection_digest: Digest32,
        now: u64,
    ) -> Result<SharedTerminalModelV1, SharedTerminalCellError> {
        let binding = self
            .artifacts
            .as_ref()
            .ok_or(SharedTerminalCellError::Binding(
                "artifact owner not configured",
            ))?;
        let selection = binding
            .owner
            .lock()
            .map_err(|_| SharedTerminalCellError::Binding("artifact owner poisoned"))?
            .read_selected_descriptor(&binding.selector, selection_digest, now)
            .map_err(|_| SharedTerminalCellError::Binding("selected descriptor unavailable"))?;
        self.load(ledger, selection, now).await
    }

    /// Restore a selected version entirely from durable owner bytes. Neither an
    /// in-memory training candidate nor a caller-supplied registry is accepted.
    pub async fn load(
        &self,
        ledger: &LedgerWriter,
        selection: SignedArtifactSelectionV1,
        now: u64,
    ) -> Result<SharedTerminalModelV1, SharedTerminalCellError> {
        let binding = self
            .artifacts
            .as_ref()
            .ok_or(SharedTerminalCellError::Binding(
                "artifact owner not configured",
            ))?;
        if selection.encoded_size_bytes > 4 * 1024 * 1024 {
            return Err(SharedTerminalCellError::Binding("recovery payload bound"));
        }
        let (manifest, admitted, bytes) = {
            let owner = binding
                .owner
                .lock()
                .map_err(|_| SharedTerminalCellError::Binding("artifact owner poisoned"))?;
            let (manifest, bytes) = owner
                .read_current_selected_payload(&binding.selector, &selection, now)
                .map_err(|_| SharedTerminalCellError::Binding("current artifact selection"))?;
            let admitted = owner
                .read_current_selected_manifest(&binding.selector, &selection, now)
                .map_err(|_| SharedTerminalCellError::Binding("current artifact manifest"))?;
            (manifest, admitted, bytes)
        };
        let recovered = crate::shared_terminal_recovery::decode(&bytes, &manifest, &admitted)?;
        let source = self
            .source
            .read_shared_experience(&self.consumer, &recovered.policy_id, &self.purpose)
            .await?;
        if source.policy_revision() != recovered.policy_revision
            || source.source_support_digest() != recovered.source_support
        {
            return Err(SharedTerminalCellError::Binding("recovery source changed"));
        }
        let support: Digest32 = source
            .source_support_digest()
            .as_str()
            .parse()
            .map_err(|_| SharedTerminalCellError::Binding("recovery source digest"))?;
        let records = ledger.read_dataset_records(&recovered.dataset, now)?;
        if records.iter().any(|record| {
            matches!(&record.event, LedgerEvent::AuthenticatedDecisionV2(value)
                if value.support_digest != support)
        }) {
            return Err(SharedTerminalCellError::Binding("decision source support"));
        }
        self.revalidate(
            &source,
            &recovered.dataset,
            recovered.trust_distribution_digest,
            ledger,
            now,
        )
        .await?;
        // Source reads yield. Do not retain a CURRENT view across that boundary.
        let owner = binding
            .owner
            .lock()
            .map_err(|_| SharedTerminalCellError::Binding("artifact owner poisoned"))?;
        let current = owner
            .current_registry_view(now)
            .map_err(|_| SharedTerminalCellError::Binding("current artifact selection"))?;
        let verified = binding
            .selector
            .verify(&selection, &current, now)
            .map_err(|_| SharedTerminalCellError::Binding("current artifact selection"))?;
        if verified.manifest() != &manifest {
            return Err(SharedTerminalCellError::Binding(
                "artifact manifest changed",
            ));
        }
        Ok(SharedTerminalModelV1 {
            dataset: recovered.dataset,
            source,
            loaded: recovered.loaded,
            selection,
            manifest,
            manifest_expires_at: admitted.manifest.expires_at,
            trust_distribution_digest: recovered.trust_distribution_digest,
            closed: false,
        })
    }

    /// Failure or cancellation closes this loaded consumer. An explicit load
    /// with a currently accepted selection is required before any further use.
    pub async fn predict(
        &self,
        model: &mut SharedTerminalModelV1,
        ledger: &LedgerWriter,
        sensor: &StableId,
        action: &StableId,
        now: u64,
    ) -> Result<TabularOperatorPredictionV1, SharedTerminalCellError> {
        if model.closed {
            return Err(SharedTerminalCellError::Binding("model consumer closed"));
        }
        model.closed = true;
        if now > model.manifest_expires_at {
            return Err(SharedTerminalCellError::Binding(
                "artifact manifest expired",
            ));
        }
        self.revalidate(
            &model.source,
            &model.dataset,
            model.trust_distribution_digest,
            ledger,
            now,
        )
        .await?;
        let binding = self
            .artifacts
            .as_ref()
            .ok_or(SharedTerminalCellError::Binding(
                "artifact owner not configured",
            ))?;
        let owner = binding
            .owner
            .lock()
            .map_err(|_| SharedTerminalCellError::Binding("artifact owner poisoned"))?;
        let current = owner
            .current_registry_view(now)
            .map_err(|_| SharedTerminalCellError::Binding("current artifact selection"))?;
        let verified = binding
            .selector
            .verify(&model.selection, &current, now)
            .map_err(|_| SharedTerminalCellError::Binding("current artifact selection"))?;
        if verified.manifest() != &model.manifest {
            return Err(SharedTerminalCellError::Binding(
                "artifact manifest changed",
            ));
        }
        // Pure inference and owner refresh share the publication lock; no await,
        // effect dispatch, or live authority escapes this boundary.
        let result = model
            .loaded
            .predict(sensor, action)
            .map_err(|_| SharedTerminalCellError::Binding("prediction cell"))?;
        model.closed = false;
        Ok(result)
    }

    async fn revalidate(
        &self,
        source: &SharedExperienceUseV1,
        dataset: &DatasetSnapshotReceiptV3,
        trust_distribution_digest: Digest32,
        ledger: &LedgerWriter,
        now: u64,
    ) -> Result<(), SharedTerminalCellError> {
        if trust_distribution_digest.is_zero()
            || trust_distribution_digest != ledger.trust_distribution_digest()
        {
            return Err(SharedTerminalCellError::Binding(
                "current learning trust changed",
            ));
        }
        let current = self
            .source
            .read_shared_experience(&self.consumer, source.policy_id(), &self.purpose)
            .await?;
        if &current != source {
            return Err(SharedTerminalCellError::Binding("source use changed"));
        }
        ledger.revalidate_dataset_snapshot(dataset, now)?;
        Ok(())
    }
}
