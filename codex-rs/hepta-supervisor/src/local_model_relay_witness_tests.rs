use super::*;
use pretty_assertions::assert_eq;

fn prompt(role: &str, candidate: Option<&str>) -> String {
    let binding = serde_json::to_string(&(
        "hepta.self-iteration.model-assessment.v1",
        "original.round.generator",
        role,
        Digest32::of_bytes(b"original-policy").to_string(),
        candidate,
        200_u64,
        1024_u32,
    ))
    .unwrap();
    format!(
        "{PURPOSE} Your output grants no authority. Return at most 1024 UTF-8 bytes.\nBinding: {binding}\nInput:\nactual bounded input"
    )
}

fn observation() -> Observation {
    Observation {
        directory: PathBuf::from("/run/unused-root-custody-test"),
        identity: "unused".to_string(),
        fact: RootModelTerminalReceiptV1 {
            schema: "hepta.root-model-terminal.v1".to_string(),
            binding: RootModelAssessmentBindingV1::parse(&prompt("Generator", None), 100)
                .unwrap()
                .unwrap(),
            subject: "actual.subject".to_string(),
            pid: 17,
            start_ticks: 33,
            cgroup: "actual.original.cgroup".to_string(),
            executable_sha256: "fixture-only".to_string(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
            model: "actual.model".to_string(),
            native_prompt: prompt("Generator", None),
            admitted_at_ms: 100,
            completed_at_ms: 0,
            response_id: String::new(),
            stream_sha256: [0; 32],
            model_output_sha256: [0; 32],
            model_output_bytes: 0,
        },
        stream: Sha256::new(),
        pending: Vec::new(),
        completed: None,
        failure: None,
    }
}

fn completed(output: Value) -> Vec<u8> {
    format!(
        "data: {}\r\n\r\n",
        serde_json::json!({
            "type":"response.completed", "response": {
                "id":"actual.response", "status":"completed", "output": output,
            }
        })
    )
    .into_bytes()
}

#[test]
fn fragmented_provider_terminal_preserves_exact_order_unicode_and_full_hash() {
    let bytes = completed(serde_json::json!([
        {"type":"reasoning"},
        {"type":"message","role":"assistant","content":[{"type":"output_text","text":"  中文\n"}]},
        {"type":"message","role":"assistant","content":[{"type":"output_text","text":"second"}]},
    ]));
    let mut original = observation();
    for fragment in bytes.chunks(1) {
        original.observe(fragment).unwrap();
    }
    assert_eq!(
        original.completed,
        Some(("actual.response".to_string(), "  中文\nsecond".to_string()))
    );
    assert!(original.pending.is_empty());
    assert_eq!(
        <[u8; 32]>::from(original.stream.finalize()),
        <[u8; 32]>::from(Sha256::digest(bytes))
    );
}

#[test]
fn incomplete_duplicate_tool_and_oversized_stream_never_form_terminal_facts() {
    let plain = serde_json::json!([{"type":"message","role":"assistant","content":[{"type":"output_text","text":"actual"}]}]);
    let mut original = observation();
    original
        .observe(b"data: {\"type\":\"response.output_text.delta\",\"delta\":\"unsettled\"}\n\n")
        .unwrap();
    assert!(original.completed.is_none());
    assert!(original.finish(150).is_err());
    let mut original = observation();
    original.observe(&completed(plain.clone())).unwrap();
    assert!(original.observe(&completed(plain)).is_err());
    for invalid in [
        serde_json::json!([{"type":"function_call","name":"cannot_grant_effect"}]),
        serde_json::json!([{"type":"message","role":"assistant","content":[{"type":"output_text","text":"x".repeat(1025)}]}]),
    ] {
        assert!(observation().observe(&completed(invalid)).is_err());
    }
    assert!(
        observation()
            .observe(&vec![b'x'; MAX_EVENT_BYTES + 1])
            .is_err()
    );
    assert!(
        observation()
            .observe(b"data: {\"type\":\"response.failed\"}\n\n")
            .is_err()
    );
}

#[test]
fn original_binding_rejects_expiry_wrong_role_and_invented_assessment_candidate() {
    assert!(
        RootModelAssessmentBindingV1::parse("normal user chat", 100)
            .unwrap()
            .is_none()
    );
    assert!(RootModelAssessmentBindingV1::parse(&prompt("Generator", None), 200).is_err());
    assert!(RootModelAssessmentBindingV1::parse(&prompt("Root", None), 100).is_err());
    assert!(RootModelAssessmentBindingV1::parse(&prompt("Evaluator", None), 100).is_err());
    assert!(
        RootModelAssessmentBindingV1::parse(
            &prompt("Generator", Some(&Digest32::ZERO.to_string())),
            100
        )
        .is_err()
    );
}

#[test]
fn workload_owned_files_are_not_root_terminal_custody() {
    if rustix::process::geteuid().as_raw() == 0 {
        return;
    }
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cannot.qualify.json");
    assert!(create_fact(&path, b"workload-projection").is_err());
    assert!(!path.exists());
}

#[test]
#[ignore = "requires an actual Root process and isolated protected /run directory"]
fn actual_root_custody_publishes_complete_bytes_once_without_replacement() {
    use std::os::unix::fs::MetadataExt;
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    let directory = tempfile::Builder::new()
        .prefix("hepta-model-terminal-test-")
        .tempdir_in("/run")
        .unwrap();
    let path = directory.path().join("original.intent.json");
    let original = b"complete original durable fact";
    create_fact(&path, original).unwrap();
    assert_eq!(store::read_protected(&path, 1024, true).unwrap(), original);
    let error = create_fact(&path, b"cannot overwrite original").unwrap_err();
    assert_eq!(
        error.downcast_ref::<std::io::Error>().unwrap().kind(),
        std::io::ErrorKind::AlreadyExists
    );
    assert_eq!(store::read_protected(&path, 1024, true).unwrap(), original);
    let metadata = std::fs::symlink_metadata(&path).unwrap();
    assert_eq!(
        (metadata.uid(), metadata.mode() & 0o777, metadata.nlink()),
        (0, 0o600, 1)
    );
    assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 1);
    let mut late = observation();
    late.directory = directory.path().to_path_buf();
    late.observe(&completed(serde_json::json!([
        {"type":"message","role":"assistant","content":[{"type":"output_text","text":"original late output"}]}
    ]))).unwrap();
    late.finish(201).unwrap();
    let outcome: RootModelOutcomeReceiptV1 = serde_json::from_slice(
        &store::read_protected(&directory.path().join("unused.terminal.json"), 16_384, true)
            .unwrap(),
    )
    .unwrap();
    let RootModelOutcomeReceiptV1::Completed { receipt } = outcome else {
        panic!("actual completed receipt absent")
    };
    assert!(receipt.completed_at_ms >= receipt.binding.deadline_ms);
    assert_eq!(receipt.native_prompt, prompt("Generator", None));
    assert_eq!(
        receipt.model_output_sha256,
        <[u8; 32]>::from(Sha256::digest(b"original late output"))
    );
    let mut failed = observation();
    failed.directory = directory.path().to_path_buf();
    failed.identity = "failed".to_string();
    assert!(
        failed
            .observe(
                b"data: {\"type\":\"response.failed\",\"response\":{\"id\":\"actual.failed\"}}\n\n"
            )
            .is_err()
    );
    let actual_failure = failed.failure().cloned().unwrap();
    failed.fail(actual_failure.clone(), 202).unwrap();
    let outcome: RootModelOutcomeReceiptV1 = serde_json::from_slice(
        &store::read_protected(&directory.path().join("failed.terminal.json"), 16_384, true)
            .unwrap(),
    )
    .unwrap();
    let RootModelOutcomeReceiptV1::Failed {
        failure,
        observed_at_ms,
        ..
    } = outcome
    else {
        panic!("actual failure receipt absent")
    };
    assert_eq!((failure, observed_at_ms), (actual_failure, 202));
}
