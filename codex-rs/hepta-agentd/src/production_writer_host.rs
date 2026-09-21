//! Explicit Agentd/host seam for the production durable writer.
//!
//! The host must supply an externally verified authority lease and verifier.
//! Nothing in Agentd startup installs this capability automatically; the
//! default runtime remains read-only. A dispatcher target is likewise an
//! explicit attachment and dispatch fails closed while it is absent.

use std::fmt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::AuthoritativeCognitiveSnapshotProvider;
use codex_hepta_cognitive_read::AuthoritativeSnapshotV1;
use codex_hepta_cognitive_read::SnapshotAcquisitionRequestV1;
use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_compact_engine::CompactionInputRecordV2;
use codex_hepta_compact_engine::CompactionPolicyV2;
use codex_hepta_compact_engine::CompactionProofWitnessV1;
use codex_hepta_compact_engine::CompactionQualificationV2;
use codex_hepta_compact_engine::CompactionSemanticPayloadV2;
use codex_hepta_compact_engine::QualifiedCompactionError;
use codex_hepta_compact_engine::TrustedCompactionEvaluatorV1;
use codex_hepta_compact_engine::TrustedTokenizerV1;
use codex_hepta_compact_engine::build_qualified_candidate;
use codex_hepta_compact_engine::prove_compaction;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionDispatchReceipt;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionOutboxDispatcher;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionQueuedReceipt;
use codex_hepta_memory::ProductionWriterError;
use codex_hepta_memory::QualifiedCompactCheckpointPublication;
use codex_hepta_memory::QualifiedCompactRollbackCandidate;
use codex_hepta_memory::QualifiedCompactSelection;
use codex_hepta_memory::QualifiedCompactStoreError;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AgentdConfig;
use crate::AgentdError;

/// Host-owned production writer handle. Constructing this value does not
/// mutate Agentd's runtime configuration; callers explicitly attach/use it.
#[derive(Clone)]
pub struct AgentdProductionWriterHost {
    writer: Arc<ProductionDurableWriter>,
    dispatcher: Option<ProductionOutboxDispatcher>,
    compaction_trust: Option<AgentdCompactionTrustV1>,
    snapshot_provider: Option<Arc<dyn AuthoritativeCognitiveSnapshotProvider + Send + Sync>>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdCompactionTrustV1 {
    pub tokenizer: TrustedTokenizerV1,
    pub evaluator: TrustedCompactionEvaluatorV1,
}

impl AgentdCompactionTrustV1 {
    pub fn new(tokenizer: TrustedTokenizerV1, evaluator: TrustedCompactionEvaluatorV1) -> Self {
        Self {
            tokenizer,
            evaluator,
        }
    }
}

/// Externally supplied runtime bootstrap for the production writer.
///
/// Nothing here manufactures authority or trust. The caller must provide an
/// already-verified production lease, an independent verifier, enrolled
/// tokenizer/evaluator trust roots, and the authoritative snapshot provider.
/// Agentd only composes these dependencies against its already-open owner store.
#[derive(Clone)]
pub struct AgentdProductionWriterBootstrap {
    authority: ProductionAuthorityLease,
    verifier: Arc<dyn ProductionAuthorityVerifier>,
    lease_id: Arc<str>,
    lease_generation: u64,
    compaction_trust: AgentdCompactionTrustV1,
    snapshot_provider: Arc<dyn AuthoritativeCognitiveSnapshotProvider + Send + Sync>,
}

impl AgentdProductionWriterBootstrap {
    pub fn new(
        authority: ProductionAuthorityLease,
        verifier: Arc<dyn ProductionAuthorityVerifier>,
        lease_id: impl Into<String>,
        lease_generation: u64,
        compaction_trust: AgentdCompactionTrustV1,
        snapshot_provider: Arc<dyn AuthoritativeCognitiveSnapshotProvider + Send + Sync>,
    ) -> Result<Self, AgentdError> {
        let lease_id = lease_id.into();
        if lease_id.trim().is_empty() || lease_id.len() > 512 || lease_generation == 0 {
            return Err(AgentdError::Invalid(
                "production writer bootstrap requires a bounded lease id and non-zero generation"
                    .to_string(),
            ));
        }
        Ok(Self {
            authority,
            verifier,
            lease_id: Arc::from(lease_id),
            lease_generation,
            compaction_trust,
            snapshot_provider,
        })
    }

