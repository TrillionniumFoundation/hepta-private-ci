use super::*;

#[test]
fn explicit_retry_rereads_inputs_and_success_consumes_retry_loop() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("input.json");
    std::fs::write(&path, "invalid").unwrap();
    let mut reads = 0;
    let mut recoveries = 0;
    let value = retry_inputs(
        || {
            reads += 1;
            let value = std::fs::read_to_string(&path).unwrap();
            if value == "valid" {
                Ok(value)
            } else {
                Err(StartupFailure::new(
                    StartupStage::Configuration,
                    "fixture input is not ready",
                ))
            }
        },
        |_| {
            recoveries += 1;
            if recoveries == 2 {
                std::fs::write(&path, "valid").unwrap();
            }
            Ok(StartupDecision::RetryInputs)
        },
    )
    .unwrap();
    assert_eq!((value, reads, recoveries), (Some("valid".into()), 3, 2));
}

#[test]
fn closing_recovery_never_reloads_or_admits_initialization() {
    let mut reads = 0;
    let mut initialization_calls = 0;
    let value = retry_inputs::<()>(
        || {
            reads += 1;
            Err(StartupFailure::new(
                StartupStage::Trust,
                "fixture rejection",
            ))
        },
        |_| Ok(StartupDecision::Exit),
    )
    .unwrap();
    if value.is_some() {
        initialization_calls += 1;
    }
    assert_eq!((reads, initialization_calls), (1, 0));
}

#[test]
fn machine_and_update_handoff_failures_remain_noninteractive() {
    for raw in [
        vec!["--check-connection".into()],
        vec![
            "--config".into(),
            "/fixture/config.json".into(),
            "--check-connection".into(),
        ],
        vec!["--update-handoff".into(), "fixture-nonce".into()],
    ] {
        assert!(!interactive_launch(&raw));
    }
    assert!(interactive_launch(&[]));
    assert!(interactive_launch(&[
        "--config".into(),
        "/fixture/config.json".into()
    ]));
}

#[test]
fn malformed_machine_invocations_never_open_recovery_ui() {
    for flag in [
        "--native-picker-helper",
        "--native-notification-helper",
        "--register-notification-identity",
        "--qualification-e2e",
        "--qualification-journal-child",
        "--qualification-updater-child",
        "--self-test",
        "--help",
    ] {
        assert!(!interactive_launch(&[flag.into(), "unexpected".into()]));
    }
}

#[test]
fn real_input_retry_never_creates_state_or_repairs_untrusted_inputs() {
    let root = tempfile::tempdir().unwrap();
    let config = root.path().join("config.json");
    let state = root.path().join("state");
    let trust = root.path().join("missing-trust.json");
    let endpoint = root.path().join("missing-endpoint.json");
    std::fs::write(
        &config,
        serde_json::to_vec(&serde_json::json!({
            "endpoint_manifest": endpoint,
            "trusted_keys": trust,
            "state_dir": state
        }))
        .unwrap(),
    )
    .unwrap();
    let raw = ["--config".into(), config.to_str().unwrap().into()];
    let mut failures = 0;
    let result = retry_inputs(
        || load(&raw),
        |_| {
            failures += 1;
            Ok(if failures == 1 {
                StartupDecision::RetryInputs
            } else {
                StartupDecision::Exit
            })
        },
    )
    .unwrap();
    assert!(result.is_none());
    assert_eq!(failures, 2);
    assert!(!state.exists());
    assert!(!trust.exists());
    assert!(!endpoint.exists());
}
