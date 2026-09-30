//! Additive Neural Circuit V2 definition/compiler and durable sequential runtime.
//!
//! V1 TaskFlow remains byte- and replay-compatible.  V2 is stored in separate
//! tables and advances through the existing Automation owner one activation at
//! a time.  Decision/guard choices are committed before a downstream Effect
//! activation can be claimed.  Effect execution itself remains owned by the
//! existing final-use-authorized TaskFlow effect seam.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

use crate::AutomationStore;
use crate::CircuitNodeRoleV1;
use crate::NeuralCircuitCandidateV1;
use crate::TaskFlowError;
use crate::TaskFlowFence;

pub const CIRCUIT_V2_SCHEMA_VERSION: u32 = 2;
const MAX_CIRCUIT_V2_NODES: usize = 256;
const MAX_CIRCUIT_V2_EDGES: usize = 1_024;
const MAX_CIRCUIT_V2_PORTS_PER_NODE: usize = 64;
const MAX_CIRCUIT_V2_CAPABILITIES: usize = 256;
const MAX_CIRCUIT_V2_ROUNDS: u32 = 1_024;
const MAX_CIRCUIT_V2_ACTIVATIONS: u32 = 65_536;
const MAX_CIRCUIT_V2_JOIN_RECEIPTS: usize = 256;
const MAX_TEXT_BYTES: usize = 256;

