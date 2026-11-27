use super::*;
use crate::durable_control::tests::held_journal_bytes;

type TestResult<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn input() -> TestResult<NativePreparedInputV2> {
    Ok(NativePreparedInputV2 {
        schema_version: 2,
        prompt: "Use only the original admitted evidence.".to_string(),
        context_query: Some("original query".to_string()),
        agentd_socket: std::path::absolute(std::env::temp_dir().join("original-owner.sock"))?,
        timeout_ms: 5_000,
        intelligence: Some(NativeIntelligenceInputBindingV2 {
            snapshot: NativeRunSnapshotV2 {
                run_id: "original-intelligence-run".to_string(),
                request_digest: "1".repeat(64),
                objective_digest: "2".repeat(64),
                body_digest: "3".repeat(64),
                artifact_set_digest: "4".repeat(64),
                authority_epoch: 9,
                generation: 5,
                fence_digest: "5".repeat(64),
                deadline_ms: 10_000,
            },
            expected_revision: 2,
            context_digest: "b".repeat(64),
            envelope_digest: "c".repeat(64),
        }),
    })
}

fn prepared_request() -> TestResult<NativeRequest> {
    Ok(NativeRequest {
        payload_digest: input()?.payload_digest()?,
        ..request("r1")
    })
}

#[test]
fn v2_input_survives_reopen_exact_retry_and_all_later_events() -> TestResult<()> {
    let path = path("prepared-v2-reopen");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let mut expected = control
        .reserve_native_prepared_v2(prepared_request()?, /*maximum_in_flight*/ 1, input()?)
        .unwrap();
    assert_eq!(expected.prepared_input_v2, Some(input()?));
    for _ in 0..3 {
        drop(control);
        control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
        assert_eq!(control.native_record("r1"), Some(&expected));
        let bytes = held_journal_bytes(&control.file).unwrap();
        assert_eq!(
            control
                .reserve_native_prepared_v2(
                    prepared_request()?,
                    /*maximum_in_flight*/ 1,
                    input()?
                )
                .unwrap(),
            expected
        );
        assert_eq!(held_journal_bytes(&control.file).unwrap(), bytes);
    }
    control.dispatch_native("r1", dispatch()).unwrap();
    control.native_started("r1", "turn-1".to_string()).unwrap();
    control.cancel_native("r1").unwrap();
    expected = control
        .settle_native("r1", output(NativeRunStatus::Interrupted, None))
        .unwrap();
    assert_eq!(expected.prepared_input_v2, Some(input()?));
    assert!(expected.cancel_requested);
    assert_eq!(expected.state, NativeReservationState::Released);
    drop(control);
    let control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&expected));
    drop(control);
    std::fs::remove_file(path).unwrap();
    Ok(())
}

