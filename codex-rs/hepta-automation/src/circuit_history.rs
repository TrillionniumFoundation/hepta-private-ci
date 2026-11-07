//! Canonical events replay through the same reducer used for live admission.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::BoundedCircuitDefinitionV2;
use crate::CircuitActivationStatusV2;
use crate::CircuitDispatchV2;
use crate::CircuitEventV2;
use crate::CircuitRunV2;
use crate::CircuitStartV2;
use crate::CircuitStopReasonV2;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::circuit_profile::digest;
use crate::circuit_profile::invalid;
use crate::circuit_state::CircuitWriterV2;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CircuitFenceIdentityV2 {
    owner_id: String,
    owner_epoch: u64,
    generation: u64,
    fencing_token: String,
}

impl CircuitFenceIdentityV2 {
    pub fn from_fence(fence: &TaskFlowFence) -> Result<Self, TaskFlowError> {
        CircuitWriterV2::new(fence, /*expires_at_ms*/ 0)?;
        Ok(Self {
            owner_id: fence.owner_id.clone(),
            owner_epoch: fence.owner_epoch,
            generation: fence.generation,
            fencing_token: fence.fencing_token.clone(),
        })
    }

    fn to_fence(&self, owner: &AgentId) -> Result<TaskFlowFence, TaskFlowError> {
        TaskFlowFence::new(
            owner.clone(),
            &self.owner_id,
            self.owner_epoch,
            self.generation,
            &self.fencing_token,
        )
    }

