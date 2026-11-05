//! Deterministic bounded circuit reducer. Dispatches describe computation intent.
//! Execution additionally requires the durable owner's sealed claim; pure DTOs
//! grant neither computation nor external-effect authority.

use std::collections::BTreeMap;

use crate::BoundedCircuitDefinitionV2;
use crate::CircuitActivationStatusV2 as Status;
use crate::CircuitBudgetV2;
use crate::CircuitDispatchV2;
use crate::CircuitEventV2;
use crate::CircuitRunV2;
use crate::CircuitStartV2;
use crate::CircuitStopReasonV2 as Stop;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::circuit_profile::digest;
use crate::circuit_profile::hash;
use crate::circuit_profile::invalid;
use crate::circuit_profile::text;
use crate::circuit_state::CircuitInstanceV2;
use crate::circuit_state::CircuitWriterV2;

impl CircuitRunV2 {
    /// Construct a pure initial state. Persistence and owner fencing are supplied
    /// by AutomationStore; this method grants no effect or scheduling authority.
    pub fn prepare(
        definition: &BoundedCircuitDefinitionV2,
        start: &CircuitStartV2,
        fence: &TaskFlowFence,
    ) -> Result<Self, TaskFlowError> {
        definition.validate()?;
        text(&start.run_id)?;
        digest(&start.scope_digest)?;
        digest(&start.input_digest)?;
        if start.lease_duration_ms == 0 || start.lease_duration_ms > 3_600_000 {
            return Err(invalid("invalid circuit lease duration"));
        }
        let expires = start.created_at_ms.checked_add(start.lease_duration_ms)
            .ok_or_else(|| invalid("lease overflow"))?;
        start.created_at_ms.checked_add(definition.limits.max_elapsed_ms)
            .ok_or_else(|| invalid("deadline overflow"))?;
        let mut run = Self {
            owner_agent_id: fence.owner_agent_id.as_str().to_string(),
            run_id: start.run_id.clone(),
            definition_digest: definition.definition_digest()?,
            scope_digest: start.scope_digest.clone(),
            created_at_ms: start.created_at_ms,
            last_observed_ms: start.created_at_ms,
            revision: 0,
            writer: CircuitWriterV2::new(fence, expires)?,
            instances: BTreeMap::new(),
            activations: BTreeMap::new(),
            next_activation: 1,
            stop_reason: None,
        };
        run.instances.insert(0, CircuitInstanceV2 {
            program_id: definition.entry_program.clone(),
            parent_activation: None,
            child_depth: 0,
            budget: CircuitBudgetV2::new(definition.limits.work_budget),
            exit: None,
            returned: false,
            progress: BTreeMap::new(),
        });
        let entry = &definition.program(&definition.entry_program)?.entry_node;
        run.enqueue(definition, /*instance_id*/ 0, entry, /*round*/ 0, Vec::new(),
            start.input_digest.clone(), start.created_at_ms, /*edge_id*/ None)?;
        Ok(run)
    }

    /// Calculate the next immutable state. Callers must persist a successful
    /// transition before consuming newly returned dispatches. A failed reduction
    /// leaves the original state unchanged.
    pub fn reduce(
        &self,
        definition: &BoundedCircuitDefinitionV2,
        event: &CircuitEventV2,
        now_ms: u64,
    ) -> Result<(Self, Vec<CircuitDispatchV2>), TaskFlowError> {
        if hash("hepta.circuit.definition.v2", definition)? != self.definition_digest || now_ms < self.last_observed_ms {
            return Err(invalid("circuit definition mismatch or time regression"));
        }
        if self.outcome().is_some() {
            return Err(invalid("circuit is already terminal"));
        }
        let mut next = self.clone();
        next.last_observed_ms = now_ms;
        next.revision = next.revision.checked_add(1).ok_or_else(|| invalid("circuit revision overflow"))?;
        if now_ms - self.created_at_ms >= definition.limits.max_elapsed_ms {
            next.stop(definition, Stop::Deadline)?;
        }
        if next.activations.values().any(|a| a.status == Status::Joining
            && a.join_deadline_ms.is_some_and(|end| now_ms >= end))
        {
            next.stop(definition, Stop::JoinTimeout)?;
        }
        let mut dispatches = Vec::new();
        match event {
            CircuitEventV2::Advance { quantum } => {
                if *quantum == 0 || *quantum > definition.limits.max_quantum {
                    return Err(invalid("invalid circuit scheduling quantum"));
                }
                if next.revision > u64::from(definition.limits.max_events) {
                    next.stop(definition, Stop::EventLimit)?;
                }
                for _ in 0..*quantum {
                    if next.stop_reason.is_some() {
                        break;
                    }
                    let ready = next.activations.values()
                        .filter(|a| a.status == Status::Ready && a.ready_at_ms <= now_ms)
                        .min_by_key(|a| (a.ready_at_ms, a.activation_id))
                        .map(|a| a.activation_id);
                    let Some(id) = ready else { break; };
                    next.activate(definition, id, &mut dispatches)?;
                    next.finish_instances(definition)?;
                }
            }
            CircuitEventV2::Complete { completion } => {
                next.complete(definition, completion, Status::InFlight)?;
            }
            CircuitEventV2::Reconcile { completion } => {
                next.complete(definition, completion, Status::Indeterminate)?;
            }
            CircuitEventV2::MarkIndeterminate { activation_id, observation_digest } => {
                digest(observation_digest)?;
                let activation = next.activations.get_mut(activation_id)
                    .ok_or_else(|| invalid("unknown activation"))?;
                if activation.status != Status::InFlight {
                    return Err(invalid("only in-flight work can become indeterminate"));
                }
                activation.status = Status::Indeterminate;
                activation.receipt_digest = Some(observation_digest.clone());
            }
            CircuitEventV2::Cancel => next.stop(definition, Stop::Cancelled)?,
        }
        next.finish_instances(definition)?;
        let mut admitted = Vec::new();
        for dispatch in dispatches {
            let activation = &next.activations[&dispatch.activation_id];
            if activation.cancel_requested {
                // This dispatch exists only inside the current reducer call.
                // It has never crossed the commit/return boundary, so no backend
                // could have received it. Cancel and refund it atomically.
                let instance_id = activation.instance_id;
                next.instances.get_mut(&instance_id).ok_or_else(|| invalid("unknown instance"))?
                    .budget.settle(dispatch.activation_id, /*actual_work*/ 0)?;
                let activation = next.activations.get_mut(&dispatch.activation_id)
                    .ok_or_else(|| invalid("unknown cancelled dispatch"))?;
                activation.status = Status::Cancelled;
                activation.receipt_digest = Some(hash("hepta.circuit.pre-dispatch-cancel.v2",
                    &dispatch.invocation_digest)?);
            } else {
                admitted.push(dispatch);
            }
        }
        next.finish_instances(definition)?;
        Ok((next, admitted))
    }
}
