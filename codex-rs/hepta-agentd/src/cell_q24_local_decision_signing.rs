//! The original Selector journal and key. Callers must first read the actual
//! Model owner and must re-read that same owner after the durable operation.
//! Neither Missing nor Pending recovery may manufacture a new decision.

use super::*;
use ed25519_dalek::Signer;

impl<W: AnchorWitnessStore> OriginalCellQ24LocalDecisionOwnerV1<W> {
    pub(super) fn sign_original_proposal(
        &mut self,
        proposal: &LearningIterationSnapshotV1,
        saved: &ProductEvaluationExecutionKeyV1,
    ) -> Result<Vec<u8>, Error> {
        let config = &self.config;
        let key = &self.key;
        let bytes = match self.journal.read(saved) {
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
                decision(config.policy, proposal, current)?;
                self.journal.commit_once(saved, || {
                    let issued_at = now()?;
                    if issued_at >= config.initial.request.envelope.expiry_unix_seconds {
                        return Err(Error::Binding("new local decision after deadline"));
                    }
                    config.verifier.require_signer_binding(
                        LearningEvidenceRoleV1::Selector,
                        &config.signer,
                        issued_at,
                    )?;
                    let receipt = decision(config.policy, proposal, issued_at)?;
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
        Ok(bytes)
    }
}
