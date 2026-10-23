//! Qualification-only executable for the production codec. This creates no
//! source, store, authority, runtime owner or alternative contract definitions.

use std::error::Error;
use std::hint::black_box;
use std::io;
use std::io::Read;
use std::process::ExitCode;
use std::time::Instant;

use codex_hepta_cognitive_types::hnmf::CrossModalBindingV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1;
use codex_hepta_cognitive_types::hnmf_learning::EngramNodeV1;
use codex_hepta_cognitive_types::hnmf_learning::ForgetPropagationReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::MemoryCueV1;
use codex_hepta_cognitive_types::hnmf_learning::OutcomeSignalV1;
use codex_hepta_cognitive_types::hnmf_learning::PlasticityBatchV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1;
use codex_hepta_cognitive_types::hnmf_learning::ReplaySelectionReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::SynapseV1;
use codex_hepta_cognitive_types::hnmf_learning::TopologyProposalV1;
use codex_hepta_cognitive_types::shared_experience::SharedExperiencePublicationV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceRevocationReceiptV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceSnapshotV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceUseReceiptV2;
use codex_hepta_cognitive_types::wire::CognitiveContractV1;
use codex_hepta_cognitive_types::wire::CognitiveWireError;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_bound_v1;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
use codex_hepta_cognitive_types::wire::decode_validated_wire_v1;
use codex_hepta_cognitive_types::wire::encode_wire_v1;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

const MAX_INPUT_BYTES: usize = 1_048_576 + 1_024;

fn inspect<T: CognitiveContractV1>(bytes: &[u8], repeat: u32) -> Result<Value, CognitiveWireError> {
    let value = decode_validated_wire_v1::<T>(bytes)?;
    let encoded = encode_wire_v1(value.as_inner())?;
    if encoded != bytes {
        return Err(CognitiveWireError::NonCanonicalInput);
    }
    let frozen = canonical_contract_digest_v1(value.as_inner())?;
    let bound = canonical_contract_digest_bound_v1(value.as_inner())?;
    let start = Instant::now();
    for _ in 0..repeat {
        let decoded = decode_validated_wire_v1::<T>(black_box(bytes))?;
        black_box(encode_wire_v1(decoded.as_inner())?);
    }
    Ok(json!({
        "outcome": "accepted",
        "contract": T::CONTRACT_ID,
        "encoded_bytes": encoded.len(),
        "wire_sha256": Digest32::of_bytes(bytes).to_string(),
        "frozen_sha256": frozen.to_string(),
        "bound_sha256": bound.to_string(),
        "repeat": repeat,
        "elapsed_ns": start.elapsed().as_nanos().to_string(),
        "allocation_measurement": null,
    }))
}

fn dispatch(bytes: &[u8], repeat: u32) -> Result<Value, CognitiveWireError> {
    if bytes.len() > MAX_INPUT_BYTES {
        return Err(CognitiveWireError::EnvelopeLength {
            actual: bytes.len(),
            maximum: MAX_INPUT_BYTES,
        });
    }
    let envelope: Value = serde_json::from_slice(bytes).map_err(CognitiveWireError::Json)?;
    match envelope.get("contract").and_then(Value::as_str) {
        Some("ModalitySpanRefV1") => inspect::<ModalitySpanRefV1>(bytes, repeat),
        Some("MemoryEventV1") => inspect::<MemoryEventV1>(bytes, repeat),
        Some("CrossModalBindingV1") => inspect::<CrossModalBindingV1>(bytes, repeat),
        Some("EngramNodeV1") => inspect::<EngramNodeV1>(bytes, repeat),
        Some("SynapseV1") => inspect::<SynapseV1>(bytes, repeat),
        Some("MemoryCueV1") => inspect::<MemoryCueV1>(bytes, repeat),
        Some("RecallPacketV1") => inspect::<RecallPacketV1>(bytes, repeat),
        Some("OutcomeSignalV1") => inspect::<OutcomeSignalV1>(bytes, repeat),
        Some("ReplaySelectionReceiptV1") => inspect::<ReplaySelectionReceiptV1>(bytes, repeat),
        Some("PlasticityBatchV1") => inspect::<PlasticityBatchV1>(bytes, repeat),
        Some("TopologyProposalV1") => inspect::<TopologyProposalV1>(bytes, repeat),
        Some("ForgetPropagationReceiptV1") => inspect::<ForgetPropagationReceiptV1>(bytes, repeat),
        Some("SharedExperiencePublicationV2") => {
            inspect::<SharedExperiencePublicationV2>(bytes, repeat)
        }
        Some("SharedExperienceSnapshotV2") => inspect::<SharedExperienceSnapshotV2>(bytes, repeat),
        Some("SharedExperienceUseReceiptV2") => {
            inspect::<SharedExperienceUseReceiptV2>(bytes, repeat)
        }
        Some("SharedExperienceRevocationReceiptV2") => {
            inspect::<SharedExperienceRevocationReceiptV2>(bytes, repeat)
        }
        _ => Err(CognitiveWireError::ContractMismatch),
    }
}

fn run() -> Result<ExitCode, Box<dyn Error>> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let repeat: u32 = match args.as_slice() {
        [] => 1,
        [flag, count] if flag == "--repeat" => count.parse()?,
        _ => return Err(io::Error::other("usage: canonical_probe [--repeat 1..256]").into()),
    };
    if !(1..=256).contains(&repeat) {
        return Err(io::Error::other("repeat outside bounded profile").into());
    }
    let mut input = Vec::new();
    io::stdin()
        .lock()
        .take((MAX_INPUT_BYTES + 1) as u64)
        .read_to_end(&mut input)?;
    let (exit, report) = match dispatch(&input, repeat) {
        Ok(report) => (ExitCode::SUCCESS, report),
        Err(error) => (
            ExitCode::from(2),
            json!({ "outcome": "rejected", "violation": error.violation() }),
        ),
    };
    serde_json::to_writer(io::stdout().lock(), &report)?;
    Ok(exit)
}

fn main() -> ExitCode {
    match run() {
        Ok(exit) => exit,
        Err(error) => {
            eprintln!("qualification infrastructure error: {error}");
            ExitCode::FAILURE
        }
    }
}
