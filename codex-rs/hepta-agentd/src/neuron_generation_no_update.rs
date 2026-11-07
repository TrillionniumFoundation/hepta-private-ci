//! Bind an evaluated native NoUpdate to the existing same-model task owner.
//!
//! This profile uses the completed generation's actual owner checkpoint as
//! `completed_task_receipt`, and the selected canonical V2 manifest payload as
//! `selected_artifact_digest`. Learning remains terminal NoUpdate. Its evidence
//! does not select a model, issue FinalUse, or authorize a zero-delta update.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationObservationV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Serialize;

use super::NeuronGenerationCurrentOwnerV1;
use super::NeuronGenerationPredecessorCompletionV1;
use super::PublishedNeuronGenerationUpdateV1;
use crate::AgentdError;
use crate::AgentdGenerationSelectionObservationV1;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::AgentdGenerationUpdateTargetV1;
use crate::AgentdSelectedGenerationV1;
use crate::LearningIterationOwnerPortsV1;
use crate::PreparedAgentdGenerationUpdateV1;
use crate::ReadyAgentdGenerationUpdateV1;
use crate::learning_iteration_auth::authenticate_iteration_receipt_v1;
use crate::prepare_agentd_generation_same_model_task_v1;

/// Pins and clock come from the admitted host, never the incoming checkpoint.
/// Restore must enforce its existing authenticated rollback/revocation domain.
/// An observation is not a lease across the learning and Control owners;
/// independently issued FinalUse and live selection checks remain mandatory.
#[derive(Clone, Copy)]
pub struct AgentdLearningNoUpdateInputsV1<'a> {
    pub ports: &'a dyn LearningIterationOwnerPortsV1,
    pub verifier: &'a LearningEvidenceVerifierV1,
    pub request: &'a LearningIterationRequestV1,
    pub owners: &'a LearningIterationOwnersV1,
    pub expected_head: Digest32,
    pub now_unix_seconds: u64,
}

/// Keeps the existing exclusive journals until normal Control publication.
pub struct PreparedAgentdLearningNoUpdateTaskV1<Old: AnchorWitnessStore, New: AnchorWitnessStore> {
    prepared: PreparedAgentdGenerationUpdateV1<Old, New>,
    operation_id: String,
}

impl<Old: AnchorWitnessStore, New: AnchorWitnessStore>
    PreparedAgentdLearningNoUpdateTaskV1<Old, New>
{
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.prepared.final_use_binding()
    }

    pub fn recovery(&self) -> AgentdGenerationUpdateRecoveryV1 {
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: self.operation_id.clone(),
            intent_digest: self.prepared.intent_digest(),
        }
    }

    pub fn publish(
        self,
        signed: &SignedFinalUseGrant,
    ) -> Result<ReadyAgentdGenerationUpdateV1<New>, AgentdError> {
        self.prepared.publish(signed)
    }
}

/// Re-read an evaluated NoUpdate before preparing the ordinary same-model
/// boundary. Only the four-stage evaluated profile is accepted here; a proposal
/// rejection requires its own anchored proposal-owner evidence and is refused.
pub async fn prepare_agentd_generation_evaluated_no_update_task_v1<Old, New>(
    learning: AgentdLearningNoUpdateInputsV1<'_>,
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    old: CellGenerationJournalV2<Old>,
    selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<New>,
) -> Result<PreparedAgentdLearningNoUpdateTaskV1<Old, New>, AgentdError>
where
    Old: AnchorWitnessStore,
    New: AnchorWitnessStore,
{
    let snapshot = authenticate_no_update(learning).await?;
    let observed = old.observe_generation().map_err(invalid)?;
    let previous = old
        .owner_binding()
        .ok_or_else(|| invalid("NoUpdate continuation requires a guarded predecessor"))?;
    require_source(
        &snapshot,
        previous,
        observed.owner_checkpoint(),
        selected.observation(),
    )?;
    let target_binding =
        CellGenerationOwnerBindingV1::new(&target.config, target.max_records).map_err(invalid)?;
    let operation_id = operation_id(
        snapshot.head_digest,
        observed.owner_checkpoint(),
        selected.observation(),
        &target_binding,
    )?;
    let prepared = prepare_agentd_generation_same_model_task_v1(
        current,
        authorities,
        old,
        selected,
        target,
        AgentdGenerationUpdateRequestV1 {
            operation_id: operation_id.clone(),
        },
    )?;
    Ok(PreparedAgentdLearningNoUpdateTaskV1 {
        prepared,
        operation_id,
    })
}

/// Historical readback, derived from sealed native observations. Serializing
/// this value does not create a portable authority or a trusted decoder.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AgentdLearningNoUpdateNextUseV1 {
    learning_head: [u8; 32],
    source_owner_checkpoint: [u8; 32],
    selected_payload: [u8; 32],
    continuation_operation_id: String,
    continuation_intent: [u8; 32],
    final_use_grant: [u8; 32],
    target: CellGenerationOwnerBindingV1,
    next_owner_checkpoint: [u8; 32],
    next_observation: [u8; 32],
    first_input: [u8; 32],
}

