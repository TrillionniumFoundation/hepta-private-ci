//! Causal frontier, joins, child return, and cancellation for the V2 reducer.

use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;

use crate::BoundedCircuitDefinitionV2;
use crate::CircuitActivationStatusV2 as Status;
use crate::CircuitActivationV2;
use crate::CircuitExitV2;
use crate::CircuitJoinV2;
use crate::CircuitNodeKindV2;
use crate::CircuitRunV2;
use crate::CircuitStopReasonV2 as Stop;
use crate::TaskFlowError;
use crate::circuit_budget::CircuitWorkSettlementV2;
use crate::circuit_profile::hash;
use crate::circuit_profile::invalid;

impl CircuitRunV2 {
    #[allow(clippy::too_many_arguments, reason = "each causal-delivery field is bound explicitly")]
    pub(crate) fn enqueue(
        &mut self, definition: &BoundedCircuitDefinitionV2, instance_id: u64, node_id: &str,
        round: u32, parents: Vec<u64>, input: Sha256Digest, ready_at_ms: u64, edge_id: Option<&str>,
    ) -> Result<(), TaskFlowError> {
        if self.instances[&instance_id].exit.is_some() {
            return Ok(());
        }
        if round >= definition.limits.max_rounds {
            return self.stop(definition, Stop::RoundLimit);
        }
        let depth = parents.iter()
            .map(|p| self.activations.get(p).map(|a| a.causal_depth).ok_or_else(|| invalid("future causal parent")))
            .collect::<Result<Vec<_>, _>>()?.into_iter().max().unwrap_or(0) + 1;
        if depth > definition.limits.max_causal_depth {
            return self.stop(definition, Stop::DepthLimit);
        }
        let program = definition.program(&self.instances[&instance_id].program_id)?;
        let node = program.node(node_id)?;
        let join = match node.kind {
            CircuitNodeKindV2::Join { mode, timeout_ms } => Some((mode, timeout_ms)),
            CircuitNodeKindV2::Compute { .. } | CircuitNodeKindV2::Decide { .. }
            | CircuitNodeKindV2::Subcircuit { .. } | CircuitNodeKindV2::Exit { .. } => None,
        };
        if let Some((mode, timeout_ms)) = join {
            let edge = edge_id.ok_or_else(|| invalid("join requires a named branch"))?;
            let producer = *parents.last().ok_or_else(|| invalid("join arrival has no causal producer"))?;
            let existing = self.activations.values()
                .find(|a| a.instance_id == instance_id && a.node_id == node_id && a.round == round)
                .map(|a| a.activation_id);
            let id = if let Some(id) = existing {
                if self.activations[&id].status != Status::Joining {
                    return Ok(());
                }
                if self.activations[&id].arrivals.contains_key(edge) {
                    return self.stop(definition, Stop::JoinConflict);
                }
                id
            } else {
                if !self.has_capacity(definition) {
                    return self.stop(definition, Stop::Capacity);
                }
                let id = self.next_activation;
                self.next_activation += 1;
                self.activations.insert(id, CircuitActivationV2 {
                    activation_id: id, instance_id, node_id: node_id.to_string(), round,
                    causal_depth: depth, causal_parents: Vec::new(), input_digest: input.clone(),
                    ready_at_ms, status: Status::Joining, cancel_requested: false,
                    output_digest: None, receipt_digest: None, selected_edges: Vec::new(),
                    arrivals: BTreeMap::new(), arrival_inputs: Vec::new(), continuation_parents: Vec::new(),
                    join_deadline_ms: Some(ready_at_ms.checked_add(timeout_ms)
                        .ok_or_else(|| invalid("join deadline overflow"))?),
                });
                id
            };
            let branch_sources: BTreeMap<_, _> = program.edges.iter().filter(|e| e.to == node_id)
                .map(|e| (e.edge_id.as_str(), e.from.as_str())).collect();
            let required = match mode {
                CircuitJoinV2::All => branch_sources.len(),
                CircuitJoinV2::Any => 1,
                CircuitJoinV2::Quorum { required } => usize::from(required),
            };
            let activation = self.activations.get_mut(&id).ok_or_else(|| invalid("unknown join"))?;
            activation.arrivals.insert(edge.to_string(), producer);
            activation.arrival_inputs.push(input);
            activation.causal_parents.extend(parents);
            activation.causal_depth = activation.causal_depth.max(depth);
            activation.ready_at_ms = activation.ready_at_ms.max(ready_at_ms);
            if activation.arrivals.len() >= required {
                activation.status = Status::Ready;
                activation.join_deadline_ms = None;
                let accepted = activation.arrivals.clone();
                activation.input_digest = hash("hepta.circuit.join-input.v2",
                    &(node_id, round, &activation.causal_parents, &activation.arrival_inputs))?;
                let surplus: Vec<_> = self.activations.values()
                    .filter(|a| a.instance_id == instance_id && a.round == round
                        && branch_sources.iter().any(|(edge, source)|
                            !accepted.contains_key(*edge) && *source == a.node_id)
                        && !a.status.settled())
                    .map(|a| a.activation_id).collect();
                for surplus_id in surplus {
                    self.request_cancel(definition, surplus_id)?;
                }
            }
            return Ok(());
        }
        if !self.has_capacity(definition) {
            return self.stop(definition, Stop::Capacity);
        }
        let id = self.next_activation;
        self.next_activation += 1;
        self.activations.insert(id, CircuitActivationV2 {
            activation_id: id, instance_id, node_id: node_id.to_string(), round, causal_depth: depth,
            causal_parents: parents, input_digest: input, ready_at_ms, status: Status::Ready,
            cancel_requested: false, output_digest: None, receipt_digest: None, selected_edges: Vec::new(),
            arrivals: BTreeMap::new(), arrival_inputs: Vec::new(), join_deadline_ms: None,
            continuation_parents: Vec::new(),
        });
        Ok(())
    }

