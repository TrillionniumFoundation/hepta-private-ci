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
    execute(
        candidate,
        event,
        profile,
        candidate.entry_node.clone(),
        RuntimeAccumulator::default(),
        decision_cell,
        organ_port,
        wait_port,
        cancellation,
    )
}

/// Resume a previously committed pending Wait boundary. The checkpoint is
/// validated against the exact circuit, event and runtime profile before a port
/// is contacted. Decision and organ work already represented by the checkpoint
/// is never re-executed.
pub fn resume_neural_circuit_v1<D, O, W, C>(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    checkpoint: &CircuitRuntimeCheckpointV1,
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
    validate_checkpoint(candidate, event, profile, checkpoint)?;
    let node = candidate
        .nodes
        .iter()
        .find(|node| node.node_id == checkpoint.node_id)
        .ok_or_else(|| {
            NeuralCircuitRuntimeError::Invalid(
                "checkpoint node is absent from the admitted circuit".to_string(),
            )
        })?;
    if node.role != CircuitNodeRoleV1::WaitJoin {
        return Err(NeuralCircuitRuntimeError::Invalid(
            "generic circuit resume is permitted only at a pending Wait boundary".to_string(),
        ));
    }
    execute(
        candidate,
        event,
        profile,
        checkpoint.node_id.clone(),
        accumulator_from_checkpoint(checkpoint),
        decision_cell,
        organ_port,
        wait_port,
        cancellation,
    )
}

/// Continue after the existing authorized-effect owner has supplied a terminal
/// effect observation. The runtime does not dispatch the effect and cannot turn
/// an unknown result into success or failure.
pub fn resume_neural_circuit_after_effect_v1<D, O, W, C>(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    checkpoint: &CircuitRuntimeCheckpointV1,
    resolution: &CircuitEffectResolutionV1,
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
    validate_checkpoint(candidate, event, profile, checkpoint)?;
    validate_digest(&resolution.observation_digest, "effect observation digest")?;
    let nodes = node_map(candidate);
    let node = nodes
        .get(checkpoint.node_id.as_str())
        .copied()
        .ok_or_else(|| {
            NeuralCircuitRuntimeError::Invalid(
                "effect checkpoint node is absent from the admitted circuit".to_string(),
            )
        })?;
    if node.role != CircuitNodeRoleV1::Effect {
        return Err(NeuralCircuitRuntimeError::Invalid(
            "effect resolution does not match an Effect checkpoint".to_string(),
        ));
    }
    let outgoing = outgoing_map(candidate);
    let next = effect_successor(&nodes, &outgoing, &checkpoint.node_id, resolution.state)?;
    let mut accumulator = accumulator_from_checkpoint(checkpoint);
    charge(&mut accumulator, profile, resolution.cost_units)?;
    accumulator.observation_digests.push(digest_value(
        b"hepta.neural-circuit.effect-observation.v1\0",
        &(&checkpoint.node_id, resolution),
    )?);
    transition(&mut accumulator, profile)?;
    execute(
        candidate,
        event,
        profile,
        next,
        accumulator,
        decision_cell,
        organ_port,
        wait_port,
        cancellation,
    )
}

/// Return the recoverable checkpoint carried by a Wait or Effect boundary.
/// Terminal outcomes intentionally have no continuation checkpoint.
pub fn checkpoint_for_circuit_outcome_v1(
    outcome: &CircuitRuntimeOutcomeV1,
) -> Result<Option<CircuitRuntimeCheckpointV1>, NeuralCircuitRuntimeError> {
    match outcome {
        CircuitRuntimeOutcomeV1::Terminal(_) => Ok(None),
        CircuitRuntimeOutcomeV1::WaitPending(boundary) => {
            checkpoint_from_trace(&boundary.node_id, &boundary.trace).map(Some)
        }
        CircuitRuntimeOutcomeV1::EffectPending(boundary) => {
            checkpoint_from_trace(&boundary.node_id, &boundary.trace).map(Some)
        }
    }
}

pub fn runtime_profile_digest_v1(
    profile: &CircuitRuntimeProfileV1,
) -> Result<Sha256Digest, NeuralCircuitRuntimeError> {
    profile.validate()?;
    digest_value(b"hepta.neural-circuit.runtime-profile.v1\0", profile)
}

