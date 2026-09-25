use super::*;

fn input() -> NativePreparedInputV1 {
    NativePreparedInputV1 {
        schema_version: 1,
        prompt: "Use the admitted evidence, not new model parameters.".to_string(),
        context_query: Some("original query".to_string()),
        agentd_socket: PathBuf::from("/tmp/original-owner.sock"),
        timeout_ms: 5_000,
        intelligence: Some(NativeIntelligenceInputBindingV1 {
            run_id: "original-intelligence-run".to_string(),
            expected_revision: 2,
            context_digest: "b".repeat(64),
            envelope_digest: "c".repeat(64),
        }),
    }
}

fn prepared_request() -> NativeRequest {
    NativeRequest {
        payload_digest: input().payload_digest().unwrap(),
        ..request("r1")
    }
}

#[test]
fn prepared_input_survives_reopen_compaction_and_exact_retry() {
    let path = path("prepared-input");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let expected = control
        .reserve_native_prepared(prepared_request(), 1, input())
        .unwrap();
    assert_eq!(expected.prepared_input, Some(input()));
    for _ in 0..3 {
        control.compact_journal().unwrap();
        drop(control);
        control = DurableInferenceControl::open(&path, 8).unwrap();
        assert_eq!(control.native_record("r1"), Some(&expected));
        assert_eq!(
            control
                .reserve_native_prepared(prepared_request(), 1, input())
                .unwrap(),
            expected
        );
    }
    control.dispatch_native("r1", dispatch()).unwrap();
    control.cancel_native("r1").unwrap();
    let expected = control.native_record("r1").unwrap().clone();
    control.compact_journal().unwrap();
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&expected));
    assert!(expected.cancel_requested);
    assert_eq!(expected.prepared_input, Some(input()));
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn prepared_payload_mutations_fail_before_reservation_or_io() {
    let path = path("prepared-mutation");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let original = input();
    for field in [
        "prompt", "query", "socket", "timeout", "run", "revision", "context", "envelope",
    ] {
        let mut changed = original.clone();
        match field {
            "prompt" => changed.prompt.push('!'),
            "query" => changed.context_query = Some("replacement".to_string()),
            "socket" => changed.agentd_socket = PathBuf::from("/tmp/other-owner.sock"),
            "timeout" => changed.timeout_ms += 1,
            "run" => changed.intelligence.as_mut().unwrap().run_id = "another-run".to_string(),
            "revision" => changed.intelligence.as_mut().unwrap().expected_revision += 1,
            "context" => changed.intelligence.as_mut().unwrap().context_digest = "d".repeat(64),
            "envelope" => changed.intelligence.as_mut().unwrap().envelope_digest = "e".repeat(64),
            _ => unreachable!(),
        }
        assert_eq!(
            control.reserve_native_prepared(prepared_request(), 1, changed),
            Err(Error::Conflict),
            "{field}"
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        assert!(control.native_record("r1").is_none());
    }
    control
        .reserve_native_prepared(prepared_request(), 1, original)
        .unwrap();
    let mut changed_request = prepared_request();
    changed_request.model = "new-model".to_string();
    assert_eq!(
        control.reserve_native_prepared(changed_request, 1, input()),
        Err(Error::Conflict)
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn malformed_prepared_inputs_are_not_admitted() {
    let original = input();
    for field in [
        "schema", "empty", "size", "relative", "timeout", "query", "revision",
    ] {
        let mut changed = original.clone();
        match field {
            "schema" => changed.schema_version = 2,
            "empty" => changed.prompt.clear(),
            "size" => changed.prompt = "x".repeat(32 * 1024 + 1),
            "relative" => changed.agentd_socket = PathBuf::from("relative.sock"),
            "timeout" => changed.timeout_ms = 0,
            "query" => changed.context_query = Some(String::new()),
            "revision" => changed.intelligence.as_mut().unwrap().expected_revision = 0,
            _ => unreachable!(),
        }
        assert!(changed.payload_digest().is_err(), "{field}");
    }
    let mut wire = serde_json::to_value(original).unwrap();
    wire["authority"] = true.into();
    assert!(serde_json::from_value::<NativePreparedInputV1>(wire).is_err());
}

#[test]
fn replay_and_checkpoint_reject_replaced_original_input() {
    for compact in [false, true] {
        let path = path("prepared-corruption");
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        control
            .reserve_native_prepared(prepared_request(), 1, input())
            .unwrap();
        if compact {
            control.compact_journal().unwrap();
        }
        drop(control);
        let bytes = std::fs::read_to_string(&path).unwrap();
        let changed = bytes.replace("original query", "replaced query");
        assert_ne!(changed, bytes);
        std::fs::write(&path, &changed).unwrap();
        assert!(DurableInferenceControl::open(&path, 8).is_err());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), changed);
        std::fs::remove_file(path).unwrap();
    }
}

#[test]
fn old_digest_only_history_is_not_silently_upgraded() {
    let path = path("prepared-legacy");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let legacy = control.reserve_native(prepared_request(), 1).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    assert_eq!(
        control
            .reserve_native_prepared(prepared_request(), 1, input())
            .unwrap(),
        legacy
    );
    assert!(
        control
            .native_record("r1")
            .unwrap()
            .prepared_input
            .is_none()
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn prepared_input_crash_child() {
    let Some(path) = std::env::var_os("HEPTA_NATIVE_PREPARED_CHILD") else {
        return;
    };
    let mut control = DurableInferenceControl::open(PathBuf::from(path), 8).unwrap();
    control
        .reserve_native_prepared(prepared_request(), 1, input())
        .unwrap();
    control.dispatch_native("r1", dispatch()).unwrap();
    std::process::exit(0);
}

#[test]
fn process_loss_recovers_original_input_and_retains_uncertain_reservation() {
    let path = path("prepared-process-loss");
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "durable_control::native::tests::prepared_input::prepared_input_crash_child",
        ])
        .env("HEPTA_NATIVE_PREPARED_CHILD", &path)
        .status()
        .unwrap();
    assert!(status.success());
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let recovered = control.native_record("r1").unwrap();
    assert_eq!(recovered.prepared_input, Some(input()));
    assert_eq!(recovered.state, NativeReservationState::Dispatching);
    assert_eq!(
        control.reserve_native(request("new"), 1),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(
        control.dispatch_native("r1", dispatch()),
        Err(Error::InvalidTransition)
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}
