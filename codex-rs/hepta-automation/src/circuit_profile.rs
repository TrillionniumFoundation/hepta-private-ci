//! A separate bounded-feedback profile. TaskFlow V1 retains its DAG contract.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::TaskFlowError;
use crate::circuit_join::circuit_join_output_schema_v2;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitProfileV2 {
    BoundedFeedbackV2,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitExitV2 {
    Succeeded,
    Failed,
    Abstained,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum CircuitJoinV2 {
    All,
    Any,
    Quorum { required: u16 },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum CircuitNodeKindV2 {
    /// A bounded computation on the existing inference/transform facilities.
    Compute {
        max_work: u64,
    },
    /// Select exactly one declared edge; the committed choice is never rerun.
    Decide {
        max_work: u64,
    },
    Subcircuit {
        program: String,
        max_work: u64,
    },
    /// This profile joins successful computation branches. A failed required
    /// computation takes the declared fallback; unknown outcomes remain open.
    Join {
        mode: CircuitJoinV2,
        timeout_ms: u64,
    },
    Exit {
        outcome: CircuitExitV2,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitNodeV2 {
    pub node_id: String,
    pub input_schema: Sha256Digest,
    pub output_schema: Sha256Digest,
    pub kind: CircuitNodeKindV2,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitEdgeV2 {
    pub edge_id: String,
    pub from: String,
    pub to: String,
    /// None belongs to the acyclic activation graph. Some(d > 0) advances
    /// the feedback round and cannot run before the current timestamp plus d.
    pub feedback_delay_ms: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitProgramV2 {
    pub program_id: String,
    pub entry_node: String,
    /// Every exhausted/failed execution takes this explicit non-success exit.
    pub fallback_node: String,
    pub nodes: Vec<CircuitNodeV2>,
    pub edges: Vec<CircuitEdgeV2>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitLimitsV2 {
    pub max_rounds: u32,
    pub max_activations: u32,
    pub max_frontier: u32,
    pub max_events: u32,
    pub max_causal_depth: u32,
    pub max_child_depth: u16,
    pub max_quantum: u16,
    pub max_no_progress: u32,
    pub max_elapsed_ms: u64,
    pub work_budget: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BoundedCircuitDefinitionV2 {
    pub profile: CircuitProfileV2,
    pub circuit_id: String,
    pub version: u32,
    pub predecessor_digest: Option<Sha256Digest>,
    pub entry_program: String,
    pub parameter_bundle_digest: Sha256Digest,
    pub route_policy_digest: Sha256Digest,
    pub limits: CircuitLimitsV2,
    pub programs: Vec<CircuitProgramV2>,
}

impl BoundedCircuitDefinitionV2 {
    pub fn validate(&self) -> Result<(), TaskFlowError> {
        text(&self.circuit_id)?;
        text(&self.entry_program)?;
        digest(&self.parameter_bundle_digest)?;
        digest(&self.route_policy_digest)?;
        if let Some(value) = &self.predecessor_digest {
            digest(value)?;
        }
        if self.version == 0 || (self.version == 1) != self.predecessor_digest.is_none() {
            return Err(invalid("circuit version/predecessor mismatch"));
        }
        let l = &self.limits;
        if !(1..=4_096).contains(&l.max_rounds)
            || !(1..=4_096).contains(&l.max_activations)
            || !(1..=l.max_activations).contains(&l.max_frontier)
            || !(1..=16_384).contains(&l.max_events)
            || !(1..=4_096).contains(&l.max_causal_depth)
            || !(1..=16).contains(&l.max_child_depth)
            || !(1..=64).contains(&l.max_quantum)
            || !(1..=4_096).contains(&l.max_no_progress)
            || l.max_elapsed_ms == 0
            || l.max_elapsed_ms > 86_400_000
            || l.work_budget == 0
            || l.work_budget > i64::MAX as u64
        {
            return Err(invalid(
                "circuit resource limits are outside the bounded profile",
            ));
        }
        if self.programs.is_empty() || self.programs.len() > 32 {
            return Err(invalid(
                "circuit program count is outside the bounded profile",
            ));
        }
        let mut programs = BTreeMap::new();
        let mut nodes = 0_usize;
        let mut edges = 0_usize;
        let mut largest_degree = 0_usize;
        for program in &self.programs {
            text(&program.program_id)?;
            if programs
                .insert(program.program_id.as_str(), program)
                .is_some()
            {
                return Err(invalid("duplicate circuit program"));
            }
            nodes += program.nodes.len();
            edges += program.edges.len();
            program.validate(l)?;
            for node in &program.nodes {
                largest_degree = largest_degree.max(
                    program
                        .edges
                        .iter()
                        .filter(|edge| edge.from == node.node_id || edge.to == node.node_id)
                        .count(),
                );
            }
        }
        if nodes > 256 || edges > 1_024 {
            return Err(invalid("circuit graph exceeds bounded profile"));
        }
        // Reserve space for IDs, receipts, joins and child reservation maps.
        // Admission must not promise a run whose bounded trace cannot persist.
        let state_bound = u64::from(l.max_activations) * (1_536 + largest_degree as u64 * 288);
        if state_bound > 7_340_032 {
            return Err(invalid(
                "activation/branch product exceeds circuit state byte bound",
            ));
        }
        // Process each call edge once. Enumerating ancestor paths here would
        // be exponential for a small DAG containing shared subprograms.
        let mut incoming: BTreeMap<_, usize> = programs.keys().map(|id| (*id, 0)).collect();
        let mut calls: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
        for program in &self.programs {
            for node in &program.nodes {
                if let CircuitNodeKindV2::Subcircuit { program: child, .. } = &node.kind {
                    let child = programs
                        .get(child.as_str())
                        .ok_or_else(|| invalid("unknown subcircuit"))?;
                    if child.node(&child.entry_node)?.input_schema != node.input_schema
                        || child.nodes.iter().any(|n| {
                            matches!(n.kind, CircuitNodeKindV2::Exit { .. })
                                && n.output_schema != node.output_schema
                        })
                    {
                        return Err(invalid("subcircuit port schema mismatch"));
                    }
                    *incoming
                        .get_mut(child.program_id.as_str())
                        .ok_or_else(|| invalid("unknown child"))? += 1;
                    calls
                        .entry(&program.program_id)
                        .or_default()
                        .push(&child.program_id);
                }
            }
        }
        if incoming.get(self.entry_program.as_str()) != Some(&0) {
            return Err(invalid("circuit entry has a recursive parent or is absent"));
        }
        let mut depths = BTreeMap::from([(self.entry_program.as_str(), 0_u16)]);
        let mut pending = vec![self.entry_program.as_str()];
        let mut visited = 0;
        while let Some(id) = pending.pop() {
            visited += 1;
            for child in calls.get(id).into_iter().flatten() {
                let depth = depths[id] + 1;
                if depth > l.max_child_depth {
                    return Err(invalid("subcircuit depth exceeds profile"));
                }
                depths
                    .entry(child)
                    .and_modify(|d| *d = (*d).max(depth))
                    .or_insert(depth);
                let count = incoming
                    .get_mut(child)
                    .ok_or_else(|| invalid("unknown child"))?;
                *count -= 1;
                if *count == 0 {
                    pending.push(child);
                }
            }
        }
        if visited != programs.len() {
            return Err(invalid("cyclic or unreachable subcircuit program"));
        }
        Ok(())
    }

    pub fn definition_digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        self.validate()?;
        hash("hepta.circuit.definition.v2", self)
    }

    pub(crate) fn program(&self, id: &str) -> Result<&CircuitProgramV2, TaskFlowError> {
        self.programs
            .iter()
            .find(|p| p.program_id == id)
            .ok_or_else(|| invalid("unknown program"))
    }
}

impl CircuitProgramV2 {
    pub(crate) fn node(&self, id: &str) -> Result<&CircuitNodeV2, TaskFlowError> {
        self.nodes
            .iter()
            .find(|n| n.node_id == id)
            .ok_or_else(|| invalid("unknown node"))
    }

    fn validate(&self, limits: &CircuitLimitsV2) -> Result<(), TaskFlowError> {
        if self.nodes.is_empty() || self.nodes.len() > 256 || self.edges.len() > 1_024 {
            return Err(invalid("invalid program size"));
        }
        let mut nodes = BTreeSet::new();
        for node in &self.nodes {
            text(&node.node_id)?;
            digest(&node.input_schema)?;
            digest(&node.output_schema)?;
            if !nodes.insert(node.node_id.as_str()) {
                return Err(invalid("duplicate circuit node"));
            }
            match &node.kind {
                CircuitNodeKindV2::Compute { max_work }
                | CircuitNodeKindV2::Decide { max_work }
                | CircuitNodeKindV2::Subcircuit { max_work, .. } => {
                    if *max_work == 0 || *max_work > limits.work_budget {
                        return Err(invalid("invalid node work reservation"));
                    }
                }
                CircuitNodeKindV2::Join { timeout_ms, .. } => {
                    if *timeout_ms == 0
                        || *timeout_ms > limits.max_elapsed_ms
                        || node.output_schema != circuit_join_output_schema_v2()
                    {
                        return Err(invalid("invalid join timeout or output envelope schema"));
                    }
                }
                CircuitNodeKindV2::Exit { .. } => {
                    if node.input_schema != node.output_schema {
                        return Err(invalid("exit cannot perform an implicit schema conversion"));
                    }
                }
            }
        }
        if matches!(
            self.node(&self.entry_node)?.kind,
            CircuitNodeKindV2::Join { .. }
        ) || !matches!(
            self.node(&self.fallback_node)?.kind,
            CircuitNodeKindV2::Exit {
                outcome: CircuitExitV2::Failed | CircuitExitV2::Abstained
            }
        ) {
            return Err(invalid("invalid circuit entry or fallback"));
        }
        let mut edge_ids = BTreeSet::new();
        let mut indegree: BTreeMap<_, usize> = nodes.iter().map(|id| (*id, 0)).collect();
        for edge in &self.edges {
            text(&edge.edge_id)?;
            if !edge_ids.insert(edge.edge_id.as_str())
                || edge.feedback_delay_ms == Some(0)
                || edge
                    .feedback_delay_ms
                    .is_some_and(|d| d > limits.max_elapsed_ms)
            {
                return Err(invalid("duplicate edge or unbounded feedback delay"));
            }
            let source = self.node(&edge.from)?;
            let destination = self.node(&edge.to)?;
            if source.output_schema != destination.input_schema {
                return Err(invalid("incompatible circuit port schemas"));
            }
            // Join arrivals are observations at receipt time in this profile.
            // Delayed feedback must enter a computation before it reaches a join.
            if edge.feedback_delay_ms.is_some()
                && matches!(destination.kind, CircuitNodeKindV2::Join { .. })
            {
                return Err(invalid("delayed feedback cannot directly enter a join"));
            }
            if edge.feedback_delay_ms.is_none() {
                *indegree
                    .get_mut(edge.to.as_str())
                    .ok_or_else(|| invalid("unknown edge target"))? += 1;
            }
        }
        let mut ready: Vec<_> = indegree
            .iter()
            .filter_map(|(id, degree)| (*degree == 0).then_some(*id))
            .collect();
        let mut ordered = 0;
        while let Some(id) = ready.pop() {
            ordered += 1;
            for edge in self
                .edges
                .iter()
                .filter(|e| e.from == id && e.feedback_delay_ms.is_none())
            {
                let degree = indegree
                    .get_mut(edge.to.as_str())
                    .ok_or_else(|| invalid("unknown target"))?;
                *degree -= 1;
                if *degree == 0 {
                    ready.push(edge.to.as_str());
                }
            }
        }
        if ordered != self.nodes.len() {
            return Err(invalid(
                "same-round graph contains a cycle; declare delayed feedback",
            ));
        }
        let mut reached = BTreeSet::new();
        let mut queue = vec![self.entry_node.as_str()];
        while let Some(id) = queue.pop() {
            if reached.insert(id) {
                queue.extend(
                    self.edges
                        .iter()
                        .filter(|e| e.from == id)
                        .map(|e| e.to.as_str()),
                );
            }
        }
        reached.insert(self.fallback_node.as_str());
        if reached != nodes {
            return Err(invalid("unreachable circuit node"));
        }
        for node in &self.nodes {
            let outgoing = self.edges.iter().filter(|e| e.from == node.node_id).count();
            let incoming = self.edges.iter().filter(|e| e.to == node.node_id).count();
            if outgoing > 256 || incoming > 256 {
                return Err(invalid(
                    "circuit port fan-in/out exceeds receipt byte bound",
                ));
            }
            if matches!(node.kind, CircuitNodeKindV2::Exit { .. }) != (outgoing == 0) {
                return Err(invalid("exit has outgoing edges or non-exit has none"));
            }
            if let CircuitNodeKindV2::Join { mode, .. } = node.kind {
                let required = match mode {
                    CircuitJoinV2::All => incoming,
                    CircuitJoinV2::Any => 1,
                    CircuitJoinV2::Quorum { required } => usize::from(required),
                };
                if incoming < 2 || required == 0 || required > incoming {
                    return Err(invalid("invalid join branch count"));
                }
            }
        }
        Ok(())
    }
}

pub(crate) fn text(value: &str) -> Result<(), TaskFlowError> {
    if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
        return Err(invalid("invalid circuit identifier"));
    }
    Ok(())
}

pub(crate) fn digest(value: &Sha256Digest) -> Result<(), TaskFlowError> {
    if value.as_str().len() != 64
        || !value
            .as_str()
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        || value.as_str().bytes().all(|b| b == b'0')
    {
        return Err(invalid("invalid circuit digest"));
    }
    Ok(())
}

pub(crate) fn hash<T: Serialize>(domain: &str, value: &T) -> Result<Sha256Digest, TaskFlowError> {
    let bytes = serde_json::to_vec(&(domain, value))
        .map_err(|e| TaskFlowError::Corrupt(format!("circuit encoding: {e}")))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

pub(crate) fn invalid(message: &str) -> TaskFlowError {
    TaskFlowError::Invalid(message.to_string())
}
