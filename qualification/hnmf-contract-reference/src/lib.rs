#![forbid(unsafe_code)]

//! Qualification-only conformance checks for the production cognitive contract owner.
//!
//! This package intentionally defines no cognitive/memory protocol structs. The
//! only canonical Rust definitions live in `codex-rs/hepta-cognitive-types`.
//! These checks bind the HNMF documentation/registry and qualification cases to
//! that production source without creating a second schema or authority spine.

use std::error::Error as StdError;
use std::fmt;

const CANONICAL_HNMF_SOURCE: &str =
    include_str!("../../../codex-rs/hepta-cognitive-types/src/hnmf.rs");
const CANONICAL_WIRE_SOURCE: &str =
    include_str!("../../../codex-rs/hepta-cognitive-types/src/wire.rs");
const CANONICAL_PORT_SOURCE: &str =
    include_str!("../../../codex-rs/hepta-cognitive-types/src/ports.rs");
const HNMF_TEST_SOURCE: &str =
    include_str!("../../../codex-rs/hepta-cognitive-types/src/hnmf_tests.rs");
const WIRE_TEST_SOURCE: &str =
    include_str!("../../../codex-rs/hepta-cognitive-types/src/wire_tests.rs");
const HNMF_REGISTRY: &str = include_str!("../../../docs/hnmf/HNMF.json");
const PROTOCOL_REGISTRY: &str =
    include_str!("../../../docs/contracts/PROTOCOL_SCHEMAS.json");
const PORT_REGISTRY: &str =
    include_str!("../../../docs/modules/cognitive.types/PORT_SCHEMAS.json");

pub const REQUIRED_PROTOCOLS: [&str; 12] = [
    "ModalitySpanRefV1",
    "MemoryEventV1",
    "CrossModalBindingV1",
    "EngramNodeV1",
    "SynapseV1",
    "MemoryCueV1",
    "RecallPacketV1",
    "OutcomeSignalV1",
    "ReplaySelectionReceiptV1",
    "PlasticityBatchV1",
    "MemoryTopologyProposalV1",
    "ForgetPropagationReceiptV1",
];

pub const CTYPE_CASES: [&str; 4] = [
    "ctype_01_modality_units_are_not_interchangeable",
    "ctype_02_asset_bounds_and_selectors_fail_closed",
    "ctype_03_correction_and_tombstone_are_distinct_semantics",
    "ctype_04_cross_language_canonical_vector_is_stable",
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReferenceError {
    MissingCanonicalType(&'static str),
    MissingRegistryProtocol(&'static str),
    MissingQualificationCase(&'static str),
    MissingWireInvariant(&'static str),
    MissingPortBinding(&'static str),
    TopologyProtocolCollision,
}

impl fmt::Display for ReferenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingCanonicalType(name) => {
                write!(formatter, "canonical cognitive type missing from production source: {name}")
            }
            Self::MissingRegistryProtocol(name) => {
                write!(formatter, "canonical cognitive protocol missing from registry: {name}")
            }
            Self::MissingQualificationCase(name) => {
                write!(formatter, "canonical cognitive qualification case missing: {name}")
            }
            Self::MissingWireInvariant(name) => {
                write!(formatter, "canonical wire invariant missing: {name}")
            }
            Self::MissingPortBinding(name) => {
                write!(formatter, "canonical cognitive port binding missing: {name}")
            }
            Self::TopologyProtocolCollision => formatter.write_str(
                "memory topology protocol collides with learning-owned TopologyProposalV1",
            ),
        }
    }
}

impl StdError for ReferenceError {}

pub fn verify_canonical_contract_owner() -> Result<(), ReferenceError> {
    for protocol in REQUIRED_PROTOCOLS {
        let struct_marker = format!("pub struct {protocol}");
        let enum_marker = format!("pub enum {protocol}");
        if !CANONICAL_HNMF_SOURCE.contains(&struct_marker)
            && !CANONICAL_HNMF_SOURCE.contains(&enum_marker)
        {
            return Err(ReferenceError::MissingCanonicalType(protocol));
        }
        let registry_marker = format!("\"id\": \"{protocol}\"");
        if !HNMF_REGISTRY.contains(&registry_marker)
            || !PROTOCOL_REGISTRY.contains(&registry_marker)
        {
            return Err(ReferenceError::MissingRegistryProtocol(protocol));
        }
    }

    for qualification_case in CTYPE_CASES {
        if !HNMF_TEST_SOURCE.contains(qualification_case)
            && !WIRE_TEST_SOURCE.contains(qualification_case)
        {
            return Err(ReferenceError::MissingQualificationCase(
                qualification_case,
            ));
        }
    }

    for invariant in [
        "pub trait CanonicalContractV1",
        "MAX_ENCODED_BYTES",
        "decode_canonical_json",
        "canonical != bytes",
        "contract_digest",
        "hepta.cognitive.canonical-json.v1",
    ] {
        if !CANONICAL_WIRE_SOURCE.contains(invariant) {
            return Err(ReferenceError::MissingWireInvariant(invariant));
        }
    }

    for port in [
        "ModulePort::cognitive.types::cognitive.read",
        "ModulePort::cognitive.types::cognitive.store",
        "ModulePort::cognitive.types::knowledge.graph",
        "ModulePort::cognitive.types::learning.ledger",
    ] {
        if !CANONICAL_PORT_SOURCE.contains(port) || !PORT_REGISTRY.contains(port) {
            return Err(ReferenceError::MissingPortBinding(port));
        }
    }

    let learning_topology = "\"id\": \"TopologyProposalV1\"";
    let memory_topology = "\"id\": \"MemoryTopologyProposalV1\"";
    if !PROTOCOL_REGISTRY.contains(learning_topology)
        || !PROTOCOL_REGISTRY.contains(memory_topology)
        || CANONICAL_HNMF_SOURCE.contains("pub struct TopologyProposalV1")
    {
        return Err(ReferenceError::TopologyProtocolCollision);
    }

    Ok(())
}

#[cfg(test)]
mod tests;
