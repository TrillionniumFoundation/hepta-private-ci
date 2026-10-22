//! Exact authenticated unlearning read through the original durable writer.
use super::*;

/// A read fact borrowed from one live writer, not a portable authorization or
/// artifact-membership proof. Only that writer can construct it, after checking
/// the actual record, current signed evidence and independent witness. It cannot
/// be deserialized, and its borrow prevents that writer's trust/state mutation.
pub struct VerifiedCommittedUnlearningV1<'a> {
    lineage: &'a UnlearningLineageEventV1,
    event_digest: Digest32,
    frontier: LedgerWitnessFrontier,
}

impl VerifiedCommittedUnlearningV1<'_> {
    #[must_use]
    pub fn record_id(&self) -> &StableId {
        &self.lineage.record_id
    }
    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.lineage.artifact_id
    }
    #[must_use]
    pub fn dataset_digest(&self) -> Digest32 {
        self.lineage.dataset_digest
    }
    #[must_use]
    pub fn event_digest(&self) -> Digest32 {
        self.event_digest
    }
    #[must_use]
    pub fn frontier(&self) -> LedgerWitnessFrontier {
        self.frontier
    }
}

impl LedgerWriter {
    /// Verify the supplied original signed evidence against current trust and
    /// resolve its exact already-committed event through the original index.
    /// No public append receipt, copied snapshot or caller frontier is accepted.
    /// A real but unacknowledged ledger tail blocks this read. Expired/rotated
    /// evidence fails closed for new delivery; it never undoes an artifact denial
    /// already acknowledged by the artifact owner. This is not FinalUse authority.
    pub fn verify_committed_unlearning(
        &self,
        request: &UnlearningLineageRequestV1,
        dataset: &DatasetSnapshotReceiptV3,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<VerifiedCommittedUnlearningV1<'_>, ProductionLedgerError> {
        let core = self.backend.core()?;
        let frontier = self.witness.frontier()?;
        if self.backend.frontier()? != frontier {
            return Err(ProductionLedgerError::WitnessLag);
        }
        // Preserve append_unlearning's historical dataset validity rule. Current
        // mutation authority comes from the separate signed evidence below.
        verify_dataset_snapshot_receipt_v3(dataset, dataset.producer.authenticated_at)?;
        if request.dataset_snapshot_id != dataset.snapshot.snapshot_id
            || request.dataset_digest != dataset.snapshot.dataset_digest
            || dataset.snapshot.objective_digest != self.verifier().objective_digest()
        {
            return Err(ProductionLedgerError::Binding(
                "unlearning dataset identity or objective",
            ));
        }
        let verified = self.verifier().verify(
            LearningEvidenceRoleV1::UnlearningAuthority,
            evidence,
            &unlearning_signing_payload_v1(request),
            now,
        )?;
        let source =
            core.record_by_id(&request.source_record_id)?
                .ok_or(ProductionLedgerError::Binding(
                    "unlearning source unavailable",
                ))?;
        if !dataset
            .snapshot
            .source_record_digests
            .contains(&source.event_digest)
        {
            return Err(ProductionLedgerError::Binding(
                "unlearning source not in dataset",
            ));
        }
        let record =
            core.record_by_id(&request.record_id)?
                .ok_or(ProductionLedgerError::Binding(
                    "unlearning event not committed",
                ))?;
        let LedgerEvent::UnlearningLineageV1(lineage) = &record.event else {
            return Err(ProductionLedgerError::Binding("unlearning event kind"));
        };
        let expected = UnlearningLineageEventV1 {
            record_id: request.record_id.clone(),
            lineage_id: request.lineage_id.clone(),
            source_record_id: request.source_record_id.clone(),
            source_event_digest: source.event_digest,
            dataset_snapshot_id: request.dataset_snapshot_id.clone(),
            dataset_digest: request.dataset_digest,
            artifact_id: request.artifact_id.clone(),
            authority_id: verified.principal().principal_id.clone(),
            reason_digest: request.reason_digest,
            authentication_digest: signed_evidence_digest(evidence),
        };
        if lineage != &expected || record.sequence.get() > frontier.anchor.sequence {
            return Err(ProductionLedgerError::Binding(
                "unlearning committed event mismatch",
            ));
        }
        Ok(VerifiedCommittedUnlearningV1 {
            lineage,
            event_digest: record.event_digest,
            frontier,
        })
    }
}
