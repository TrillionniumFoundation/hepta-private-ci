//! Exact compiled payload, physical binding and terminal output boundaries.

use super::*;
use codex_hepta_types::CellExecutionIntentV1;
use codex_hepta_types::ExecutionIntentKindV1;
use codex_hepta_types::FinalPayloadDigestV1;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde_json::json;

fn admitted() -> AdmittedTool {
    let params: ProcessStartParams = serde_json::from_value(json!({
        "host":"fixture", "executable":"/usr/bin/true",
        "env":{"ORIGINAL":"one"}, "idempotency_key":"tool:original", "timeout_seconds":10,
    }))
    .unwrap();
    let arguments = serde_json::to_vec(&params).unwrap();
    let digest = Digest32::of_bytes(&arguments);
    let generation = Generation::new(1).unwrap();
    let organ = StableId::new("organ:qualification").unwrap();
    let intent = RuntimeToolIntentV1 {
        cell: CellExecutionIntentV1 {
            operation_id: StableId::new("operation:original").unwrap(),
            cell_id: StableId::new("cell:qualification").unwrap(),
            organ_id: organ.clone(),
            generation,
            kind: ExecutionIntentKindV1::RuntimeTool,
            codex_binding: None,
            input_digest: Digest32::of_bytes(b"model-proposal"),
            final_payload: FinalPayloadDigestV1 {
                scope_id: organ,
                generation,
                payload_kind: StableId::new("process_start.params").unwrap(),
                digest,
            },
            deadline_ms: u64::MAX,
        },
        tool_id: StableId::new("process_start").unwrap(),
        arguments_digest: digest,
        idempotency_key: StableId::new("tool:original").unwrap(),
        host_scope: StableId::new("fixture").unwrap(),
    };
    AdmittedTool {
        intent,
        arguments,
        params,
    }
}

#[test]
fn compiled_payload_and_original_identity_cannot_be_substituted() {
    let original = admitted();
    validate_admission(&original, &original.intent, Some(&original.arguments)).unwrap();
    assert!(validate_admission(&original, &original.intent, Some(b"{}")).is_err());
    let mut altered = original.clone();
    altered.params.env.insert("ORIGINAL".into(), "two".into());
    assert!(validate_admission(&altered, &original.intent, None).is_err());
    let mut altered = original.clone();
    altered.params.idempotency_key = Some("tool:replacement".into());
    altered.arguments = serde_json::to_vec(&altered.params).unwrap();
    altered.intent.arguments_digest = Digest32::of_bytes(&altered.arguments);
    altered.intent.cell.final_payload.digest = altered.intent.arguments_digest;
    assert!(validate_admission(&altered, &altered.intent, None).is_err());
    let mut altered = original.clone();
    altered.params.host = "another-configured-host".to_owned();
    altered.arguments = serde_json::to_vec(&altered.params).unwrap();
    altered.intent.arguments_digest = Digest32::of_bytes(&altered.arguments);
    altered.intent.cell.final_payload.digest = altered.intent.arguments_digest;
    assert!(validate_admission(&altered, &altered.intent, None).is_err());
}

#[test]
fn runtime_binding_requires_full_digest_and_original_physical_host() {
    let original = admitted();
    let host: HostConfig = serde_json::from_value(json!({
        "ssh_target":"never-connect.invalid", "remote_state_dir":"/private-original",
        "execution_mode":"operator", "allow_execute":true, "allow_job_network":true,
    }))
    .unwrap();
    let envelope = json!({"job":{
        "id":"original-job", "host":"fixture", "ssh_target":host.ssh_target,
        "remote_job_dir":"/private-original/jobs/original-job", "execution_mode":"operator",
        "idempotency_key":"tool:original", "request_digest":runtime_request_digest(&original.params).unwrap(),
        "executable":"/usr/bin/true", "args":[], "cwd":null, "env_keys":["ORIGINAL"],
    }});
    assert_eq!(
        validate_job(&envelope, &original, &host).unwrap(),
        "original-job"
    );
    for (field, value) in [
        ("request_digest", Value::String("a".repeat(64))),
        ("ssh_target", json!("substituted.invalid")),
        ("remote_job_dir", json!("/different-root/jobs/original-job")),
        ("idempotency_key", json!("tool:replacement")),
    ] {
        let mut changed = envelope.clone();
        changed["job"][field] = value;
        assert!(validate_job(&changed, &original, &host).is_err(), "{field}");
    }
    let mut changed = original;
    changed.params.stdin = Some("changed but not present in JobRecord fields".into());
    assert!(validate_job(&envelope, &changed, &host).is_err());
}

fn terminal() -> Value {
    json!({
        "job_id":"original-job", "state":"succeeded", "exit_code":0,
        "terminal_publication_protocol":1, "terminal_publication_confirmed":true,
        "launch_nonce":"a123456789abcdef0123456789abcdef", "at_unix_ms":1,
        "cancelled":false, "timed_out":false,
        "output_complete":true, "output_durable":true,
        "log_bytes":{"stdout":{"stored":3,"seen":3},"stderr":{"stored":0,"seen":0}},
        "log_truncated":{"stdout":false,"stderr":false},
        "log_errors":{"stdout":null,"stderr":null},
        "log_synced":{"stdout":true,"stderr":true},
    })
}

#[test]
fn terminal_receipt_requires_witness_and_lossless_durable_streams() {
    assert!(
        terminal_proof(&terminal(), "original-job")
            .unwrap()
            .is_some()
    );
    assert!(
        terminal_proof(
            &json!({"job_id":"original-job","state":"status_unavailable",
        "outcome":"unknown"}),
            "original-job"
        )
        .unwrap()
        .is_none()
    );
    let mut value = terminal();
    value["terminal_publication_confirmed"] = json!(false);
    assert!(terminal_proof(&value, "original-job").is_err());
    let mut value = terminal();
    value["log_bytes"]["stdout"]["seen"] = json!(4);
    assert!(terminal_proof(&value, "original-job").is_err());
    let mut value = terminal();
    value["exit_code"] = json!(9);
    assert!(terminal_proof(&value, "original-job").is_err());
    assert!(terminal_proof(&terminal(), "replacement-job").is_err());
}

#[test]
fn binary_pages_preserve_independent_byte_cursors_and_reject_loss() {
    let first = json!({"offset":0,"next_offset":2,"size":3,"eof":false,
        "bytes_hex":"fff0","text":"\u{fffd}\u{fffd}"});
    let page = decode_page(&first, 0, 3, 2).unwrap();
    assert_eq!(page.bytes, [255, 240]);
    let second = json!({"offset":2,"next_offset":3,"size":3,"eof":true,"bytes_hex":"0a"});
    assert_eq!(
        decode_page(&second, page.next_offset, 3, 2).unwrap().bytes,
        [10]
    );
    let empty = json!({"offset":0,"next_offset":0,"size":0,"eof":true,"bytes_hex":""});
    assert!(decode_page(&empty, 0, 0, 2).unwrap().eof);
    assert!(decode_page(&first, 1, 3, 2).is_err());
    assert!(decode_page(&first, 0, 4, 2).is_err());
    assert!(decode_page(&first, 0, 3, 1).is_err());
    let mut gap = first.clone();
    gap["next_offset"] = json!(3);
    assert!(decode_page(&gap, 0, 3, 3).is_err());
    let mut lossy = first;
    lossy.as_object_mut().unwrap().remove("bytes_hex");
    assert!(decode_page(&lossy, 0, 3, 2).is_err());
}