    pub async fn open_with_store(
        &self,
        store: CognitiveStore,
    ) -> Result<AgentdProductionWriterHost, ProductionWriterError> {
        let host = AgentdProductionWriterHost::open_with_store(
            store,
            self.authority.clone(),
            self.verifier.as_ref(),
            self.lease_id.to_string(),
            self.lease_generation,
        )
        .await?;
        Ok(host
            .attach_compaction_trust(self.compaction_trust.clone())
            .attach_snapshot_provider(Arc::clone(&self.snapshot_provider)))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdCompactionCheckpointRequest {
    pub snapshot_acquisition_request: SnapshotAcquisitionRequestV1,
    pub generation: Generation,
    pub predecessor_checkpoint_digest: Option<Digest32>,
    pub policy: CompactionPolicyV2,
    pub semantic_payload: CompactionSemanticPayloadV2,
    pub inputs: Vec<CompactionInputRecordV2>,
    pub qualification: CompactionQualificationV2,
}

#[derive(Debug, thiserror::Error)]
pub enum AgentdCompactionCheckpointError {
    #[error(transparent)]
    Snapshot(#[from] SnapshotProviderError),
    #[error(transparent)]
    Qualification(#[from] QualifiedCompactionError),
    #[error(transparent)]
    Writer(#[from] ProductionWriterError),
    #[error(transparent)]
    Store(#[from] QualifiedCompactStoreError),
    #[error("compact checkpoint trust roots are not attached to this host")]
    CompactionTrustUnavailable,
    #[error("authoritative cognitive snapshot provider is not attached to this host")]
    SnapshotProviderUnavailable,
    #[error("system clock is unavailable for snapshot freshness validation: {0}")]
    Clock(String),
}

impl fmt::Debug for AgentdProductionWriterHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AgentdProductionWriterHost")
            .field("writer", &self.writer)
            .field("dispatcher_attached", &self.dispatcher.is_some())
            .field(
                "compaction_trust_attached",
                &self.compaction_trust.is_some(),
            )
            .field(
                "snapshot_provider_attached",
                &self.snapshot_provider.is_some(),
            )
            .finish()
    }
}

impl AgentdProductionWriterHost {
    /// Open the writer against Agentd's exact private cognitive store. The
    /// verifier is mandatory and runs before any lease/event/outbox mutation.
    pub async fn open<V>(
        config: &AgentdConfig,
        authority: ProductionAuthorityLease,
        verifier: &V,
        lease_id: impl Into<String>,
        lease_generation: u64,
    ) -> Result<Self, AgentdError>
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        let store = CognitiveStore::open(&config.identity().layout)
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("open production cognitive store: {error}"))
            })?;
        let writer =
            ProductionDurableWriter::open(store, authority, verifier, lease_id, lease_generation)
                .await?;
        Ok(Self {
            writer: Arc::new(writer),
            dispatcher: None,
            compaction_trust: None,
            snapshot_provider: None,
        })
    }

    /// Build a host handle around an already-open Agentd-owned store. This is
    /// useful when the runtime has already attached a CognitiveStore and keeps
    /// the same mandatory external verifier contract.
    pub async fn open_with_store<V>(
        store: CognitiveStore,
        authority: ProductionAuthorityLease,
        verifier: &V,
        lease_id: impl Into<String>,
        lease_generation: u64,
    ) -> Result<Self, ProductionWriterError>
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        let writer =
            ProductionDurableWriter::open(store, authority, verifier, lease_id, lease_generation)
                .await?;
        Ok(Self {
            writer: Arc::new(writer),
            dispatcher: None,
            compaction_trust: None,
            snapshot_provider: None,
        })
    }

    pub fn writer(&self) -> Arc<ProductionDurableWriter> {
        Arc::clone(&self.writer)
    }

    /// Attach deployment-enrolled tokenizer and evaluator trust roots. These
    /// are host configuration, never request fields, so untrusted callers
    /// cannot self-assert the keys that authenticate their own evidence.
    pub fn attach_compaction_trust(mut self, trust: AgentdCompactionTrustV1) -> Self {
        self.compaction_trust = Some(trust);
        self
    }

    pub fn has_compaction_trust(&self) -> bool {
        self.compaction_trust.is_some()
    }

    /// Attach the authoritative cognitive snapshot provider selected by the
    /// host bootstrap. Requests carry only a bounded acquisition request; they
    /// can never inject an already-constructed snapshot envelope.
    pub fn attach_snapshot_provider(
        mut self,
        provider: Arc<dyn AuthoritativeCognitiveSnapshotProvider + Send + Sync>,
    ) -> Self {
        self.snapshot_provider = Some(provider);
        self
    }

    pub fn has_snapshot_provider(&self) -> bool {
        self.snapshot_provider.is_some()
    }

    fn acquire_current_snapshot(
        &self,
        request: &SnapshotAcquisitionRequestV1,
    ) -> Result<AuthoritativeSnapshotV1, AgentdCompactionCheckpointError> {
        let provider = self
            .snapshot_provider
            .as_ref()
            .ok_or(AgentdCompactionCheckpointError::SnapshotProviderUnavailable)?;
        let snapshot = provider.acquire(request)?;
        snapshot.validate_for_request(now_unix_ms()?, request)?;
        Ok(snapshot)
    }

