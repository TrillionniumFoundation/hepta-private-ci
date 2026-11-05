//! The same pure transition validation is used for writes and journal replay.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::cell_lifecycle::*;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum LifecycleEventV1 {
    Created { at_ms: u64 },
    Prepared { at_ms: u64 },
    Observed {
        observation: RuntimeCellLifecycleObservationV1,
        authentication: String,
    },
}

pub(crate) fn transition(
    plan: &RuntimeCellLifecyclePlanV1,
    previous: Option<&RuntimeCellLifecycleSnapshotV1>,
    event: &LifecycleEventV1,
) -> Result<RuntimeCellLifecycleSnapshotV1, RuntimeCellLifecycleError> {
    let digest = plan.digest()?.to_string();
    match (previous, event) {
        (None, LifecycleEventV1::Created { at_ms }) => {
            if *at_ms < plan.created_at_ms || *at_ms >= plan.deadline_ms {
                return Err(RuntimeCellLifecycleError::Deadline);
            }
            Ok(RuntimeCellLifecycleSnapshotV1 {
                plan_digest: digest, revision: 0,
                stage: Some(RuntimeCellLifecycleStageV1::StopAdmission), pending: false,
                last_observed_ms: *at_ms, evidence: Vec::new(),
            })
        }
        (Some(state), LifecycleEventV1::Prepared { at_ms }) => {
            if state.plan_digest != digest {
                return Err(RuntimeCellLifecycleError::Conflict);
            }
            if state.pending {
                return Err(RuntimeCellLifecycleError::ReconciliationRequired);
            }
            if state.stage.is_none() {
                return Err(RuntimeCellLifecycleError::Conflict);
            }
            if *at_ms < state.last_observed_ms || *at_ms >= plan.deadline_ms {
                return Err(RuntimeCellLifecycleError::Deadline);
            }
            let mut next = state.clone();
            next.revision = next.revision.checked_add(1)
                .ok_or(RuntimeCellLifecycleError::Capacity)?;
            next.last_observed_ms = *at_ms;
            next.pending = true;
            Ok(next)
        }
        (Some(state), LifecycleEventV1::Observed { observation, authentication }) => {
            if state.plan_digest != digest || !state.pending
                || state.stage != Some(observation.stage)
                || observation.prepared_revision != state.revision
                || observation.observed_at_ms < state.last_observed_ms
            {
                return Err(RuntimeCellLifecycleError::Conflict);
            }
            nonzero(authentication)?;
            validate_observation(plan, observation)?;
            let mut next = state.clone();
            next.revision = next.revision.checked_add(1)
                .ok_or(RuntimeCellLifecycleError::Capacity)?;
            next.pending = false;
            next.stage = match observation.outcome {
                RuntimeCellLifecycleNativeOutcomeV1::Applied => observation.stage.next(),
                RuntimeCellLifecycleNativeOutcomeV1::NotApplied => Some(observation.stage),
            };
            next.last_observed_ms = observation.observed_at_ms;
            next.evidence.push(authentication.clone());
            Ok(next)
        }
        (Some(_), LifecycleEventV1::Created { .. })
        | (None, LifecycleEventV1::Prepared { .. } | LifecycleEventV1::Observed { .. }) => {
            Err(RuntimeCellLifecycleError::Conflict)
        }
    }
}

pub(crate) fn validate_observation(
    plan: &RuntimeCellLifecyclePlanV1,
    observation: &RuntimeCellLifecycleObservationV1,
) -> Result<(), RuntimeCellLifecycleError> {
    let expected = intent(plan, observation.stage, observation.prepared_revision)?;
    if observation.agent_id != plan.agent_id.as_str()
        || observation.operation_id != plan.operation_id.as_str()
        || observation.observer_id != plan.observer_id.as_str()
        || observation.observer_trust != plan.observer_trust.to_string()
        || observation.plan_digest != expected.plan_digest.to_string()
        || observation.semantic_operation != expected.semantic_operation.to_string()
        || observation.attempt_digest != expected.attempt_digest.to_string()
        || observation.observed_at_ms < plan.created_at_ms
    {
        return Err(RuntimeCellLifecycleError::ScopeMismatch);
    }
    nonzero(&observation.native_receipt)?;
    for digest in [&observation.topology, &observation.state_root, &observation.bundle] {
        nonzero(digest)?;
    }
    let requested_stage = observation.stage.code();
    let applied = observation.outcome == RuntimeCellLifecycleNativeOutcomeV1::Applied;
    let stage = if applied { requested_stage } else { requested_stage.saturating_sub(1) };
    let expects_closed = !(applied && observation.stage == RuntimeCellLifecycleStageV1::Resume
        || !applied && observation.stage == RuntimeCellLifecycleStageV1::StopAdmission);
    if observation.admission_closed != expects_closed
        || (stage >= RuntimeCellLifecycleStageV1::Drain.code()
            && (observation.inflight != 0 || observation.unknown_effects != 0))
        || (stage >= RuntimeCellLifecycleStageV1::FenceWriters.code()
            && observation.writer_fence != plan.handoff.successor_writer_fence)
        || (stage < RuntimeCellLifecycleStageV1::FenceWriters.code()
            && observation.writer_fence != plan.handoff.predecessor_writer_fence)
    {
        return Err(RuntimeCellLifecycleError::InvalidObservation);
    }
    let published = stage >= RuntimeCellLifecycleStageV1::Publish.code();
    let generation = if published { plan.successor_generation } else { plan.predecessor_generation };
    let topology = if published { plan.successor_topology } else { plan.predecessor_topology };
    if observation.generation != generation.get() || observation.topology != topology.to_string() {
        return Err(RuntimeCellLifecycleError::InvalidObservation);
    }
    if stage >= RuntimeCellLifecycleStageV1::TransferState.code()
        && (observation.state_root != plan.successor_state_root.to_string()
            || observation.bundle != plan.successor_bundle.to_string())
    {
        return Err(RuntimeCellLifecycleError::InvalidObservation);
    }
    if stage < RuntimeCellLifecycleStageV1::TransferState.code()
        && observation.state_root != plan.predecessor_state_root.to_string()
    {
        return Err(RuntimeCellLifecycleError::InvalidObservation);
    }
    Ok(())
}

fn nonzero(value: &str) -> Result<Digest32, RuntimeCellLifecycleError> {
    let digest: Digest32 = value.parse().map_err(|_| RuntimeCellLifecycleError::InvalidObservation)?;
    if digest.is_zero() {
        return Err(RuntimeCellLifecycleError::InvalidObservation);
    }
    Ok(digest)
}
