use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;

use crate::CircuitNodeRoleV1;
use crate::CircuitNodeV1;
use crate::NeuralCircuitCandidateV1;

use super::types::*;

/// Execute one circuit activation until it reaches a terminal, pending wait or
/// external-effect boundary. Effects are deliberately returned to the existing
/// final-use-authorized TaskFlow seam instead of being executed here.
pub fn run_neural_circuit_v1<D, O, W, C>(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    decision_cell: &mut D,
    organ_port: &mut O,
    wait_port: &mut W,
    cancellation: &C,
) -> Result<CircuitRuntimeOutcomeV1, NeuralCircuitRuntimeError>
where
    D: CircuitDecisionCellV1,
    O: CircuitOrganPortV1,
    W: CircuitWaitJoinPortV1,
    C: CircuitCancellationV1,
{
    candidate.validate()?;
    profile.validate()?;
    event.validate()?;

    let nodes: BTreeMap<&str, &CircuitNodeV1> = candidate
        .nodes
        .iter()
        .map(|node| (node.node_id.as_str(), node))
        .collect();
    let mut outgoing: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
    for edge in &candidate.edges {
        outgoing
            .entry(edge.from.as_str())
            .or_default()
            .push(edge.to.as_str());
    }

    let mut current = candidate.entry_node.clone();
    let mut accumulator = RuntimeAccumulator::default();

    loop {
        if cancellation.is_cancelled() {
            return Ok(CircuitRuntimeOutcomeV1::Terminal(terminal_receipt(
                candidate,
                event,
                profile,
                &current,
                CircuitTerminalStateV1::Cancelled,
                accumulator,
            )?));
        }
        accumulator.steps = accumulator
            .steps
            .checked_add(1)
            .ok_or(NeuralCircuitRuntimeError::StepBudgetExhausted)?;
        if accumulator.steps > profile.max_steps {
            return Err(NeuralCircuitRuntimeError::StepBudgetExhausted);
        }
        let node = nodes.get(current.as_str()).copied().ok_or_else(|| {
            NeuralCircuitRuntimeError::Invalid(format!(
                "runtime node {current} is absent from the admitted circuit"
            ))
        })?;

        match node.role {
            CircuitNodeRoleV1::Observe | CircuitNodeRoleV1::TransformGuard => {
                let next = sole_successor(&outgoing, &current)?;
                transition(&mut current, next, &mut accumulator, profile)?;
            }
            CircuitNodeRoleV1::Decide => {
                accumulator.decision_activations = accumulator
                    .decision_activations
                    .checked_add(1)
                    .ok_or(NeuralCircuitRuntimeError::StepBudgetExhausted)?;
                let request = CircuitDecisionRequestV1 {
                    circuit_id: candidate.circuit_id.clone(),
                    circuit_digest: candidate.circuit_digest.clone(),
                    event_digest: event.event_digest.clone(),
                    node_id: current.clone(),
                    activation: accumulator.decision_activations,
                    feedback_round: accumulator.feedback_round,
                    remaining_cost_units: remaining_cost(profile, &accumulator),
                };
                match decision_cell.decide(&request)? {
                    CircuitDecisionV1::Route {
                        next_node,
                        cost_units,
                        decision_digest,
                    } => {
                        validate_digest(&decision_digest, "decision_digest")?;
                        ensure_admitted_route(&outgoing, &current, &next_node)?;
                        charge(&mut accumulator, profile, cost_units)?;
                        let choice = recorded_choice(
                            &request,
                            CircuitChoiceKindV1::Route,
                            next_node.clone(),
                            decision_digest,
                        )?;
                        accumulator.recorded_choices.push(choice);
                        accumulator.feedback_round = 0;
                        transition(&mut current, next_node, &mut accumulator, profile)?;
                    }
                    CircuitDecisionV1::Feedback {
                        feedback_digest,
                        cost_units,
                    } => {
                        validate_digest(&feedback_digest, "feedback_digest")?;
                        if accumulator.feedback_round >= profile.max_feedback_rounds {
                            return Err(NeuralCircuitRuntimeError::FeedbackBudgetExhausted);
                        }
                        charge(&mut accumulator, profile, cost_units)?;
                        let choice = recorded_choice(
                            &request,
                            CircuitChoiceKindV1::Feedback,
                            current.clone(),
                            feedback_digest,
                        )?;
                        accumulator.recorded_choices.push(choice);
                        accumulator.feedback_round = accumulator
                            .feedback_round
                            .checked_add(1)
                            .ok_or(NeuralCircuitRuntimeError::FeedbackBudgetExhausted)?;
                    }
                }
            }
            CircuitNodeRoleV1::OrganCall => {
                let capability = node.capability.clone().ok_or_else(|| {
                    NeuralCircuitRuntimeError::Invalid(format!(
                        "organ node {} has no admitted capability",
                        node.node_id
                    ))
                })?;
                let request = CircuitOrganRequestV1 {
                    circuit_id: candidate.circuit_id.clone(),
                    circuit_digest: candidate.circuit_digest.clone(),
                    event_digest: event.event_digest.clone(),
                    node_id: current.clone(),
                    capability,
                    remaining_cost_units: remaining_cost(profile, &accumulator),
                };
                let receipt = organ_port.call(&request)?;
                validate_digest(&receipt.output_digest, "organ output digest")?;
                charge(&mut accumulator, profile, receipt.cost_units)?;
                accumulator.observation_digests.push(digest_value(
                    b"hepta.neural-circuit.organ-observation.v1\0",
                    &(&request, &receipt),
                )?);
                let next = sole_successor(&outgoing, &current)?;
                transition(&mut current, next, &mut accumulator, profile)?;
            }
            CircuitNodeRoleV1::WaitJoin => {
                let request = CircuitWaitRequestV1 {
                    circuit_id: candidate.circuit_id.clone(),
                    circuit_digest: candidate.circuit_digest.clone(),
                    event_digest: event.event_digest.clone(),
                    node_id: current.clone(),
                    timeout_ms: node.wait_timeout_ms,
                    remaining_cost_units: remaining_cost(profile, &accumulator),
                };
                let receipt = wait_port.wait(&request)?;
                validate_digest(&receipt.observation_digest, "wait observation digest")?;
                charge(&mut accumulator, profile, receipt.cost_units)?;
                let observation_digest = digest_value(
                    b"hepta.neural-circuit.wait-observation.v1\0",
                    &(&request, &receipt),
                )?;
                accumulator
                    .observation_digests
                    .push(observation_digest.clone());
                if receipt.state == CircuitWaitStateV1::Pending {
                    let trace = runtime_trace(candidate, event, profile, accumulator)?;
                    let boundary_digest = digest_value(
                        b"hepta.neural-circuit.wait-boundary.v1\0",
                        &(&current, &observation_digest, &trace.trace_digest),
                    )?;
                    return Ok(CircuitRuntimeOutcomeV1::WaitPending(
                        CircuitWaitBoundaryV1 {
                            node_id: current,
                            observation_digest,
                            trace,
                            boundary_digest,
                        },
                    ));
                }
                let next = sole_successor(&outgoing, &current)?;
                transition(&mut current, next, &mut accumulator, profile)?;
            }
            CircuitNodeRoleV1::Effect => {
                let capability = node.capability.clone().ok_or_else(|| {
                    NeuralCircuitRuntimeError::Invalid(format!(
                        "effect node {} has no capability",
                        node.node_id
                    ))
                })?;
                let idempotency_template = node.idempotency_template.clone().ok_or_else(|| {
                    NeuralCircuitRuntimeError::Invalid(format!(
                        "effect node {} has no idempotency template",
                        node.node_id
                    ))
                })?;
                let trace = runtime_trace(candidate, event, profile, accumulator)?;
                let boundary_digest = digest_value(
                    b"hepta.neural-circuit.effect-boundary.v1\0",
                    &(
                        &current,
                        &capability,
                        &idempotency_template,
                        &trace.trace_digest,
                    ),
                )?;
                return Ok(CircuitRuntimeOutcomeV1::EffectPending(
                    CircuitEffectBoundaryV1 {
                        node_id: current,
                        capability,
                        idempotency_template,
                        trace,
                        boundary_digest,
                    },
                ));
            }
            CircuitNodeRoleV1::ExitSuccess => {
                return Ok(CircuitRuntimeOutcomeV1::Terminal(terminal_receipt(
                    candidate,
                    event,
                    profile,
                    &current,
                    CircuitTerminalStateV1::Succeeded,
                    accumulator,
                )?));
            }
            CircuitNodeRoleV1::ExitFailure => {
                return Ok(CircuitRuntimeOutcomeV1::Terminal(terminal_receipt(
                    candidate,
                    event,
                    profile,
                    &current,
                    CircuitTerminalStateV1::Failed,
                    accumulator,
                )?));
            }
        }
    }
}

