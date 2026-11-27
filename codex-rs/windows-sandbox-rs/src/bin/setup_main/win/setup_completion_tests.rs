use super::super::Payload;
use super::super::SetupMode;
use super::finish_acl_setup;
use super::run_with_marker;
use anyhow::Result;
use codex_windows_sandbox::SETUP_VERSION;
use codex_windows_sandbox::SetupErrorCode;
use codex_windows_sandbox::SetupFailure;
use codex_windows_sandbox::extract_setup_failure;
use pretty_assertions::assert_eq;
use std::cell::RefCell;
use std::fs;
use std::io;
use std::io::Write;

struct Observation {
    outcome: Result<()>,
    calls: Vec<&'static str>,
    marker: Vec<u8>,
}

// Exercise production completion with owned marker I/O and collected ACL outcomes.
// These controls do not provision accounts, change ACLs, or configure the firewall.
fn observe_completion(
    refresh_only: bool,
    errors: &[String],
    work_result: Result<()>,
    log: &mut dyn Write,
) -> Observation {
    let temp = tempfile::tempdir().expect("owned marker directory");
    let marker = temp.path().join("setup_marker.json");
    fs::write(&marker, b"previous-ready").expect("seed marker");
    let payload = Payload {
        version: SETUP_VERSION,
        offline_username: "unused-offline".to_string(),
        online_username: "unused-online".to_string(),
        codex_home: temp.path().to_path_buf(),
        command_cwd: temp.path().to_path_buf(),
        read_roots: Vec::new(),
        write_roots: Vec::new(),
        deny_read_paths: Vec::new(),
        deny_write_paths: Vec::new(),
        proxy_ports: Vec::new(),
        allow_local_binding: false,
        otel: None,
        real_user: "unused-user".to_string(),
        mode: SetupMode::Full,
        refresh_only,
    };
    let calls = RefCell::new(Vec::new());
    let outcome = run_with_marker(
        &payload,
        || {
            calls.borrow_mut().push("prepare");
            fs::write(&marker, b"")?;
            Ok(())
        },
        || {
            calls.borrow_mut().push("work");
            assert_eq!(
                fs::read(&marker).expect("marker before work"),
                if refresh_only {
                    b"previous-ready".to_vec()
                } else {
                    Vec::new()
                },
            );
            finish_acl_setup(&payload, errors, work_result, log)
        },
        || {
            calls.borrow_mut().push("commit");
            fs::write(&marker, b"ready")?;
            Ok(())
        },
    );
    let observation = Observation {
        outcome,
        calls: calls.into_inner(),
        marker: fs::read(&marker).expect("marker after completion"),
    };
    temp.close().expect("close owned marker directory");
    observation
}

fn assert_acl_failures(refresh_only: bool) {
    for errors in [
        vec!["write ACE failed on grant-root: access denied".to_string()],
        vec!["deny ACE failed on protected-child: access denied".to_string()],
        vec![
            "write ACE check failed on first-root: unreadable DACL".to_string(),
            "write ACE failed on grant-root: access denied".to_string(),
            "deny ACE failed on protected-child: access denied".to_string(),
        ],
    ] {
        let mut log = Vec::new();
        let observation = observe_completion(refresh_only, &errors, Ok(()), &mut log);
        let error = observation
            .outcome
            .expect_err("ACL failure must reject setup");
        let phase = if refresh_only {
            "setup refresh"
        } else {
            "setup"
        };
        let expected = SetupFailure::new(
            SetupErrorCode::HelperUnknownError,
            format!("{phase} completed with errors: {errors:?}"),
        );
        assert_eq!(extract_setup_failure(&error), Some(&expected));
        assert_eq!(error.to_string(), format!("{phase} had errors"));
        assert_eq!(
            (observation.calls, observation.marker),
            if refresh_only {
                (vec!["work"], b"previous-ready".to_vec())
            } else {
                (vec!["prepare", "work"], Vec::new())
            },
        );
        assert!(
            String::from_utf8(log)
                .expect("UTF-8 log")
                .ends_with(&format!("{}\n", expected.message))
        );
    }
}

