//! Opt-in host composition of the original learning and artifact owners.
use super::CognitiveRetrievalLearningSink;
use codex_hepta_learning_artifacts as art;
use codex_hepta_learning_ledger as led;
use codex_hepta_types::Digest32;

/// Immutable pins supplied by the trusted embedding from its already authorized
/// ledger/activated trust and artifact-owner configuration, never from a request
/// or the fact being checked. This is configuration, not a new authority issuer.
/// The activated distribution commits the original scope/objective and signer set.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CognitiveArtifactUnlearningOwnerV1 {
    pub ledger_binding: Digest32,
    pub learning_root_digest: Digest32,
    pub learning_distribution_digest: Digest32,
    pub artifact_trust_digest: Digest32,
    pub artifact_storage_binding: Digest32,
}

/// Complete untrusted handoff inputs. No public receipt or borrowed fact can
/// substitute for original signed evidence, exact source manifest and CURRENT.
#[derive(Clone, Debug)]
pub struct CognitiveArtifactUnlearningRequestV1 {
    pub lineage: led::UnlearningLineageRequestV1,
    pub dataset: led::DatasetSnapshotReceiptV3,
    pub evidence: led::SignedLearningEvidenceV1,
    pub source_manifest: art::LearningArtifactManifestV2,
    pub revocation: art::LearningArtifactRevokeRequestV1,
    /// Trusted host clock in the learning evidence's original time domain.
    /// Artifact time remains the original revocation request's separate clock.
    pub learning_now: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum CognitiveArtifactUnlearningError {
    #[error("artifact unlearning owner is not configured")]
    Unconfigured,
    #[error("artifact unlearning owner binding mismatch")]
    OwnerBinding,
    #[error("learning owner lock unavailable")]
    OwnerUnavailable,
    #[error("unlearning artifact identity mismatch")]
    ArtifactBinding,
    #[error("learning owner: {0}")]
    Ledger(#[from] led::ProductionLedgerError),
    #[error("artifact manifest: {0}")]
    Manifest(#[from] art::ArtifactPublicationError),
    #[error("artifact owner: {0}")]
    Artifact(#[from] art::LearningArtifactOwnerServiceError),
}

impl CognitiveRetrievalLearningSink {
    /// Explicit host construction only; the default sink has no such path.
    /// Pins may be installed once before sharing this original sink. The host
    /// still provisions keys, retains independent CURRENT floors and supplies
    /// the artifact owner. There is no new daemon/IPC or signing transport.
    pub fn with_artifact_unlearning_owner(
        mut self,
        owner: CognitiveArtifactUnlearningOwnerV1,
    ) -> Result<Self, CognitiveArtifactUnlearningError> {
        if self.unlearning_owner.is_some()
            || [
                owner.ledger_binding,
                owner.learning_root_digest,
                owner.learning_distribution_digest,
                owner.artifact_trust_digest,
                owner.artifact_storage_binding,
            ]
            .iter()
            .any(|digest| digest.is_zero())
        {
            return Err(CognitiveArtifactUnlearningError::OwnerBinding);
        }
        self.unlearning_owner = Some(owner);
        Ok(self)
    }

    /// Deliver one already-committed exact lineage through the original owners.
    /// The original writer mutex remains held synchronously through the original
    /// artifact service's W/O/checkpoint/ACK operation. No async closure, retry,
    /// deadline guarantee or extra lock/ledger is introduced. Unknown failures
    /// leave the artifact service's original operation and fence intact.
    ///
    /// An opaque fact is obtained only inside this call, from this sink's writer;
    /// externally supplied facts cannot cross owner domains. Independent signed
    /// CURRENT still authorizes the exact successor, evaluator, operation/reason.
    /// This does not withdraw a whole dataset, implement fanout or hold FinalUse.
    pub fn revoke_artifact_from_unlearning(
        &self,
        service: &mut art::LearningArtifactOwnerService,
        request: CognitiveArtifactUnlearningRequestV1,
    ) -> Result<art::ArtifactRevocationReceiptV1, CognitiveArtifactUnlearningError> {
        let owner = self
            .unlearning_owner
            .ok_or(CognitiveArtifactUnlearningError::Unconfigured)?;
        let writer = self
            .writer
            .lock()
            .map_err(|_| CognitiveArtifactUnlearningError::OwnerUnavailable)?;
        let fact = writer.verify_committed_unlearning(
            &request.lineage,
            &request.dataset,
            &request.evidence,
            request.learning_now,
        )?;
        if fact.ledger_binding() != owner.ledger_binding
            || fact.root_digest() != owner.learning_root_digest
            || fact.distribution_digest() != owner.learning_distribution_digest
        {
            return Err(CognitiveArtifactUnlearningError::OwnerBinding);
        }
        // Identity must be checked even during same-operation recovery. A
        // general CURRENT read intentionally rejects that unsettled state and
        // therefore cannot be used to gate the original reconciliation call.
        service
            .verify_owner_binding(owner.artifact_trust_digest, owner.artifact_storage_binding)?;
        let indexed = service
            .registry()
            .manifest(fact.artifact_id())
            .ok_or(CognitiveArtifactUnlearningError::ArtifactBinding)?;
        let source = art::validate_published_artifact_manifest_v2(
            indexed,
            request.source_manifest,
            request.revocation.now,
        )?
        .manifest;
        if source.artifact_id != *fact.artifact_id()
            || source.objective_class_digest != request.dataset.snapshot.objective_digest
            || !source
                .source_dataset_digests
                .contains(&fact.dataset_digest())
            || request.revocation.operation_id != *fact.record_id()
            || request.revocation.change.event_id != *fact.record_id()
            || request.revocation.change.artifact_id != *fact.artifact_id()
            || request.revocation.change.reason_digest != fact.event_digest()
        {
            return Err(CognitiveArtifactUnlearningError::ArtifactBinding);
        }
        // Eligibility is deliberately not a precondition: the same acknowledged
        // operation must reach the original owner's exact terminal readback.
        Ok(service.revoke(request.revocation)?)
    }
}
