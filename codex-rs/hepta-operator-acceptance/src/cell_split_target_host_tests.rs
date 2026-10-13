use super::*;

#[test]
fn local_harness_persists_restart_and_no_resurrection() {
    let mut harness = CellSplitTargetHostHarnessV1::new("split.1", "host.fixture", 7, 8, 10_000)
        .expect("harness");
    harness
        .load_child_artifact("child.bundle.digest")
        .expect("artifact");
    harness
        .dispatch("parent.route", "child.route", 500)
        .expect("dispatch");
    harness.restart().expect("restart");
    harness.retain().expect("retain");
    harness.retire().expect("retire");

    let path = tempfile::NamedTempFile::new().expect("tempfile");
    harness.persist(path.path()).expect("persist");
    let reopened = CellSplitTargetHostHarnessV1::reopen(path.path()).expect("reopen");
    assert_eq!(reopened.report(), harness.report());
    assert!(!reopened.try_resurrect());
}

#[test]
fn failed_canary_rolls_back_and_budget_is_enforced() {
    let mut harness =
        CellSplitTargetHostHarnessV1::new("split.2", "host.fixture", 1, 2, 20).expect("harness");
    harness
        .load_child_artifact("child.bundle.digest")
        .expect("artifact");
    assert!(harness.dispatch("parent.route", "child.route", 21).is_err());
    harness
        .dispatch("parent.route", "child.route", 20)
        .expect("dispatch");
    harness.rollback().expect("rollback");
    assert_eq!(
        harness.report().state,
        CellSplitQualificationStateV1::RolledBack
    );
    assert!(harness.report().gates.rollback_to_predecessor);
    assert!(harness.report().gates.no_resurrection);
    assert!(!harness.try_resurrect());
    assert!(!harness.report().production_evidence);
}

#[test]
fn report_schema_cannot_claim_hardware_or_production() {
    let harness =
        CellSplitTargetHostHarnessV1::new("split.3", "host.fixture", 4, 5, 10).expect("harness");
    assert_eq!(
        harness.report().origin,
        CellSplitQualificationOriginV1::SourceSimulation
    );
    assert!(!harness.report().gates.hardware_fault_injected);
    assert!(!harness.report().gates.external_observer_attested);
    assert!(!harness.report().production_activation_authorized);
}

#[test]
fn quarantine_is_terminal_for_fixture_replay() {
    let mut harness =
        CellSplitTargetHostHarnessV1::new("split.4", "host.fixture", 2, 3, 10).expect("harness");
    harness
        .load_child_artifact("child.bundle.digest")
        .expect("artifact");
    harness
        .dispatch("parent.route", "child.route", 1)
        .expect("dispatch");
    harness.quarantine().expect("quarantine");
    assert_eq!(
        harness.report().state,
        CellSplitQualificationStateV1::Quarantined
    );
    assert!(harness.report().gates.no_resurrection);
    assert!(!harness.try_resurrect());
}

#[test]
fn reopening_fixture_rejects_forged_production_claims() {
    let harness =
        CellSplitTargetHostHarnessV1::new("split.5", "host.fixture", 2, 3, 10).expect("harness");
    let path = tempfile::NamedTempFile::new().expect("tempfile");
    harness.persist(path.path()).expect("persist");
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(path.path()).expect("read")).expect("json");
    value["productionEvidence"] = serde_json::Value::Bool(true);
    std::fs::write(path.path(), serde_json::to_vec(&value).expect("encode")).expect("tamper");
    assert!(CellSplitTargetHostHarnessV1::reopen(path.path()).is_err());
}
