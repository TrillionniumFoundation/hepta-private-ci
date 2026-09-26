//! Versioned neural-circuit candidates compiled onto the existing TaskFlow owner.
//!
//! A circuit is a bounded control program, not a second executor, scheduler, store,
//! authority issuer, or topology owner. Structural evolution creates a successor
//! candidate with an exact predecessor digest. The active TaskFlow definition keeps
//! using the existing durable run/recovery path; widening capabilities requires a
//! separately governed topology/authority change.

use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::TaskFlowDefinition;
use crate::TaskFlowEdgeSpec;
use crate::TaskFlowError;
use crate::TaskFlowNodeKind;
use crate::TaskFlowNodeSpec;

pub const NEURAL_CIRCUIT_SCHEMA_VERSION: u32 = 1;
const MAX_CIRCUIT_NODES: usize = 256;
const MAX_CIRCUIT_EDGES: usize = 1_024;
const MAX_CIRCUIT_CAPABILITIES: usize = 256;
const MAX_ID_BYTES: usize = 256;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitNodeRoleV1 {
    Observe,
    Decide,
    TransformGuard,
    OrganCall,
    WaitJoin,
    Effect,
    ExitSuccess,
    ExitFailure,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitNodeV1 {
    pub node_id: String,
    pub role: CircuitNodeRoleV1,
    pub capability: Option<String>,
    pub idempotency_template: Option<String>,
    pub max_attempts: u32,
    pub wait_timeout_ms: Option<u64>,
}

impl CircuitNodeV1 {
    #[must_use]
    pub fn new(node_id: impl Into<String>, role: CircuitNodeRoleV1) -> Self {
        Self {
            node_id: node_id.into(),
            role,
            capability: None,
            idempotency_template: None,
            max_attempts: 1,
            wait_timeout_ms: None,
        }
    }

    #[must_use]
    pub fn effect(
        node_id: impl Into<String>,
        capability: impl Into<String>,
        idempotency_template: impl Into<String>,
    ) -> Self {
        Self {
            node_id: node_id.into(),
            role: CircuitNodeRoleV1::Effect,
            capability: Some(capability.into()),
            idempotency_template: Some(idempotency_template.into()),
            max_attempts: 1,
            wait_timeout_ms: None,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitEdgeV1 {
    pub from: String,
    pub to: String,
}

impl CircuitEdgeV1 {
    #[must_use]
    pub fn new(from: impl Into<String>, to: impl Into<String>) -> Self {
        Self {
            from: from.into(),
            to: to.into(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NeuralCircuitCandidateV1 {
    pub circuit_id: String,
    pub version: u32,
    pub predecessor_digest: Option<Sha256Digest>,
    pub entry_node: String,
    pub nodes: Vec<CircuitNodeV1>,
    pub edges: Vec<CircuitEdgeV1>,
    pub capability_set: Vec<String>,
    pub route_policy_digest: Sha256Digest,
    pub parameter_bundle_digest: Sha256Digest,
    pub resource_profile_digest: Sha256Digest,
    pub circuit_digest: Sha256Digest,
}

/// Unsealed named circuit inputs; construction validates and seals the candidate.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuralCircuitDefinitionV1 {
    pub circuit_id: String,
    pub version: u32,
    pub predecessor_digest: Option<Sha256Digest>,
    pub entry_node: String,
    pub nodes: Vec<CircuitNodeV1>,
    pub edges: Vec<CircuitEdgeV1>,
    pub capability_set: Vec<String>,
    pub route_policy_digest: Sha256Digest,
    pub parameter_bundle_digest: Sha256Digest,
    pub resource_profile_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitCompilationReceiptV1 {
    pub circuit_id: String,
    pub circuit_version: u32,
    pub circuit_digest: Sha256Digest,
    pub predecessor_digest: Option<Sha256Digest>,
    pub taskflow_definition_digest: Sha256Digest,
    pub authority_granted: bool,
}

impl NeuralCircuitCandidateV1 {
    pub fn new(definition: NeuralCircuitDefinitionV1) -> Result<Self, TaskFlowError> {
        let NeuralCircuitDefinitionV1 {
            circuit_id,
            version,
            predecessor_digest,
            entry_node,
            mut nodes,
            mut edges,
            mut capability_set,
            route_policy_digest,
            parameter_bundle_digest,
            resource_profile_digest,
        } = definition;
        nodes.sort_by(|left, right| left.node_id.cmp(&right.node_id));
        edges.sort_by(|left, right| {
            left.from
                .cmp(&right.from)
                .then_with(|| left.to.cmp(&right.to))
        });
        capability_set.sort();
        let mut candidate = Self {
            circuit_id,
            version,
            predecessor_digest,
            entry_node,
            nodes,
            edges,
            capability_set,
            route_policy_digest,
            parameter_bundle_digest,
            resource_profile_digest,
            circuit_digest: Sha256Digest::for_bytes(b"uncomputed-neural-circuit-v1"),
        };
        candidate.validate_shape()?;
        candidate.circuit_digest = candidate.compute_digest()?;
        Ok(candidate)
    }

    pub fn validate(&self) -> Result<(), TaskFlowError> {
        self.validate_shape()?;
        if self.circuit_digest != self.compute_digest()? {
            return Err(TaskFlowError::Corrupt(
                "neural circuit digest does not match canonical bytes".to_string(),
            ));
        }
        Ok(())
    }

    pub fn compile_taskflow(
        &self,
    ) -> Result<(TaskFlowDefinition, CircuitCompilationReceiptV1), TaskFlowError> {
        self.validate()?;
        let nodes = self
            .nodes
            .iter()
            .map(taskflow_node)
            .collect::<Result<Vec<_>, _>>()?;
        let edges = self
            .edges
            .iter()
            .map(|edge| TaskFlowEdgeSpec::new(&edge.from, &edge.to))
            .collect();
        let policy_digest = compiled_policy_digest(self)?;
        let definition = TaskFlowDefinition::new(
            format!("circuit:{}", self.circuit_id),
            self.version,
            &self.entry_node,
            nodes,
            edges,
            self.capability_set.clone(),
            policy_digest,
        )?;
        let receipt = CircuitCompilationReceiptV1 {
            circuit_id: self.circuit_id.clone(),
            circuit_version: self.version,
            circuit_digest: self.circuit_digest.clone(),
            predecessor_digest: self.predecessor_digest.clone(),
            taskflow_definition_digest: definition.definition_digest().clone(),
            authority_granted: false,
        };
        Ok((definition, receipt))
    }

    fn validate_shape(&self) -> Result<(), TaskFlowError> {
        validate_text(&self.circuit_id, "circuit_id")?;
        validate_text(&self.entry_node, "entry_node")?;
        if self.version == 0 {
            return Err(invalid("circuit version must be non-zero"));
        }
        match (self.version, self.predecessor_digest.as_ref()) {
            (1, None) => {}
            (1, Some(_)) => return Err(invalid("first circuit version cannot have a predecessor")),
            (_, None) => return Err(invalid("successor circuit requires predecessor digest")),
            (_, Some(digest)) => validate_digest(digest, "predecessor digest")?,
        }
        if self.nodes.is_empty() || self.nodes.len() > MAX_CIRCUIT_NODES {
            return Err(invalid("circuit node count is outside the bounded limit"));
        }
        if self.edges.len() > MAX_CIRCUIT_EDGES {
            return Err(invalid("circuit edge count exceeds the bounded limit"));
        }
        if self.capability_set.len() > MAX_CIRCUIT_CAPABILITIES {
            return Err(invalid(
                "circuit capability count exceeds the bounded limit",
            ));
        }
        validate_digest(&self.route_policy_digest, "route policy digest")?;
        validate_digest(&self.parameter_bundle_digest, "parameter bundle digest")?;
        validate_digest(&self.resource_profile_digest, "resource profile digest")?;
        let mut capabilities = BTreeSet::new();
        for capability in &self.capability_set {
            validate_text(capability, "capability")?;
            if !capabilities.insert(capability.as_str()) {
                return Err(invalid("circuit capability set contains a duplicate"));
            }
        }
        for node in &self.nodes {
            validate_text(&node.node_id, "node_id")?;
            if node.max_attempts == 0 || node.max_attempts > 32 {
                return Err(invalid("circuit node max_attempts must be in 1..=32"));
            }
            if let Some(capability) = node.capability.as_deref() {
                validate_text(capability, "node capability")?;
                if !capabilities.contains(capability) {
                    return Err(invalid("circuit node uses an undeclared capability"));
                }
            }
            if matches!(node.role, CircuitNodeRoleV1::Effect)
                && (node.capability.is_none() || node.idempotency_template.is_none())
            {
                return Err(invalid(
                    "circuit effect requires capability and idempotency template",
                ));
            }
            if !matches!(node.role, CircuitNodeRoleV1::Effect)
                && node.idempotency_template.is_some()
            {
                return Err(invalid(
                    "only a circuit effect may carry an idempotency template",
                ));
            }
        }
        // Reuse TaskFlow's graph, reachability and terminal checks. This also
        // guarantees that a candidate cannot smuggle a loop into the V1 owner.
        let _ = self.compile_unchecked_taskflow()?;
        Ok(())
    }

    fn compile_unchecked_taskflow(&self) -> Result<TaskFlowDefinition, TaskFlowError> {
        let nodes = self
            .nodes
            .iter()
            .map(taskflow_node)
            .collect::<Result<Vec<_>, _>>()?;
        let edges = self
            .edges
            .iter()
            .map(|edge| TaskFlowEdgeSpec::new(&edge.from, &edge.to))
            .collect();
        TaskFlowDefinition::new(
            format!("circuit:{}", self.circuit_id),
            self.version,
            &self.entry_node,
            nodes,
            edges,
            self.capability_set.clone(),
            compiled_policy_digest(self)?,
        )
    }

    fn compute_digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        #[derive(Serialize)]
        struct Canonical<'a> {
            schema_version: u32,
            circuit_id: &'a str,
            version: u32,
            predecessor_digest: &'a Option<Sha256Digest>,
            entry_node: &'a str,
            nodes: &'a [CircuitNodeV1],
            edges: &'a [CircuitEdgeV1],
            capability_set: &'a [String],
            route_policy_digest: &'a Sha256Digest,
            parameter_bundle_digest: &'a Sha256Digest,
            resource_profile_digest: &'a Sha256Digest,
        }
        let bytes = serde_json::to_vec(&Canonical {
            schema_version: NEURAL_CIRCUIT_SCHEMA_VERSION,
            circuit_id: &self.circuit_id,
            version: self.version,
            predecessor_digest: &self.predecessor_digest,
            entry_node: &self.entry_node,
            nodes: &self.nodes,
            edges: &self.edges,
            capability_set: &self.capability_set,
            route_policy_digest: &self.route_policy_digest,
            parameter_bundle_digest: &self.parameter_bundle_digest,
            resource_profile_digest: &self.resource_profile_digest,
        })
        .map_err(|error| TaskFlowError::Corrupt(format!("circuit serialization: {error}")))?;
        Ok(Sha256Digest::for_bytes(&bytes))
    }
}

/// Admit a structural successor without changing the active circuit in place.
/// Capability widening is intentionally rejected here; a separately governed
/// topology/authority transition must establish a wider capability ceiling.
pub fn validate_circuit_successor_v1(
    current: &NeuralCircuitCandidateV1,
    successor: &NeuralCircuitCandidateV1,
) -> Result<(), TaskFlowError> {
    current.validate()?;
    successor.validate()?;
    if current.circuit_id != successor.circuit_id {
        return Err(invalid("circuit successor changes stable circuit identity"));
    }
    let expected_version = current
        .version
        .checked_add(1)
        .ok_or_else(|| invalid("circuit version space is exhausted"))?;
    if successor.version != expected_version {
        return Err(invalid("circuit successor version is not monotone by one"));
    }
    if successor.predecessor_digest.as_ref() != Some(&current.circuit_digest) {
        return Err(invalid(
            "circuit successor predecessor does not match current digest",
        ));
    }
    let current_capabilities: BTreeSet<_> = current.capability_set.iter().collect();
    if successor
        .capability_set
        .iter()
        .any(|capability| !current_capabilities.contains(capability))
    {
        return Err(invalid(
            "circuit successor cannot widen capabilities without topology admission",
        ));
    }
    Ok(())
}

fn taskflow_node(node: &CircuitNodeV1) -> Result<TaskFlowNodeSpec, TaskFlowError> {
    let kind = match node.role {
        CircuitNodeRoleV1::Observe
        | CircuitNodeRoleV1::Decide
        | CircuitNodeRoleV1::TransformGuard
        | CircuitNodeRoleV1::OrganCall => TaskFlowNodeKind::Activity,
        CircuitNodeRoleV1::WaitJoin => TaskFlowNodeKind::Wait,
        CircuitNodeRoleV1::Effect => TaskFlowNodeKind::Effect,
        CircuitNodeRoleV1::ExitSuccess => TaskFlowNodeKind::TerminalSuccess,
        CircuitNodeRoleV1::ExitFailure => TaskFlowNodeKind::TerminalFailure,
    };
    let mut compiled = TaskFlowNodeSpec::new(&node.node_id, kind);
    compiled.capability.clone_from(&node.capability);
    compiled
        .idempotency_template
        .clone_from(&node.idempotency_template);
    compiled.max_attempts = node.max_attempts;
    compiled.wait_timeout_ms = node.wait_timeout_ms;
    compiled.recovery_path = true;
    Ok(compiled)
}

fn compiled_policy_digest(
    candidate: &NeuralCircuitCandidateV1,
) -> Result<Sha256Digest, TaskFlowError> {
    let mut bytes = b"hepta.neural-circuit.compiled-policy.v1\0".to_vec();
    for digest in [
        &candidate.route_policy_digest,
        &candidate.parameter_bundle_digest,
        &candidate.resource_profile_digest,
        &candidate.circuit_digest,
    ] {
        validate_digest(digest, "compiled policy input")?;
        bytes.extend_from_slice(digest.as_str().as_bytes());
        bytes.push(0);
    }
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn validate_text(value: &str, field: &str) -> Result<(), TaskFlowError> {
    if value.is_empty() || value.len() > MAX_ID_BYTES || value.chars().any(char::is_control) {
        return Err(invalid(format!("{field} is invalid")));
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, field: &str) -> Result<(), TaskFlowError> {
    let value = digest.as_str();
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || value.bytes().all(|byte| byte == b'0')
    {
        return Err(invalid(format!(
            "{field} must be a non-zero lowercase sha256"
        )));
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Invalid(message.into())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(label: &str) -> Sha256Digest {
        Sha256Digest::for_bytes(label.as_bytes())
    }

    fn v1() -> NeuralCircuitCandidateV1 {
        NeuralCircuitCandidateV1::new(NeuralCircuitDefinitionV1 {
            circuit_id: ("retrieval-control").into(),
            version: 1,
            predecessor_digest: None,
            entry_node: ("observe").into(),
            nodes: vec![
                CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
                CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
                CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
                CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            ],
            edges: vec![
                CircuitEdgeV1::new("observe", "decide"),
                CircuitEdgeV1::new("decide", "success"),
                CircuitEdgeV1::new("decide", "failure"),
            ],
            capability_set: vec![],
            route_policy_digest: digest("route-v1"),
            parameter_bundle_digest: digest("parameters-v1"),
            resource_profile_digest: digest("resources-v1"),
        })
        .expect("v1 circuit")
    }

    #[test]
    fn circuit_compiles_to_existing_taskflow_without_authority() {
        let circuit = v1();
        let (taskflow, receipt) = circuit.compile_taskflow().expect("compile");
        assert_eq!(taskflow.workflow_id, "circuit:retrieval-control");
        assert_eq!(taskflow.version, 1);
        assert_eq!(receipt.circuit_digest, circuit.circuit_digest);
        assert_eq!(
            receipt.taskflow_definition_digest,
            *taskflow.definition_digest()
        );
        assert!(!receipt.authority_granted);
    }

    #[test]
    fn successor_binds_exact_predecessor_and_can_change_route_and_parameters() {
        let current = v1();
        let successor = NeuralCircuitCandidateV1::new(NeuralCircuitDefinitionV1 {
            circuit_id: current.circuit_id.clone(),
            version: 2,
            predecessor_digest: Some(current.circuit_digest.clone()),
            entry_node: ("observe").into(),
            nodes: vec![
                CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
                CircuitNodeV1::new("guard", CircuitNodeRoleV1::TransformGuard),
                CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
                CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
                CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            ],
            edges: vec![
                CircuitEdgeV1::new("observe", "guard"),
                CircuitEdgeV1::new("guard", "decide"),
                CircuitEdgeV1::new("guard", "failure"),
                CircuitEdgeV1::new("decide", "success"),
                CircuitEdgeV1::new("decide", "failure"),
            ],
            capability_set: vec![],
            route_policy_digest: digest("route-v2"),
            parameter_bundle_digest: digest("parameters-v2"),
            resource_profile_digest: digest("resources-v1"),
        })
        .expect("successor");
        validate_circuit_successor_v1(&current, &successor).expect("admitted successor");
        assert_ne!(current.circuit_digest, successor.circuit_digest);
    }

    #[test]
    fn structural_successor_cannot_rebind_predecessor_or_widen_capabilities() {
        let current = v1();
        let wrong = NeuralCircuitCandidateV1::new(NeuralCircuitDefinitionV1 {
            circuit_id: current.circuit_id.clone(),
            version: 2,
            predecessor_digest: Some(digest("wrong-predecessor")),
            entry_node: ("observe").into(),
            nodes: current.nodes.clone(),
            edges: current.edges.clone(),
            capability_set: vec![],
            route_policy_digest: digest("route-v2"),
            parameter_bundle_digest: digest("parameters-v2"),
            resource_profile_digest: digest("resources-v1"),
        })
        .expect("wrong successor shape");
        assert!(validate_circuit_successor_v1(&current, &wrong).is_err());

        let widened = NeuralCircuitCandidateV1::new(NeuralCircuitDefinitionV1 {
            circuit_id: current.circuit_id.clone(),
            version: 2,
            predecessor_digest: Some(current.circuit_digest.clone()),
            entry_node: ("observe").into(),
            nodes: vec![
                CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
                CircuitNodeV1::effect("effect", "network.http", "circuit/{run}/effect"),
                CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
                CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            ],
            edges: vec![
                CircuitEdgeV1::new("observe", "effect"),
                CircuitEdgeV1::new("observe", "failure"),
                CircuitEdgeV1::new("effect", "success"),
                CircuitEdgeV1::new("effect", "failure"),
            ],
            capability_set: vec!["network.http".to_string()],
            route_policy_digest: digest("route-v2"),
            parameter_bundle_digest: digest("parameters-v2"),
            resource_profile_digest: digest("resources-v1"),
        })
        .expect("widened successor shape");
        assert!(validate_circuit_successor_v1(&current, &widened).is_err());
    }

    #[test]
    fn exhausted_version_space_rejects_same_version_successor() {
        let current = NeuralCircuitCandidateV1::new(NeuralCircuitDefinitionV1 {
            circuit_id: ("circuit-max-version").into(),
            version: u32::MAX,
            predecessor_digest: Some(digest("prior-version")),
            entry_node: ("observe").into(),
            nodes: vec![
                CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
                CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
                CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            ],
            edges: vec![
                CircuitEdgeV1::new("observe", "success"),
                CircuitEdgeV1::new("observe", "failure"),
            ],
            capability_set: Vec::new(),
            route_policy_digest: digest("route-max"),
            parameter_bundle_digest: digest("parameters-max"),
            resource_profile_digest: digest("resources-max"),
        })
        .expect("current max-version circuit");
        let successor = NeuralCircuitCandidateV1::new(NeuralCircuitDefinitionV1 {
            circuit_id: ("circuit-max-version").into(),
            version: u32::MAX,
            predecessor_digest: Some(current.circuit_digest.clone()),
            entry_node: ("observe").into(),
            nodes: current.nodes.clone(),
            edges: current.edges.clone(),
            capability_set: Vec::new(),
            route_policy_digest: digest("route-max-next"),
            parameter_bundle_digest: digest("parameters-max-next"),
            resource_profile_digest: digest("resources-max-next"),
        })
        .expect("same-version candidate remains structurally valid");
        assert!(matches!(
            validate_circuit_successor_v1(&current, &successor),
            Err(TaskFlowError::Invalid(message)) if message.contains("exhausted")
        ));
    }

    #[test]
    fn circuit_reuses_taskflow_cycle_and_terminal_rejection() {
        let result = NeuralCircuitCandidateV1::new(NeuralCircuitDefinitionV1 {
            circuit_id: ("loop").into(),
            version: 1,
            predecessor_digest: None,
            entry_node: ("a").into(),
            nodes: vec![
                CircuitNodeV1::new("a", CircuitNodeRoleV1::Decide),
                CircuitNodeV1::new("b", CircuitNodeRoleV1::TransformGuard),
                CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
                CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            ],
            edges: vec![
                CircuitEdgeV1::new("a", "b"),
                CircuitEdgeV1::new("b", "a"),
                CircuitEdgeV1::new("a", "success"),
                CircuitEdgeV1::new("b", "failure"),
            ],
            capability_set: vec![],
            route_policy_digest: digest("route"),
            parameter_bundle_digest: digest("params"),
            resource_profile_digest: digest("resources"),
        });
        assert!(result.is_err());
    }
}
