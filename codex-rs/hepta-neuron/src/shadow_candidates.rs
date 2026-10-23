//! Typed DecisionCell action/routing/topology/no-change shadow candidates.
//!
//! This is candidate binding, not candidate execution or self-directed split.
//! The caller must provide distinct candidate payloads; the no-change payload
//! is derived from the frozen current topology. Only an independent evaluator
//! may consider the proposals for future windows.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::PopulationSparseSignalReceiptV2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ShadowCellCandidateKindV1 {
    NoChange,
    Action,
    Routing,
    Topology,
}

impl ShadowCellCandidateKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::NoChange => 0,
            Self::Action => 1,
            Self::Routing => 2,
            Self::Topology => 3,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ShadowCellCandidateV1 {
    pub kind: ShadowCellCandidateKindV1,
    pub cell_id: StableId,
    pub objective_digest: Digest32,
    pub frozen_topology_digest: Digest32,
    pub parent_signal_digest: Digest32,
    pub payload_digest: Digest32,
    pub candidate_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ShadowCellCandidateSetV1 {
    pub no_change: ShadowCellCandidateV1,
    pub action: ShadowCellCandidateV1,
    pub routing: ShadowCellCandidateV1,
    pub topology: ShadowCellCandidateV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ShadowCellCandidateErrorV1 {
    EmptyDigest,
    IdentityCollision,
    InvalidSignal,
}

impl std::fmt::Display for ShadowCellCandidateErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for ShadowCellCandidateErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ShadowCellCandidatePayloadsV1 {
    pub action: Digest32,
    pub routing: Digest32,
    pub topology: Digest32,
}

/// Build a deterministic, authority-free candidate family from one exact
/// in-process neural signal receipt. Payloads are externally realized,
/// content-addressed proposals; this function does not invent an action.
pub fn propose_shadow_cell_candidates_v1(
    cell_id: StableId,
    objective_digest: Digest32,
    frozen_topology_digest: Digest32,
    signal: &PopulationSparseSignalReceiptV2,
    payloads: ShadowCellCandidatePayloadsV1,
) -> Result<ShadowCellCandidateSetV1, ShadowCellCandidateErrorV1> {
    if objective_digest.is_zero()
        || frozen_topology_digest.is_zero()
        || signal.config_digest.is_zero()
        || signal.input_digest.is_zero()
        || signal.checkpoint_after.is_zero()
        || signal.authority.grants_any()
        || signal.requires_calibration
    {
        return Err(ShadowCellCandidateErrorV1::InvalidSignal);
    }
    if payloads.action.is_zero() || payloads.routing.is_zero() || payloads.topology.is_zero() {
        return Err(ShadowCellCandidateErrorV1::EmptyDigest);
    }
    if payloads.action == payloads.routing
        || payloads.action == payloads.topology
        || payloads.routing == payloads.topology
        || [payloads.action, payloads.routing, payloads.topology]
            .contains(&frozen_topology_digest)
    {
        return Err(ShadowCellCandidateErrorV1::IdentityCollision);
    }

    let build = |kind: ShadowCellCandidateKindV1, payload_digest: Digest32| {
        let mut bytes = b"hepta.neuron.shadow-cell-candidate.v1\0".to_vec();
        let id = cell_id.as_str().as_bytes();
        bytes.extend_from_slice(&(id.len() as u32).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(objective_digest.as_array());
        bytes.extend_from_slice(frozen_topology_digest.as_array());
        bytes.extend_from_slice(signal.config_digest.as_array());
        bytes.extend_from_slice(signal.input_digest.as_array());
        bytes.extend_from_slice(signal.checkpoint_after.as_array());
        bytes.push(kind.tag());
        bytes.extend_from_slice(payload_digest.as_array());
        ShadowCellCandidateV1 {
            kind,
            cell_id: cell_id.clone(),
            objective_digest,
            frozen_topology_digest,
            parent_signal_digest: signal.checkpoint_after,
            payload_digest,
            candidate_digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        }
    };
    Ok(ShadowCellCandidateSetV1 {
        no_change: build(ShadowCellCandidateKindV1::NoChange, frozen_topology_digest),
        action: build(ShadowCellCandidateKindV1::Action, payloads.action),
        routing: build(ShadowCellCandidateKindV1::Routing, payloads.routing),
        topology: build(ShadowCellCandidateKindV1::Topology, payloads.topology),
    })
}

#[cfg(test)]
#[path = "shadow_candidates_tests.rs"]
mod tests;
