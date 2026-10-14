#![cfg(unix)]

// Deliberately external integration test: this links the operator library
// without its cfg(test) reference-only admission exception.
use std::cell::Cell;
use std::path::Path;

use codex_hepta_operator_acceptance::run_pinned_cell_split_execution_with_admission_v1;

#[test]
fn public_callback_cannot_start_split_before_reading_config_or_invoking_admission() {
    let root = tempfile::tempdir().expect("private test storage");
    let missing = root.path().join("no-authorization.json");
    let calls = Cell::new(0_usize);
    let result = run_pinned_cell_split_execution_with_admission_v1(
        "advance",
        &missing,
        "not-an-authority-pin",
        |_| {
            calls.set(calls.get() + 1);
            Ok(())
        },
    );
    assert!(matches!(
        result,
        Err(ref message) if message ==
            "callback-only CellSplit advancement requires the Evidence-bound Agentd owner"
    ));
    assert_eq!(calls.get(), 0, "no allow-all callback invocation");
    assert!(!missing.exists(), "no fake config or journal initialized");
}

#[test]
fn public_callback_reconcile_alias_is_not_an_effect_authority() {
    let calls = Cell::new(0_usize);
    let result = run_pinned_cell_split_execution_with_admission_v1(
        "reconcile",
        Path::new("/does-not-exist/hepta-unsafe-reconcile"),
        "still-not-authority",
        |_| {
            calls.set(calls.get() + 1);
            Ok(())
        },
    );
    assert!(matches!(
        result,
        Err(ref message) if message ==
            "callback-only CellSplit advancement requires the Evidence-bound Agentd owner"
    ));
    assert_eq!(calls.get(), 0);
}
