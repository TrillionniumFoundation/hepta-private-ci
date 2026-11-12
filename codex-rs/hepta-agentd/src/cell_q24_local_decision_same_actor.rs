//! Phase-only local decision entry over the same original Selector journal.
//! The default public attestation and its authorization checks are unchanged.

use std::sync::Arc;

use super::*;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork;

impl<W: AnchorWitnessStore> OriginalCellQ24LocalDecisionOwnerV1<W> {
    pub(crate) async fn attest_original_same_actor_decision<
        T: AnchorWitnessStore,
        S: FinalHoldoutCasStoreV1,
    >(
        &mut self,
        factory: &mut AgentdRootQ24ModelFactoryV1,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset: &LearningIterationSnapshotV1,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
        snapshot: &LearningIterationSnapshotV1,
        phase: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let mut closing = phase.original_failure_scope();
        phase
            .require_training_context(dataset, &self.config.scope)
            .map_err(|_| Error::Binding("original same-actor local decision scope"))?;
        let proposal = self
            .original_proposal(factory, trainer, dataset, inputs, snapshot)
            .await?;
        phase
            .require_original_work_entry()
            .map_err(|_| Error::CommitUncertain)?;
        let saved = self.saved(&proposal);
        let config = &self.config;
        let key = &self.key;
        let bytes = match self.journal.read(&saved) {
            Ok(bytes) => bytes,
            Err(Error::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {
                let current = now()?;
                if current >= config.initial.request.envelope.expiry_unix_seconds {
                    return Err(Error::Binding("new local decision after deadline"));
                }
                config.verifier.require_signer_binding(
                    LearningEvidenceRoleV1::Selector,
                    &config.signer,
                    current,
                )?;
                decision(config.policy, &proposal, current)?;
                phase
                    .require_original_work_entry()
                    .map_err(|_| Error::CommitUncertain)?;
                self.journal.commit_once(&saved, || {
                    phase
                        .require_original_work_entry()
                        .map_err(|_| Error::CommitUncertain)?;
                    let issued_at = now()?;
                    if issued_at >= config.initial.request.envelope.expiry_unix_seconds {
                        return Err(Error::Binding("new local decision after deadline"));
                    }
                    config.verifier.require_signer_binding(
                        LearningEvidenceRoleV1::Selector,
                        &config.signer,
                        issued_at,
                    )?;
                    let receipt = decision(config.policy, &proposal, issued_at)?;
                    let payload = payload(&receipt)?;
                    let mut signed = SignedLearningEvidenceV1 {
                        evidence_id: evidence_id(saved.binding_digest)?,
                        principal_id: config.signer.principal.principal_id.clone(),
                        role: LearningEvidenceRoleV1::Selector,
                        trust_digest: config.verifier.trust_digest(),
                        scope_digest: config.verifier.scope_digest(),
                        objective_digest: config.verifier.objective_digest(),
                        authority_epoch: config.signer.principal.authority_epoch,
                        issued_at,
                        expires_at: issued_at
                            .checked_add(config.maximum_signature_lifetime_seconds)
                            .ok_or(Error::Binding("local decision expiry overflow"))?
                            .min(config.signer.principal.expires_at),
                        payload_digest: Digest32::of_bytes(&payload),
                        signature: [0; 64],
                    };
                    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
                    config.verifier.verify(
                        LearningEvidenceRoleV1::Selector,
                        &signed,
                        &payload,
                        issued_at,
                    )?;
                    learning_owner_evidence::encode(&payload, &signed)
                })?
            }
            Err(error) => return Err(error),
        };
        if self
            .original_proposal(factory, trainer, dataset, inputs, snapshot)
            .await?
            != proposal
        {
            return Err(Error::CommitUncertain);
        }
        let result = self.authenticate(snapshot, &proposal, &saved, &bytes)?;
        phase
            .require_original_work_entry()
            .map_err(|_| Error::CommitUncertain)?;
        closing.disarm();
        Ok(result)
    }
}