pub fn circuit_runtime_outcome_digest_v1(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    outcome: &CircuitRuntimeOutcomeV1,
) -> Result<Sha256Digest, NeuralCircuitRuntimeError> {
    validate_circuit_runtime_outcome_v1(candidate, event, profile, outcome)?;
    digest_value(b"hepta.neural-circuit.runtime-outcome.v1\0", outcome)
}

pub fn validate_circuit_runtime_outcome_v1(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    outcome: &CircuitRuntimeOutcomeV1,
) -> Result<(), NeuralCircuitRuntimeError> {
    candidate.validate()?;
    event.validate()?;
    profile.validate()?;
    validate_trace(candidate, event, profile, outcome.trace())?;
    let nodes = node_map(candidate);
    match outcome {
        CircuitRuntimeOutcomeV1::Terminal(receipt) => {
            validate_text(&receipt.terminal_node_id, "terminal_node_id", 256)?;
            let node = nodes
                .get(receipt.terminal_node_id.as_str())
                .copied()
                .ok_or_else(|| {
                    NeuralCircuitRuntimeError::Invalid(
                        "terminal receipt node is absent from the admitted circuit".to_string(),
                    )
                })?;
            let role_matches = match receipt.state {
                CircuitTerminalStateV1::Succeeded => node.role == CircuitNodeRoleV1::ExitSuccess,
                CircuitTerminalStateV1::Failed => node.role == CircuitNodeRoleV1::ExitFailure,
                CircuitTerminalStateV1::Cancelled => true,
            };
            if !role_matches {
                return Err(NeuralCircuitRuntimeError::Invalid(
                    "terminal state does not match the admitted terminal node".to_string(),
                ));
            }
            let expected = digest_value(
                b"hepta.neural-circuit.terminal-receipt.v1\0",
                &(
                    &receipt.terminal_node_id,
                    receipt.state,
                    &receipt.trace.trace_digest,
                ),
            )?;
            if receipt.receipt_digest != expected {
                return Err(NeuralCircuitRuntimeError::Invalid(
                    "terminal receipt digest mismatch".to_string(),
                ));
            }
        }
        CircuitRuntimeOutcomeV1::WaitPending(boundary) => {
            let node = nodes
                .get(boundary.node_id.as_str())
                .copied()
                .ok_or_else(|| {
                    NeuralCircuitRuntimeError::Invalid(
                        "wait boundary node is absent from the admitted circuit".to_string(),
                    )
                })?;
            if node.role != CircuitNodeRoleV1::WaitJoin {
                return Err(NeuralCircuitRuntimeError::Invalid(
                    "wait boundary is not bound to a Wait node".to_string(),
                ));
            }
            validate_digest(&boundary.observation_digest, "wait observation digest")?;
            let expected = digest_value(
                b"hepta.neural-circuit.wait-boundary.v1\0",
                &(
                    &boundary.node_id,
                    &boundary.observation_digest,
                    &boundary.trace.trace_digest,
                ),
            )?;
            if boundary.boundary_digest != expected {
                return Err(NeuralCircuitRuntimeError::Invalid(
                    "wait boundary digest mismatch".to_string(),
                ));
            }
        }
        CircuitRuntimeOutcomeV1::EffectPending(boundary) => {
            let node = nodes
                .get(boundary.node_id.as_str())
                .copied()
                .ok_or_else(|| {
                    NeuralCircuitRuntimeError::Invalid(
                        "effect boundary node is absent from the admitted circuit".to_string(),
                    )
                })?;
            if node.role != CircuitNodeRoleV1::Effect
                || node.capability.as_deref() != Some(boundary.capability.as_str())
                || node.idempotency_template.as_deref()
                    != Some(boundary.idempotency_template.as_str())
            {
                return Err(NeuralCircuitRuntimeError::Invalid(
                    "effect boundary differs from the admitted Effect node".to_string(),
                ));
            }
            let expected = digest_value(
                b"hepta.neural-circuit.effect-boundary.v1\0",
                &(
                    &boundary.node_id,
                    &boundary.capability,
                    &boundary.idempotency_template,
                    &boundary.trace.trace_digest,
                ),
            )?;
            if boundary.boundary_digest != expected {
                return Err(NeuralCircuitRuntimeError::Invalid(
                    "effect boundary digest mismatch".to_string(),
                ));
            }
        }
    }
    Ok(())
}

