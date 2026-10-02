use super::*;

const DIGEST: &str = "1111111111111111111111111111111111111111111111111111111111111111";

fn reply(selection: Option<&str>) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "schema": "hepta.native-file-picker.v1", "binary_digest": DIGEST, "selection": selection,
    }))
    .unwrap()
}

#[test]
fn selected_name_is_never_trimmed_or_lossily_replaced() {
    for path in [
        "/tmp/grant\n",
        "/tmp/grant\r\n",
        "/tmp/grant\0",
        "relative",
        "",
    ] {
        assert!(parse_reply(&reply(Some(path)), DIGEST).is_err());
    }
    assert!(
        parse_reply(
            &reply(Some(&format!("/{}", "a".repeat(MAX_SELECTION_BYTES)))),
            DIGEST
        )
        .is_err()
    );
    assert!(parse_reply(b"\xff", DIGEST).is_err());
}

#[cfg(unix)]
#[test]
fn typed_selection_preserves_spaces_unicode_and_backslashes() {
    let path = "/tmp/ 中 \\ file ";
    assert_eq!(
        parse_reply(&reply(Some(path)), DIGEST).unwrap(),
        Some(PathBuf::from(path))
    );
}

#[test]
fn cancellation_is_explicit_and_protocol_failures_are_errors() {
    assert_eq!(parse_reply(&reply(None), DIGEST).unwrap(), None);
    assert!(parse_reply(b"", DIGEST).is_err());
    assert!(parse_reply(&reply(None), &"2".repeat(64)).is_err());
    let mut malformed = reply(None);
    malformed.extend_from_slice(b"{}");
    assert!(parse_reply(&malformed, DIGEST).is_err());
    assert!(parse_reply(&vec![b' '; MAX_DIALOG_OUTPUT_BYTES + 1], DIGEST).is_err());
}

#[cfg(target_os = "linux")]
#[test]
fn portal_is_explicit_and_retired_backend_never_silently_falls_back() {
    assert!(validate_linux_backend(None).is_ok());
    assert!(validate_linux_backend(Some(OsStr::new("portal"))).is_ok());
    assert!(
        validate_linux_backend(Some(OsStr::new("zenity")))
            .unwrap_err()
            .to_string()
            .contains("retired")
    );
    assert!(validate_linux_backend(Some(OsStr::new("auto"))).is_err());
}

#[test]
fn helper_environment_does_not_inherit_unrelated_values() {
    let mut command = Command::new("fixture");
    command.env("HEPTA_UNTRUSTED_TEST_VALUE", "must-not-survive");
    restrict_desktop_environment(&mut command);
    assert!(
        command
            .get_envs()
            .all(|(key, _)| key != "HEPTA_UNTRUSTED_TEST_VALUE")
    );
}

#[cfg(unix)]
#[test]
fn owned_process_distinguishes_cancel_success_failure_and_timeout() {
    for selection in [None, Some("/tmp/selected")] {
        let encoded = String::from_utf8(reply(selection)).unwrap();
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "printf '%s' \"$1\"", "picker-fixture", &encoded]);
        assert_eq!(
            run_dialog(command, DIGEST, Duration::from_secs(2)).unwrap(),
            selection.map(PathBuf::from)
        );
    }
    let mut failed = Command::new("/bin/sh");
    failed.args(["-c", "exit 1"]);
    assert!(run_dialog(failed, DIGEST, Duration::from_secs(2)).is_err());
    let mut stalled = Command::new("/bin/sleep");
    stalled.arg("10");
    assert!(
        run_dialog(stalled, DIGEST, Duration::from_millis(20))
            .unwrap_err()
            .to_string()
            .contains("deadline")
    );
}

#[cfg(unix)]
#[test]
fn descendant_held_stdout_does_not_extend_picker_deadline() {
    for script in ["sleep 1.5 & exit 0", "sleep 1.5 & sleep 1.5"] {
        let mut command = Command::new("/bin/sh");
        command.args(["-c", script]);
        let started = Instant::now();
        assert!(run_dialog(command, DIGEST, Duration::from_millis(30)).is_err());
        assert!(started.elapsed() < Duration::from_millis(750));
    }
}

#[cfg(unix)]
#[test]
fn picker_drains_bytes_written_between_empty_read_and_exit_observation() {
    let root = tempfile::tempdir().unwrap();
    let release = root.path().join("release");
    let bytes = String::from_utf8(reply(Some("/tmp/late final result"))).unwrap();
    let mut command = Command::new("/bin/sh");
    command
        .args([
            "-c",
            "while [ ! -e \"$2\" ]; do sleep 0.01; done; printf '%s' \"$1\"",
            "picker-fixture",
            &bytes,
        ])
        .arg(&release);
    let result = run_dialog_at_boundary(command, DIGEST, Duration::from_secs(2), |child| {
        // Before this boundary the child cannot write. Between the empty read
        // and try_wait it writes the complete final frame and definitely exits.
        std::fs::write(&release, b"release")?;
        child.wait()?;
        Ok(())
    })
    .unwrap();
    assert_eq!(result, Some(PathBuf::from("/tmp/late final result")));
}
