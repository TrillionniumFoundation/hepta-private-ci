use std::error::Error as StdError;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::SchemaCodecError;
use codex_hepta_wire::WireEnvelopeV2;

use super::*;
use crate::CompilationRequest;
use crate::ContextItem;
use crate::ContextRole;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier rejected");
    };
    value
}

#[test]
fn compiler_composes_into_admitted_v2_transport_without_serializing_authority()
-> Result<(), Box<dyn StdError>> {
    let request = CompilationRequest {
        compilation_id: id("compile.wire.v2"),
        run_snapshot_digest: Digest32::of_bytes(b"snapshot"),
        objective_digest: Digest32::of_bytes(b"objective"),
        token_budget: 10,
        items: vec![ContextItem {
            item_id: id("instruction.1"),
            role: ContextRole::TrustedInstruction,
            content_digest: Digest32::of_bytes(b"content"),
            source_digest: Digest32::of_bytes(b"source"),
            token_count: 3,
            contains_secret: false,
        }],
    };
    let (receipt, envelope) =
        compile_to_wire_v2(request, id("context.compiler"), Generation::new(1)?)?;
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        envelope.schema().as_str(),
        CONTEXT_COMPILATION_WIRE_SCHEMA_V2
    );

    let decoded = decode_compilation_receipt_wire_v2(&envelope)?;
    assert_eq!(decoded.compilation_id, receipt.compilation_id.to_string());
    assert_eq!(decoded.context_digest, receipt.context_digest.to_string());
    assert!(!String::from_utf8_lossy(envelope.payload()).contains("authority"));
    assert!(matches!(
        encode_compilation_receipt_wire_v2(&receipt, id("runtime.agentd"), Generation::new(2)?,),
        Err(ContextWireError::UnexpectedProducer(_))
    ));
    Ok(())
}

#[test]
fn context_wire_rejects_unknown_fields_and_duplicate_id_partitions() -> Result<(), Box<dyn StdError>>
{
    let digest = Digest32::of_bytes(b"context");
    let invalid = WireEnvelopeV2::new(
        id(CONTEXT_COMPILATION_WIRE_SCHEMA_V2),
        id("context.compiler"),
        Generation::new(1)?,
        format!(
            "{{\"compilation_id\":\"compile.1\",\"trusted_instruction_ids\":[\"item.1\"],\"untrusted_evidence_ids\":[],\"omitted_ids\":[],\"used_tokens\":1,\"context_digest\":\"{digest}\",\"authority\":true}}"
        )
        .into_bytes(),
    )?;
    assert!(matches!(
        decode_compilation_receipt_wire_v2(&invalid),
        Err(ContextWireError::Codec(SchemaCodecError::Rejected(
            "context compilation schema rejected"
        )))
    ));

    let duplicate = WireEnvelopeV2::new(
        id(CONTEXT_COMPILATION_WIRE_SCHEMA_V2),
        id("context.compiler"),
        Generation::new(1)?,
        format!(
            "{{\"compilation_id\":\"compile.1\",\"trusted_instruction_ids\":[\"item.1\"],\"untrusted_evidence_ids\":[\"item.1\"],\"omitted_ids\":[],\"used_tokens\":1,\"context_digest\":\"{digest}\"}}"
        )
        .into_bytes(),
    )?;
    assert!(matches!(
        decode_compilation_receipt_wire_v2(&duplicate),
        Err(ContextWireError::Codec(SchemaCodecError::Rejected(
            "duplicate context id"
        )))
    ));

    let wrong_producer = WireEnvelopeV2::new(
        id(CONTEXT_COMPILATION_WIRE_SCHEMA_V2),
        id("runtime.agentd"),
        Generation::new(1)?,
        format!(
            "{{\"compilation_id\":\"compile.1\",\"trusted_instruction_ids\":[],\"untrusted_evidence_ids\":[],\"omitted_ids\":[],\"used_tokens\":0,\"context_digest\":\"{digest}\"}}"
        )
        .into_bytes(),
    )?;
    assert!(matches!(
        decode_compilation_receipt_wire_v2(&wrong_producer),
        Err(ContextWireError::UnexpectedProducer(_))
    ));
    Ok(())
}

#[test]
fn context_wire_rejects_impossible_token_accounting_on_encode_and_decode()
-> Result<(), Box<dyn StdError>> {
    let codec = ContextCompilationWireCodec::new()?;
    for (selected, used_tokens) in [
        (vec!["item.1".to_string()], 0),
        (vec!["item.1".to_string(), "item.2".to_string()], 1),
        (Vec::new(), 1),
        (vec!["item.1".to_string()], crate::MAX_TOKENS + 1),
        (vec!["item.1".to_string()], u64::MAX),
    ] {
        let value = ContextCompilationWireV2 {
            compilation_id: "compile.tokens".to_string(),
            trusted_instruction_ids: selected,
            untrusted_evidence_ids: Vec::new(),
            omitted_ids: vec!["omitted.1".to_string()],
            used_tokens,
            context_digest: Digest32::of_bytes(b"context").to_string(),
        };
        let rejected = Err(SchemaCodecError::Rejected(
            "invalid context token accounting",
        ));
        assert_eq!(codec.encode_value(&value), rejected);
        assert_eq!(
            codec.decode_value(&serde_json::to_vec(&value)?),
            Err(SchemaCodecError::Rejected(
                "invalid context token accounting"
            ))
        );
    }
    for (selected, used_tokens) in [
        (Vec::new(), 0),
        (vec!["item.1".to_string()], crate::MAX_TOKENS),
    ] {
        let value = ContextCompilationWireV2 {
            compilation_id: "compile.tokens.valid".to_string(),
            trusted_instruction_ids: selected,
            untrusted_evidence_ids: Vec::new(),
            omitted_ids: Vec::new(),
            used_tokens,
            context_digest: Digest32::of_bytes(b"context").to_string(),
        };
        assert_eq!(codec.decode_value(&codec.encode_value(&value)?)?, value);
    }
    Ok(())
}
