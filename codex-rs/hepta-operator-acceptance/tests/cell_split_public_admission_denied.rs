//! The operator-acceptance library is compiled without cfg(test) in this
//! integration test. A public callback is NOT an NDU/Selector/Final-use grant.

#[cfg(unix)]
#[test]
fn callback_only_advance_denies_before_config_access_or_caller_admission() {
    use codex_hepta_operator_acceptance::run_pinned_cell_split_execution_with_admission_v1;
    use std::path::Path;

    let mut callback_calls = 0_usize;
    let error = run_pinned_cell_split_execution_with_admission_v1(
        "advance",
        Path::new(""),
        &"00".repeat(32),
        |_| {
            callback_calls += 1;
            Ok(())
        },
    )
    .expect_err("a public allow-all callback cannot authorize physical Cell Split");

    assert_eq!(callback_calls, 0, "admission callback must never run");
    assert!(
        error.contains("callback-only advance is denied"),
        "the denial must precede configuration reads and all owner I/O: {error}"
    );
}

#[cfg(unix)]
#[test]
fn legacy_operator_advance_stays_non_authorizing() {
    use codex_hepta_operator_acceptance::run_pinned_cell_split_execution_v1;
    use std::path::Path;

    let error = run_pinned_cell_split_execution_v1("advance", Path::new(""), &"00".repeat(32))
        .expect_err("legacy operator entry must be read-only");
    assert!(
        error.contains("requires independently admitted NDU/Selector selection"),
        "pinned bytes are not an effect grant: {error}"
    );
}
