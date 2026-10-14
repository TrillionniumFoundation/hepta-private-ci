use serde_json::Value;
use serde_json::json;

use super::*;
use crate::execution_contract_v1::EXECUTION_ENVELOPE_SCHEMA_VERSION_V1;

const OPERATION: &str = "operation:exec-start-1";

fn wire() -> Value {
    json!({
        "id": OPERATION,
        "method": "process/start",
        "params": {
            "processId": OPERATION,
            "argv": ["/bin/echo", "synthetic"],
            "cwd": "file:///tmp",
            "env": {},
            "tty": false,
            "pipeStdin": false,
            "arg0": null
        }
    })
}

fn serialize(value: Value) -> Vec<u8> {
    serde_json::to_vec(&value).expect("wire serialization")
}

fn intent_for(raw: &[u8]) -> ExecutionIntentV1 {
    ExecutionIntentV1 {
        schema_version: EXECUTION_ENVELOPE_SCHEMA_VERSION_V1,
        operation_id: OPERATION.into(),
        subject_id: "agent:p2c".into(),
        scope_id: "scope:p2c".into(),
        destination_id: CODEX_EXEC_SERVER_P2C_DESTINATION.into(),
        target: ExecutionTargetV1::CodexExecServerProcess,
        generation: 3,
        fence: 4,
        authority_epoch: 5,
        payload_sha256: Sha256Digest::for_bytes(raw),
        payload_bytes: u32::try_from(raw.len()).expect("bounded wire"),
        deadline_unix_ms: 1_800_000_000_000,
        max_wall_ms: 2000,
    }
}

fn reject(
    raw: Vec<u8>,
    expected: CodexExecServerStartPreflightErrorV1,
) {
    let intent = intent_for(&raw);
    assert_eq!(
        inspect_codex_exec_server_start_v1(&intent, &raw),
        Err(expected)
    );
}

#[test]
fn pinned_process_start_is_inspectable_but_has_no_effect_authority() {
    let raw = serialize(wire());
    let intent = intent_for(&raw);
    let observation =
        inspect_codex_exec_server_start_v1(&intent, &raw).expect("read-only check");
    assert_eq!(observation.operation_id, OPERATION);
    assert_eq!(observation.method, CODEX_EXEC_SERVER_P2C_START_METHOD);
    assert_eq!(observation.original_wire_sha256, intent.payload_sha256);
    assert_eq!(observation.argv_count, 2);
    assert_eq!(
        observation.request_sha256,
        intent.binding_proposal().expect("request binding").request_sha256
    );
    assert_ne!(observation.argv_sha256, [0; 32]);
    assert!(!CODEX_EXEC_SERVER_P2C_EFFECT_AUTHORITY);
}

#[test]
fn process_start_never_aliases_app_server_model_only_or_other_destination() {
    let raw = serialize(wire());
    let mut intent = intent_for(&raw);
    intent.target = ExecutionTargetV1::CodexAppServerModelOnly;
    assert_eq!(
        inspect_codex_exec_server_start_v1(&intent, &raw),
        Err(CodexExecServerStartPreflightErrorV1::NotExecServerProcess)
    );
    intent.target = ExecutionTargetV1::CodexExecServerProcess;
    intent.destination_id = "codex:other".into();
    assert_eq!(
        inspect_codex_exec_server_start_v1(&intent, &raw),
        Err(CodexExecServerStartPreflightErrorV1::WrongDestination)
    );
}

#[test]
fn all_non_start_methods_are_forbidden_even_when_exactly_digest_bound() {
    for method in [
        "process/read",
        "process/write",
        "process/signal",
        "process/terminate",
        "fs/readFile",
        "fs/remove",
        "fs/writeFile",
        "http/request",
        "environment/info",
        "initialize",
        "turn/start",
    ] {
        let mut value = wire();
        value["method"] = json!(method);
        reject(
            serialize(value),
            CodexExecServerStartPreflightErrorV1::ForbiddenRpcMethod,
        );
    }
}

#[test]
fn identity_correlation_binds_both_rpc_and_process_identity() {
    for changed in ["id", "processId"] {
        let mut value = wire();
        if changed == "id" {
            value["id"] = json!("other-request");
        } else {
            value["params"]["processId"] = json!("other-process");
        }
        reject(
            serialize(value),
            CodexExecServerStartPreflightErrorV1::WrongOperationIdentity,
        );
    }
}

