//! Exact, domain-separated checkpoint and signed-observation encodings.

use codex_hepta_types::Digest32;

use crate::LearningIterationError;
use crate::cell_bundle::append_id;
use crate::learning_iteration_types::*;

pub(crate) fn initial_digest(
    request: &LearningIterationRequestV1,
    owners: &LearningIterationOwnersV1,
) -> Result<Digest32, LearningIterationError> {
    let mut bytes = b"hepta.learning.iteration-checkpoint.v1\0".to_vec();
    for id in [
        &request.operation_id,
        &request.principal_id,
        &request.agent_id,
        &request.cell_id,
        &request.source_run_id,
        &request.envelope.envelope_id,
        &owners.experience,
        &owners.dataset,
        &owners.trainer,
        &owners.evaluator,
        &owners.proposal,
        &owners.selector,
        &owners.next_use_observer,
    ] {
        append_id(&mut bytes, id);
    }
    let envelope = &request.envelope;
    for digest in [
        request.completed_task_receipt,
        request.selected_artifact_digest,
        request.selected_bundle.digest()?,
        envelope.base_commit,
        envelope.base_tree,
        envelope.objective_digest,
        envelope.grammar_digest,
        owners.evidence_trust_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&envelope.maximum_files.to_be_bytes());
    bytes.extend_from_slice(&envelope.maximum_diff_bytes.to_be_bytes());
    bytes.extend_from_slice(&envelope.maximum_candidates.to_be_bytes());
    bytes.push(envelope.maximum_parallel_sandboxes);
    bytes.extend_from_slice(&envelope.expiry_unix_seconds.to_be_bytes());
    bytes.extend_from_slice(&request.budget.maximum_dataset_rows.to_be_bytes());
    for quota in [
        request.budget.maximum_dataset_bytes,
        request.budget.maximum_training_steps,
        request.budget.maximum_training_milliseconds,
        request.budget.maximum_artifact_bytes,
    ] {
        bytes.extend_from_slice(&quota.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub(crate) fn receipt_digest(
    receipt: &LearningIterationReceiptV1,
) -> Result<Digest32, LearningIterationError> {
    learning_iteration_receipt_signing_bytes_v1(receipt).map(|bytes| Digest32::of_bytes(&bytes))
}

/// Complete canonical payload for the existing learning-evidence signer.
pub fn learning_iteration_receipt_signing_bytes_v1(
    receipt: &LearningIterationReceiptV1,
) -> Result<Vec<u8>, LearningIterationError> {
    let mut bytes = b"hepta.learning.iteration-observation.v1\0".to_vec();
    append_id(&mut bytes, &receipt.operation_id);
    bytes.extend_from_slice(receipt.predecessor.as_array());
    append_id(&mut bytes, &receipt.actor_id);
    bytes.extend_from_slice(receipt.evidence_digest.as_array());
    bytes.extend_from_slice(&receipt.observed_unix_seconds.to_be_bytes());
    match &receipt.observation {
        LearningIterationObservationV1::Experience {
            episode_digest,
            completed_task_receipt,
        } => {
            bytes.push(0);
            bytes.extend_from_slice(episode_digest.as_array());
            bytes.extend_from_slice(completed_task_receipt.as_array());
        }
        LearningIterationObservationV1::Dataset {
            snapshot_digest,
            episode_digest,
            withdrawal_frontier,
            rows,
            bytes: dataset_bytes,
        } => {
            bytes.push(1);
            bytes.extend_from_slice(snapshot_digest.as_array());
            bytes.extend_from_slice(episode_digest.as_array());
            bytes.extend_from_slice(withdrawal_frontier.as_array());
            bytes.extend_from_slice(&rows.to_be_bytes());
            bytes.extend_from_slice(&dataset_bytes.to_be_bytes());
        }
        LearningIterationObservationV1::Training {
            candidate,
            steps,
            milliseconds,
            artifact_bytes,
        } => {
            bytes.push(2);
            bytes.extend_from_slice(candidate.digest()?.as_array());
            bytes.extend_from_slice(&steps.to_be_bytes());
            bytes.extend_from_slice(&milliseconds.to_be_bytes());
            bytes.extend_from_slice(&artifact_bytes.to_be_bytes());
        }
        LearningIterationObservationV1::Evaluation {
            candidate_bundle,
            evaluation_profile,
            disposition,
        } => {
            bytes.push(3);
            bytes.extend_from_slice(candidate_bundle.as_array());
            bytes.extend_from_slice(evaluation_profile.as_array());
            bytes.push(match disposition {
                LearningEvaluationDispositionV1::Qualified => 0,
                LearningEvaluationDispositionV1::NoUpdate => 1,
            });
        }
        LearningIterationObservationV1::Proposal {
            candidate_bundle,
            proposal_id,
            composition_digest,
            disposition,
        } => {
            bytes.push(4);
            bytes.extend_from_slice(candidate_bundle.as_array());
            append_id(&mut bytes, proposal_id);
            bytes.extend_from_slice(composition_digest.as_array());
            bytes.push(match disposition {
                LearningProposalDispositionV1::UpdateCandidates => 0,
                LearningProposalDispositionV1::NoAdmissibleUpdate => 1,
            });
        }
        LearningIterationObservationV1::Selection {
            candidate_bundle,
            selection_digest,
        } => {
            bytes.push(5);
            bytes.extend_from_slice(candidate_bundle.as_array());
            bytes.extend_from_slice(selection_digest.as_array());
        }
        LearningIterationObservationV1::NextUse {
            candidate_bundle,
            state_partition,
            checkpoint_digest,
            selection_digest,
            committed_step_receipt,
            state_cutover_receipt,
        } => {
            bytes.push(6);
            bytes.extend_from_slice(candidate_bundle.as_array());
            bytes.extend_from_slice(state_partition.digest().as_array());
            bytes.extend_from_slice(checkpoint_digest.as_array());
            bytes.extend_from_slice(selection_digest.as_array());
            bytes.extend_from_slice(committed_step_receipt.as_array());
            bytes.extend_from_slice(state_cutover_receipt.as_array());
        }
    }
    Ok(bytes)
}
