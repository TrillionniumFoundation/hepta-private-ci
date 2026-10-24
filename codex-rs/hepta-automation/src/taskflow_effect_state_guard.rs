//! Preserve the original admitted effect's run and step recovery ownership.

use super::check_step_fence;
use super::load_step_events;
use super::reconstruct_step;
use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepState;
use crate::TaskFlowTransition;
use crate::effect_dispatch_ledger::EffectDispatchAttempt;
use crate::effect_dispatch_ledger::EffectDispatchObservationKind;
use crate::effect_dispatch_ledger::load_effect_dispatch_attempt;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

/// The caller holds the same transaction as the run mutation. Generic
/// commands cannot move an admitted effect away from its recovery owner.
pub(crate) async fn guard_run_transition(
    store: &AutomationStore,
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    run_id: &str,
    fence: &TaskFlowFence,
    transition: &TaskFlowTransition,
    effect_reconciliation: bool,
) -> Result<(), TaskFlowError> {
    if matches!(transition, TaskFlowTransition::Indeterminate { .. }) {
        // Quarantine retains the exact owner tuple and accepts later evidence.
        return Ok(());
    }
    let attempts = load_attempts(store, tx, run_id).await?;
    if attempts.is_empty() {
        return Ok(()); // Preserve the existing non-effect TaskFlow APIs.
    }
    if let TaskFlowTransition::Reconcile {
        receipt_digest,
        outcome,
    } = transition
    {
        if !effect_reconciliation {
            return Err(conflict(
                "admitted effects require original evidence-owned reconciliation",
            ));
        }
        let expected = match outcome {
            TaskFlowReconcileOutcome::Succeeded => EffectDispatchObservationKind::Succeeded,
            TaskFlowReconcileOutcome::Failed => EffectDispatchObservationKind::Failed,
            TaskFlowReconcileOutcome::Cancelled => {
                return Err(conflict(
                    "no provider cancellation acknowledgement is defined",
                ));
            }
        };
        let mut non_absent = 0;
        for attempt in &attempts {
            let observation = attempt
                .observation
                .as_ref()
                .ok_or_else(|| conflict("another admitted effect still lacks provider evidence"))?;
            if observation.kind != EffectDispatchObservationKind::ProvenAbsent {
                non_absent += 1;
                if observation.kind != expected || observation.evidence_digest != *receipt_digest {
                    return Err(conflict(
                        "run reconciliation differs from admitted provider evidence",
                    ));
                }
            }
            require_settled_step(store, tx, attempt, fence).await?;
        }
        if non_absent != 1 {
            // No existing aggregate-outcome contract: retain every fence and
            // receipt instead of choosing the last completion's result.
            return Err(conflict(
                "multiple-effect terminal aggregation is not defined",
            ));
        }
        return Ok(());
    }
    // This is the original pending-effect predicate: only provider-proven
    // absence permits an ordinary transition or original absence recovery.
    if attempts.iter().any(|attempt| {
        attempt.observation.as_ref().is_none_or(|observation| {
            observation.kind != EffectDispatchObservationKind::ProvenAbsent
        })
    }) {
        return Err(conflict(
            "admitted provider effect requires original terminal evidence",
        ));
    }
    let mut matches_absence_proof = false;
    for attempt in &attempts {
        require_settled_step(store, tx, attempt, fence).await?;
        if let TaskFlowTransition::RequeueProvenAbsent { proof_digest }
        | TaskFlowTransition::CancelProvenAbsent { proof_digest } = transition
        {
            matches_absence_proof |= attempt
                .observation
                .as_ref()
                .is_some_and(|observation| observation.evidence_digest == *proof_digest);
        }
    }
    if matches!(
        transition,
        TaskFlowTransition::RequeueProvenAbsent { .. }
            | TaskFlowTransition::CancelProvenAbsent { .. }
    ) && !matches_absence_proof
    {
        return Err(conflict(
            "absence recovery is not bound to retained effect evidence",
        ));
    }
    Ok(())
}

