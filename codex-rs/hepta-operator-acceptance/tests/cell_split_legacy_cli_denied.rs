#![cfg(unix)]

// This integration test compiles the library without cfg(test). A passing
// coordinator unit test cannot demonstrate that the public production entry
// refuses fresh physical effects.
use codex_hepta_operator_acceptance::run_pinned_cell_split_execution_v1;

#[test]
fn legacy_operator_write_actions_deny_before_config_or_ledger_io() {
    let root = tempfile::tempdir().expect("private fixture");
    let absent = root.path().join("absent-operator-config.json");

    for (action, expected) in [
        (
            "advance",
            "CellSplit advance requires independently admitted NDU/Selector selection",
        ),
        (
            "reconcile",
            "CellSplit recovery requires the explicit pending-only reconciliation API",
        ),
    ] {
        let result =
            run_pinned_cell_split_execution_v1(action, &absent, "not-an-authority-or-valid-pin");
        assert_eq!(result.err().as_deref(), Some(expected));
        assert!(
            !absent.exists(),
            "{action} must deny without creating a config or execution ledger"
        );
    }
    assert!(
        root.path().read_dir().expect("directory").next().is_none(),
        "public write actions must create no execution artifacts"
    );
}

#[test]
fn compiled_operator_binary_rejects_write_actions_before_io() {
    // Running the actual binary is essential: a library-only cfg(test)
    // assertion does not prove the product's command dispatcher is closed.
    let root = tempfile::tempdir().expect("private fixture");
    let absent = root.path().join("missing-binary-config.json");

    for (action, expected) in [
        (
            "advance",
            "CellSplit advance requires independently admitted NDU/Selector selection",
        ),
        (
            "reconcile",
            "CellSplit recovery requires the explicit pending-only reconciliation API",
        ),
    ] {
        let output = std::process::Command::new(env!("CARGO_BIN_EXE_hepta-operator-acceptance"))
            .arg("cell-split-execution")
            .arg(action)
            .arg(&absent)
            .arg("not-a-trusted-config-pin")
            .output()
            .expect("real operator binary must execute");
        assert!(!output.status.success(), "{action} must be rejected");
        assert!(output.stdout.is_empty(), "{action} must return no positive receipt");
        let diagnostic = String::from_utf8_lossy(&output.stderr);
        assert!(diagnostic.contains(expected), "{action} denied unexpectedly: {diagnostic}");
        assert!(!absent.exists(), "{action} must not materialize config or ledger");
    }
    assert!(
        root.path().read_dir().expect("directory").next().is_none(),
        "rejected binary commands must not create execution artifacts"
    );
}