    fn has_capacity(&self, definition: &BoundedCircuitDefinitionV2) -> bool {
        self.activations.len() < definition.limits.max_activations as usize
            && self.activations.values().filter(|a| !a.status.settled()).count()
                < definition.limits.max_frontier as usize
    }

    pub(crate) fn route(
        &mut self, definition: &BoundedCircuitDefinitionV2, id: u64, selected: &[String],
    ) -> Result<(), TaskFlowError> {
        let source = self.activations[&id].clone();
        if source.cancel_requested || self.instances[&source.instance_id].exit.is_some() {
            return Ok(());
        }
        let program = definition.program(&self.instances[&source.instance_id].program_id)?;
        let output = source.output_digest.clone().ok_or_else(|| invalid("route has no output"))?;
        let parents = if source.continuation_parents.is_empty() { vec![id] } else { source.continuation_parents.clone() };
        self.activations.get_mut(&id).ok_or_else(|| invalid("unknown route source"))?.selected_edges = selected.to_vec();
        for edge_id in selected {
            let edge = program.edges.iter().find(|e| e.edge_id == *edge_id && e.from == source.node_id)
                .ok_or_else(|| invalid("undeclared circuit route"))?;
            let round = source.round + u32::from(edge.feedback_delay_ms.is_some());
            let ready = self.last_observed_ms.checked_add(edge.feedback_delay_ms.unwrap_or(0))
                .ok_or_else(|| invalid("feedback delay overflow"))?;
            self.enqueue(definition, source.instance_id, &edge.to, round, parents.clone(),
                output.clone(), ready, Some(&edge.edge_id))?;
        }
        Ok(())
    }

    pub(crate) fn stop(
        &mut self, definition: &BoundedCircuitDefinitionV2, reason: Stop,
    ) -> Result<(), TaskFlowError> {
        if self.stop_reason.is_none() {
            self.stop_reason = Some(reason);
        }
        let summary = hash("hepta.circuit.stop.v2", &(&self.run_id, self.stop_reason))?;
        self.fallback_instance(definition, /*instance_id*/ 0, summary)
    }

    pub(crate) fn fallback_instance(
        &mut self, definition: &BoundedCircuitDefinitionV2, instance_id: u64, output: Sha256Digest,
    ) -> Result<(), TaskFlowError> {
        let program = definition.program(&self.instances[&instance_id].program_id)?;
        let CircuitNodeKindV2::Exit { outcome } = program.node(&program.fallback_node)?.kind else {
            return Err(invalid("fallback is not an exit"));
        };
        self.exit_instance(definition, instance_id, outcome, output)
    }