/// A generic step receipt cannot preempt a contacted effect's original ledger.
/// Non-effect steps retain their existing caller-owned observation semantics.
pub(super) async fn validate_step_observation(
    store: &AutomationStore,
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    run_id: &str,
    step_id: &str,
    attempt: u32,
    receipt: &Sha256Digest,
    kind: EffectDispatchObservationKind,
) -> Result<(), TaskFlowError> {
    let Some(admitted) = load_effect_dispatch_attempt(
        &mut **tx,
        store.taskflow_owner_agent_id().as_str(),
        run_id,
        step_id,
        attempt,
    )
    .await?
    else {
        return Ok(());
    };
    if admitted.observation.as_ref().is_none_or(|observation| {
        observation.kind != kind || observation.evidence_digest != *receipt
    }) {
        return Err(conflict(
            "step observation differs from the original effect ledger",
        ));
    }
    Ok(())
}

async fn load_attempts(
    store: &AutomationStore,
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    run_id: &str,
) -> Result<Vec<EffectDispatchAttempt>, TaskFlowError> {
    let rows = sqlx::query(
        "SELECT step_id, attempt FROM taskflow_effect_dispatch_attempts
        WHERE owner_agent_id = ? AND run_id = ? ORDER BY step_id, attempt",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(run_id)
    .fetch_all(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let mut attempts = Vec::with_capacity(rows.len());
    for row in rows {
        let step: String = row.try_get("step_id").map_err(|_| corrupt())?;
        let attempt = u32::try_from(row.try_get::<i64, _>("attempt").map_err(|_| corrupt())?)
            .map_err(|_| corrupt())?;
        attempts.push(
            load_effect_dispatch_attempt(
                &mut **tx,
                store.taskflow_owner_agent_id().as_str(),
                run_id,
                &step,
                attempt,
            )
            .await?
            .ok_or_else(corrupt)?,
        );
    }
    Ok(attempts)
}

async fn require_settled_step(
    store: &AutomationStore,
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    attempt: &EffectDispatchAttempt,
    fence: &TaskFlowFence,
) -> Result<(), TaskFlowError> {
    let observation = attempt
        .observation
        .as_ref()
        .ok_or_else(|| conflict("admitted effect has no provider observation"))?;
    let (observed, terminal) = match observation.kind {
        EffectDispatchObservationKind::Succeeded => (
            Some(TaskFlowStepObservation::Succeeded),
            TaskFlowReconcileOutcome::Succeeded,
        ),
        EffectDispatchObservationKind::Failed => (
            Some(TaskFlowStepObservation::Failed),
            TaskFlowReconcileOutcome::Failed,
        ),
        EffectDispatchObservationKind::ProvenAbsent => (None, TaskFlowReconcileOutcome::Cancelled),
        EffectDispatchObservationKind::Indeterminate => {
            return Err(conflict(
                "indeterminate provider evidence must retain its recovery fence",
            ));
        }
    };
    let events = load_step_events(
        tx,
        store,
        &attempt.run_id,
        &attempt.step_id,
        attempt.attempt,
    )
    .await?;
    let step = reconstruct_step(
        store.taskflow_owner_agent_id(),
        &attempt.run_id,
        &attempt.step_id,
        attempt.attempt,
        &events,
    )?;
    if observation.kind != EffectDispatchObservationKind::ProvenAbsent {
        check_step_fence(&step.fence, fence)?;
    }
    // A fully settled absent attempt may predate the current legitimate
    // generation. Its immutable chain and exact admitted payload/evidence
    // remain authoritative; never rewrite that historical fence.
    let settled = (step.state == TaskFlowStepState::Recorded
        && observed.is_some()
        && step.observation == observed)
        || (step.state == TaskFlowStepState::Reconciled && step.final_outcome == Some(terminal));
    if !settled
        || step.intent_digest != attempt.intent_digest
        || step.payload_digest != attempt.payload_digest
        || step.receipt_digest.as_ref() != Some(&observation.evidence_digest)
    {
        return Err(conflict(
            "effect step receipt must settle before its run lease is cleared",
        ));
    }
    Ok(())
}

fn conflict(message: &str) -> TaskFlowError {
    TaskFlowError::Conflict(message.into())
}
fn corrupt() -> TaskFlowError {
    TaskFlowError::Corrupt("effect recovery guard row".into())
}
