use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::SchemaRegistry;

use super::*;
use crate::CompilationRequest;
use crate::ContextItem;
use crate::ContextRole;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test id")
}

#[test]
fn compiler_composes_into_admitted_v2_transport_without_serializing_authority() {
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
    let (receipt, envelope) = compile_to_wire_v2(
        request,
        id("context.compiler"),
        Generation::new(1).expect("generation"),
    )
    .expect("compile to wire");
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(envelope.schema().as_str(), CONTEXT_COMPILATION_WIRE_SCHEMA_V2);

    let mut registry = SchemaRegistry::new();
    registry
        .register(context_compilation_wire_schema_v2().expect("schema"))
        .expect("register");
    let decoded: ContextCompilationWireV2 = registry.decode_typed(&envelope).expect("decode");
    assert_eq!(decoded.compilation_id, receipt.compilation_id.to_string());
    assert_eq!(decoded.context_digest, receipt.context_digest.to_string());
    assert!(!String::from_utf8_lossy(envelope.payload()).contains("authority"));
}