fn uncomputed_digest() -> Sha256Digest {
    Sha256Digest::for_bytes(b"uncomputed-neural-circuit-v2")
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitNodeRoleV2 {
    /// Compatibility-only role for a V1 Activity whose finer semantics were
    /// never recorded. New V2 definitions should use a concrete role.
    LegacyActivity,
    Observe,
    Decide,
    TransformGuard,
    OrganCall,
    Wait,
    Join,
    Effect,
    ExitSuccess,
    ExitFailure,
    ExitAbstain,
    ExitCancel,
}

impl CircuitNodeRoleV2 {
    const fn is_exit(self) -> bool {
        matches!(
            self,
            Self::ExitSuccess | Self::ExitFailure | Self::ExitAbstain | Self::ExitCancel
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitPortV2 {
    pub name: String,
    pub schema_digest: Sha256Digest,
}

impl CircuitPortV2 {
    pub fn new(
        name: impl Into<String>,
        schema_digest: Sha256Digest,
    ) -> Result<Self, TaskFlowError> {
        let value = Self {
            name: name.into(),
            schema_digest,
        };
        value.validate()?;
        Ok(value)
    }

    fn validate(&self) -> Result<(), TaskFlowError> {
        validate_text(&self.name, "circuit port")?;
        validate_digest(&self.schema_digest, "circuit port schema")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitNodeV2 {
    pub node_id: String,
    pub role: CircuitNodeRoleV2,
    pub input_ports: Vec<CircuitPortV2>,
    pub output_ports: Vec<CircuitPortV2>,
    pub capability: Option<String>,
    pub idempotency_template: Option<String>,
}

impl CircuitNodeV2 {
    #[must_use]
    pub fn new(node_id: impl Into<String>, role: CircuitNodeRoleV2) -> Self {
        Self {
            node_id: node_id.into(),
            role,
            input_ports: Vec::new(),
            output_ports: Vec::new(),
            capability: None,
            idempotency_template: None,
        }
    }

    #[must_use]
    pub fn with_ports(
        mut self,
        input_ports: Vec<CircuitPortV2>,
        output_ports: Vec<CircuitPortV2>,
    ) -> Self {
        self.input_ports = input_ports;
        self.output_ports = output_ports;
        self
    }

    #[must_use]
    pub fn with_capability(mut self, capability: impl Into<String>) -> Self {
        self.capability = Some(capability.into());
        self
    }

    #[must_use]
    pub fn with_idempotency_template(mut self, value: impl Into<String>) -> Self {
        self.idempotency_template = Some(value.into());
        self
    }

    fn validate(&self, capabilities: &BTreeSet<String>) -> Result<(), TaskFlowError> {
        validate_text(&self.node_id, "circuit node")?;
        validate_ports(&self.input_ports, "input")?;
        validate_ports(&self.output_ports, "output")?;
        if let Some(capability) = &self.capability {
            validate_text(capability, "circuit node capability")?;
            if !capabilities.contains(capability) {
                return Err(invalid("circuit node uses an undeclared capability"));
            }
        }
        if self.role == CircuitNodeRoleV2::Effect {
            if self.capability.is_none() || self.idempotency_template.is_none() {
                return Err(invalid(
                    "Circuit V2 Effect requires capability and idempotency template",
                ));
            }
        } else if self.idempotency_template.is_some() {
            return Err(invalid(
                "only Circuit V2 Effect may carry an idempotency template",
            ));
        }
        if self.role.is_exit() && !self.output_ports.is_empty() {
            return Err(invalid("Circuit V2 exit nodes cannot expose output ports"));
        }
        Ok(())
    }

    fn input(&self, name: &str) -> Option<&CircuitPortV2> {
        self.input_ports.iter().find(|port| port.name == name)
    }

    fn output(&self, name: &str) -> Option<&CircuitPortV2> {
        self.output_ports.iter().find(|port| port.name == name)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitEdgeV2 {
    pub edge_id: String,
    pub from_node: String,
    pub from_port: String,
    pub to_node: String,
    pub to_port: String,
    /// None is same-round flow. Some(n) is explicit delayed feedback and must
    /// advance by at least one durable activation round.
    pub feedback_round_delay: Option<u32>,
    pub condition_digest: Option<Sha256Digest>,
}

impl CircuitEdgeV2 {
    #[must_use]
    pub fn new(
        edge_id: impl Into<String>,
        from_node: impl Into<String>,
        from_port: impl Into<String>,
        to_node: impl Into<String>,
        to_port: impl Into<String>,
    ) -> Self {
        Self {
            edge_id: edge_id.into(),
            from_node: from_node.into(),
            from_port: from_port.into(),
            to_node: to_node.into(),
            to_port: to_port.into(),
            feedback_round_delay: None,
            condition_digest: None,
        }
    }

    #[must_use]
    pub fn feedback(mut self, round_delay: u32) -> Self {
        self.feedback_round_delay = Some(round_delay);
        self
    }

    #[must_use]
    pub fn conditioned(mut self, digest: Sha256Digest) -> Self {
        self.condition_digest = Some(digest);
        self
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitDefinitionV2 {
    pub circuit_id: String,
    pub version: u32,
    pub predecessor_digest: Option<Sha256Digest>,
    pub compatibility_source_digest: Option<Sha256Digest>,
    pub entry_node: String,
    pub nodes: Vec<CircuitNodeV2>,
    pub edges: Vec<CircuitEdgeV2>,
    pub capability_set: Vec<String>,
    pub route_policy_digest: Sha256Digest,
    pub parameter_bundle_digest: Sha256Digest,
    pub resource_profile_digest: Sha256Digest,
    pub max_rounds: u32,
    pub max_activations: u32,
    pub definition_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitPlanV2 {
    pub circuit_id: String,
    pub version: u32,
    pub definition_digest: Sha256Digest,
    pub topological_order: Vec<String>,
    pub feedback_edges: Vec<String>,
    pub max_rounds: u32,
    pub max_activations: u32,
    pub authority_granted: bool,
}

impl CircuitDefinitionV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        circuit_id: impl Into<String>,
        version: u32,
        predecessor_digest: Option<Sha256Digest>,
        compatibility_source_digest: Option<Sha256Digest>,
        entry_node: impl Into<String>,
        mut nodes: Vec<CircuitNodeV2>,
        mut edges: Vec<CircuitEdgeV2>,
        mut capability_set: Vec<String>,
        route_policy_digest: Sha256Digest,
        parameter_bundle_digest: Sha256Digest,
        resource_profile_digest: Sha256Digest,
        max_rounds: u32,
        max_activations: u32,
    ) -> Result<Self, TaskFlowError> {
        for node in &mut nodes {
            node.input_ports.sort_by(|left, right| left.name.cmp(&right.name));
            node.output_ports
                .sort_by(|left, right| left.name.cmp(&right.name));
        }
        nodes.sort_by(|left, right| left.node_id.cmp(&right.node_id));
        edges.sort_by(|left, right| left.edge_id.cmp(&right.edge_id));
        capability_set.sort();
        let mut value = Self {
            circuit_id: circuit_id.into(),
            version,
            predecessor_digest,
            compatibility_source_digest,
            entry_node: entry_node.into(),
            nodes,
            edges,
            capability_set,
            route_policy_digest,
            parameter_bundle_digest,
            resource_profile_digest,
            max_rounds,
            max_activations,
            definition_digest: uncomputed_digest(),
        };
        value.validate_shape()?;
        value.definition_digest = value.compute_digest()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), TaskFlowError> {
        self.validate_shape()?;
        if self.definition_digest != self.compute_digest()? {
            return Err(TaskFlowError::Corrupt(
                "Circuit V2 definition digest does not match canonical bytes".to_string(),
            ));
        }
        Ok(())
    }

    pub fn compile_plan(&self) -> Result<CircuitPlanV2, TaskFlowError> {
        self.validate()?;
        let (topological_order, feedback_edges) = self.plan_parts()?;
        Ok(CircuitPlanV2 {
            circuit_id: self.circuit_id.clone(),
            version: self.version,
            definition_digest: self.definition_digest.clone(),
            topological_order,
            feedback_edges,
            max_rounds: self.max_rounds,
            max_activations: self.max_activations,
            authority_granted: false,
        })
    }

    /// Compatibility compiler from the already-admitted V1 Neural Circuit
    /// candidate. The source digest is retained explicitly and V1 bytes are
    /// never rewritten or reinterpreted in place.
    pub fn from_neural_circuit_v1(
        source: &NeuralCircuitCandidateV1,
    ) -> Result<Self, TaskFlowError> {
        source.validate()?;
        let control_schema =
            Sha256Digest::for_bytes(b"hepta.neural-circuit.v2.compat-control-signal.v1");
        let mut nodes = Vec::with_capacity(source.nodes.len());
        for old in &source.nodes {
            let role = match old.role {
                CircuitNodeRoleV1::Observe => CircuitNodeRoleV2::Observe,
                CircuitNodeRoleV1::Decide => CircuitNodeRoleV2::Decide,
                CircuitNodeRoleV1::TransformGuard => CircuitNodeRoleV2::TransformGuard,
                CircuitNodeRoleV1::OrganCall => CircuitNodeRoleV2::OrganCall,
                CircuitNodeRoleV1::WaitJoin => CircuitNodeRoleV2::Wait,
                CircuitNodeRoleV1::Effect => CircuitNodeRoleV2::Effect,
                CircuitNodeRoleV1::ExitSuccess => CircuitNodeRoleV2::ExitSuccess,
                CircuitNodeRoleV1::ExitFailure => CircuitNodeRoleV2::ExitFailure,
            };
            let mut node = CircuitNodeV2::new(&old.node_id, role);
            if old.node_id != source.entry_node {
                node.input_ports.push(CircuitPortV2::new(
                    "control",
                    control_schema.clone(),
                )?);
            }
            if !role.is_exit() {
                node.output_ports.push(CircuitPortV2::new(
                    "control",
                    control_schema.clone(),
                )?);
            }
            node.capability.clone_from(&old.capability);
            node.idempotency_template
                .clone_from(&old.idempotency_template);
            nodes.push(node);
        }
        let mut edges = Vec::with_capacity(source.edges.len());
        for (index, old) in source.edges.iter().enumerate() {
            edges.push(CircuitEdgeV2::new(
                format!("compat-edge-{index:04}"),
                &old.from,
                "control",
                &old.to,
                "control",
            ));
        }
        Self::new(
            source.circuit_id.clone(),
            source.version,
            source.predecessor_digest.clone(),
            Some(source.circuit_digest.clone()),
            source.entry_node.clone(),
            nodes,
            edges,
            source.capability_set.clone(),
            source.route_policy_digest.clone(),
            source.parameter_bundle_digest.clone(),
            source.resource_profile_digest.clone(),
            1,
            u32::try_from(source.nodes.len())
                .unwrap_or(u32::MAX)
                .saturating_mul(32)
                .clamp(1, MAX_CIRCUIT_V2_ACTIVATIONS),
        )
    }

    fn validate_shape(&self) -> Result<(), TaskFlowError> {
        validate_text(&self.circuit_id, "circuit_id")?;
        validate_text(&self.entry_node, "entry_node")?;
        if self.version == 0 {
            return Err(invalid("Circuit V2 version must be non-zero"));
        }
        if self.max_rounds == 0 || self.max_rounds > MAX_CIRCUIT_V2_ROUNDS {
            return Err(invalid("Circuit V2 max_rounds is outside the bounded limit"));
        }
        if self.max_activations == 0 || self.max_activations > MAX_CIRCUIT_V2_ACTIVATIONS {
            return Err(invalid(
                "Circuit V2 max_activations is outside the bounded limit",
            ));
        }
        if self.nodes.is_empty() || self.nodes.len() > MAX_CIRCUIT_V2_NODES {
            return Err(invalid("Circuit V2 node count is outside the bounded limit"));
        }
        if self.edges.len() > MAX_CIRCUIT_V2_EDGES {
            return Err(invalid("Circuit V2 edge count exceeds the bounded limit"));
        }
        validate_digest(&self.route_policy_digest, "route policy")?;
        validate_digest(&self.parameter_bundle_digest, "parameter bundle")?;
        validate_digest(&self.resource_profile_digest, "resource profile")?;
        if let Some(digest) = &self.predecessor_digest {
            validate_digest(digest, "predecessor")?;
        }
        if let Some(digest) = &self.compatibility_source_digest {
            validate_digest(digest, "compatibility source")?;
        }

        let mut capabilities = BTreeSet::new();
        if self.capability_set.len() > MAX_CIRCUIT_V2_CAPABILITIES {
            return Err(invalid("Circuit V2 capability set exceeds the bounded limit"));
        }
        for capability in &self.capability_set {
            validate_text(capability, "circuit capability")?;
            if !capabilities.insert(capability.clone()) {
                return Err(invalid("Circuit V2 capability set contains a duplicate"));
            }
        }

        let mut nodes = BTreeMap::new();
        for node in &self.nodes {
            node.validate(&capabilities)?;
            if nodes.insert(node.node_id.clone(), node).is_some() {
                return Err(invalid("Circuit V2 contains duplicate node ids"));
            }
        }
        if !nodes.contains_key(&self.entry_node) {
            return Err(invalid("Circuit V2 entry node is missing"));
        }

        let mut edge_ids = BTreeSet::new();
        let mut outgoing: BTreeMap<String, Vec<&CircuitEdgeV2>> =
            nodes.keys().cloned().map(|node| (node, Vec::new())).collect();
        let mut all_adjacency: BTreeMap<String, Vec<String>> =
            nodes.keys().cloned().map(|node| (node, Vec::new())).collect();
        for edge in &self.edges {
            validate_text(&edge.edge_id, "circuit edge id")?;
            validate_text(&edge.from_node, "circuit edge source")?;
            validate_text(&edge.to_node, "circuit edge target")?;
            validate_text(&edge.from_port, "circuit edge source port")?;
            validate_text(&edge.to_port, "circuit edge target port")?;
            if !edge_ids.insert(edge.edge_id.clone()) {
                return Err(invalid("Circuit V2 contains duplicate edge ids"));
            }
            let from = nodes
                .get(&edge.from_node)
                .ok_or_else(|| invalid("Circuit V2 edge references unknown source node"))?;
            let to = nodes
                .get(&edge.to_node)
                .ok_or_else(|| invalid("Circuit V2 edge references unknown target node"))?;
            if edge.from_node == edge.to_node && edge.feedback_round_delay.is_none() {
                return Err(invalid(
                    "Circuit V2 same-round self-loop requires explicit feedback delay",
                ));
            }
            let from_port = from
                .output(&edge.from_port)
                .ok_or_else(|| invalid("Circuit V2 edge references unknown source port"))?;
            let to_port = to
                .input(&edge.to_port)
                .ok_or_else(|| invalid("Circuit V2 edge references unknown target port"))?;
            if from_port.schema_digest != to_port.schema_digest {
                return Err(invalid("Circuit V2 edge connects incompatible port schemas"));
            }
            if let Some(delay) = edge.feedback_round_delay
                && (delay == 0 || delay > self.max_rounds)
            {
                return Err(invalid(
                    "Circuit V2 feedback delay must be in 1..=max_rounds",
                ));
            }
            if let Some(condition) = &edge.condition_digest {
                validate_digest(condition, "edge condition")?;
            }
            outgoing
                .get_mut(&edge.from_node)
                .expect("source map contains validated node")
                .push(edge);
            all_adjacency
                .get_mut(&edge.from_node)
                .expect("source map contains validated node")
                .push(edge.to_node.clone());
        }
        for node in &self.nodes {
            let outgoing_edges = outgoing
                .get(&node.node_id)
                .expect("outgoing map contains every node");
            if node.role.is_exit() && !outgoing_edges.is_empty() {
                return Err(invalid("Circuit V2 exit node has outgoing edges"));
            }
            if !node.role.is_exit() && outgoing_edges.is_empty() {
                return Err(invalid("Circuit V2 non-exit node has no successor"));
            }
        }

        let reachable = reachable_nodes(&self.entry_node, &all_adjacency);
        if reachable.len() != self.nodes.len() {
            return Err(invalid("Circuit V2 contains an unreachable node"));
        }
        let _ = self.plan_parts()?;

        if self.definition_digest != uncomputed_digest()
            && self.definition_digest != self.compute_digest()?
        {
            return Err(TaskFlowError::Corrupt(
                "Circuit V2 definition digest does not match canonical bytes".to_string(),
            ));
        }
        Ok(())
    }

    fn plan_parts(&self) -> Result<(Vec<String>, Vec<String>), TaskFlowError> {
        let mut indegree: BTreeMap<String, usize> = self
            .nodes
            .iter()
            .map(|node| (node.node_id.clone(), 0))
            .collect();
        let mut adjacency: BTreeMap<String, Vec<String>> = self
            .nodes
            .iter()
            .map(|node| (node.node_id.clone(), Vec::new()))
            .collect();
        let mut feedback_edges = Vec::new();
        for edge in &self.edges {
            if edge.feedback_round_delay.is_some() {
                feedback_edges.push(edge.edge_id.clone());
                continue;
            }
            adjacency
                .get_mut(&edge.from_node)
                .ok_or_else(|| invalid("Circuit V2 source node missing during planning"))?
                .push(edge.to_node.clone());
            *indegree
                .get_mut(&edge.to_node)
                .ok_or_else(|| invalid("Circuit V2 target node missing during planning"))? += 1;
        }
        let mut ready: BTreeSet<String> = indegree
            .iter()
            .filter(|(_, degree)| **degree == 0)
            .map(|(node, _)| node.clone())
            .collect();
        let mut order = Vec::with_capacity(indegree.len());
        while let Some(node) = ready.pop_first() {
            order.push(node.clone());
            for target in adjacency
                .get(&node)
                .expect("adjacency contains every planned node")
            {
                let degree = indegree
                    .get_mut(target)
                    .expect("indegree contains every target node");
                *degree -= 1;
                if *degree == 0 {
                    ready.insert(target.clone());
                }
            }
        }
        if order.len() != self.nodes.len() {
            return Err(invalid(
                "Circuit V2 same-round graph contains a cycle; feedback must be delayed",
            ));
        }
        feedback_edges.sort();
        Ok((order, feedback_edges))
    }

    fn compute_digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        #[derive(Serialize)]
        struct Canonical<'a> {
            schema_version: u32,
            circuit_id: &'a str,
            version: u32,
            predecessor_digest: &'a Option<Sha256Digest>,
            compatibility_source_digest: &'a Option<Sha256Digest>,
            entry_node: &'a str,
            nodes: &'a [CircuitNodeV2],
            edges: &'a [CircuitEdgeV2],
            capability_set: &'a [String],
            route_policy_digest: &'a Sha256Digest,
            parameter_bundle_digest: &'a Sha256Digest,
            resource_profile_digest: &'a Sha256Digest,
            max_rounds: u32,
            max_activations: u32,
        }
        let bytes = serde_json::to_vec(&Canonical {
            schema_version: CIRCUIT_V2_SCHEMA_VERSION,
            circuit_id: &self.circuit_id,
            version: self.version,
            predecessor_digest: &self.predecessor_digest,
            compatibility_source_digest: &self.compatibility_source_digest,
            entry_node: &self.entry_node,
            nodes: &self.nodes,
            edges: &self.edges,
            capability_set: &self.capability_set,
            route_policy_digest: &self.route_policy_digest,
            parameter_bundle_digest: &self.parameter_bundle_digest,
            resource_profile_digest: &self.resource_profile_digest,
            max_rounds: self.max_rounds,
            max_activations: self.max_activations,
        })
        .map_err(|error| TaskFlowError::Corrupt(format!("Circuit V2 serialization: {error}")))?;
        Ok(Sha256Digest::for_bytes(&bytes))
    }

    fn node(&self, node_id: &str) -> Result<&CircuitNodeV2, TaskFlowError> {
        self.nodes
            .iter()
            .find(|node| node.node_id == node_id)
            .ok_or_else(|| TaskFlowError::Corrupt("Circuit V2 run references missing node".into()))
    }

    fn edge(&self, edge_id: &str) -> Result<&CircuitEdgeV2, TaskFlowError> {
        self.edges
            .iter()
            .find(|edge| edge.edge_id == edge_id)
            .ok_or_else(|| invalid("Circuit V2 selected edge is not in the frozen definition"))
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitFleetLeaseRefV1 {
    pub allocation_id: String,
    pub host_id: String,
    pub host_generation: u64,
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub expires_at_ms: u64,
    pub semantic_digest: Sha256Digest,
    pub verified_use_witness_digest: Sha256Digest,
    pub resource_profile_digest: Sha256Digest,
    pub remaining_projection_digest: Sha256Digest,
}

impl CircuitFleetLeaseRefV1 {
    pub fn validate_at(&self, now_ms: u64) -> Result<(), TaskFlowError> {
        validate_text(&self.allocation_id, "Fleet allocation id")?;
        validate_text(&self.host_id, "Fleet host id")?;
        if self.host_generation == 0
            || self.authority_epoch == 0
            || self.lease_generation == 0
            || self.expires_at_ms <= now_ms
        {
            return Err(invalid("Circuit V2 Fleet lease reference is stale or malformed"));
        }
        validate_digest(&self.semantic_digest, "Fleet allocation semantic digest")?;
        validate_digest(
            &self.verified_use_witness_digest,
            "Fleet verified-use witness digest",
        )?;
        validate_digest(&self.resource_profile_digest, "Fleet resource profile digest")?;
        validate_digest(
            &self.remaining_projection_digest,
            "Fleet remaining projection digest",
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitDecisionReceiptV2 {
    pub candidate_set_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub model_receipt_digest: Sha256Digest,
    pub selected_edge_id: String,
    /// Optional fixed-point propensity in millionths.
    pub propensity_micros: Option<u32>,
}

impl CircuitDecisionReceiptV2 {
    fn validate(
        &self,
        definition: &CircuitDefinitionV2,
        selected_edge_id: &str,
    ) -> Result<(), TaskFlowError> {
        validate_digest(&self.candidate_set_digest, "decision candidate set")?;
        validate_digest(&self.policy_digest, "decision policy")?;
        validate_digest(&self.model_receipt_digest, "decision model receipt")?;
        validate_text(&self.selected_edge_id, "decision selected edge")?;
        if self.policy_digest != definition.route_policy_digest
            || self.selected_edge_id != selected_edge_id
            || self.propensity_micros.is_some_and(|value| value > 1_000_000)
        {
            return Err(invalid(
                "Circuit V2 decision receipt does not match frozen policy/selection",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitJoinReceiptV2 {
    pub source_id: String,
    pub receipt_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitActivationCompletionV2 {
    pub completion_id: String,
    pub output_digest: Sha256Digest,
    pub receipt_digest: Sha256Digest,
    pub selected_edge_id: Option<String>,
    pub decision_receipt: Option<CircuitDecisionReceiptV2>,
    pub join_receipts: Vec<CircuitJoinReceiptV2>,
    pub child_run_id: Option<String>,
    pub effect_step_id: Option<String>,
}

impl CircuitActivationCompletionV2 {
    fn validate(
        &self,
        definition: &CircuitDefinitionV2,
        node: &CircuitNodeV2,
    ) -> Result<(), TaskFlowError> {
        validate_text(&self.completion_id, "Circuit V2 completion id")?;
        validate_digest(&self.output_digest, "Circuit V2 output")?;
        validate_digest(&self.receipt_digest, "Circuit V2 owner receipt")?;

        if node.role.is_exit() {
            if self.selected_edge_id.is_some() {
                return Err(invalid("Circuit V2 exit completion cannot select an edge"));
            }
        } else {
            let edge_id = self
                .selected_edge_id
                .as_deref()
                .ok_or_else(|| invalid("Circuit V2 non-exit completion must select one edge"))?;
            let edge = definition.edge(edge_id)?;
            if edge.from_node != node.node_id {
                return Err(invalid(
                    "Circuit V2 selected edge does not leave the completed node",
                ));
            }
        }

        if node.role == CircuitNodeRoleV2::Decide {
            let selected = self
                .selected_edge_id
                .as_deref()
                .ok_or_else(|| invalid("Circuit V2 Decide must select an edge"))?;
            self.decision_receipt
                .as_ref()
                .ok_or_else(|| invalid("Circuit V2 Decide requires a decision receipt"))?
                .validate(definition, selected)?;
        } else if self.decision_receipt.is_some() {
            return Err(invalid("only Circuit V2 Decide may carry a decision receipt"));
        }

        if node.role == CircuitNodeRoleV2::Join {
            if self.join_receipts.len() < 2 || self.join_receipts.len() > MAX_CIRCUIT_V2_JOIN_RECEIPTS
            {
                return Err(invalid(
                    "Circuit V2 Join requires a bounded set of at least two receipts",
                ));
            }
            let mut seen = BTreeSet::new();
            for receipt in &self.join_receipts {
                validate_text(&receipt.source_id, "Circuit V2 join source")?;
                validate_digest(&receipt.receipt_digest, "Circuit V2 join receipt")?;
                if !seen.insert(&receipt.source_id) {
                    return Err(invalid("Circuit V2 Join contains duplicate source ids"));
                }
            }
        } else if !self.join_receipts.is_empty() {
            return Err(invalid("only Circuit V2 Join may carry join receipts"));
        }

        if node.role == CircuitNodeRoleV2::OrganCall {
            let child = self
                .child_run_id
                .as_deref()
                .ok_or_else(|| invalid("Circuit V2 OrganCall requires child run identity"))?;
            validate_text(child, "Circuit V2 child run id")?;
        } else if self.child_run_id.is_some() {
            return Err(invalid("only Circuit V2 OrganCall may bind a child run"));
        }

        if node.role == CircuitNodeRoleV2::Effect {
            let step = self
                .effect_step_id
                .as_deref()
                .ok_or_else(|| invalid("Circuit V2 Effect requires TaskFlow effect step identity"))?;
            validate_text(step, "Circuit V2 effect step id")?;
        } else if self.effect_step_id.is_some() {
            return Err(invalid("only Circuit V2 Effect may bind a TaskFlow effect step"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitRunStateV2 {
    Queued,
    Running,
    Succeeded,
    Failed,
    Abstained,
    Cancelled,
}

impl CircuitRunStateV2 {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Abstained => "abstained",
            Self::Cancelled => "cancelled",
        }
    }

    fn parse(value: &str) -> Result<Self, TaskFlowError> {
        match value {
            "queued" => Ok(Self::Queued),
            "running" => Ok(Self::Running),
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "abstained" => Ok(Self::Abstained),
            "cancelled" => Ok(Self::Cancelled),
            _ => Err(corrupt("unknown Circuit V2 run state")),
        }
    }

    const fn terminal(self) -> bool {
        matches!(
            self,
            Self::Succeeded | Self::Failed | Self::Abstained | Self::Cancelled
        )
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitActivationStateV2 {
    Ready,
    Claimed,
    Completed,
}

impl CircuitActivationStateV2 {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Ready => "ready",
            Self::Claimed => "claimed",
            Self::Completed => "completed",
        }
    }

    fn parse(value: &str) -> Result<Self, TaskFlowError> {
        match value {
            "ready" => Ok(Self::Ready),
            "claimed" => Ok(Self::Claimed),
            "completed" => Ok(Self::Completed),
            _ => Err(corrupt("unknown Circuit V2 activation state")),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitRunV2 {
    pub run_id: String,
    pub circuit_id: String,
    pub circuit_version: u32,
    pub definition_digest: Sha256Digest,
    pub state: CircuitRunStateV2,
    pub next_activation_id: u32,
    pub max_rounds: u32,
    pub max_activations: u32,
    pub fleet_lease: CircuitFleetLeaseRefV1,
    pub owner_id: Option<String>,
    pub owner_epoch: Option<u64>,
    pub generation: Option<u64>,
    pub fencing_token: Option<String>,
    pub lease_expires_at_ms: Option<u64>,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitActivationV2 {
    pub run_id: String,
    pub activation_id: u32,
    pub round: u32,
    pub node_id: String,
    pub state: CircuitActivationStateV2,
    pub input_digest: Sha256Digest,
    pub predecessor_activation_id: Option<u32>,
    pub completion: Option<CircuitActivationCompletionV2>,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitDefinitionReceiptV2 {
    pub circuit_id: String,
    pub version: u32,
    pub definition_digest: Sha256Digest,
    pub inserted: bool,
    pub authority_granted: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitAdvanceV2 {
    pub completed: CircuitActivationV2,
    pub next_activation: Option<CircuitActivationV2>,
    pub run_state: CircuitRunStateV2,
}

impl AutomationStore {
    pub async fn register_circuit_definition_v2(
        &self,
        definition: &CircuitDefinitionV2,
        registered_at_ms: u64,
    ) -> Result<CircuitDefinitionReceiptV2, TaskFlowError> {
        definition.validate()?;
        let json = serde_json::to_string(definition)
            .map_err(|error| corrupt(format!("Circuit V2 definition JSON: {error}")))?;
        let existing = sqlx::query(
            "SELECT definition_digest, definition_json
             FROM circuit_v2_definitions
             WHERE owner_agent_id = ? AND circuit_id = ? AND version = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&definition.circuit_id)
        .bind(i64::from(definition.version))
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        if let Some(row) = existing {
            let digest: String = row.try_get("definition_digest").map_err(|_| {
                corrupt("Circuit V2 definition digest column")
            })?;
            let stored: String = row.try_get("definition_json").map_err(|_| {
                corrupt("Circuit V2 definition JSON column")
            })?;
            if digest != definition.definition_digest.as_str() || stored != json {
                return Err(TaskFlowError::Conflict(
                    "Circuit V2 version is already bound to different bytes".into(),
                ));
            }
            return Ok(CircuitDefinitionReceiptV2 {
                circuit_id: definition.circuit_id.clone(),
                version: definition.version,
                definition_digest: definition.definition_digest.clone(),
                inserted: false,
                authority_granted: false,
            });
        }
        sqlx::query(
            "INSERT INTO circuit_v2_definitions (
                owner_agent_id, circuit_id, version, definition_digest,
                definition_json, compatibility_source_digest, registered_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&definition.circuit_id)
        .bind(i64::from(definition.version))
        .bind(definition.definition_digest.as_str())
        .bind(json)
        .bind(
            definition
                .compatibility_source_digest
                .as_ref()
                .map(Sha256Digest::as_str),
        )
        .bind(to_i64(registered_at_ms)?)
        .execute(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        Ok(CircuitDefinitionReceiptV2 {
            circuit_id: definition.circuit_id.clone(),
            version: definition.version,
            definition_digest: definition.definition_digest.clone(),
            inserted: true,
            authority_granted: false,
        })
    }

    pub async fn circuit_definition_v2(
        &self,
        circuit_id: &str,
        version: u32,
    ) -> Result<Option<CircuitDefinitionV2>, TaskFlowError> {
        validate_text(circuit_id, "circuit_id")?;
        let row = sqlx::query(
            "SELECT definition_json, definition_digest
             FROM circuit_v2_definitions
             WHERE owner_agent_id = ? AND circuit_id = ? AND version = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(circuit_id)
        .bind(i64::from(version))
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let json: String = row
            .try_get("definition_json")
            .map_err(|_| corrupt("Circuit V2 definition JSON column"))?;
        let stored_digest: String = row
            .try_get("definition_digest")
            .map_err(|_| corrupt("Circuit V2 definition digest column"))?;
        let definition: CircuitDefinitionV2 =
            serde_json::from_str(&json).map_err(|_| corrupt("Circuit V2 definition JSON invalid"))?;
        definition.validate()?;
        if definition.definition_digest.as_str() != stored_digest {
            return Err(corrupt("Circuit V2 persisted definition digest mismatch"));
        }
        Ok(Some(definition))
    }

    pub async fn start_circuit_run_v2(
        &self,
        run_id: impl Into<String>,
        definition: &CircuitDefinitionV2,
        input_digest: &Sha256Digest,
        fleet_lease: &CircuitFleetLeaseRefV1,
        now_ms: u64,
    ) -> Result<CircuitRunV2, TaskFlowError> {
        let run_id = run_id.into();
        validate_text(&run_id, "Circuit V2 run id")?;
        validate_digest(input_digest, "Circuit V2 run input")?;
        definition.validate()?;
        fleet_lease.validate_at(now_ms)?;
        if fleet_lease.resource_profile_digest != definition.resource_profile_digest {
            return Err(invalid(
                "Circuit V2 Fleet lease does not bind the frozen resource profile",
            ));
        }
        let registered = self
            .circuit_definition_v2(&definition.circuit_id, definition.version)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict("Circuit V2 definition is not registered".into())
            })?;
        if registered.definition_digest != definition.definition_digest {
            return Err(TaskFlowError::Conflict(
                "Circuit V2 run definition digest is not current for the registered version".into(),
            ));
        }

        let lease_json = serde_json::to_string(fleet_lease)
            .map_err(|error| corrupt(format!("Circuit V2 Fleet lease JSON: {error}")))?;
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        if let Some(row) = sqlx::query(
            "SELECT * FROM circuit_v2_runs WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&run_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
        {
            let existing = circuit_run_from_row(&row)?;
            if existing.circuit_id != definition.circuit_id
                || existing.circuit_version != definition.version
                || existing.definition_digest != definition.definition_digest
                || existing.fleet_lease != *fleet_lease
            {
                return Err(TaskFlowError::Conflict(
                    "Circuit V2 run id is already bound to different inputs".into(),
                ));
            }
            tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(existing);
        }
        sqlx::query(
            "INSERT INTO circuit_v2_runs (
                owner_agent_id, run_id, circuit_id, circuit_version,
                definition_digest, state, next_activation_id, max_rounds,
                max_activations, fleet_lease_json, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, 'queued', 2, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&run_id)
        .bind(&definition.circuit_id)
        .bind(i64::from(definition.version))
        .bind(definition.definition_digest.as_str())
        .bind(i64::from(definition.max_rounds))
        .bind(i64::from(definition.max_activations))
        .bind(lease_json)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        sqlx::query(
            "INSERT INTO circuit_v2_activations (
                owner_agent_id, run_id, activation_id, round, node_id, state,
                input_digest, predecessor_activation_id, completion_id,
                completion_json, created_at_ms, updated_at_ms
             ) VALUES (?, ?, 1, 1, ?, 'ready', ?, NULL, NULL, NULL, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&run_id)
        .bind(&definition.entry_node)
        .bind(input_digest.as_str())
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        self.circuit_run_v2(&run_id)
            .await?
            .ok_or_else(|| corrupt("Circuit V2 run vanished after creation"))
    }

    pub async fn circuit_run_v2(
        &self,
        run_id: &str,
    ) -> Result<Option<CircuitRunV2>, TaskFlowError> {
        validate_text(run_id, "Circuit V2 run id")?;
        let row = sqlx::query(
            "SELECT * FROM circuit_v2_runs WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.as_ref().map(circuit_run_from_row).transpose()
    }

    pub async fn circuit_activation_v2(
        &self,
        run_id: &str,
        activation_id: u32,
    ) -> Result<Option<CircuitActivationV2>, TaskFlowError> {
        validate_text(run_id, "Circuit V2 run id")?;
        let row = sqlx::query(
            "SELECT * FROM circuit_v2_activations
             WHERE owner_agent_id = ? AND run_id = ? AND activation_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(i64::from(activation_id))
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.as_ref().map(circuit_activation_from_row).transpose()
    }

    pub async fn claim_next_circuit_activation_v2(
        &self,
        run_id: &str,
        fence: &TaskFlowFence,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<Option<CircuitActivationV2>, TaskFlowError> {
        validate_text(run_id, "Circuit V2 run id")?;
        validate_circuit_fence(self, fence)?;
        if lease_duration_ms == 0 {
            return Err(invalid("Circuit V2 lease duration must be non-zero"));
        }
        let requested_expiry = now_ms
            .checked_add(lease_duration_ms)
            .ok_or_else(|| invalid("Circuit V2 lease duration overflows"))?;
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let row = sqlx::query(
            "SELECT * FROM circuit_v2_runs WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
        .ok_or_else(|| TaskFlowError::Conflict("Circuit V2 run does not exist".into()))?;
        let mut run = circuit_run_from_row(&row)?;
        if run.state.terminal() {
            return Err(TaskFlowError::Conflict(
                "terminal Circuit V2 run cannot be claimed".into(),
            ));
        }
        run.fleet_lease.validate_at(now_ms)?;

        let active_lease = run.lease_expires_at_ms.is_some_and(|value| value > now_ms);
        if active_lease {
            if !run_matches_fence(&run, fence) {
                return Err(TaskFlowError::StaleFence);
            }
        } else {
            if run.generation.is_some_and(|value| fence.generation <= value)
                || run.owner_epoch.is_some_and(|value| fence.owner_epoch < value)
            {
                return Err(TaskFlowError::StaleFence);
            }
            run.owner_id = Some(fence.owner_id.clone());
            run.owner_epoch = Some(fence.owner_epoch);
            run.generation = Some(fence.generation);
            run.fencing_token = Some(fence.fencing_token.clone());
            run.lease_expires_at_ms = Some(requested_expiry);
        }

        let activation_row = sqlx::query(
            "SELECT * FROM circuit_v2_activations
             WHERE owner_agent_id = ? AND run_id = ? AND state = 'ready'
             ORDER BY round, activation_id LIMIT 1",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        let Some(activation_row) = activation_row else {
            tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(None);
        };
        let mut activation = circuit_activation_from_row(&activation_row)?;
        sqlx::query(
            "UPDATE circuit_v2_activations
             SET state = 'claimed', updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ? AND activation_id = ?
               AND state = 'ready'",
        )
        .bind(to_i64(now_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(i64::from(activation.activation_id))
        .execute(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        run.state = CircuitRunStateV2::Running;
        run.updated_at_ms = now_ms;
        sqlx::query(
            "UPDATE circuit_v2_runs SET
                state = ?, owner_id = ?, owner_epoch = ?, generation = ?,
                fencing_token = ?, lease_expires_at_ms = ?, updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(run.state.as_str())
        .bind(&run.owner_id)
        .bind(run.owner_epoch.map(to_i64).transpose()?)
        .bind(run.generation.map(to_i64).transpose()?)
        .bind(&run.fencing_token)
        .bind(run.lease_expires_at_ms.map(to_i64).transpose()?)
        .bind(to_i64(now_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .execute(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        activation.state = CircuitActivationStateV2::Claimed;
        activation.updated_at_ms = now_ms;
        Ok(Some(activation))
    }

    pub async fn complete_circuit_activation_v2(
        &self,
        run_id: &str,
        activation_id: u32,
        fence: &TaskFlowFence,
        completion: &CircuitActivationCompletionV2,
        now_ms: u64,
    ) -> Result<CircuitAdvanceV2, TaskFlowError> {
        validate_text(run_id, "Circuit V2 run id")?;
        validate_circuit_fence(self, fence)?;
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let run_row = sqlx::query(
            "SELECT * FROM circuit_v2_runs WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
        .ok_or_else(|| TaskFlowError::Conflict("Circuit V2 run does not exist".into()))?;
        let mut run = circuit_run_from_row(&run_row)?;
        if run.state.terminal() || !run_matches_fence(&run, fence) {
            return Err(TaskFlowError::StaleFence);
        }
        if !run.lease_expires_at_ms.is_some_and(|value| value > now_ms) {
            return Err(TaskFlowError::StaleFence);
        }
        run.fleet_lease.validate_at(now_ms)?;

        let activation_row = sqlx::query(
            "SELECT * FROM circuit_v2_activations
             WHERE owner_agent_id = ? AND run_id = ? AND activation_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(i64::from(activation_id))
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
        .ok_or_else(|| TaskFlowError::Conflict("Circuit V2 activation does not exist".into()))?;
        let activation = circuit_activation_from_row(&activation_row)?;
        if activation.state == CircuitActivationStateV2::Completed {
            if activation.completion.as_ref() == Some(completion) {
                tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
                return Ok(CircuitAdvanceV2 {
                    completed: activation,
                    next_activation: None,
                    run_state: run.state,
                });
            }
            return Err(TaskFlowError::Conflict(
                "Circuit V2 activation is already completed with different evidence".into(),
            ));
        }
        if activation.state != CircuitActivationStateV2::Claimed {
            return Err(TaskFlowError::Conflict(
                "Circuit V2 activation must be claimed before completion".into(),
            ));
        }

        let definition_row = sqlx::query(
            "SELECT definition_json, definition_digest
             FROM circuit_v2_definitions
             WHERE owner_agent_id = ? AND circuit_id = ? AND version = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&run.circuit_id)
        .bind(i64::from(run.circuit_version))
        .fetch_one(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        let definition_json: String = definition_row
            .try_get("definition_json")
            .map_err(|_| corrupt("Circuit V2 definition JSON column"))?;
        let definition: CircuitDefinitionV2 = serde_json::from_str(&definition_json)
            .map_err(|_| corrupt("Circuit V2 definition JSON invalid"))?;
        definition.validate()?;
        if definition.definition_digest != run.definition_digest {
            return Err(corrupt("Circuit V2 run definition binding drifted"));
        }
        let node = definition.node(&activation.node_id)?;
        completion.validate(&definition, node)?;

        let completion_json = serde_json::to_string(completion)
            .map_err(|error| corrupt(format!("Circuit V2 completion JSON: {error}")))?;
        sqlx::query(
            "UPDATE circuit_v2_activations
             SET state = 'completed', completion_id = ?, completion_json = ?, updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ? AND activation_id = ?
               AND state = 'claimed'",
        )
        .bind(&completion.completion_id)
        .bind(&completion_json)
        .bind(to_i64(now_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(i64::from(activation_id))
        .execute(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;

        let mut next_activation = None;
        if node.role.is_exit() {
            run.state = match node.role {
                CircuitNodeRoleV2::ExitSuccess => CircuitRunStateV2::Succeeded,
                CircuitNodeRoleV2::ExitFailure => CircuitRunStateV2::Failed,
                CircuitNodeRoleV2::ExitAbstain => CircuitRunStateV2::Abstained,
                CircuitNodeRoleV2::ExitCancel => CircuitRunStateV2::Cancelled,
                _ => unreachable!(),
            };
        } else {
            let edge_id = completion
                .selected_edge_id
                .as_deref()
                .expect("validated non-exit completion selects an edge");
            let edge = definition.edge(edge_id)?;
            let next_round = match edge.feedback_round_delay {
                Some(delay) => activation
                    .round
                    .checked_add(delay)
                    .ok_or_else(|| invalid("Circuit V2 feedback round overflow"))?,
                None => activation.round,
            };
            if next_round > run.max_rounds {
                return Err(TaskFlowError::Conflict(
                    "Circuit V2 feedback exceeds the frozen round budget".into(),
                ));
            }
            if run.next_activation_id > run.max_activations {
                return Err(TaskFlowError::Conflict(
                    "Circuit V2 activation budget is exhausted".into(),
                ));
            }
            let next_id = run.next_activation_id;
            run.next_activation_id = run
                .next_activation_id
                .checked_add(1)
                .ok_or_else(|| corrupt("Circuit V2 activation id overflow"))?;
            sqlx::query(
                "INSERT INTO circuit_v2_activations (
                    owner_agent_id, run_id, activation_id, round, node_id, state,
                    input_digest, predecessor_activation_id, completion_id,
                    completion_json, created_at_ms, updated_at_ms
                 ) VALUES (?, ?, ?, ?, ?, 'ready', ?, ?, NULL, NULL, ?, ?)",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(run_id)
            .bind(i64::from(next_id))
            .bind(i64::from(next_round))
            .bind(&edge.to_node)
            .bind(completion.output_digest.as_str())
            .bind(i64::from(activation.activation_id))
            .bind(to_i64(now_ms)?)
            .bind(to_i64(now_ms)?)
            .execute(&mut *tx)
            .await
            .map_err(|error| {
                if is_unique(&error) {
                    TaskFlowError::Conflict(
                        "Circuit V2 selected path would duplicate a node in the same round".into(),
                    )
                } else {
                    TaskFlowError::Unavailable
                }
            })?;
            next_activation = Some(CircuitActivationV2 {
                run_id: run_id.to_string(),
                activation_id: next_id,
                round: next_round,
                node_id: edge.to_node.clone(),
                state: CircuitActivationStateV2::Ready,
                input_digest: completion.output_digest.clone(),
                predecessor_activation_id: Some(activation.activation_id),
                completion: None,
                created_at_ms: now_ms,
                updated_at_ms: now_ms,
            });
        }
        run.updated_at_ms = now_ms;
        sqlx::query(
            "UPDATE circuit_v2_runs SET
                state = ?, next_activation_id = ?, updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(run.state.as_str())
        .bind(i64::from(run.next_activation_id))
        .bind(to_i64(now_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .execute(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;

        let mut completed = activation;
        completed.state = CircuitActivationStateV2::Completed;
        completed.completion = Some(completion.clone());
        completed.updated_at_ms = now_ms;
        Ok(CircuitAdvanceV2 {
            completed,
            next_activation,
            run_state: run.state,
        })
    }
}

pub(crate) async fn verify_circuit_v2_store(
    pool: &sqlx::SqlitePool,
    owner_agent_id: &codex_hepta_contracts::AgentId,
) -> Result<(), TaskFlowError> {
    let foreign_definitions: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM circuit_v2_definitions WHERE owner_agent_id != ?",
    )
    .bind(owner_agent_id.as_str())
    .fetch_one(pool)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let foreign_runs: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM circuit_v2_runs WHERE owner_agent_id != ?")
            .bind(owner_agent_id.as_str())
            .fetch_one(pool)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
    let foreign_activations: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM circuit_v2_activations WHERE owner_agent_id != ?")
            .bind(owner_agent_id.as_str())
            .fetch_one(pool)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
    if foreign_definitions != 0 || foreign_runs != 0 || foreign_activations != 0 {
        return Err(TaskFlowError::StaleFence);
    }
    let malformed: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM circuit_v2_runs r
         LEFT JOIN circuit_v2_definitions d
           ON d.owner_agent_id = r.owner_agent_id
          AND d.circuit_id = r.circuit_id
          AND d.version = r.circuit_version
         WHERE d.circuit_id IS NULL OR d.definition_digest != r.definition_digest",
    )
    .fetch_one(pool)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    if malformed != 0 {
        return Err(corrupt("Circuit V2 run has no exact immutable definition"));
    }
    Ok(())
}

fn validate_circuit_fence(store: &AutomationStore, fence: &TaskFlowFence) -> Result<(), TaskFlowError> {
    if fence.owner_agent_id != *store.taskflow_owner_agent_id()
        || fence.owner_id.is_empty()
        || fence.owner_epoch == 0
        || fence.generation == 0
        || fence.fencing_token.is_empty()
    {
        return Err(TaskFlowError::StaleFence);
    }
    Ok(())
}

fn run_matches_fence(run: &CircuitRunV2, fence: &TaskFlowFence) -> bool {
    run.owner_id.as_deref() == Some(fence.owner_id.as_str())
        && run.owner_epoch == Some(fence.owner_epoch)
        && run.generation == Some(fence.generation)
        && run.fencing_token.as_deref() == Some(fence.fencing_token.as_str())
}

fn circuit_run_from_row(row: &sqlx::sqlite::SqliteRow) -> Result<CircuitRunV2, TaskFlowError> {
    let lease_json: String = row
        .try_get("fleet_lease_json")
        .map_err(|_| corrupt("Circuit V2 Fleet lease column"))?;
    let fleet_lease = serde_json::from_str(&lease_json)
        .map_err(|_| corrupt("Circuit V2 Fleet lease JSON invalid"))?;
    Ok(CircuitRunV2 {
        run_id: row
            .try_get("run_id")
            .map_err(|_| corrupt("Circuit V2 run id column"))?,
        circuit_id: row
            .try_get("circuit_id")
            .map_err(|_| corrupt("Circuit V2 circuit id column"))?,
        circuit_version: to_u32(
            row.try_get("circuit_version")
                .map_err(|_| corrupt("Circuit V2 version column"))?,
        )?,
        definition_digest: parse_digest(
            row.try_get("definition_digest")
                .map_err(|_| corrupt("Circuit V2 definition digest column"))?,
        )?,
        state: CircuitRunStateV2::parse(
            &row.try_get::<String, _>("state")
                .map_err(|_| corrupt("Circuit V2 state column"))?,
        )?,
        next_activation_id: to_u32(
            row.try_get("next_activation_id")
                .map_err(|_| corrupt("Circuit V2 next activation column"))?,
        )?,
        max_rounds: to_u32(
            row.try_get("max_rounds")
                .map_err(|_| corrupt("Circuit V2 max rounds column"))?,
        )?,
        max_activations: to_u32(
            row.try_get("max_activations")
                .map_err(|_| corrupt("Circuit V2 max activations column"))?,
        )?,
        fleet_lease,
        owner_id: row
            .try_get("owner_id")
            .map_err(|_| corrupt("Circuit V2 owner id column"))?,
        owner_epoch: optional_u64(
            row.try_get("owner_epoch")
                .map_err(|_| corrupt("Circuit V2 owner epoch column"))?,
        )?,
        generation: optional_u64(
            row.try_get("generation")
                .map_err(|_| corrupt("Circuit V2 generation column"))?,
        )?,
        fencing_token: row
            .try_get("fencing_token")
            .map_err(|_| corrupt("Circuit V2 fencing token column"))?,
        lease_expires_at_ms: optional_u64(
            row.try_get("lease_expires_at_ms")
                .map_err(|_| corrupt("Circuit V2 lease expiry column"))?,
        )?,
        created_at_ms: to_u64(
            row.try_get("created_at_ms")
                .map_err(|_| corrupt("Circuit V2 created time column"))?,
        )?,
        updated_at_ms: to_u64(
            row.try_get("updated_at_ms")
                .map_err(|_| corrupt("Circuit V2 updated time column"))?,
        )?,
    })
}

fn circuit_activation_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<CircuitActivationV2, TaskFlowError> {
    let completion_json: Option<String> = row
        .try_get("completion_json")
        .map_err(|_| corrupt("Circuit V2 completion column"))?;
    let completion = completion_json
        .as_deref()
        .map(serde_json::from_str)
        .transpose()
        .map_err(|_| corrupt("Circuit V2 completion JSON invalid"))?;
    Ok(CircuitActivationV2 {
        run_id: row
            .try_get("run_id")
            .map_err(|_| corrupt("Circuit V2 activation run id column"))?,
        activation_id: to_u32(
            row.try_get("activation_id")
                .map_err(|_| corrupt("Circuit V2 activation id column"))?,
        )?,
        round: to_u32(
            row.try_get("round")
                .map_err(|_| corrupt("Circuit V2 activation round column"))?,
        )?,
        node_id: row
            .try_get("node_id")
            .map_err(|_| corrupt("Circuit V2 activation node column"))?,
        state: CircuitActivationStateV2::parse(
            &row.try_get::<String, _>("state")
                .map_err(|_| corrupt("Circuit V2 activation state column"))?,
        )?,
        input_digest: parse_digest(
            row.try_get("input_digest")
                .map_err(|_| corrupt("Circuit V2 activation input column"))?,
        )?,
        predecessor_activation_id: optional_u32(
            row.try_get("predecessor_activation_id")
                .map_err(|_| corrupt("Circuit V2 predecessor column"))?,
        )?,
        completion,
        created_at_ms: to_u64(
            row.try_get("created_at_ms")
                .map_err(|_| corrupt("Circuit V2 activation created column"))?,
        )?,
        updated_at_ms: to_u64(
            row.try_get("updated_at_ms")
                .map_err(|_| corrupt("Circuit V2 activation updated column"))?,
        )?,
    })
}

fn validate_ports(ports: &[CircuitPortV2], kind: &str) -> Result<(), TaskFlowError> {
    if ports.len() > MAX_CIRCUIT_V2_PORTS_PER_NODE {
        return Err(invalid(format!(
            "Circuit V2 {kind} port count exceeds the bounded limit"
        )));
    }
    let mut names = BTreeSet::new();
    for port in ports {
        port.validate()?;
        if !names.insert(&port.name) {
            return Err(invalid(format!(
                "Circuit V2 {kind} ports contain duplicate names"
            )));
        }
    }
    Ok(())
}

fn reachable_nodes(
    entry: &str,
    adjacency: &BTreeMap<String, Vec<String>>,
) -> BTreeSet<String> {
    let mut seen = BTreeSet::from([entry.to_string()]);
    let mut frontier = vec![entry.to_string()];
    while let Some(node) = frontier.pop() {
        if let Some(targets) = adjacency.get(&node) {
            for target in targets {
                if seen.insert(target.clone()) {
                    frontier.push(target.clone());
                }
            }
        }
    }
    seen
}

fn validate_text(value: &str, field: &str) -> Result<(), TaskFlowError> {
    if value.is_empty()
        || value.len() > MAX_TEXT_BYTES
        || value.chars().any(char::is_control)
    {
        return Err(invalid(format!("{field} is invalid")));
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, field: &str) -> Result<(), TaskFlowError> {
    let value = digest.as_str();
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(invalid(format!("{field} must be a non-zero lowercase sha256")));
    }
    Ok(())
}

fn parse_digest(value: String) -> Result<Sha256Digest, TaskFlowError> {
    Sha256Digest::parse(value).map_err(|_| corrupt("invalid persisted sha256"))
}

fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| invalid("Circuit V2 integer exceeds SQLite range"))
}

fn to_u64(value: i64) -> Result<u64, TaskFlowError> {
    u64::try_from(value).map_err(|_| corrupt("negative Circuit V2 integer"))
}

fn to_u32(value: i64) -> Result<u32, TaskFlowError> {
    u32::try_from(value).map_err(|_| corrupt("Circuit V2 integer exceeds u32"))
}

fn optional_u64(value: Option<i64>) -> Result<Option<u64>, TaskFlowError> {
    value.map(to_u64).transpose()
}

fn optional_u32(value: Option<i64>) -> Result<Option<u32>, TaskFlowError> {
    value.map(to_u32).transpose()
}

fn is_unique(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation())
}

fn invalid(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Invalid(message.into())
}

fn corrupt(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Corrupt(message.into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CircuitEdgeV1;
    use crate::CircuitNodeV1;

    fn digest(label: &str) -> Sha256Digest {
        Sha256Digest::for_bytes(label.as_bytes())
    }

    fn v1() -> NeuralCircuitCandidateV1 {
        NeuralCircuitCandidateV1::new(
            "compat",
            1,
            None,
            "observe",
            vec![
                CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
                CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
                CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
                CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            ],
            vec![
                CircuitEdgeV1::new("observe", "decide"),
                CircuitEdgeV1::new("decide", "success"),
                CircuitEdgeV1::new("decide", "failure"),
            ],
            vec![],
            digest("route"),
            digest("parameters"),
            digest("resources"),
        )
        .expect("V1")
    }

    #[test]
    fn compatibility_compiler_preserves_v1_source_identity() {
        let source = v1();
        let v2 = CircuitDefinitionV2::from_neural_circuit_v1(&source).expect("compile V2");
        assert_eq!(
            v2.compatibility_source_digest.as_ref(),
            Some(&source.circuit_digest)
        );
        assert_eq!(v2.circuit_id, source.circuit_id);
        assert!(!v2.compile_plan().expect("plan").authority_granted);
    }

    #[test]
    fn delayed_feedback_is_separate_from_same_round_dag() {
        let schema = digest("signal");
        let nodes = vec![
            CircuitNodeV2::new("observe", CircuitNodeRoleV2::Observe)
                .with_ports(vec![], vec![CircuitPortV2::new("out", schema.clone()).unwrap()]),
            CircuitNodeV2::new("decide", CircuitNodeRoleV2::Decide).with_ports(
                vec![CircuitPortV2::new("in", schema.clone()).unwrap()],
                vec![CircuitPortV2::new("out", schema.clone()).unwrap()],
            ),
            CircuitNodeV2::new("success", CircuitNodeRoleV2::ExitSuccess)
                .with_ports(vec![CircuitPortV2::new("in", schema.clone()).unwrap()], vec![]),
        ];
        let edges = vec![
            CircuitEdgeV2::new("forward", "observe", "out", "decide", "in"),
            CircuitEdgeV2::new("exit", "decide", "out", "success", "in"),
            CircuitEdgeV2::new("feedback", "decide", "out", "decide", "in").feedback(1),
        ];
        let definition = CircuitDefinitionV2::new(
            "feedback",
            1,
            None,
            None,
            "observe",
            nodes,
            edges,
            vec![],
            digest("route"),
            digest("parameters"),
            digest("resources"),
            8,
            64,
        )
        .expect("definition");
        let plan = definition.compile_plan().expect("plan");
        assert_eq!(plan.feedback_edges, ["feedback"]);
        assert_eq!(plan.topological_order.len(), 3);
    }
}
