//! Original-owner checks at the SQLite effect-admission transaction boundary.

use super::check_active_run_fence;
use super::check_step_fence;
use super::load_definition;
use super::load_run;
use super::load_step_events;
use super::reconstruct_step;
use super::validate_common;
use super::validate_fence;
use super::validate_step_node;
use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowRunState;
use crate::TaskFlowStepState;
use codex_hepta_contracts::Sha256Digest;

pub(crate) struct EffectStepAdmission<'a> {
    pub(crate) run_id: &'a str,
    pub(crate) step_id: &'a str,
    pub(crate) attempt: u32,
    pub(crate) intent_digest: &'a Sha256Digest,
    pub(crate) payload_digest: &'a Sha256Digest,
    pub(crate) fence: &'a TaskFlowFence,
    pub(crate) time: crate::taskflow_clock_effect::EffectDispatchTime<'a>,
}

/// The caller holds the existing database's IMMEDIATE write transaction
/// through validation, immutable attempt insertion and commit. No provider
/// call occurs while this transaction is held. Logical caller times stay
/// explicit; typed clock claims sample their original owner after awaited reads.
pub(crate) async fn validate_effect_step_admission(
    store: &AutomationStore,
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    admission: &EffectStepAdmission<'_>,
) -> Result<u64, TaskFlowError> {
    validate_common(
        admission.run_id,
        admission.step_id,
        admission.attempt,
        "effect-admission",
        admission.intent_digest,
        admission.payload_digest,
    )?;
    validate_fence(store, admission.fence)?;
    let run = load_run(tx, store, admission.run_id).await?;
    if run.state != TaskFlowRunState::Running || run.cancel_requested {
        return Err(TaskFlowError::Conflict(
            "effect admission requires an uncancelled running owner".into(),
        ));
    }
    let definition = load_definition(tx, store, &run).await?;
    if definition.definition_digest() != &run.definition_digest {
        return Err(TaskFlowError::Corrupt(
            "effect admission definition binding changed".into(),
        ));
    }
    validate_step_node(&definition, admission.step_id)?;
    let events = load_step_events(
        tx,
        store,
        admission.run_id,
        admission.step_id,
        admission.attempt,
    )
    .await?;
    let step = reconstruct_step(
        store.taskflow_owner_agent_id(),
        admission.run_id,
        admission.step_id,
        admission.attempt,
        &events,
    )?;
    check_step_fence(&step.fence, admission.fence)?;
    if step.state != TaskFlowStepState::Claimed
        || step.intent_digest != *admission.intent_digest
        || step.payload_digest != *admission.payload_digest
    {
        return Err(TaskFlowError::Conflict(
            "effect admission differs from the current claimed step".into(),
        ));
    }
    let now_ms = admission.time.admission_time(&run, admission.fence)?;
    check_active_run_fence(&run, admission.fence, now_ms)?;
    Ok(now_ms)
}
