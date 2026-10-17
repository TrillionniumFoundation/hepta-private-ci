//! Strict, explicitly versioned HPTC topology transport.
//! V1 read/audit decoding remains separate; neither codec supplies authority.

use std::error::Error;
use std::fmt;

use codex_hepta_types::RuntimeTopologyCandidateV2;
use codex_hepta_types::RuntimeTopologyContractErrorV2;
use codex_hepta_types::RuntimeTopologyDeltaV2;
use codex_hepta_types::RuntimeTopologyOperationV2;
use serde::Deserialize;
use serde::Serialize;

use super::platform_types_json::CanonicalU64String;
use super::platform_types_json::PlatformTypesWireError;
use super::platform_types_json::decode_json;
use super::platform_types_json::digest;
use super::platform_types_json::encode_json;
use super::platform_types_json::generation;
use super::platform_types_json::nonzero_digest;
use super::platform_types_json::stable_id;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedRuntimeTopologyCandidateV2(RuntimeTopologyCandidateV2);

impl ValidatedRuntimeTopologyCandidateV2 {
    pub fn new(mut value: RuntimeTopologyCandidateV2) -> Result<Self, PlatformTopologyV2WireError> {
        value
            .validate()
            .map_err(PlatformTopologyV2WireError::Topology)?;
        // Keep the validated owner bounded even when a small or empty DTO
        // arrives with arbitrarily large caller reservations.
        for delta in &mut value.deltas {
            if delta.related_module_ids.capacity() > RuntimeTopologyCandidateV2::MAX_DELTAS_V2 {
                delta.related_module_ids = std::mem::take(&mut delta.related_module_ids)
                    .into_boxed_slice()
                    .into_vec();
            }
        }
        if value.deltas.capacity() > RuntimeTopologyCandidateV2::MAX_DELTAS_V2 {
            value.deltas = value.deltas.into_boxed_slice().into_vec();
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_inner(&self) -> &RuntimeTopologyCandidateV2 {
        &self.0
    }

    #[must_use]
    pub fn into_inner(self) -> RuntimeTopologyCandidateV2 {
        self.0
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RuntimeTopologyCandidateV2Json {
    kind: String,
    proposal_digest: String,
    candidate_id: String,
    candidate_digest: String,
    baseline_generation: CanonicalU64String,
    candidate_generation: CanonicalU64String,
    selected_topology_digest: String,
    evaluation_digest: String,
    rollback_predecessor_digest: String,
    changed: bool,
    deltas: Vec<RuntimeTopologyDeltaV2Json>,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RuntimeTopologyDeltaV2Json {
    module_id: String,
    operation: String,
    related_module_ids: Vec<String>,
    predecessor_digest: String,
    candidate_digest: String,
    evidence_digest: String,
}

pub fn decode_runtime_topology_candidate_v2_json(
    bytes: &[u8],
) -> Result<ValidatedRuntimeTopologyCandidateV2, PlatformTopologyV2WireError> {
    let wire: RuntimeTopologyCandidateV2Json = decode_json(bytes)?;
    if wire.kind != "runtime_topology_candidate_v2" {
        return Err(PlatformTopologyV2WireError::Transport(
            PlatformTypesWireError::InvalidKind,
        ));
    }
    let value = RuntimeTopologyCandidateV2 {
        proposal_digest: nonzero_digest(&wire.proposal_digest, "proposal_digest")?,
        candidate_id: stable_id(
            "RuntimeTopologyCandidateV2",
            "candidate_id",
            &wire.candidate_id,
            "candidate_id",
        )?,
        candidate_digest: nonzero_digest(&wire.candidate_digest, "candidate_digest")?,
        baseline_generation: generation(wire.baseline_generation, "baseline_generation")?,
        candidate_generation: generation(wire.candidate_generation, "candidate_generation")?,
        selected_topology_digest: nonzero_digest(
            &wire.selected_topology_digest,
            "selected_topology_digest",
        )?,
        evaluation_digest: nonzero_digest(&wire.evaluation_digest, "evaluation_digest")?,
        rollback_predecessor_digest: nonzero_digest(
            &wire.rollback_predecessor_digest,
            "rollback_predecessor_digest",
        )?,
        changed: wire.changed,
        deltas: wire
            .deltas
            .into_iter()
            .map(decode_delta)
            .collect::<Result<Vec<_>, _>>()?,
    };
    ValidatedRuntimeTopologyCandidateV2::new(value)
}

pub fn encode_runtime_topology_candidate_v2_json(
    value: &ValidatedRuntimeTopologyCandidateV2,
) -> Result<Vec<u8>, PlatformTopologyV2WireError> {
    let value = value.as_inner();
    value
        .validate()
        .map_err(PlatformTopologyV2WireError::Topology)?;
    Ok(encode_json(&RuntimeTopologyCandidateV2Json {
        kind: "runtime_topology_candidate_v2".to_owned(),
        proposal_digest: value.proposal_digest.to_string(),
        candidate_id: value.candidate_id.to_string(),
        candidate_digest: value.candidate_digest.to_string(),
        baseline_generation: CanonicalU64String(value.baseline_generation.get()),
        candidate_generation: CanonicalU64String(value.candidate_generation.get()),
        selected_topology_digest: value.selected_topology_digest.to_string(),
        evaluation_digest: value.evaluation_digest.to_string(),
        rollback_predecessor_digest: value.rollback_predecessor_digest.to_string(),
        changed: value.changed,
        deltas: value.deltas.iter().map(encode_delta).collect(),
    })?)
}

fn decode_delta(
    wire: RuntimeTopologyDeltaV2Json,
) -> Result<RuntimeTopologyDeltaV2, PlatformTopologyV2WireError> {
    let operation = match wire.operation.as_str() {
        "add" => RuntimeTopologyOperationV2::Add,
        "replace" => RuntimeTopologyOperationV2::Replace,
        "retire" => RuntimeTopologyOperationV2::Retire,
        "rewire" => RuntimeTopologyOperationV2::Rewire,
        "split" => RuntimeTopologyOperationV2::Split,
        "merge" => RuntimeTopologyOperationV2::Merge,
        _ => {
            return Err(PlatformTopologyV2WireError::Transport(
                PlatformTypesWireError::InvalidOperation,
            ));
        }
    };
    Ok(RuntimeTopologyDeltaV2 {
        module_id: stable_id(
            "RuntimeTopologyCandidateV2",
            "deltas[].module_id",
            &wire.module_id,
            "module_id",
        )?,
        operation,
        related_module_ids: wire
            .related_module_ids
            .iter()
            .map(|value| {
                stable_id(
                    "RuntimeTopologyCandidateV2",
                    "deltas[].related_module_ids[]",
                    value,
                    "related_module_ids",
                )
            })
            .collect::<Result<Vec<_>, _>>()?,
        predecessor_digest: digest(&wire.predecessor_digest, "predecessor_digest")?,
        candidate_digest: digest(&wire.candidate_digest, "candidate_digest")?,
        evidence_digest: nonzero_digest(&wire.evidence_digest, "evidence_digest")?,
    })
}

fn encode_delta(value: &RuntimeTopologyDeltaV2) -> RuntimeTopologyDeltaV2Json {
    RuntimeTopologyDeltaV2Json {
        module_id: value.module_id.to_string(),
        operation: match value.operation {
            RuntimeTopologyOperationV2::Add => "add",
            RuntimeTopologyOperationV2::Replace => "replace",
            RuntimeTopologyOperationV2::Retire => "retire",
            RuntimeTopologyOperationV2::Rewire => "rewire",
            RuntimeTopologyOperationV2::Split => "split",
            RuntimeTopologyOperationV2::Merge => "merge",
        }
        .to_owned(),
        related_module_ids: value
            .related_module_ids
            .iter()
            .map(ToString::to_string)
            .collect(),
        predecessor_digest: value.predecessor_digest.to_string(),
        candidate_digest: value.candidate_digest.to_string(),
        evidence_digest: value.evidence_digest.to_string(),
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlatformTopologyV2WireError {
    Transport(PlatformTypesWireError),
    Topology(RuntimeTopologyContractErrorV2),
}

impl From<PlatformTypesWireError> for PlatformTopologyV2WireError {
    fn from(error: PlatformTypesWireError) -> Self {
        Self::Transport(error)
    }
}

impl fmt::Display for PlatformTopologyV2WireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PlatformTopologyV2WireError {}

#[cfg(test)]
#[path = "platform_topology_v2_json_tests.rs"]
mod tests;