fn remaining_cost(profile: &CircuitRuntimeProfileV1, accumulator: &RuntimeAccumulator) -> u64 {
    profile
        .cost_budget_units
        .saturating_sub(accumulator.consumed_cost_units)
}

fn charge(
    accumulator: &mut RuntimeAccumulator,
    profile: &CircuitRuntimeProfileV1,
    cost_units: u64,
) -> Result<(), NeuralCircuitRuntimeError> {
    let next = accumulator
        .consumed_cost_units
        .checked_add(cost_units)
        .ok_or(NeuralCircuitRuntimeError::CostBudgetExhausted)?;
    if next > profile.cost_budget_units {
        return Err(NeuralCircuitRuntimeError::CostBudgetExhausted);
    }
    accumulator.consumed_cost_units = next;
    Ok(())
}

fn transition(
    current: &mut String,
    next: String,
    accumulator: &mut RuntimeAccumulator,
    profile: &CircuitRuntimeProfileV1,
) -> Result<(), NeuralCircuitRuntimeError> {
    let depth = accumulator
        .depth
        .checked_add(1)
        .ok_or(NeuralCircuitRuntimeError::DepthBudgetExhausted)?;
    if depth > profile.max_depth {
        return Err(NeuralCircuitRuntimeError::DepthBudgetExhausted);
    }
    accumulator.depth = depth;
    *current = next;
    Ok(())
}