    pub(crate) fn exit_instance(
        &mut self, definition: &BoundedCircuitDefinitionV2, instance_id: u64,
        outcome: CircuitExitV2, output: Sha256Digest,
    ) -> Result<(), TaskFlowError> {
        let descendants: Vec<_> = self.instances.keys().copied()
            .filter(|id| self.descends_from(*id, instance_id)).collect();
        for descendant in descendants {
            let instance = self.instances.get_mut(&descendant).ok_or_else(|| invalid("unknown instance"))?;
            if instance.returned {
                continue;
            }
            let disposition = if descendant == instance_id {
                outcome
            } else {
                let program = definition.program(&instance.program_id)?;
                match program.node(&program.fallback_node)?.kind {
                    CircuitNodeKindV2::Exit { outcome } => outcome,
                    CircuitNodeKindV2::Compute { .. } | CircuitNodeKindV2::Decide { .. }
                    | CircuitNodeKindV2::Subcircuit { .. } | CircuitNodeKindV2::Join { .. } =>
                        return Err(invalid("invalid fallback")),
                }
            };
            if instance.exit.is_none() || disposition != CircuitExitV2::Succeeded {
                instance.exit = Some((disposition, output.clone()));
            }
            for activation in self.activations.values_mut()
                .filter(|a| a.instance_id == descendant && !a.status.settled())
            {
                activation.cancel_requested = true;
                if matches!(activation.status, Status::Ready | Status::Joining) {
                    activation.status = Status::Cancelled;
                }
            }
        }
        Ok(())
    }

    fn descends_from(&self, mut id: u64, ancestor: u64) -> bool {
        loop {
            if id == ancestor {
                return true;
            }
            let Some(parent) = self.instances[&id].parent_activation else { return false; };
            id = self.activations[&parent].instance_id;
        }
    }

    fn request_cancel(
        &mut self, definition: &BoundedCircuitDefinitionV2, id: u64,
    ) -> Result<(), TaskFlowError> {
        let activation = self.activations.get_mut(&id).ok_or_else(|| invalid("unknown cancellation"))?;
        activation.cancel_requested = true;
        match activation.status {
            Status::Ready | Status::Joining => activation.status = Status::Cancelled,
            Status::ChildRunning => {
                let output = hash("hepta.circuit.surplus-child.v2", &(&self.run_id, id))?;
                self.fallback_instance(definition, id, output)?;
            }
            Status::InFlight | Status::Indeterminate | Status::Completed | Status::Cancelled => {}
        }
        Ok(())
    }

    pub(crate) fn finish_instances(&mut self, definition: &BoundedCircuitDefinitionV2) -> Result<(), TaskFlowError> {
        loop {
            let ready = self.instances.iter().find(|(id, i)| !i.returned && i.exit.is_some()
                && !self.activations.values().any(|a| a.instance_id == **id && !a.status.settled()))
                .map(|(id, _)| *id);
            let Some(id) = ready else { break; };
            let instance = self.instances.get_mut(&id).ok_or_else(|| invalid("unknown returning instance"))?;
            if instance.budget.reserved() != 0 {
                return Err(invalid("settled child still owns reservations"));
            }
            instance.returned = true;
            let (outcome, output) = instance.exit.clone().ok_or_else(|| invalid("return without exit"))?;
            let spent = instance.budget.spent();
            let Some(parent_id) = instance.parent_activation else { continue; };
            let parent = self.activations[&parent_id].clone();
            let continuation_parents: Vec<_> = self.activations.values()
                .filter(|a| a.instance_id == id && a.status == Status::Completed)
                .map(|a| a.activation_id).collect();
            let settlement = self.instances.get_mut(&parent.instance_id).ok_or_else(|| invalid("unknown parent"))?
                .budget.settle(parent_id, spent)?;
            self.complete_internal(parent_id, output.clone())?;
            self.activations.get_mut(&parent_id).ok_or_else(|| invalid("unknown parent activation"))?
                .continuation_parents = continuation_parents;
            if settlement == CircuitWorkSettlementV2::Overrun {
                self.stop(definition, Stop::WorkBudget)?;
                continue;
            }
            if parent.cancel_requested || self.instances[&parent.instance_id].exit.is_some() {
                continue;
            }
            if outcome != CircuitExitV2::Succeeded {
                self.fallback_instance(definition, parent.instance_id, output)?;
                continue;
            }
            let program = definition.program(&self.instances[&parent.instance_id].program_id)?;
            let edges: Vec<_> = program.edges.iter().filter(|e| e.from == parent.node_id)
                .map(|e| e.edge_id.clone()).collect();
            self.route(definition, parent_id, &edges)?;
        }
        Ok(())
    }
}
