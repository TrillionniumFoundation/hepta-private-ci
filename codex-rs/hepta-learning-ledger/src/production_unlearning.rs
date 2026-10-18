//! Authenticated no-effect preview and the original sole writer's unlearning.
//! A preview is never an ACK: append rechecks current trust, clock and witness.
use super::*;

#[derive(Clone, Debug)]
pub struct UnlearningLineagePreviewV1 {
    event_digest: Digest32,
    source_event_digest: Digest32,
    principal: AuthenticatedPrincipalV1,
}
impl UnlearningLineagePreviewV1 {
    #[must_use]
    pub const fn event_digest(&self) -> Digest32 {
        self.event_digest
    }
    #[must_use]
    pub const fn source_event_digest(&self) -> Digest32 {
        self.source_event_digest
    }
    #[must_use]
    pub fn principal(&self) -> &AuthenticatedPrincipalV1 {
        &self.principal
    }
}

impl LedgerWriter {
    /// Authenticate and validate the exact canonical event without writing the
    /// ledger or independent witness. The host retains this writer's exclusive
    /// borrow across its delivery fence and the original `append_unlearning`.
    pub fn preview_unlearning(
        &self,
        expected_predecessor: Digest32,
        request: &UnlearningLineageRequestV1,
        dataset: &DatasetSnapshotReceiptV3,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<UnlearningLineagePreviewV1, ProductionLedgerError> {
        let (event, verified) =
            self.authenticated_unlearning_event(request, dataset, evidence, now)?;
        let source_event_digest = event.source_event_digest;
        let core = self.backend.core()?;
        let prepared = core.prepare(LedgerEvent::UnlearningLineageV1(event))?;
        if prepared.record.predecessor_chain_digest != expected_predecessor {
            return Err(ProductionLedgerError::Binding(
                "unlearning preview predecessor",
            ));
        }
        let lag = validate_witness_state(
            core.records(),
            self.backend.frontier()?,
            self.witness.frontier()?,
        )?;
        if lag == 1
            && (prepared.disposition != AppendDisposition::IdempotentReplay
                || core.records().last() != Some(&prepared.record))
        {
            return Err(ProductionLedgerError::WitnessLag);
        }
        Ok(UnlearningLineagePreviewV1 {
            event_digest: prepared.record.event_digest,
            source_event_digest,
            principal: verified.principal().clone(),
        })
    }

    pub fn append_unlearning(
        &mut self,
        expected_predecessor: Digest32,
        request: UnlearningLineageRequestV1,
        dataset: &DatasetSnapshotReceiptV3,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<UnlearningLineageReceiptV1, ProductionLedgerError> {
        let (event, _) = self.authenticated_unlearning_event(&request, dataset, evidence, now)?;
        let source_event_digest = event.source_event_digest;
        let append = self.commit(
            expected_predecessor,
            LedgerEvent::UnlearningLineageV1(event),
        )?;
        Ok(UnlearningLineageReceiptV1 {
            lineage_id: request.lineage_id,
            source_record_id: request.source_record_id,
            source_event_digest,
            dataset_snapshot_id: request.dataset_snapshot_id,
            dataset_digest: request.dataset_digest,
            artifact_id: request.artifact_id,
            append,
        })
    }

    fn authenticated_unlearning_event(
        &self,
        request: &UnlearningLineageRequestV1,
        dataset: &DatasetSnapshotReceiptV3,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<(UnlearningLineageEventV1, VerifiedLearningEvidenceV1), ProductionLedgerError> {
        // Old dataset integrity uses its authenticated producer point. Only the
        // separately signed current UnlearningAuthority may authorize removal.
        verify_dataset_snapshot_receipt_v3(dataset, dataset.producer.authenticated_at)?;
        if request.dataset_snapshot_id != dataset.snapshot.snapshot_id
            || request.dataset_digest != dataset.snapshot.dataset_digest
            || dataset.snapshot.objective_digest != self.trust.verifier().objective_digest()
        {
            return Err(ProductionLedgerError::Binding(
                "unlearning dataset identity or objective",
            ));
        }
        let snapshot = self.backend.snapshot()?;
        let source = snapshot
            .records()
            .iter()
            .find(|record| record.event.record_id() == &request.source_record_id)
            .ok_or_else(|| {
                ProductionLedgerError::Ledger(LedgerError::TargetNotFound(
                    request.source_record_id.to_string(),
                ))
            })?;
        if !dataset
            .snapshot
            .source_record_digests
            .contains(&source.event_digest)
        {
            return Err(ProductionLedgerError::Binding(
                "unlearning source not in dataset",
            ));
        }
        let verified = self.verify_current_evidence(
            LearningEvidenceRoleV1::UnlearningAuthority,
            evidence,
            &unlearning_signing_payload_v1(request),
            now,
        )?;
        require_role(&verified, LearningEvidenceRoleV1::UnlearningAuthority)?;
        let event = UnlearningLineageEventV1 {
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
        Ok((event, verified))
    }
}