impl AgentdLearningNoUpdateNextUseV1 {
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Re-authenticate the retained learning result, including after cold recovery,
/// and require a real committed, stopped and ACKed successor observation.
/// Unknown physical costs remain in that observation; no quality/adoption claim
/// or current dispatch permission follows from this historical use receipt.
pub async fn observe_agentd_evaluated_no_update_next_use_v1(
    learning: AgentdLearningNoUpdateInputsV1<'_>,
    selected: &AgentdGenerationSelectionObservationV1,
    publication: &PublishedNeuronGenerationUpdateV1,
    observed: &CellGenerationObservationV1,
) -> Result<AgentdLearningNoUpdateNextUseV1, AgentdError> {
    let snapshot = authenticate_no_update(learning).await?;
    let intent = &publication.record.intent;
    let checkpoint = Digest32::from_array(intent.previous_checkpoint);
    require_source(&snapshot, &intent.previous, checkpoint, selected)?;
    let operation_id = operation_id(snapshot.head_digest, checkpoint, selected, &intent.target)?;
    let target = &intent.target;
    let first_input = observed
        .first_advance_input_digest()
        .ok_or_else(|| invalid("successor has no committed model input"))?;
    if intent.completion != NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
        || intent.operation_id != operation_id
        || intent.selection != selected.digest().into_array()
        || intent.previous.manifest_digest() != target.manifest_digest()
        || selected.manifest_digest() != target.manifest_digest()
        || observed.snapshot().scope != *target.scope()
        || observed.snapshot().generation != target.generation()
        || observed.snapshot().writer_epoch != target.writer_epoch()
        || observed.manifest_digest() != target.manifest_digest()
        || observed.task_digest() != target.task_digest()
        || observed.source_frontier() != target.source_frontier()
        || observed.initial_snapshot_digest() != target.initial_snapshot_digest()
        || observed.owner_checkpoint() == target.genesis_checkpoint()
        || observed.snapshot().revision == 0
        || !observed.is_terminal()
    {
        return Err(invalid(
            "NoUpdate successor does not match its committed owner publication",
        ));
    }
    Ok(AgentdLearningNoUpdateNextUseV1 {
        learning_head: snapshot.head_digest.into_array(),
        source_owner_checkpoint: checkpoint.into_array(),
        selected_payload: selected.payload_digest().into_array(),
        continuation_operation_id: operation_id,
        continuation_intent: publication.intent_digest().into_array(),
        final_use_grant: publication.signed_grant_digest().into_array(),
        target: target.clone(),
        next_owner_checkpoint: observed.owner_checkpoint().into_array(),
        next_observation: observed.digest().map_err(invalid)?,
        first_input,
    })
}

async fn authenticate_no_update(
    learning: AgentdLearningNoUpdateInputsV1<'_>,
) -> Result<LearningIterationSnapshotV1, AgentdError> {
    if learning.expected_head.is_zero()
        || learning.owners.evidence_trust_digest != learning.verifier.trust_digest()
    {
        return Err(invalid("missing or inconsistent host learning pins"));
    }
    let snapshot = learning
        .ports
        .restore(learning.request)
        .await
        .map_err(invalid)?
        .ok_or_else(|| invalid("no committed learning result"))?;
    if snapshot.request != *learning.request
        || snapshot.owners != *learning.owners
        || snapshot.head_digest != learning.expected_head
        || snapshot.receipts.len() != 4
        || !matches!(
            snapshot.receipts.last().map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::NoUpdate,
                ..
            })
        )
    {
        return Err(invalid("owner did not retain the exact evaluated NoUpdate"));
    }
    LearningIterationCoordinatorV1::from_snapshot(snapshot.clone()).map_err(invalid)?;
    let mut replay =
        LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())
            .map_err(invalid)?;
    for receipt in &snapshot.receipts {
        if receipt.observed_unix_seconds > learning.now_unix_seconds {
            return Err(invalid("NoUpdate observation lies after the host clock"));
        }
        authenticate_iteration_receipt_v1(
            learning.ports,
            learning.verifier,
            &replay,
            receipt,
            learning.now_unix_seconds,
        )
        .await
        .map_err(invalid)?;
        replay
            .record(receipt.clone(), receipt.observed_unix_seconds)
            .map_err(invalid)?;
    }
    if learning
        .ports
        .restore(learning.request)
        .await
        .map_err(invalid)?
        .as_ref()
        != Some(&snapshot)
    {
        return Err(invalid("learning owner changed during observation"));
    }
    Ok(snapshot)
}

fn require_source(
    snapshot: &LearningIterationSnapshotV1,
    previous: &CellGenerationOwnerBindingV1,
    checkpoint: Digest32,
    selected: &AgentdGenerationSelectionObservationV1,
) -> Result<(), AgentdError> {
    let request = &snapshot.request;
    if request.completed_task_receipt != checkpoint
        || request.selected_artifact_digest != selected.payload_digest()
        || request.agent_id.as_str() != previous.scope().agent_id
        || request.cell_id.as_str() != previous.scope().cell_id
        || request.source_run_id.as_str() != previous.scope().run_id
        || selected.manifest_digest() != previous.manifest_digest()
    {
        return Err(invalid(
            "learning result does not bind this incumbent task checkpoint",
        ));
    }
    Ok(())
}

fn operation_id(
    head: Digest32,
    checkpoint: Digest32,
    selected: &AgentdGenerationSelectionObservationV1,
    target: &CellGenerationOwnerBindingV1,
) -> Result<String, AgentdError> {
    let digest = Digest32::of_parts(&[
        b"hepta.agentd.evaluated-no-update-next-task.v1\0",
        head.as_array(),
        checkpoint.as_array(),
        selected.payload_digest().as_array(),
        selected.digest().as_array(),
        &target.digest().map_err(invalid)?,
    ]);
    Ok(format!("evaluated-no-update:{digest}"))
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