    pub(crate) fn matches(&self, writer: &CircuitWriterV2) -> bool {
        self.owner_id == writer.owner_id
            && self.owner_epoch == writer.owner_epoch
            && self.generation == writer.generation
            && self.fencing_token == writer.fencing_token
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum CircuitLedgerEventV2 {
    Created {
        start: CircuitStartV2,
        fence: CircuitFenceIdentityV2,
    },
    Applied {
        fence: CircuitFenceIdentityV2,
        expected_revision: u64,
        now_ms: u64,
        event: CircuitEventV2,
    },
    Claimed {
        fence: CircuitFenceIdentityV2,
        expected_revision: u64,
        now_ms: u64,
        lease_duration_ms: u64,
    },
    ComputationClaimed {
        fence: CircuitFenceIdentityV2,
        expected_revision: u64,
        now_ms: u64,
        activation_id: u64,
        execution_request_digest: Sha256Digest,
    },
    #[serde(rename = "computation_claimed_with_input_v1")]
    ComputationClaimedWithInputV1 {
        fence: CircuitFenceIdentityV2,
        expected_revision: u64,
        now_ms: u64,
        activation_id: u64,
        execution_request_digest: Sha256Digest,
        input_digest: Sha256Digest,
    },
}

impl CircuitLedgerEventV2 {
    pub fn replay(
        &self,
        previous: Option<&CircuitRunV2>,
        definition: &BoundedCircuitDefinitionV2,
        owner: &AgentId,
    ) -> Result<(CircuitRunV2, Vec<CircuitDispatchV2>), TaskFlowError> {
        match self {
            Self::Created { start, fence } => {
                if previous.is_some() {
                    return Err(invalid("duplicate circuit creation"));
                }
                Ok((
                    CircuitRunV2::prepare(definition, start, &fence.to_fence(owner)?)?,
                    Vec::new(),
                ))
            }
            Self::Applied {
                fence,
                expected_revision,
                now_ms,
                event,
            } => {
                let run = previous.ok_or_else(|| invalid("circuit command before creation"))?;
                if run.revision != *expected_revision {
                    return Err(TaskFlowError::Conflict(
                        "circuit revision changed".to_string(),
                    ));
                }
                if !fence.matches(&run.writer) || *now_ms >= run.writer.expires_at_ms {
                    return Err(TaskFlowError::StaleFence);
                }
                run.reduce(definition, event, *now_ms)
            }
            Self::ComputationClaimedWithInputV1 {
                fence,
                expected_revision,
                now_ms,
                activation_id,
                execution_request_digest,
                input_digest,
            } => {
                digest(input_digest)?;
                Self::ComputationClaimed {
                    fence: fence.clone(),
                    expected_revision: *expected_revision,
                    now_ms: *now_ms,
                    activation_id: *activation_id,
                    execution_request_digest: execution_request_digest.clone(),
                }
                .replay(previous, definition, owner)
            }
            Self::ComputationClaimed {
                fence,
                expected_revision,
                now_ms,
                activation_id,
                execution_request_digest,
            } => {
                digest(execution_request_digest)?;
                let run =
                    previous.ok_or_else(|| invalid("computation claim before run creation"))?;
                if run.revision != *expected_revision || run.outcome().is_some() {
                    return Err(TaskFlowError::Conflict(
                        "computation claim revision or terminal state".to_string(),
                    ));
                }
                if !fence.matches(&run.writer)
                    || *now_ms >= run.writer.expires_at_ms
                    || *now_ms < run.last_observed_ms
                {
                    return Err(TaskFlowError::StaleFence);
                }
                if *now_ms - run.created_at_ms >= definition.limits.max_elapsed_ms {
                    return Err(invalid("computation claim is past circuit deadline"));
                }
                let activation = run
                    .activations
                    .get(activation_id)
                    .ok_or_else(|| invalid("unknown computation"))?;
                if activation.status != CircuitActivationStatusV2::InFlight
                    || activation.cancel_requested
                    || activation.execution_request_digest.is_some()
                {
                    return Err(invalid(
                        "computation is not eligible for a first execution claim",
                    ));
                }
                run.dispatch(definition, *activation_id)?;
                let mut next = run.clone();
                next.revision = next
                    .revision
                    .checked_add(1)
                    .ok_or_else(|| invalid("claim revision overflow"))?;
                next.last_observed_ms = *now_ms;
                next.activations
                    .get_mut(activation_id)
                    .ok_or_else(|| invalid("unknown computation"))?
                    .execution_request_digest = Some(execution_request_digest.clone());
                Ok((next, Vec::new()))
            }
            Self::Claimed {
                fence,
                expected_revision,
                now_ms,
                lease_duration_ms,
            } => {
                let run = previous.ok_or_else(|| invalid("circuit claim before creation"))?;
                if run.revision != *expected_revision || run.outcome().is_some() {
                    return Err(TaskFlowError::Conflict(
                        "circuit claim revision or terminal state".to_string(),
                    ));
                }
                if *now_ms < run.last_observed_ms
                    || *lease_duration_ms == 0
                    || *lease_duration_ms > 3_600_000
                {
                    return Err(invalid("invalid claim time or lease duration"));
                }
                let expires = now_ms
                    .checked_add(*lease_duration_ms)
                    .ok_or_else(|| invalid("claim lease overflow"))?;
                let expired = *now_ms >= run.writer.expires_at_ms;
                if (!expired && (!fence.matches(&run.writer) || expires < run.writer.expires_at_ms))
                    || (expired
                        && (fence.generation <= run.writer.generation
                            || fence.owner_epoch < run.writer.owner_epoch))
                {
                    return Err(TaskFlowError::StaleFence);
                }
                let mut next = run.clone();
                next.writer = CircuitWriterV2::new(&fence.to_fence(owner)?, expires)?;
                next.revision = next
                    .revision
                    .checked_add(1)
                    .ok_or_else(|| invalid("claim revision overflow"))?;
                next.last_observed_ms = *now_ms;
                if expired {
                    for activation in next
                        .activations
                        .values_mut()
                        .filter(|a| a.status == CircuitActivationStatusV2::InFlight)
                    {
                        // Lost acknowledgement is not proof of no execution.
                        activation.status = CircuitActivationStatusV2::Indeterminate;
                    }
                }
                if *now_ms - run.created_at_ms >= definition.limits.max_elapsed_ms {
                    next.stop(definition, CircuitStopReasonV2::Deadline)?;
                    next.finish_instances(definition)?;
                }
                Ok((next, Vec::new()))
            }
        }
    }
}

#[derive(Clone, Debug)]
pub struct CircuitLeaseClaimV2 {
    pub run_id: String,
    pub command_id: String,
    pub fence: TaskFlowFence,
    pub expected_revision: u64,
    pub now_ms: u64,
    pub lease_duration_ms: u64,
}
