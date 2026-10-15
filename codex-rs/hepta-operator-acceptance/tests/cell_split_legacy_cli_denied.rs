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
