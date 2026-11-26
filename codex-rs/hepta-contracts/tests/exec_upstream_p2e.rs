//! Run the unchanged Hepta preflight over the shared raw-byte corpus.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::exec_server_start_p2c::CODEX_EXEC_SERVER_P2C_DESTINATION;
use codex_hepta_contracts::exec_server_start_p2c::CODEX_EXEC_SERVER_P2C_EFFECT_AUTHORITY;
use codex_hepta_contracts::exec_server_start_p2c::inspect_codex_exec_server_start_v1;
use codex_hepta_contracts::execution_contract_v1::EXECUTION_ENVELOPE_SCHEMA_VERSION_V1;
use codex_hepta_contracts::execution_contract_v1::ExecutionIntentV1;
use codex_hepta_contracts::execution_contract_v1::ExecutionTargetV1;
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
struct Case {
    id: String,
    raw: String,
    hepta_accepts: bool,
}

#[derive(Deserialize)]
struct Corpus {
    schema: u32,
    authority: String,
    operation_id: String,
    cases: Vec<Case>,
}

#[test]
fn shared_corpus_preserves_strict_profile_and_exact_byte_binding() {
    const { assert!(!CODEX_EXEC_SERVER_P2C_EFFECT_AUTHORITY) };
    let corpus: Corpus = serde_json::from_str(include_str!(
        "../../../qualification/codex-exec-p2e/corpus.json"
    ))
    .expect("shared corpus");
    assert_eq!(corpus.schema, 1);
    assert_eq!(corpus.authority, "DENY_ALL");
    assert_eq!(corpus.cases.len(), 50);
    for case in corpus.cases {
        let wire = case.raw.as_bytes();
        let intent = ExecutionIntentV1 {
            schema_version: EXECUTION_ENVELOPE_SCHEMA_VERSION_V1,
            operation_id: corpus.operation_id.clone(),
            subject_id: "agent:p2e".into(),
            scope_id: "scope:p2e".into(),
            destination_id: CODEX_EXEC_SERVER_P2C_DESTINATION.into(),
            target: ExecutionTargetV1::CodexExecServerProcess,
            generation: 3,
            fence: 4,
            authority_epoch: 5,
            payload_sha256: Sha256Digest::for_bytes(wire),
            payload_bytes: u32::try_from(wire.len()).expect("bounded wire"),
            deadline_unix_ms: 1_800_000_000_000,
            max_wall_ms: 2000,
        };
        let actual = inspect_codex_exec_server_start_v1(&intent, wire);
        assert_eq!(actual.is_ok(), case.hepta_accepts, "{}", case.id);
        if let Ok(observation) = actual {
            assert_eq!(observation.original_wire_sha256, intent.payload_sha256);
            let mut altered = wire.to_vec();
            altered.push(b' ');
            assert!(inspect_codex_exec_server_start_v1(&intent, &altered).is_err());
        }
        println!(
            "P2E_HEPTA_ROW {}",
            json!({"id": case.id, "accepted": case.hepta_accepts, "effect_authority": false})
        );
    }
}
