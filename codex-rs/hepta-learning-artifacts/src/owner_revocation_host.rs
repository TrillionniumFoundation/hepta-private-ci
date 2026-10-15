//! Explicit v2 revocation in the original owner checkpoint journal. No
//! publication admission or payload receipt is synthesized for a denial.
use super::*;
use crate::LearningArtifactRevokeRequestV1;
use crate::StateChange;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactRevocationBindingV2 {
    pub change: StateChange,
    pub signed_head_digest: Digest32,
}

impl ArtifactRevocationBindingV2 {
    pub(super) fn encode_suffix(&self) -> String {
        format!(
            "{}\n{}\n{}\n{}\n{}\n",
            self.change.event_id,
            self.change.artifact_id,
            self.change.evaluator_id,
            self.change.reason_digest,
            self.signed_head_digest
        )
    }
}

pub(super) fn decode_binding(
    fields: &[&str],
) -> Result<ArtifactRevocationBindingV2, ArtifactOwnerHostError> {
    let id = |value: &str| {
        StableId::new(value.to_owned()).map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)
    };
    Ok(ArtifactRevocationBindingV2 {
        change: StateChange {
            event_id: id(fields[0])?,
            artifact_id: id(fields[1])?,
            evaluator_id: id(fields[2])?,
            reason_digest: parse_digest(fields[3])?,
        },
        signed_head_digest: parse_digest(fields[4])?,
    })
}

fn state_digest(checkpoint: &ArtifactOwnerPublicationCheckpointV1) -> Digest32 {
    let mut unsigned = checkpoint.clone();
    unsigned.state_digest = Digest32::ZERO;
    Digest32::of_bytes(
        &[
            b"hepta.learning-artifacts.revocation-state.v2".as_slice(),
            &encode_checkpoint(&unsigned),
        ]
        .concat(),
    )
}