    /// Product composition point for compact.engine.
    ///
    /// The pure engine constructs one canonical candidate/proof pair, then the
    /// externally-authorized durable writer performs the only persistent
    /// publication.  There is no legacy checkpoint path or unleased fallback.
    pub async fn publish_compaction_checkpoint(
        &self,
        request: AgentdCompactionCheckpointRequest,
    ) -> Result<QualifiedCompactCheckpointPublication, AgentdCompactionCheckpointError> {
        let trust = self
            .compaction_trust
            .as_ref()
            .ok_or(AgentdCompactionCheckpointError::CompactionTrustUnavailable)?;
        let AgentdCompactionCheckpointRequest {
            snapshot_acquisition_request,
            generation,
            predecessor_checkpoint_digest,
            policy,
            semantic_payload,
            inputs,
            qualification,
        } = request;
        let source_snapshot = self.acquire_current_snapshot(&snapshot_acquisition_request)?;
        let candidate = build_qualified_candidate(
            source_snapshot.snapshot_key().clone(),
            source_snapshot.snapshot(),
            generation,
            predecessor_checkpoint_digest,
            &policy,
            &semantic_payload,
            &trust.tokenizer,
            inputs,
        )?;
        let proof_witness = CompactionProofWitnessV1 {
            evaluator_verifying_key: trust.evaluator.verifying_key,
            qualification_signature: qualification.signature,
        };
        let proof = prove_compaction(&candidate, &trust.evaluator, qualification)?;
        proof_witness.verify_proof(&proof)?;
        Ok(self
            .writer
            .publish_qualified_compact_checkpoint(
                candidate.checkpoint(),
                &proof,
                &proof_witness,
                &candidate.semantic_payload().payload,
            )
            .await?)
    }

    /// Re-admit the selected durable head against a freshly authenticated
    /// owner snapshot and require the exact payload bytes to remain resolvable.
    pub async fn select_current_compaction_checkpoint(
        &self,
        snapshot_acquisition_request: &SnapshotAcquisitionRequestV1,
        compatibility_digest: Digest32,
    ) -> Result<Option<QualifiedCompactSelection>, AgentdCompactionCheckpointError> {
        let source_snapshot = self.acquire_current_snapshot(snapshot_acquisition_request)?;
        Ok(self
            .writer
            .store()
            .select_current_qualified_compact_checkpoint(
                source_snapshot.snapshot_key(),
                source_snapshot.snapshot().snapshot_digest,
                compatibility_digest,
            )
            .await?)
    }

    /// A rollback never selects historical state in place. It only exposes a
    /// historical payload as a re-admitted candidate; a new successor must be
    /// rebuilt, independently qualified and published through the normal path.
    pub async fn rollback_compaction_payload_candidate(
        &self,
        generation: Generation,
        snapshot_acquisition_request: &SnapshotAcquisitionRequestV1,
        compatibility_digest: Digest32,
    ) -> Result<Option<QualifiedCompactRollbackCandidate>, AgentdCompactionCheckpointError> {
        let source_snapshot = self.acquire_current_snapshot(snapshot_acquisition_request)?;
        Ok(self
            .writer
            .store()
            .rollback_qualified_compact_payload_candidate(
                generation,
                source_snapshot.snapshot_key(),
                source_snapshot.snapshot().snapshot_digest,
                compatibility_digest,
            )
            .await?)
    }

    pub async fn revoke_compaction_payload(
        &self,
        scope_id: &StableId,
        purpose_id: &StableId,
        payload_digest: Digest32,
        tombstone_frontier: u64,
        revocation_digest: Digest32,
    ) -> Result<(), AgentdCompactionCheckpointError> {
        Ok(self
            .writer
            .revoke_qualified_compact_payload(
                scope_id,
                purpose_id,
                payload_digest,
                tombstone_frontier,
                revocation_digest,
            )
            .await?)
    }

    pub async fn gc_revoked_compaction_payload(
        &self,
        scope_id: &StableId,
        purpose_id: &StableId,
        payload_digest: Digest32,
    ) -> Result<bool, AgentdCompactionCheckpointError> {
        Ok(self
            .writer
            .gc_revoked_qualified_compact_payload(scope_id, purpose_id, payload_digest)
            .await?)
    }

    /// Attach the provider/host target explicitly. Replacing a target is
    /// allowed only through a new host handle, avoiding an in-flight target
    /// swap behind the writer's back.
    pub fn attach_target(mut self, target: Arc<dyn ProductionOutboxTarget>) -> Self {
        self.dispatcher = Some(ProductionOutboxDispatcher::attach(target));
        self
    }

    pub fn has_target(&self) -> bool {
        self.dispatcher.is_some()
    }

    pub async fn dispatch(
        &self,
        receipt: ProductionQueuedReceipt,
    ) -> Result<ProductionDispatchReceipt, AgentdError> {
        let dispatcher = self.dispatcher.as_ref().ok_or_else(|| {
            AgentdError::Protocol(
                "production outbox dispatcher is not explicitly attached".to_string(),
            )
        })?;
        Ok(dispatcher.dispatch(self.writer.as_ref(), receipt).await?)
    }
}

fn now_unix_ms() -> Result<u64, AgentdCompactionCheckpointError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| AgentdCompactionCheckpointError::Clock(error.to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| AgentdCompactionCheckpointError::Clock("timestamp overflow".to_string()))
}

#[cfg(test)]
#[path = "production_writer_host_tests.rs"]
mod tests;
