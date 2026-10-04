//! One original signed window, revalidated against the same full live Ledger.
use super::*;
use codex_hepta_agent_components::learning_ledger::DatasetWindowFreezePlanV3;
use codex_hepta_agent_components::learning_ledger::DatasetWindowSnapshotReceiptV3;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_agent_components::learning_ledger::LedgerSnapshot;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_agent_components::learning_ledger::authenticate_ledger_snapshot_prefix_v3;
use codex_hepta_agent_components::learning_ledger::dataset_window_freeze_signing_payload_v3;
use codex_hepta_agent_components::learning_ledger::verify_dataset_window_snapshot_against_current_ledger_v3;

/// Full independent Window signature and original policy, revalidated at use.
pub struct PlasticityDatasetWindowEvidenceV3 {
    pub plan: DatasetWindowFreezePlanV3,
    pub window: DatasetWindowSnapshotReceiptV3,
    pub evaluator: SignedLearningEvidenceV1,
    pub verifier: LearningEvidenceVerifierV1,
}
impl PlasticityDatasetWindowEvidenceV3 {
    pub(crate) fn validate_current(
        &self,
        current: &LedgerSnapshot,
        now: u64,
    ) -> Result<(), PlasticityOwnerEvidenceErrorV1> {
        let fail = |_| PlasticityOwnerEvidenceErrorV1::ContextMismatch;
        let frozen = verify_dataset_window_snapshot_against_current_ledger_v3(
            &self.window,
            &self.plan,
            current,
            now,
        )
        .map_err(fail)?;
        let payload =
            dataset_window_freeze_signing_payload_v3(&frozen, &self.plan).map_err(fail)?;
        let verified = self
            .verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &self.evaluator,
                &payload,
                now,
            )
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unauthorized)?;
        if verified.principal() != &self.window.receipt.producer {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok(())
    }
    fn authenticate_observed_head(
        &self,
        current: &LedgerSnapshot,
        observed: Digest32,
    ) -> Result<(), PlasticityOwnerEvidenceErrorV1> {
        let count = current
            .records()
            .iter()
            .find(|r| r.chain_digest == observed)
            .map(|r| r.sequence.get())
            .ok_or(PlasticityOwnerEvidenceErrorV1::ContextMismatch)?;
        if count < self.window.receipt.snapshot.eligible_frontier {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        authenticate_ledger_snapshot_prefix_v3(current, observed, count)
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::ContextMismatch)?;
        Ok(())
    }
    fn receipt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.dataset-window-owner-evidence.v3\0".to_vec();
        bytes.extend_from_slice(self.plan.policy_digest().as_array());
        bytes.extend_from_slice(self.window.receipt.snapshot.dataset_digest.as_array());
        bytes.extend_from_slice(&self.evaluator.signing_bytes());
        bytes.extend_from_slice(&self.evaluator.signature);
        Digest32::of_bytes(&bytes)
    }
}
impl ConcretePlasticityOwnerEvidenceResolverV1 {
    pub fn with_dataset_window_v3(
        mut self,
        window: PlasticityDatasetWindowEvidenceV3,
        current: &LedgerSnapshot,
        now: u64,
    ) -> Result<Self, PlasticityOwnerEvidenceErrorV1> {
        if self.dataset != window.window.receipt || self.dataset_window.is_some() {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        window.validate_current(current, now)?;
        self.dataset_window = Some(window);
        Ok(self)
    }
    pub(super) fn window_qualification_head(
        &self,
        current: &LedgerSnapshot,
        expected: Option<Digest32>,
        now: u64,
    ) -> Result<Digest32, PlasticityOwnerEvidenceErrorV1> {
        let Some(window) = &self.dataset_window else {
            if expected.is_some_and(|head| head != current.head_digest) {
                return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
            }
            return Ok(current.head_digest);
        };
        window.validate_current(current, now)?;
        let head = expected.unwrap_or(current.head_digest);
        window.authenticate_observed_head(current, head)?;
        Ok(head)
    }
    pub(super) fn resolve_dataset_window(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
        current: &LedgerSnapshot,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        let window = self
            .dataset_window
            .as_ref()
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        window.validate_current(current, query.now)?;
        window.authenticate_observed_head(current, query.qualification_evidence_head_digest)?;
        let receipt = &window.window.receipt;
        let snapshot = &receipt.snapshot;
        if snapshot.dataset_digest != query.evidence_digest
            || snapshot.dataset_digest != query.dataset_digest
            || snapshot.objective_digest != query.objective_digest
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok(receipt_from_query(
            query,
            receipt.producer.principal_id.clone(),
            snapshot.ledger_head_digest,
            window.receipt_digest(),
            receipt.producer.authenticated_at,
            receipt.producer.expires_at,
        ))
    }
}