pub(super) fn validate_checkpoint(
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<(), ArtifactOwnerHostError> {
    let binding = checkpoint
        .revocation
        .as_ref()
        .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?;
    if !checkpoint.admission_digest.is_zero()
        || binding.change.reason_digest.is_zero()
        || binding.signed_head_digest.is_zero()
        || checkpoint.intent_digest.is_zero()
        || checkpoint.phase == ArtifactPublicationPhaseV1::PayloadDurable
        || checkpoint.state_digest != state_digest(checkpoint)
        || (phase_code(checkpoint.phase) >= phase_code(ArtifactPublicationPhaseV1::RegistryDurable))
            != checkpoint.registry_receipt.is_some()
        || (phase_code(checkpoint.phase) >= phase_code(ArtifactPublicationPhaseV1::WitnessDurable))
            != checkpoint.witness_receipt.is_some()
        || (checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged)
            != checkpoint.acknowledged_at.is_some()
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    Ok(())
}

impl LearningArtifactOwnerHost {
    pub(crate) fn apply_revocation(
        &self,
        request: &LearningArtifactRevokeRequestV1,
        predecessor: &ArtifactRegistry,
        withdrawal_head_digest: Digest32,
    ) -> Result<(ArtifactOwnerPublicationCheckpointV1, ArtifactRegistry), ArtifactOwnerHostError>
    {
        let writer = self.require_current_writer(request.now)?;
        let signed = &request.signed_current_head;
        let prior = self.recover_publication(&request.operation_id)?;
        let mut staged = predecessor.clone();
        let manifest = predecessor
            .manifest(&request.change.artifact_id)
            .ok_or(ArtifactOwnerHostError::RegistryPredecessorMismatch)?;
        if request.operation_id != request.change.event_id
            || predecessor.snapshot().head_digest != request.expected_registry_predecessor_head
            || manifest.producer_id != writer.producer_id
            || request.change.evaluator_id != signed.witness.signer_id
            || request.change.evaluator_id == manifest.producer_id
            || signed.withdrawal_scope_digest != self.verifier.trust.withdrawal_scope_digest
            || signed.witness.predecessor_head_digest != request.expected_registry_predecessor_head
        {
            return Err(ArtifactOwnerHostError::WriterLeaseContext);
        }
        staged.append(ArtifactEvent::Revoke(request.change.clone()))?;
        if signed.witness.head_digest != staged.snapshot().head_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        let signed_head_digest =
            Digest32::of_bytes(&[signed.signing_bytes(), signed.signature.to_vec()].concat());
        let binding = ArtifactRevocationBindingV2 {
            change: request.change.clone(),
            signed_head_digest,
        };
        let withdrawal_head = prior.as_ref().map_or(withdrawal_head_digest, |value| {
            value.checkpoint.withdrawal_head_digest
        });
        let mut intent_bytes = b"hepta.learning-artifacts.revocation-intent.v2".to_vec();
        push_id(&mut intent_bytes, &request.operation_id);
        intent_bytes.extend_from_slice(binding.encode_suffix().as_bytes());
        intent_bytes.extend_from_slice(signed.withdrawal_scope_digest.as_array());
        intent_bytes.extend_from_slice(withdrawal_head.as_array());
        intent_bytes.extend_from_slice(request.expected_registry_predecessor_head.as_array());
        let intent_digest = Digest32::of_bytes(&intent_bytes);
        let mut checkpoint = if let Some(prior) = prior {
            if prior.checkpoint.revocation.as_ref() != Some(&binding)
                || prior.checkpoint.intent_digest != intent_digest
            {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            prior.checkpoint
        } else {
            ArtifactOwnerPublicationCheckpointV1 {
                revocation: Some(binding),
                operation_id: request.operation_id.clone(),
                phase: ArtifactPublicationPhaseV1::Prepared,
                intent_digest,
                admission_digest: Digest32::ZERO,
                withdrawal_scope_digest: signed.withdrawal_scope_digest,
                withdrawal_head_digest: withdrawal_head,
                expected_registry_predecessor_head: request.expected_registry_predecessor_head,
                state_digest: Digest32::ZERO,
                original_writer_lease_digest: writer.lease_digest,
                registry_receipt: None,
                witness_receipt: None,
                acknowledged_at: None,
                authority: AuthorityPosture::DENY_ALL,
            }
        };
        // A settled exact retry is history, not a new mutation under an old
        // expired head. Reestablish ACK durability before reporting it.
        if checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
            self.reconcile_acknowledged_publication(&checkpoint)?;
            return Ok((checkpoint, staged));
        }
        let requirement = self.current_head_requirement(
            request.expected_registry_predecessor_head,
            signed,
            request.now,
        )?;
        self.verifier.verify_signed_head(
            signed,
            &requirement,
            /*require_current_signer*/ true,
        )?;
        checkpoint.state_digest = state_digest(&checkpoint);
        self.persist_publication_checkpoint(&checkpoint)?;
        if checkpoint.phase == ArtifactPublicationPhaseV1::Prepared {
            checkpoint.registry_receipt =
                Some(self.persist_registry_snapshot(&staged, signed.binding)?);
            checkpoint.phase = ArtifactPublicationPhaseV1::RegistryDurable;
            checkpoint.state_digest = state_digest(&checkpoint);
            self.persist_publication_checkpoint(&checkpoint)?;
        }
        if checkpoint.phase == ArtifactPublicationPhaseV1::RegistryDurable {
            let (witness, _) = self.persist_authenticated_head(
                request.expected_registry_predecessor_head,
                signed,
                request.now,
            )?;
            checkpoint.witness_receipt = Some(witness);
            checkpoint.phase = ArtifactPublicationPhaseV1::WitnessDurable;
            checkpoint.state_digest = state_digest(&checkpoint);
            self.persist_publication_checkpoint(&checkpoint)?;
        }
        if checkpoint.phase != ArtifactPublicationPhaseV1::WitnessDurable {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        self.require_current_writer(request.now)?;
        let current = self
            .discover_current_head(request.now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        if current.signed != *signed {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        checkpoint.phase = ArtifactPublicationPhaseV1::Acknowledged;
        checkpoint.acknowledged_at = Some(request.now);
        checkpoint.state_digest = state_digest(&checkpoint);
        self.persist_publication_checkpoint(&checkpoint)?;
        Ok((checkpoint, staged))
    }
}