fn execute<D, O, W, C>(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    mut current: String,
    mut accumulator: RuntimeAccumulator,
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
    let nodes = node_map(candidate);
    let outgoing = outgoing_map(candidate);

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
                current = sole_successor(&outgoing, &current)?;
                transition(&mut accumulator, profile)?;
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
                        current = next_node;
                        transition(&mut accumulator, profile)?;
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
                current = sole_successor(&outgoing, &current)?;
                transition(&mut accumulator, profile)?;
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
                current = sole_successor(&outgoing, &current)?;
                transition(&mut accumulator, profile)?;
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

fn node_map(candidate: &NeuralCircuitCandidateV1) -> BTreeMap<&str, &CircuitNodeV1> {
    candidate
        .nodes
        .iter()
        .map(|node| (node.node_id.as_str(), node))
        .collect()
}

fn outgoing_map(candidate: &NeuralCircuitCandidateV1) -> BTreeMap<&str, Vec<&str>> {
    let mut outgoing: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
    for edge in &candidate.edges {
        outgoing
            .entry(edge.from.as_str())
            .or_default()
            .push(edge.to.as_str());
    }
    outgoing
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

fn effect_successor(
    nodes: &BTreeMap<&str, &CircuitNodeV1>,
    outgoing: &BTreeMap<&str, Vec<&str>>,
    node_id: &str,
    state: CircuitEffectResolutionStateV1,
) -> Result<String, NeuralCircuitRuntimeError> {
    let expected_role = match state {
        CircuitEffectResolutionStateV1::Succeeded => CircuitNodeRoleV1::ExitSuccess,
        CircuitEffectResolutionStateV1::Failed => CircuitNodeRoleV1::ExitFailure,
    };
    let matches = outgoing
        .get(node_id)
        .into_iter()
        .flatten()
        .filter(|successor| {
            nodes
                .get(**successor)
                .is_some_and(|node| node.role == expected_role)
        })
        .copied()
        .collect::<Vec<_>>();
    if matches.len() != 1 {
        return Err(NeuralCircuitRuntimeError::Invalid(
            "Effect continuation requires exactly one direct success and failure terminal edge"
                .to_string(),
        ));
    }
    Ok(matches[0].to_string())
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
        &(request, kind, &selected_node, &source_decision_digest),
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
    let runtime_profile_digest = runtime_profile_digest_v1(profile)?;
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

fn validate_trace(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    trace: &CircuitRuntimeTraceV1,
) -> Result<(), NeuralCircuitRuntimeError> {
    if trace.event_digest != event.event_digest
        || trace.circuit_digest != candidate.circuit_digest
        || trace.runtime_profile_digest != runtime_profile_digest_v1(profile)?
        || trace.steps > profile.max_steps
        || trace.depth > profile.max_depth
        || trace.consumed_cost_units > profile.cost_budget_units
    {
        return Err(NeuralCircuitRuntimeError::Invalid(
            "runtime trace differs from the admitted event, circuit or profile".to_string(),
        ));
    }
    for choice in &trace.recorded_choices {
        if choice.activation == 0 || choice.feedback_round > profile.max_feedback_rounds {
            return Err(NeuralCircuitRuntimeError::Invalid(
                "recorded choice activation is outside the admitted profile".to_string(),
            ));
        }
        validate_text(&choice.node_id, "choice node_id", 256)?;
        validate_text(&choice.selected_node, "choice selected_node", 256)?;
        validate_digest(&choice.source_decision_digest, "choice source digest")?;
        validate_digest(&choice.receipt_digest, "choice receipt digest")?;
    }
    for digest in &trace.observation_digests {
        validate_digest(digest, "runtime observation digest")?;
    }
    let expected = digest_value(
        b"hepta.neural-circuit.runtime-trace.v1\0",
        &(
            &trace.event_digest,
            &trace.circuit_digest,
            &trace.runtime_profile_digest,
            trace.steps,
            trace.depth,
            trace.consumed_cost_units,
            &trace.recorded_choices,
            &trace.observation_digests,
        ),
    )?;
    if trace.trace_digest != expected {
        return Err(NeuralCircuitRuntimeError::Invalid(
            "runtime trace digest mismatch".to_string(),
        ));
    }
    Ok(())
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

fn checkpoint_from_trace(
    node_id: &str,
    trace: &CircuitRuntimeTraceV1,
) -> Result<CircuitRuntimeCheckpointV1, NeuralCircuitRuntimeError> {
    validate_text(node_id, "checkpoint node_id", 256)?;
    let decision_activations = trace
        .recorded_choices
        .iter()
        .map(|choice| choice.activation)
        .max()
        .unwrap_or(0);
    let mut checkpoint = CircuitRuntimeCheckpointV1 {
        event_digest: trace.event_digest.clone(),
        circuit_digest: trace.circuit_digest.clone(),
        runtime_profile_digest: trace.runtime_profile_digest.clone(),
        node_id: node_id.to_string(),
        steps: trace.steps,
        depth: trace.depth,
        consumed_cost_units: trace.consumed_cost_units,
        feedback_round: 0,
        decision_activations,
        recorded_choices: trace.recorded_choices.clone(),
        observation_digests: trace.observation_digests.clone(),
        checkpoint_digest: Sha256Digest::for_bytes(b"uncomputed-neural-circuit-checkpoint-v1"),
    };
    checkpoint.checkpoint_digest = checkpoint_digest(&checkpoint)?;
    Ok(checkpoint)
}

fn validate_checkpoint(
    candidate: &NeuralCircuitCandidateV1,
    event: &CircuitEventIngressV1,
    profile: &CircuitRuntimeProfileV1,
    checkpoint: &CircuitRuntimeCheckpointV1,
) -> Result<(), NeuralCircuitRuntimeError> {
    candidate.validate()?;
    event.validate()?;
    profile.validate()?;
    validate_text(&checkpoint.node_id, "checkpoint node_id", 256)?;
    if checkpoint.event_digest != event.event_digest
        || checkpoint.circuit_digest != candidate.circuit_digest
        || checkpoint.runtime_profile_digest != runtime_profile_digest_v1(profile)?
        || checkpoint.steps > profile.max_steps
        || checkpoint.depth > profile.max_depth
        || checkpoint.consumed_cost_units > profile.cost_budget_units
        || checkpoint.feedback_round > profile.max_feedback_rounds
        || checkpoint.decision_activations
            != checkpoint
                .recorded_choices
                .iter()
                .map(|choice| choice.activation)
                .max()
                .unwrap_or(0)
        || checkpoint.checkpoint_digest != checkpoint_digest(checkpoint)?
    {
        return Err(NeuralCircuitRuntimeError::Invalid(
            "runtime checkpoint differs from the admitted execution".to_string(),
        ));
    }
    if !candidate
        .nodes
        .iter()
        .any(|node| node.node_id == checkpoint.node_id)
    {
        return Err(NeuralCircuitRuntimeError::Invalid(
            "runtime checkpoint node is absent from the admitted circuit".to_string(),
        ));
    }
    for choice in &checkpoint.recorded_choices {
        validate_digest(
            &choice.source_decision_digest,
            "checkpoint choice source digest",
        )?;
        validate_digest(&choice.receipt_digest, "checkpoint choice receipt digest")?;
    }
    for digest in &checkpoint.observation_digests {
        validate_digest(digest, "checkpoint observation digest")?;
    }
    Ok(())
}

fn checkpoint_digest(
    checkpoint: &CircuitRuntimeCheckpointV1,
) -> Result<Sha256Digest, NeuralCircuitRuntimeError> {
    digest_value(
        b"hepta.neural-circuit.runtime-checkpoint.v1\0",
        &(
            &checkpoint.event_digest,
            &checkpoint.circuit_digest,
            &checkpoint.runtime_profile_digest,
            &checkpoint.node_id,
            checkpoint.steps,
            checkpoint.depth,
            checkpoint.consumed_cost_units,
            checkpoint.feedback_round,
            checkpoint.decision_activations,
            &checkpoint.recorded_choices,
            &checkpoint.observation_digests,
        ),
    )
}

fn accumulator_from_checkpoint(checkpoint: &CircuitRuntimeCheckpointV1) -> RuntimeAccumulator {
    RuntimeAccumulator {
        steps: checkpoint.steps,
        depth: checkpoint.depth,
        consumed_cost_units: checkpoint.consumed_cost_units,
        feedback_round: checkpoint.feedback_round,
        decision_activations: checkpoint.decision_activations,
        recorded_choices: checkpoint.recorded_choices.clone(),
        observation_digests: checkpoint.observation_digests.clone(),
    }
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
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || value.bytes().all(|byte| byte == b'0')
    {
        return Err(NeuralCircuitRuntimeError::Invalid(format!(
            "{field} must be a non-zero lowercase sha256"
        )));
    }
    Ok(())
}
