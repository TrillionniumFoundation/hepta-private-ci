//! Frozen Circuit-to-Cell routing. A registry shares one inference/state owner
//! across its cells; it never installs bundles or grants tool/effect authority.

use std::collections::BTreeSet;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_automation::CircuitExitV2;
use codex_hepta_automation::CircuitNodeKindV2;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_neuron::CellCandidateKindV1;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_types::StableId;

use crate::CircuitCellErrorV1;
use crate::circuit_cell_output::circuit_cell_output_schema_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitCellRouteV1 {
    pub candidate_id: StableId,
    pub outcome: CircuitExitV2,
    pub selected_edges: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitCellBindingV1 {
    pub program_id: String,
    pub node_id: String,
    pub cell: CellDefinitionV1,
    /// Exactly the Cell's canonical candidate order, including abstention.
    pub routes: Vec<CircuitCellRouteV1>,
}

/// Validated once against an immutable circuit definition. There are no mutable
/// getters: changing a route, model, encoder or calibration creates a new pin.
pub struct CircuitCellRegistryV1 {
    definition: BoundedCircuitDefinitionV2,
    definition_digest: Sha256Digest,
    bindings: Vec<CircuitCellBindingV1>,
}

impl CircuitCellRegistryV1 {
    pub fn new(
        definition: BoundedCircuitDefinitionV2,
        bindings: Vec<CircuitCellBindingV1>,
    ) -> Result<Self, CircuitCellErrorV1> {
        let definition_digest = definition.definition_digest()
            .map_err(|_| CircuitCellErrorV1::InvalidBinding)?;
        if definition.route_policy_digest != circuit_cell_route_policy_digest_v1(&bindings)? {
            return Err(CircuitCellErrorV1::InvalidBinding);
        }
        let mut keys = BTreeSet::new();
        for binding in &bindings {
            if !keys.insert((binding.program_id.as_str(), binding.node_id.as_str())) {
                return Err(CircuitCellErrorV1::InvalidBinding);
            }
            let program = definition.programs.iter()
                .find(|program| program.program_id == binding.program_id)
                .ok_or(CircuitCellErrorV1::InvalidBinding)?;
            let node = program.nodes.iter().find(|node| node.node_id == binding.node_id)
                .ok_or(CircuitCellErrorV1::InvalidBinding)?;
            let (max_work, decide) = match node.kind {
                CircuitNodeKindV2::Compute { max_work } => (max_work, false),
                CircuitNodeKindV2::Decide { max_work } => (max_work, true),
                _ => return Err(CircuitCellErrorV1::InvalidBinding),
            };
            // Work has one explicit unit. Memory and queue metrics remain in
            // the output receipt and are never added to microseconds.
            if max_work < binding.cell.runtime.resource_envelope.p99_latency_micros
                || definition.parameter_bundle_digest.as_str() != binding.cell.bundle_digest.to_string()
                || node.output_schema != circuit_cell_output_schema_v1()
                || binding.routes.len() != binding.cell.candidates.len()
            {
                return Err(CircuitCellErrorV1::InvalidBinding);
            }
            let edges: Vec<_> = program.edges.iter().filter(|edge| edge.from == node.node_id)
                .map(|edge| edge.edge_id.clone()).collect();
            for (route, candidate) in binding.routes.iter().zip(&binding.cell.candidates) {
                if route.candidate_id != candidate.candidate_id
                    || (candidate.kind == CellCandidateKindV1::Abstain
                        && route.outcome != CircuitExitV2::Abstained)
                {
                    return Err(CircuitCellErrorV1::InvalidBinding);
                }
                if route.outcome == CircuitExitV2::Succeeded {
                    if (decide && (route.selected_edges.len() != 1
                        || !edges.contains(&route.selected_edges[0])))
                        || (!decide && route.selected_edges != edges)
                    {
                        return Err(CircuitCellErrorV1::InvalidBinding);
                    }
                } else if !route.selected_edges.is_empty() {
                    return Err(CircuitCellErrorV1::InvalidBinding);
                }
            }
        }
        let computations = definition.programs.iter().flat_map(|program| &program.nodes)
            .filter(|node| matches!(node.kind,
                CircuitNodeKindV2::Compute { .. } | CircuitNodeKindV2::Decide { .. })).count();
        if computations != bindings.len() {
            return Err(CircuitCellErrorV1::InvalidBinding);
        }
        Ok(Self { definition, definition_digest, bindings })
    }

    pub fn definition(&self) -> &BoundedCircuitDefinitionV2 { &self.definition }
    pub fn definition_digest(&self) -> &Sha256Digest { &self.definition_digest }

    pub(super) fn bind_input(
        &self,
        dispatch: &CircuitDispatchV2,
        input: &CellStepInputV1,
    ) -> Result<&CircuitCellBindingV1, CircuitCellErrorV1> {
        let binding = self.bindings.iter().find(|binding|
            binding.program_id == dispatch.program_id && binding.node_id == dispatch.node_id)
            .ok_or(CircuitCellErrorV1::InvalidBinding)?;
        let program = self.definition.programs.iter().find(|program| program.program_id == dispatch.program_id)
            .ok_or(CircuitCellErrorV1::InvalidBinding)?;
        let node = program.nodes.iter().find(|node| node.node_id == dispatch.node_id)
            .ok_or(CircuitCellErrorV1::InvalidBinding)?;
        let max_work = match node.kind {
            CircuitNodeKindV2::Compute { max_work } | CircuitNodeKindV2::Decide { max_work } => max_work,
            _ => return Err(CircuitCellErrorV1::InvalidBinding),
        };
        let candidates: Vec<_> = program.edges.iter().filter(|edge| edge.from == node.node_id)
            .map(|edge| edge.edge_id.clone()).collect();
        if dispatch.route_policy_digest != self.definition.route_policy_digest
            || dispatch.parameter_bundle_digest != self.definition.parameter_bundle_digest
            || dispatch.input_schema != node.input_schema || dispatch.output_schema != node.output_schema
            || dispatch.max_work != max_work || dispatch.candidate_edges != candidates
        {
            return Err(CircuitCellErrorV1::InvalidBinding);
        }
        if dispatch.run_id != input.scope.run_id.as_str()
            || input.scope.cell_id != binding.cell.cell_id
            || dispatch.scope_digest != circuit_cell_scope_digest_v1(&input.scope)?
            || input.operation_id != circuit_cell_operation_id_v1(dispatch)?
        {
            return Err(CircuitCellErrorV1::ScopeMismatch);
        }
        if dispatch.input_digest != Sha256Digest::for_bytes(&input.observation) {
            return Err(CircuitCellErrorV1::InputMismatch);
        }
        Ok(binding)
    }
}

/// Pin this value as the Circuit V2 route_policy_digest before constructing its
/// registry. Candidate order is semantic; binding table order is canonicalized.
pub fn circuit_cell_route_policy_digest_v1(
    bindings: &[CircuitCellBindingV1],
) -> Result<Sha256Digest, CircuitCellErrorV1> {
    if bindings.is_empty() || bindings.len() > 256 {
        return Err(CircuitCellErrorV1::InvalidBinding);
    }
    let mut ordered: Vec<_> = bindings.iter().collect();
    ordered.sort_by(|left, right| (&left.program_id, &left.node_id).cmp(&(&right.program_id, &right.node_id)));
    let mut bytes = b"hepta.circuit.cell-route-policy.v1\0model_latency_micros\0".to_vec();
    bytes.extend_from_slice(&(ordered.len() as u32).to_be_bytes());
    let mut previous = None;
    for binding in ordered {
        let key = (binding.program_id.as_str(), binding.node_id.as_str());
        if previous == Some(key)
            || [key.0, key.1].iter().any(|value|
                value.is_empty() || value.len() > 128 || value.chars().any(char::is_control))
            || binding.routes.len() != binding.cell.candidates.len()
        {
            return Err(CircuitCellErrorV1::InvalidBinding);
        }
        previous = Some(key);
        push_text(&mut bytes, &binding.program_id);
        push_text(&mut bytes, &binding.node_id);
        bytes.extend_from_slice(binding.cell.semantic_digest()?.as_array());
        bytes.extend_from_slice(&(binding.routes.len() as u32).to_be_bytes());
        for route in &binding.routes {
            if route.selected_edges.len() > 256
                || route.selected_edges.iter().any(|edge|
                    edge.is_empty() || edge.len() > 128 || edge.chars().any(char::is_control))
            {
                return Err(CircuitCellErrorV1::InvalidBinding);
            }
            push_text(&mut bytes, route.candidate_id.as_str());
            bytes.push(match route.outcome {
                CircuitExitV2::Succeeded => 0,
                CircuitExitV2::Failed => 1,
                CircuitExitV2::Abstained => 2,
            });
            bytes.extend_from_slice(&(route.selected_edges.len() as u32).to_be_bytes());
            for edge in &route.selected_edges { push_text(&mut bytes, edge); }
        }
    }
    Ok(Sha256Digest::for_bytes(&bytes))
}

/// A circuit may visit many cells. The run pin binds agent/run/principal; each
/// node's frozen registry entry separately binds its exact Cell definition.
pub fn circuit_cell_scope_digest_v1(scope: &CellScopeV1) -> Result<Sha256Digest, CircuitCellErrorV1> {
    if scope.principal_digest.is_zero() { return Err(CircuitCellErrorV1::ScopeMismatch); }
    let mut bytes = b"hepta.circuit.cell-run-scope.v1\0".to_vec();
    push_text(&mut bytes, scope.agent_id.as_str());
    push_text(&mut bytes, scope.run_id.as_str());
    bytes.extend_from_slice(scope.principal_digest.as_array());
    Ok(Sha256Digest::for_bytes(&bytes))
}

pub fn circuit_cell_operation_id_v1(dispatch: &CircuitDispatchV2) -> Result<StableId, CircuitCellErrorV1> {
    StableId::new(format!("circuit-cell:{}", dispatch.invocation_digest.as_str()))
        .map_err(|_| CircuitCellErrorV1::InvalidBinding)
}

pub(super) fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
