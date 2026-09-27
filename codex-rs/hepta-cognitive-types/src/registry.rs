//! Closed registry for production cognitive wire readers.

use std::fmt;

use serde::Deserialize;

use crate::wire::COGNITIVE_WIRE_VERSION_V1;
use crate::wire::CognitiveContractV1;
use crate::wire::CognitiveWireError;
use crate::wire::decode_wire_v1;
use crate::write_receipt::MEMORY_WRITE_RECEIPT_CONTRACT_ID_V1;
use crate::write_receipt::MEMORY_WRITE_RECEIPT_SCHEMA_ID_V1;

pub const MAX_REGISTERED_ENVELOPE_BYTES_V1: usize = 1_049_600;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RegisteredContractV1 {
    pub schema_id: &'static str,
    pub contract_id: &'static str,
}

pub const REGISTERED_CONTRACTS_V1: &[RegisteredContractV1] = &[
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.modality-span-ref.v1",
        contract_id: "ModalitySpanRefV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.memory-event.v1",
        contract_id: "MemoryEventV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.cross-modal-binding.v1",
        contract_id: "CrossModalBindingV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.engram-node.v1",
        contract_id: "EngramNodeV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.synapse.v1",
        contract_id: "SynapseV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.memory-cue.v1",
        contract_id: "MemoryCueV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.recall-packet.v1",
        contract_id: "RecallPacketV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.outcome-signal.v1",
        contract_id: "OutcomeSignalV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.replay-selection-receipt.v1",
        contract_id: "ReplaySelectionReceiptV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.plasticity-batch.v1",
        contract_id: "PlasticityBatchV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.topology-proposal.v1",
        contract_id: "TopologyProposalV1",
    },
    RegisteredContractV1 {
        schema_id: "hepta.hnmf.forget-propagation-receipt.v1",
        contract_id: "ForgetPropagationReceiptV1",
    },
    RegisteredContractV1 {
        schema_id: MEMORY_WRITE_RECEIPT_SCHEMA_ID_V1,
        contract_id: MEMORY_WRITE_RECEIPT_CONTRACT_ID_V1,
    },
];

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EnvelopeHeaderV1 {
    schema: String,
    schema_version: u32,
    contract: String,
    payload: serde_json::Value,
}

#[derive(Debug)]
pub enum RegistryErrorV1 {
    EmptyOrOversize,
    Json(serde_json::Error),
    UnknownContract { schema: String, contract: String },
    UnsupportedVersion(u32),
    RequestedTypeMismatch,
    Wire(CognitiveWireError),
}

impl fmt::Display for RegistryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for RegistryErrorV1 {}

pub fn inspect_registered_envelope_v1(
    bytes: &[u8],
) -> Result<RegisteredContractV1, RegistryErrorV1> {
    if bytes.is_empty() || bytes.len() > MAX_REGISTERED_ENVELOPE_BYTES_V1 {
        return Err(RegistryErrorV1::EmptyOrOversize);
    }
    let header: EnvelopeHeaderV1 =
        serde_json::from_slice(bytes).map_err(RegistryErrorV1::Json)?;
    let _ = header.payload;
    if header.schema_version != COGNITIVE_WIRE_VERSION_V1 {
        return Err(RegistryErrorV1::UnsupportedVersion(header.schema_version));
    }
    REGISTERED_CONTRACTS_V1
        .iter()
        .copied()
        .find(|entry| entry.schema_id == header.schema && entry.contract_id == header.contract)
        .ok_or(RegistryErrorV1::UnknownContract {
            schema: header.schema,
            contract: header.contract,
        })
}

pub fn decode_registered_wire_v1<T: CognitiveContractV1>(
    bytes: &[u8],
) -> Result<T, RegistryErrorV1> {
    let registered = inspect_registered_envelope_v1(bytes)?;
    if registered.schema_id != T::SCHEMA_ID || registered.contract_id != T::CONTRACT_ID {
        return Err(RegistryErrorV1::RequestedTypeMismatch);
    }
    decode_wire_v1(bytes).map_err(RegistryErrorV1::Wire)
}
