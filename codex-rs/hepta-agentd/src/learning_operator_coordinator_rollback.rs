//! Exact-predecessor cleanup and terminal audit binding.

use super::*;
use codex_hepta_types::StableId;

#[allow(clippy::too_many_arguments)]
pub(super) fn rollback_outcome<P: LearningOperatorShadowPortsV1>(
    ports: &mut P,
    request: &LearningOperatorShadowRequestV1,
    candidate: &FittedOperatorCandidateV1,
    selection: &SelectedOperatorCandidateV1,
    persisted: &PersistedOperatorCandidateV1,
    trigger: LearningOperatorShadowRollbackTriggerV1,
    shadow_digest: Option<Digest32>,
    currentness_digest: Option<Digest32>,
    port_message: Option<String>,
) -> Result<LearningOperatorShadowOutcomeV1, LearningOperatorShadowErrorV1> {
    let recovery = || {
        Box::new(LearningOperatorPersistenceRecoveryV1 {
            run_id: request.run_id.clone(),
            candidate_artifact_digest: candidate.artifact_digest,
            selection_digest: selection.selection_digest,
            reported: Some(persisted.clone()),
        })
    };
    // Cleanup is mandatory even after the work deadline or a clock regression.
    let rollback = ports
        .rollback(request, candidate, selection, persisted, trigger)
        .map_err(|message| LearningOperatorShadowErrorV1::RollbackFailed {
            trigger,
            recovery: recovery(),
            message,
        })?;
    if rollback.failed_artifact_digest != candidate.artifact_digest
        || rollback.failed_selection_digest != selection.selection_digest
        || rollback.restored_artifact_digest != request.predecessor_artifact_digest
        || rollback.restored_generation != request.predecessor_generation
        || rollback.rollback_digest.is_zero()
        || rollback.owner_id != request.owner_id
        || rollback.authority_epoch != request.expected_authority_epoch
        || rollback.stop_epoch != request.expected_stop_epoch
        || rollback.trigger != trigger
    {
        return Err(LearningOperatorShadowErrorV1::RollbackFailed {
            trigger,
            recovery: recovery(),
            message: "rollback did not verify the exact predecessor under the current epochs"
                .to_owned(),
        });
    }
    let rollback_digest = rollback.rollback_digest;
    let terminal = match trigger {
        LearningOperatorShadowRollbackTriggerV1::ShadowCompleted => {
            LearningOperatorShadowTerminalV1::QualifiedAndRolledBack(rollback)
        }
        LearningOperatorShadowRollbackTriggerV1::CandidateRevoked => {
            LearningOperatorShadowTerminalV1::RevokedAndRolledBack(rollback)
        }
        LearningOperatorShadowRollbackTriggerV1::ShadowRejected
        | LearningOperatorShadowRollbackTriggerV1::CurrentnessMismatch
        | LearningOperatorShadowRollbackTriggerV1::FreshProcessLoadMismatch
        | LearningOperatorShadowRollbackTriggerV1::PersistDeadlineExceeded => {
            LearningOperatorShadowTerminalV1::RejectedAndRolledBack(rollback)
        }
    };
    let audit_digest = audit_digest(
        request,
        candidate,
        selection,
        persisted,
        trigger,
        shadow_digest,
        currentness_digest,
        port_message.as_deref(),
        rollback_digest,
    );
    Ok(LearningOperatorShadowOutcomeV1 {
        run_id: request.run_id.clone(),
        candidate_artifact_digest: candidate.artifact_digest,
        selection_digest: selection.selection_digest,
        shadow_digest,
        currentness_digest,
        terminal,
        audit_digest,
    })
}

#[allow(clippy::too_many_arguments)]
fn audit_digest(
    request: &LearningOperatorShadowRequestV1,
    candidate: &FittedOperatorCandidateV1,
    selection: &SelectedOperatorCandidateV1,
    persisted: &PersistedOperatorCandidateV1,
    trigger: LearningOperatorShadowRollbackTriggerV1,
    shadow_digest: Option<Digest32>,
    currentness_digest: Option<Digest32>,
    port_message: Option<&str>,
    rollback_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-operator.shadow-audit.v1\0".to_vec();
    push_id(&mut bytes, &request.run_id);
    push_id(&mut bytes, &request.owner_id);
    push_id(&mut bytes, &request.producer_id);
    push_id(&mut bytes, &candidate.artifact_id);
    for digest in [
        request.objective_digest,
        request.training_source_digest,
        request.evaluation_source_digest,
        request.predecessor_artifact_digest,
        candidate.artifact_digest,
        candidate.payload_digest,
        selection.selection_digest,
        selection.reason.policy_digest,
        persisted.storage_receipt_digest,
        shadow_digest.unwrap_or(Digest32::ZERO),
        currentness_digest.unwrap_or(Digest32::ZERO),
        rollback_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&candidate.generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.expected_authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&request.expected_stop_epoch.to_be_bytes());
    bytes.extend_from_slice(&request.now_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&request.deadline_unix_micros.to_be_bytes());
    bytes.push(rollback_trigger_code(trigger));
    bytes.push(match selection.reason.code {
        LearningOperatorSelectionReasonCodeV1::IndependentFutureWindowSuperiority => 1,
        LearningOperatorSelectionReasonCodeV1::SafetyEquivalentLowerResourceCost => 2,
        LearningOperatorSelectionReasonCodeV1::IndependentlyVerifiedRollback => 3,
    });
    if let Some(message) = port_message {
        bytes.extend_from_slice(Digest32::of_bytes(message.as_bytes()).as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn rollback_trigger_code(value: LearningOperatorShadowRollbackTriggerV1) -> u8 {
    match value {
        LearningOperatorShadowRollbackTriggerV1::ShadowCompleted => 1,
        LearningOperatorShadowRollbackTriggerV1::ShadowRejected => 2,
        LearningOperatorShadowRollbackTriggerV1::CandidateRevoked => 3,
        LearningOperatorShadowRollbackTriggerV1::CurrentnessMismatch => 4,
        LearningOperatorShadowRollbackTriggerV1::FreshProcessLoadMismatch => 5,
        LearningOperatorShadowRollbackTriggerV1::PersistDeadlineExceeded => 6,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let length = u64::try_from(raw.len()).unwrap_or(u64::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
}
