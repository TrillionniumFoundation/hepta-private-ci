use super::*;

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
fn unconfigured_console_preflight_never_creates_state_or_repairs_inputs() {
    let root = tempfile::tempdir().unwrap();
    let config = root.path().join("config.json");
    let state = root.path().join("state");
    let trust = root.path().join("missing-trust.json");
    let endpoint = root.path().join("missing-endpoint.json");
    std::fs::write(&config, serde_json::to_vec(&serde_json::json!({ "endpoint_manifest": endpoint, "trusted_keys": trust, "state_dir": state })).unwrap()).unwrap();
    let raw = ["--config".into(), config.to_str().unwrap().into()];
    assert!(load(&raw).is_err());
    assert!(!state.exists());
    assert!(!trust.exists());
    assert!(!endpoint.exists());
}

#[test]
fn chat_selection_remains_independent_when_console_is_absent_or_invalid() {
    let root = tempfile::tempdir().unwrap();
    let config = root.path().join("config.json");
    let chat = root.path().join("chat.json");
    let empty = ["--config".into(), config.to_str().unwrap().into()];
    assert!(
        hepta_native::launch_config::chat_config_path(&empty)
            .unwrap()
            .is_none()
    );
    assert!(load(&empty).is_err());
    let only_chat = ["--chat-config".into(), chat.to_str().unwrap().into()];
    assert_eq!(
        hepta_native::launch_config::chat_config_path(&only_chat).unwrap(),
        Some(chat.clone())
    );
    assert!(load(&only_chat).is_err());
    std::fs::write(
        &config,
        serde_json::to_vec(
            &serde_json::json!({"chat_config": chat, "endpoint_manifest": "invalid-console"}),
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(
        hepta_native::launch_config::chat_config_path(&empty).unwrap(),
        Some(chat.clone())
    );
    assert!(load(&empty).is_err());
}

#[test]
fn console_only_and_combined_configuration_keep_explicit_owner_selection() {
    let root = tempfile::tempdir().unwrap();
    let config = root.path().join("config.json");
    let chat = root.path().join("chat.json");
    let raw = ["--config".into(), config.to_str().unwrap().into()];
    let mut value = serde_json::json!({"endpoint_manifest": root.path().join("endpoint.json"), "trusted_keys": root.path().join("trust.json"), "state_dir": root.path().join("state")});
    std::fs::write(&config, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(
        hepta_native::launch_config::chat_config_path(&raw)
            .unwrap()
            .is_none()
    );
    let expanded = hepta_native::launch_config::expand_launch_arguments(&raw).unwrap();
    assert!(AppConfig::parse(&expanded).unwrap().chat_config.is_none());
    value["chat_config"] = serde_json::json!(chat);
    std::fs::write(&config, serde_json::to_vec(&value).unwrap()).unwrap();
    let expanded = hepta_native::launch_config::expand_launch_arguments(&raw).unwrap();
    assert_eq!(AppConfig::parse(&expanded).unwrap().chat_config, Some(chat));
}

#[test]
fn malformed_chat_selection_never_synthesizes_console_or_chat_authority() {
    assert!(
        hepta_native::launch_config::chat_config_path(&[
            "--chat-config".into(),
            "relative.json".into()
        ])
        .is_err()
    );
    assert!(hepta_native::launch_config::chat_config_path(&["--chat-config".into()]).is_err());
    assert!(
        hepta_native::launch_config::chat_config_path(&[
            "--chat-config".into(),
            "/one".into(),
            "--chat-config".into(),
            "/two".into()
        ])
        .is_err()
    );
}

#[test]
fn only_connection_unavailability_can_open_late_chat_fallback() {
    use hepta_native::error::ShellError;
    let unavailable =
        classify_console_connection_error(hepta_native::ui::NativeAppStartupError::Connection(
            ShellError::Io(std::io::Error::from(std::io::ErrorKind::ConnectionRefused)),
        ));
    assert!(unavailable.is::<ConsoleUnavailable>());
    for fatal in [
        ShellError::Security("invalid MAC".into()),
        ShellError::Update("rejected candidate".into()),
        ShellError::State("invalid generation".into()),
        ShellError::Indeterminate("unknown operation".into()),
        ShellError::Backend("invalid gateway identity".into()),
        ShellError::Io(std::io::Error::from(std::io::ErrorKind::PermissionDenied)),
    ] {
        assert!(
            !classify_console_connection_error(
                hepta_native::ui::NativeAppStartupError::Connection(fatal)
            )
            .is::<ConsoleUnavailable>()
        );
    }
    let rollback: Box<dyn std::error::Error> =
        "interrupted update rolled back; restart the admitted predecessor".into();
    assert!(!rollback.is::<ConsoleUnavailable>());
}

#[test]
fn state_and_updater_timeouts_after_connect_remain_fatal() {
    for stage in [
        "journal recovery",
        "session reference",
        "operation history",
        "pending update",
    ] {
        let error: hepta_native::ui::NativeAppStartupError = hepta_native::error::ShellError::Io(
            std::io::Error::new(std::io::ErrorKind::TimedOut, stage),
        )
        .into();
        let classified = classify_console_connection_error(error);
        assert!(
            !classified.is::<ConsoleUnavailable>(),
            "{stage} must not admit fallback"
        );
        assert!(classified.to_string().contains(stage));
    }
}
