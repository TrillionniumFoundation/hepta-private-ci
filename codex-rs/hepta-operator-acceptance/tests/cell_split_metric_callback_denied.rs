#![cfg(unix)]

use std::cell::Cell;
use std::sync::Arc;

use codex_hepta_operator_acceptance::run_pinned_cell_split_execution_with_admission_and_metrics_v1;
use codex_hepta_types::PhaseMetricEventV1;
use codex_hepta_types::PhaseMetricSinkErrorV1;
use codex_hepta_types::PhaseMetricSinkV1;

#[derive(Debug)]
struct CallerProvidedAlwaysHealthySink;

impl PhaseMetricSinkV1 for CallerProvidedAlwaysHealthySink {
    fn record(&self, _: PhaseMetricEventV1) -> Result<(), PhaseMetricSinkErrorV1> {
        Ok(())
    }

    fn healthy(&self) -> bool {
        true
    }

    fn flush(&self) -> Result<(), PhaseMetricSinkErrorV1> {
        Ok(())
    }
}

#[test]
fn fabricated_healthy_metrics_and_allow_all_callback_never_dispatch_advance() {
    let dir = tempfile::tempdir().expect("private fixture");
    let absent = dir.path().join("missing-execution-config.json");
    let callback_calls = Cell::new(0_usize);
    let result = run_pinned_cell_split_execution_with_admission_and_metrics_v1(
        "advance",
        &absent,
        "unsigned-not-a-config-pin",
        Arc::new(CallerProvidedAlwaysHealthySink),
        |_| {
            callback_calls.set(callback_calls.get() + 1);
            Ok(())
        },
    );
    assert!(matches!(
        result,
        Err(ref error)
            if error == "public metrics callback cannot authorize CellSplit advance"
    ));
    assert_eq!(callback_calls.get(), 0, "no arbitrary admission callback");
    assert!(!absent.exists(), "no configuration or ledger was created");
}