fn sole_successor(
    outgoing: &BTreeMap<&str, Vec<&str>>,
    node_id: &str,
) -> Result<String, NeuralCircuitRuntimeError> {
    let Some(successors) = outgoing.get(node_id) else {
        return Err(NeuralCircuitRuntimeError::Invalid(format!(
            "non-terminal node {node_id} has no successor"
        )));
    };
    if successors.len() != 1 {
        return Err(NeuralCircuitRuntimeError::Invalid(format!(
            "non-decision node {node_id} must have exactly one successor"
        )));
    }
    Ok(successors[0].to_string())
}

fn ensure_admitted_route(
    outgoing: &BTreeMap<&str, Vec<&str>>,
    node_id: &str,
    next_node: &str,
) -> Result<(), NeuralCircuitRuntimeError> {
    if outgoing
        .get(node_id)
        .is_some_and(|successors| successors.contains(&next_node))
    {
        Ok(())
    } else {
        Err(NeuralCircuitRuntimeError::Invalid(format!(
            "DecisionCell route {node_id}->{next_node} is not admitted"
        )))
    }
}

fn recorded_choice(
    request: &CircuitDecisionRequestV1,
    kind: CircuitChoiceKindV1,
    selected_node: String,
    source_decision_digest: Sha256Digest,
) -> Result<CircuitRecordedChoiceV1, NeuralCircuitRuntimeError> {
    let receipt_digest = digest_value(
        b"hepta.neural-circuit.recorded-choice.v1\0",
        &(
            request,
            kind,
            &selected_node,
            &source_decision_digest,
        ),
    )?;
    Ok(CircuitRecordedChoiceV1 {
        activation: request.activation,
        feedback_round: request.feedback_round,
        node_id: request.node_id.clone(),
        selected_node,
        kind,
        source_decision_digest,
        receipt_digest,
    })
}

fn runtime_trace(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    accumulator: RuntimeAccumulator,
) -> Result<CircuitRuntimeTraceV1, NeuralCircuitRuntimeError> {
    let runtime_profile_digest = digest_value(
        b"hepta.neural-circuit.runtime-profile.v1\0",
        profile,
    )?;
    let trace_digest = digest_value(
        b"hepta.neural-circuit.runtime-trace.v1\0",
        &(
            &event.event_digest,
            &candidate.circuit_digest,
            &runtime_profile_digest,
            accumulator.steps,
            accumulator.depth,
            accumulator.consumed_cost_units,
            &accumulator.recorded_choices,
            &accumulator.observation_digests,
        ),
    )?;
    Ok(CircuitRuntimeTraceV1 {
        event_digest: event.event_digest.clone(),
        circuit_digest: candidate.circuit_digest.clone(),
        runtime_profile_digest,
        steps: accumulator.steps,
        depth: accumulator.depth,
        consumed_cost_units: accumulator.consumed_cost_units,
        recorded_choices: accumulator.recorded_choices,
        observation_digests: accumulator.observation_digests,
        trace_digest,
    })
}

fn terminal_receipt(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    terminal_node_id: &str,
    state: CircuitTerminalStateV1,
    accumulator: RuntimeAccumulator,
) -> Result<CircuitTerminalReceiptV1, NeuralCircuitRuntimeError> {
    let trace = runtime_trace(candidate, event, profile, accumulator)?;
    let receipt_digest = digest_value(
        b"hepta.neural-circuit.terminal-receipt.v1\0",
        &(terminal_node_id, state, &trace.trace_digest),
    )?;
    Ok(CircuitTerminalReceiptV1 {
        terminal_node_id: terminal_node_id.to_string(),
        state,
        trace,
        receipt_digest,
    })
}

pub(super) fn digest_value<T: Serialize>(
    domain: &[u8],
    value: &T,
) -> Result<Sha256Digest, NeuralCircuitRuntimeError> {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(&serde_json::to_vec(value).map_err(|error| {
        NeuralCircuitRuntimeError::Invalid(format!("canonical runtime serialization: {error}"))
    })?);
    Ok(Sha256Digest::for_bytes(&bytes))
}

pub(super) fn validate_text(
    value: &str,
    field: &str,
    max_bytes: usize,
) -> Result<(), NeuralCircuitRuntimeError> {
    if value.is_empty() || value.len() > max_bytes || value.chars().any(char::is_control) {
        return Err(NeuralCircuitRuntimeError::Invalid(format!(
            "{field} is invalid"
        )));
    }
    Ok(())
}

pub(super) fn validate_digest(
    digest: &Sha256Digest,
    field: &str,
) -> Result<(), NeuralCircuitRuntimeError> {
    let value = digest.as_str();
    if value.len() != 64 || value.bytes().all(|byte| byte == b'0') {
        return Err(NeuralCircuitRuntimeError::Invalid(format!(
            "{field} must be a non-zero sha256"
        )));
    }
    Ok(())
}