#[test]
fn v2_payload_mutations_fail_before_reservation_or_io() -> TestResult<()> {
    let path = path("prepared-v2-mutation");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let bytes = held_journal_bytes(&control.file).unwrap();
    for field in [
        "prompt",
        "query",
        "socket",
        "timeout",
        "run",
        "request",
        "objective",
        "body",
        "artifacts",
        "epoch",
        "generation",
        "fence",
        "deadline",
        "revision",
        "context",
        "envelope",
    ] {
        let mut changed = input()?;
        let binding = changed.intelligence.as_mut().unwrap();
        match field {
            "prompt" => changed.prompt.push('!'),
            "query" => changed.context_query = Some("replacement".to_string()),
            "socket" => changed.agentd_socket.set_file_name("other-owner.sock"),
            "timeout" => changed.timeout_ms += 1,
            "run" => binding.snapshot.run_id.push_str("-other"),
            "request" => binding.snapshot.request_digest = "6".repeat(64),
            "objective" => binding.snapshot.objective_digest = "6".repeat(64),
            "body" => binding.snapshot.body_digest = "6".repeat(64),
            "artifacts" => binding.snapshot.artifact_set_digest = "6".repeat(64),
            "epoch" => binding.snapshot.authority_epoch += 1,
            "generation" => binding.snapshot.generation += 1,
            "fence" => binding.snapshot.fence_digest = "6".repeat(64),
            "deadline" => binding.snapshot.deadline_ms += 1,
            "revision" => binding.expected_revision += 1,
            "context" => binding.context_digest = "d".repeat(64),
            "envelope" => binding.envelope_digest = "e".repeat(64),
            _ => unreachable!(),
        }
        assert_eq!(
            control.reserve_native_prepared_v2(
                prepared_request()?,
                /*maximum_in_flight*/ 1,
                changed
            ),
            Err(Error::Conflict),
            "{field}"
        );
        assert_eq!(held_journal_bytes(&control.file).unwrap(), bytes);
        assert!(control.native_record("r1").is_none());
    }
    control
        .reserve_native_prepared_v2(prepared_request()?, /*maximum_in_flight*/ 1, input()?)
        .unwrap();
    let mut replacement = prepared_request()?;
    replacement.model = "replacement-model".to_string();
    assert_eq!(
        control.reserve_native_prepared_v2(replacement, /*maximum_in_flight*/ 1, input()?),
        Err(Error::Conflict)
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
    Ok(())
}

#[test]
fn v2_malformed_input_and_missing_snapshot_fields_are_rejected() -> TestResult<()> {
    for field in [
        "schema",
        "empty",
        "size",
        "relative",
        "timeout",
        "query",
        "revision",
        "epoch",
        "generation",
        "deadline",
        "digest",
    ] {
        let mut changed = input()?;
        match field {
            "schema" => changed.schema_version = 1,
            "empty" => changed.prompt.clear(),
            "size" => changed.prompt = "x".repeat(32 * 1024 + 1),
            "relative" => changed.agentd_socket = PathBuf::from("relative.sock"),
            "timeout" => changed.timeout_ms = 3_600_001,
            "query" => changed.context_query = Some(String::new()),
            "revision" => changed.intelligence.as_mut().unwrap().expected_revision = 0,
            "epoch" => {
                changed
                    .intelligence
                    .as_mut()
                    .unwrap()
                    .snapshot
                    .authority_epoch = 0
            }
            "generation" => changed.intelligence.as_mut().unwrap().snapshot.generation = 0,
            "deadline" => changed.intelligence.as_mut().unwrap().snapshot.deadline_ms = 0,
            "digest" => changed
                .intelligence
                .as_mut()
                .unwrap()
                .snapshot
                .request_digest
                .clear(),
            _ => unreachable!(),
        }
        assert!(changed.payload_digest().is_err(), "{field}");
    }
    let value = serde_json::to_value(input()?).unwrap();
    for field in [
        "run_id",
        "request_digest",
        "objective_digest",
        "body_digest",
        "artifact_set_digest",
        "authority_epoch",
        "generation",
        "fence_digest",
        "deadline_ms",
    ] {
        let mut missing = value.clone();
        missing["intelligence"]["snapshot"]
            .as_object_mut()
            .unwrap()
            .remove(field);
        assert!(
            serde_json::from_value::<NativePreparedInputV2>(missing).is_err(),
            "{field}"
        );
    }
    let mut unknown = value;
    unknown["intelligence"]["snapshot"]["current_snapshot_fallback"] = true.into();
    assert!(serde_json::from_value::<NativePreparedInputV2>(unknown).is_err());
    Ok(())
}

#[test]
fn v2_replay_rejects_replaced_input_without_repairing_bytes() -> TestResult<()> {
    let path = path("prepared-v2-corruption");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    control
        .reserve_native_prepared_v2(prepared_request()?, /*maximum_in_flight*/ 1, input()?)
        .unwrap();
    drop(control);
    let original = std::fs::read_to_string(&path).unwrap();
    let changed = original.replace("original query", "replaced query");
    assert_ne!(changed, original);
    std::fs::write(&path, &changed).unwrap();
    assert!(DurableInferenceControl::open(&path, /*capacity*/ 8).is_err());
    assert_eq!(std::fs::read_to_string(&path).unwrap(), changed);
    std::fs::remove_file(path).unwrap();
    Ok(())
}

#[test]
fn v2_never_upgrades_digest_only_history_from_ambient_input() -> TestResult<()> {
    let path = path("prepared-v2-legacy");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let legacy = control
        .reserve_native(prepared_request()?, /*maximum_in_flight*/ 1)
        .unwrap();
    let bytes = held_journal_bytes(&control.file).unwrap();
    assert_eq!(
        control
            .reserve_native_prepared_v2(prepared_request()?, /*maximum_in_flight*/ 1, input()?)
            .unwrap(),
        legacy
    );
    assert!(
        control
            .native_record("r1")
            .unwrap()
            .prepared_input_v2
            .is_none()
    );
    assert_eq!(held_journal_bytes(&control.file).unwrap(), bytes);
    drop(control);
    let control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    assert!(
        control
            .native_record("r1")
            .unwrap()
            .prepared_input_v2
            .is_none()
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
    Ok(())
}

#[test]
fn v1_run_id_only_input_cannot_be_reinterpreted_as_v3() -> TestResult<()> {
    let mut legacy = serde_json::to_value(input()?).unwrap();
    legacy["schema_version"] = 1.into();
    legacy["intelligence"]
        .as_object_mut()
        .unwrap()
        .remove("snapshot");
    legacy["intelligence"]["run_id"] = "original-intelligence-run".into();
    assert!(serde_json::from_value::<NativePreparedInputV2>(legacy).is_err());
    Ok(())
}

#[test]
fn v2_prepared_input_crash_child() -> TestResult<()> {
    let Some(path) = std::env::var_os("HEPTA_NATIVE_PREPARED_V2_CHILD") else {
        return Ok(());
    };
    let mut control = DurableInferenceControl::open(PathBuf::from(path), /*capacity*/ 8).unwrap();
    control
        .reserve_native_prepared_v2(prepared_request()?, /*maximum_in_flight*/ 1, input()?)
        .unwrap();
    control.dispatch_native("r1", dispatch()).unwrap();
    std::process::exit(0);
}

#[test]
fn v2_process_loss_retains_original_input_and_uncertain_slot() -> TestResult<()> {
    let path = path("prepared-v2-process-loss");
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "durable_control::native::tests::prepared_input_v2::v2_prepared_input_crash_child",
        ])
        .env("HEPTA_NATIVE_PREPARED_V2_CHILD", &path)
        .status()
        .unwrap();
    assert!(status.success());
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
    let recovered = control.native_record("r1").unwrap();
    assert_eq!(recovered.prepared_input_v2, Some(input()?));
    assert_eq!(recovered.state, NativeReservationState::Dispatching);
    assert_eq!(
        control.reserve_native(request("new"), /*maximum_in_flight*/ 1),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(
        control.dispatch_native("r1", dispatch()),
        Err(Error::InvalidTransition)
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
    Ok(())
}

#[path = "native_compaction_v3_tests.rs"]
mod compaction_tests;
