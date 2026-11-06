//! Deterministic, authority-free NDU graph backup shadow profile.
//!
//! Controlled actions maximize additive task value minus declared resource
//! cost. Chance edges are *expected*, never maximized. Shared descendants are
//! evaluated once per call by exact identity; no model inference, effects,
//! cross-principal state sharing, nonlinear NDU semantics or topology mutation.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

const MAX_SNG_GRAPH_NODES: usize = 256;
const MAX_SNG_GRAPH_EDGES: usize = 1024;
const MAX_SNG_GRAPH_DEPTH: usize = 64;
const MAX_NAME_BYTES: usize = 256;
const MAX_BRANCHES_PER_NODE: usize = 128;
const PROBABILITY_TOLERANCE: f64 = 1e-10;

#[derive(Clone, Debug, PartialEq)]
pub struct SngrActionShadowV1 {
    pub name: String,
    pub successor: String,
    pub compute_cost: f64,
    pub task_reward: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SngrChanceShadowV1 {
    pub successor: String,
    pub probability: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub enum SngrGraphNodeShadowV1 {
    Terminal { utility: f64 },
    Decision { actions: Vec<SngrActionShadowV1> },
    Chance { outcomes: Vec<SngrChanceShadowV1> },
}

#[derive(Clone, Debug, PartialEq)]
pub struct SngrGraphShadowV1 {
    pub root: String,
    pub nodes: BTreeMap<String, SngrGraphNodeShadowV1>,
    pub legal_actions: BTreeSet<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct SngrGraphReceiptShadowV1 {
    pub root_utility: f64,
    pub node_values: BTreeMap<String, f64>,
    pub selected_actions: BTreeMap<String, String>,
    pub unique_evaluated_nodes: usize,
    pub memoized_references: usize,
    /// Synthetic inputs/decisions digest; never an independently observed outcome.
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SngrGraphShadowError {
    GraphSize,
    BadIdentifier,
    MissingRoot,
    MissingSuccessor,
    InvalidBranchCount,
    InvalidCost,
    InvalidProbability,
    DuplicateAction,
    NoLegalAction,
    Cycle,
    Depth,
    NonFinite,
}

impl fmt::Display for SngrGraphShadowError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SngrGraphShadowError {}

fn finite(value: f64) -> Result<f64, SngrGraphShadowError> {
    if value.is_finite() {
        Ok(value)
    } else {
        Err(SngrGraphShadowError::NonFinite)
    }
}

fn validate_name(name: &str) -> Result<(), SngrGraphShadowError> {
    if name.is_empty() || name.len() > MAX_NAME_BYTES {
        Err(SngrGraphShadowError::BadIdentifier)
    } else {
        Ok(())
    }
}

fn validate_shape(graph: &SngrGraphShadowV1) -> Result<(), SngrGraphShadowError> {
    if !(1..=MAX_SNG_GRAPH_NODES).contains(&graph.nodes.len()) {
        return Err(SngrGraphShadowError::GraphSize);
    }
    validate_name(&graph.root)?;
    if !graph.nodes.contains_key(&graph.root) {
        return Err(SngrGraphShadowError::MissingRoot);
    }
    for action in &graph.legal_actions {
        validate_name(action)?;
    }
    let mut edges = 0_usize;
    for (id, node) in &graph.nodes {
        validate_name(id)?;
        match node {
            SngrGraphNodeShadowV1::Terminal { utility } => {
                finite(*utility)?;
            }
            SngrGraphNodeShadowV1::Chance { outcomes } => {
                if outcomes.is_empty() || outcomes.len() > MAX_BRANCHES_PER_NODE {
                    return Err(SngrGraphShadowError::InvalidBranchCount);
                }
                edges = edges.saturating_add(outcomes.len());
                let mut total = 0.0;
                for edge in outcomes {
                    validate_name(&edge.successor)?;
                    if !graph.nodes.contains_key(&edge.successor) {
                        return Err(SngrGraphShadowError::MissingSuccessor);
                    }
                    let probability = finite(edge.probability)?;
                    if !(0.0..=1.0).contains(&probability) {
                        return Err(SngrGraphShadowError::InvalidProbability);
                    }
                    total = finite(total + probability)?;
                }
                if (total - 1.0).abs() > PROBABILITY_TOLERANCE {
                    return Err(SngrGraphShadowError::InvalidProbability);
                }
            }
            SngrGraphNodeShadowV1::Decision { actions } => {
                if actions.is_empty() || actions.len() > MAX_BRANCHES_PER_NODE {
                    return Err(SngrGraphShadowError::InvalidBranchCount);
                }
                edges = edges.saturating_add(actions.len());
                let mut seen = BTreeSet::new();
                for edge in actions {
                    validate_name(&edge.name)?;
                    validate_name(&edge.successor)?;
                    if !graph.nodes.contains_key(&edge.successor) {
                        return Err(SngrGraphShadowError::MissingSuccessor);
                    }
                    if !seen.insert(&edge.name) {
                        return Err(SngrGraphShadowError::DuplicateAction);
                    }
                    if finite(edge.compute_cost)? < 0.0 {
                        return Err(SngrGraphShadowError::InvalidCost);
                    }
                    finite(edge.task_reward)?;
                }
            }
        }
        if edges > MAX_SNG_GRAPH_EDGES {
            return Err(SngrGraphShadowError::GraphSize);
        }
    }
    Ok(())
}

fn successors(node: &SngrGraphNodeShadowV1) -> Vec<&str> {
    match node {
        SngrGraphNodeShadowV1::Terminal { .. } => Vec::new(),
        SngrGraphNodeShadowV1::Chance { outcomes } => outcomes
            .iter()
            .map(|edge| edge.successor.as_str())
            .collect(),
        SngrGraphNodeShadowV1::Decision { actions } => {
            actions.iter().map(|edge| edge.successor.as_str()).collect()
        }
    }
}

fn check_cycle(
    graph: &SngrGraphShadowV1,
    id: &str,
    state: &mut BTreeMap<String, u8>,
    depth: usize,
) -> Result<(), SngrGraphShadowError> {
    if depth > MAX_SNG_GRAPH_DEPTH {
        return Err(SngrGraphShadowError::Depth);
    }
    match state.get(id).copied() {
        Some(1) => return Err(SngrGraphShadowError::Cycle),
        Some(2) => return Ok(()),
        Some(_) | None => {}
    }
    state.insert(id.to_owned(), 1);
    let node = graph
        .nodes
        .get(id)
        .ok_or(SngrGraphShadowError::MissingSuccessor)?;
    for next in successors(node) {
        check_cycle(graph, next, state, depth + 1)?;
    }
    state.insert(id.to_owned(), 2);
    Ok(())
}

fn score(
    graph: &SngrGraphShadowV1,
    id: &str,
    depth: usize,
    values: &mut BTreeMap<String, f64>,
    choices: &mut BTreeMap<String, String>,
    cache_hits: &mut usize,
) -> Result<f64, SngrGraphShadowError> {
    if depth > MAX_SNG_GRAPH_DEPTH {
        return Err(SngrGraphShadowError::Depth);
    }
    if let Some(value) = values.get(id) {
        *cache_hits += 1;
        return Ok(*value);
    }
    let node = graph
        .nodes
        .get(id)
        .ok_or(SngrGraphShadowError::MissingSuccessor)?;
    let value = match node {
        SngrGraphNodeShadowV1::Terminal { utility } => *utility,
        SngrGraphNodeShadowV1::Chance { outcomes } => {
            let mut result = 0.0;
            for edge in outcomes {
                let next = score(
                    graph,
                    &edge.successor,
                    depth + 1,
                    values,
                    choices,
                    cache_hits,
                )?;
                result = finite(result + edge.probability * next)?;
            }
            result
        }
        SngrGraphNodeShadowV1::Decision { actions } => {
            let mut best: Option<(f64, &str)> = None;
            for edge in actions {
                if !graph.legal_actions.contains(&edge.name) {
                    continue;
                }
                let next = score(
                    graph,
                    &edge.successor,
                    depth + 1,
                    values,
                    choices,
                    cache_hits,
                )?;
                let value = finite(edge.task_reward - edge.compute_cost + next)?;
                match best {
                    Some((previous, action))
                        if value < previous
                            || (value == previous && edge.name.as_str() >= action) => {}
                    _ => best = Some((value, edge.name.as_str())),
                }
            }
            let (value, action) = best.ok_or(SngrGraphShadowError::NoLegalAction)?;
            choices.insert(id.to_owned(), action.to_owned());
            value
        }
    };
    let value = finite(value)?;
    values.insert(id.to_owned(), value);
    Ok(value)
}

fn add_name(bytes: &mut Vec<u8>, name: &str) {
    bytes.extend_from_slice(&(name.len() as u64).to_be_bytes());
    bytes.extend_from_slice(name.as_bytes());
}

/// Preflight all declared nodes including unreachable/illegal branches, then
/// value only the reachable legal trace. Never consults a model or effect owner.
pub fn evaluate_sngr_graph_shadow(
    graph: &SngrGraphShadowV1,
) -> Result<SngrGraphReceiptShadowV1, SngrGraphShadowError> {
    validate_shape(graph)?;
    let mut states = BTreeMap::new();
    for id in graph.nodes.keys() {
        check_cycle(graph, id, &mut states, 0)?;
    }
    let mut values = BTreeMap::new();
    let mut choices = BTreeMap::new();
    let mut cache_hits = 0;
    let root_utility = score(
        graph,
        &graph.root,
        0,
        &mut values,
        &mut choices,
        &mut cache_hits,
    )?;

    let mut bytes = b"hepta.ndu.sngr-additive-dag.synthetic.shadow.v1".to_vec();
    add_name(&mut bytes, &graph.root);
    bytes.extend_from_slice(&(graph.legal_actions.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&(graph.nodes.len() as u64).to_be_bytes());
    for legal in &graph.legal_actions {
        add_name(&mut bytes, legal);
    }
    for (id, node) in &graph.nodes {
        add_name(&mut bytes, id);
        match node {
            SngrGraphNodeShadowV1::Terminal { utility } => {
                bytes.push(0);
                bytes.extend_from_slice(&utility.to_bits().to_be_bytes());
            }
            SngrGraphNodeShadowV1::Decision { actions } => {
                bytes.push(1);
                bytes.extend_from_slice(&(actions.len() as u64).to_be_bytes());
                for edge in actions {
                    add_name(&mut bytes, &edge.name);
                    add_name(&mut bytes, &edge.successor);
                    bytes.extend_from_slice(&edge.compute_cost.to_bits().to_be_bytes());
                    bytes.extend_from_slice(&edge.task_reward.to_bits().to_be_bytes());
                }
            }
            SngrGraphNodeShadowV1::Chance { outcomes } => {
                bytes.push(2);
                bytes.extend_from_slice(&(outcomes.len() as u64).to_be_bytes());
                for edge in outcomes {
                    add_name(&mut bytes, &edge.successor);
                    bytes.extend_from_slice(&edge.probability.to_bits().to_be_bytes());
                }
            }
        }
    }
    for (id, value) in &values {
        add_name(&mut bytes, id);
        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
    }
    for (id, action) in &choices {
        add_name(&mut bytes, id);
        add_name(&mut bytes, action);
    }
    Ok(SngrGraphReceiptShadowV1 {
        root_utility,
        unique_evaluated_nodes: values.len(),
        memoized_references: cache_hits,
        node_values: values,
        selected_actions: choices,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "sngr_graph_shadow_tests.rs"]
mod tests;