#[test]
fn forged_or_modified_physical_wire_rejects_before_rpc_inspection() {
    let raw = serialize(wire());
    let mut tampered = raw.clone();
    tampered.push(b' ');
    assert_eq!(
        inspect_codex_exec_server_start_v1(&intent_for(&raw), &tampered),
        Err(CodexExecServerStartPreflightErrorV1::InvalidIntentOrPhysicalBytes)
    );
}

#[test]
fn duplicate_unknown_or_legacy_rpc_fields_fail_closed() {
    let mut value = wire();
    value["jsonrpc"] = json!("2.0");
    reject(
        serialize(value),
        CodexExecServerStartPreflightErrorV1::MalformedOrUnknownRpc,
    );
    let mut value = wire();
    value["trace"] = json!({"traceparent": "pretend"});
    reject(
        serialize(value),
        CodexExecServerStartPreflightErrorV1::MalformedOrUnknownRpc,
    );
    let mut value = wire();
    value["params"]["authority"] = json!("granted");
    reject(
        serialize(value),
        CodexExecServerStartPreflightErrorV1::MalformedOrUnknownRpc,
    );
    let raw = format!(
        "{{\"id\":\"{OPERATION}\",\"id\":\"forged\",\
         \"method\":\"process/start\",\"params\":{{}}}}"
    );
    reject(
        raw.into_bytes(),
        CodexExecServerStartPreflightErrorV1::MalformedOrUnknownRpc,
    );
}

#[test]
fn responses_notifications_non_string_ids_and_missing_params_reject() {
    for value in [
        json!({"id": OPERATION, "result": {"processId": OPERATION}}),
        json!({"method": "process/start", "params": wire()["params"]}),
        json!({"id": 1, "method": "process/start", "params": wire()["params"]}),
        json!({"id": OPERATION, "method": "process/start"}),
    ] {
        reject(
            serialize(value),
            CodexExecServerStartPreflightErrorV1::MalformedOrUnknownRpc,
        );
    }
}

#[test]
fn interactive_and_environment_expansion_require_a_different_profile() {
    for (field, setting) in [
        ("tty", json!(true)),
        ("pipeStdin", json!(true)),
        ("env", json!({"SECRET": "do-not-export"})),
        ("arg0", json!("impersonated-argv-zero")),
        ("cwd", json!("https://example.invalid/")),
        ("cwd", json!("file:///".to_string() + &"a".repeat(2049))),
    ] {
        let mut value = wire();
        value["params"][field] = setting;
        reject(
            serialize(value),
            CodexExecServerStartPreflightErrorV1::InvalidProcessProfile,
        );
    }
}

#[test]
fn argv_must_be_nonempty_bounded_and_without_nul() {
    for argv in [
        json!([]),
        json!([""]),
        json!(["a\u{0000}b"]),
        json!(vec!["a"; CODEX_EXEC_SERVER_P2C_MAX_ARGV_ENTRIES + 1]),
        json!(["x".repeat(4097)]),
        json!(["a".repeat(4096), "b".repeat(4096), "c"]),
    ] {
        let mut value = wire();
        value["params"]["argv"] = argv;
        reject(
            serialize(value),
            CodexExecServerStartPreflightErrorV1::InvalidProcessProfile,
        );
    }
}

#[test]
fn oversized_frames_fail_before_untrusted_rpc_parse() {
    let raw = b" ".repeat(CODEX_EXEC_SERVER_P2C_MAX_WIRE_BYTES + 1);
    reject(
        raw,
        CodexExecServerStartPreflightErrorV1::OversizedWire,
    );
}

#[test]
fn malicious_or_malformed_json_cannot_be_accepted_as_an_rpc() {
    for raw in [
        b"not-json".to_vec(),
        b"{}".to_vec(),
        b"[]".to_vec(),
        b"null".to_vec(),
    ] {
        reject(
            raw,
            CodexExecServerStartPreflightErrorV1::MalformedOrUnknownRpc,
        );
    }
}

#[test]
fn reordering_wire_object_members_does_not_change_meaning_but_binds_bytes() {
    let value = wire();
    let original = serialize(value.clone());
    let reordered = format!(
        "{{\"params\":{},\"method\":\"process/start\",\"id\":\"{OPERATION}\"}}",
        serde_json::to_string(&value["params"]).expect("params")
    );
    let reordered = reordered.into_bytes();
    let left = inspect_codex_exec_server_start_v1(&intent_for(&original), &original)
        .expect("left");
    let right = inspect_codex_exec_server_start_v1(&intent_for(&reordered), &reordered)
        .expect("right");
    assert_eq!(left.argv_sha256, right.argv_sha256);
    assert_ne!(left.request_sha256, right.request_sha256);
}