#[test]
fn full_setup_commits_only_after_success() {
    let observation = observe_completion(/*refresh_only*/ false, &[], Ok(()), &mut Vec::new());
    observation.outcome.expect("full setup success");
    assert_eq!(
        (observation.calls, observation.marker),
        (vec!["prepare", "work", "commit"], b"ready".to_vec()),
    );
}

#[test]
fn refresh_success_does_not_rewrite_existing_marker() {
    let observation = observe_completion(/*refresh_only*/ true, &[], Ok(()), &mut Vec::new());
    observation.outcome.expect("refresh success");
    assert_eq!(
        (observation.calls, observation.marker),
        (vec!["work"], b"previous-ready".to_vec()),
    );
}

#[test]
fn full_setup_acl_failures_keep_marker_unready() {
    assert_acl_failures(/*refresh_only*/ false);
}

#[test]
fn refresh_acl_failures_do_not_commit_marker() {
    assert_acl_failures(/*refresh_only*/ true);
}

#[test]
fn collected_acl_errors_survive_later_setup_failure() {
    let errors = vec![
        "write ACE failed on grant-root: access denied".to_string(),
        "deny ACE failed on protected-child: access denied".to_string(),
    ];
    for refresh_only in [false, true] {
        let original = SetupFailure::new(
            SetupErrorCode::HelperSandboxLockFailed,
            "fixture final lock failed",
        );
        let expected_message = format!(
            "{} completed with errors: {errors:?}; setup also failed: {original}",
            if refresh_only {
                "setup refresh"
            } else {
                "setup"
            },
        );
        let observation = observe_completion(
            refresh_only,
            &errors,
            Err(anyhow::Error::new(original)),
            &mut Vec::new(),
        );
        let error = observation.outcome.expect_err("later setup failure");
        assert_eq!(
            extract_setup_failure(&error),
            Some(&SetupFailure::new(
                SetupErrorCode::HelperSandboxLockFailed,
                expected_message,
            )),
        );
        assert_eq!(
            (observation.calls, observation.marker),
            if refresh_only {
                (vec!["work"], b"previous-ready".to_vec())
            } else {
                (vec!["prepare", "work"], Vec::new())
            },
        );
    }
}

struct FailedLog;

impl Write for FailedLog {
    fn write(&mut self, _buffer: &[u8]) -> io::Result<usize> {
        Err(io::Error::other("fixture log failure"))
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[test]
fn collected_acl_errors_survive_failed_error_log() {
    let errors = vec!["deny ACE failed on protected-child: access denied".to_string()];
    for refresh_only in [false, true] {
        let observation = observe_completion(refresh_only, &errors, Ok(()), &mut FailedLog);
        let error = observation.outcome.expect_err("ACL and log failure");
        let phase = if refresh_only {
            "setup refresh"
        } else {
            "setup"
        };
        assert_eq!(
            extract_setup_failure(&error),
            Some(&SetupFailure::new(
                SetupErrorCode::HelperLogFailed,
                format!(
                    "{phase} completed with errors: {errors:?}; error log also failed: helper_log_failed: failed to write setup log line: fixture log failure"
                ),
            )),
        );
        assert_eq!(
            (observation.calls, observation.marker),
            if refresh_only {
                (vec!["work"], b"previous-ready".to_vec())
            } else {
                (vec!["prepare", "work"], Vec::new())
            },
        );
    }
}

#[test]
fn setup_failure_without_collected_acl_errors_is_preserved() {
    for refresh_only in [false, true] {
        let expected = SetupFailure::new(
            SetupErrorCode::HelperSandboxLockFailed,
            "fixture final lock failed",
        );
        let observation = observe_completion(
            refresh_only,
            &[],
            Err(anyhow::Error::new(SetupFailure::new(
                expected.code,
                expected.message.clone(),
            ))),
            &mut Vec::new(),
        );
        let error = observation.outcome.expect_err("original setup failure");
        assert_eq!(extract_setup_failure(&error), Some(&expected));
        assert_eq!(error.to_string(), expected.to_string());
        assert_eq!(
            (observation.calls, observation.marker),
            if refresh_only {
                (vec!["work"], b"previous-ready".to_vec())
            } else {
                (vec!["prepare", "work"], Vec::new())
            },
        );
    }
}
