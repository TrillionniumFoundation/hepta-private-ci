//! The original Generator signs only a current challenge received from Root's
//! actual independent B lane. Claim and witness precede signing. A second plan
//! for the same Training cut cannot replace the first retained statement.

use super::*;
use crate::cell_q24_training_receipt_owner::now;
use crate::cell_q24_training_receipt_owner::validate_config;
use crate::learning_owner_evidence;
use crate::root_independent_b_client::OriginalRootBPlanChallengeV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;

impl<TW: AnchorWitnessStore, RW: AnchorWitnessStore>
    OriginalQ24TrainingOperationV1<'_, '_, TW, RW>
{
    pub(crate) fn attest_original_root_b_plan(
        &mut self,
        challenge: &OriginalRootBPlanChallengeV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, RuntimeError> {
        let original = self.read_original_training_evidence()?;
        let scope = self.owners.receipts.config.scope.clone();
        let payload = challenge.require_original_training(&original, &scope)?;
        let binding = challenge.original_binding()?;
        let (key, encoded, signed) = {
            let owner = &mut self.owners.receipts;
            validate_config(&owner.config, &owner.key).map_err(owner_error)?;
            let identity = Digest32::of_parts(&[
                b"hepta.agentd.original-root-b-plan.v1\0",
                owner.saved.binding_digest.as_array(),
                original.snapshot().head_digest.as_array(),
                binding.as_array(),
            ]);
            let key = codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1 {
                plan_id: StableId::new(format!("original-b-plan:{identity}"))
                    .map_err(owner_error)?,
                // Plan bytes are deliberately excluded: a conflicting plan
                // reads the original claim and fails, instead of signing again.
                binding_digest: identity,
            };
            let config = &owner.config;
            let signing = &owner.key;
            let encoded = owner
                .journal
                .commit_once(&key, || {
                    let issued_at = now()?;
                    config.verifier.require_signer_binding(
                        LearningEvidenceRoleV1::Generator,
                        &config.signer,
                        issued_at,
                    )?;
                    let expires_at = issued_at
                        .checked_add(config.maximum_signature_lifetime_seconds)
                        .ok_or(LearningOriginalOwnerErrorV1::Binding(
                            "original B plan signature overflow",
                        ))?
                        .min(config.signer.principal.expires_at)
                        .min(original.snapshot().request.envelope.expiry_unix_seconds);
                    if expires_at <= issued_at {
                        return Err(LearningOriginalOwnerErrorV1::Binding(
                            "original B plan signature expired",
                        ));
                    }
                    let mut signed = SignedLearningEvidenceV1 {
                        evidence_id: key.plan_id.clone(),
                        principal_id: config.signer.principal.principal_id.clone(),
                        role: LearningEvidenceRoleV1::Generator,
                        trust_digest: config.verifier.trust_digest(),
                        scope_digest: config.verifier.scope_digest(),
                        objective_digest: config.verifier.objective_digest(),
                        authority_epoch: config.signer.principal.authority_epoch,
                        issued_at,
                        expires_at,
                        payload_digest: Digest32::of_bytes(payload.as_array()),
                        signature: [0; 64],
                    };
                    signed.signature = signing.sign(&signed.signing_bytes()).to_bytes();
                    config.verifier.verify(
                        LearningEvidenceRoleV1::Generator,
                        &signed,
                        payload.as_array(),
                        issued_at,
                    )?;
                    learning_owner_evidence::encode(payload.as_array(), &signed)
                })
                .map_err(owner_error)?;
            let (saved_payload, signed) =
                learning_owner_evidence::decode(&encoded).map_err(owner_error)?;
            let verified = config
                .verifier
                .verify(
                    LearningEvidenceRoleV1::Generator,
                    &signed,
                    payload.as_array(),
                    now().map_err(owner_error)?,
                )
                .map_err(owner_error)?;
            if saved_payload != payload.as_array()
                || signed.evidence_id != key.plan_id
                || verified.principal() != &config.signer.principal
                || verified.controller_id() != &config.signer.controller_id
                || owner.journal.read(&key).map_err(owner_error)? != encoded
            {
                return Err(RuntimeError::CommitUncertain);
            }
            (key, encoded, signed)
        };
        let after = self.read_original_training_evidence()?;
        if after.snapshot() != original.snapshot()
            || after.receipt() != original.receipt()
            || after.attestation() != original.attestation()
            || challenge.require_original_training(&after, &scope)? != payload
            || self
                .owners
                .receipts
                .journal
                .read(&key)
                .map_err(owner_error)?
                != encoded
        {
            return Err(RuntimeError::CommitUncertain);
        }
        Ok(signed)
    }
}
