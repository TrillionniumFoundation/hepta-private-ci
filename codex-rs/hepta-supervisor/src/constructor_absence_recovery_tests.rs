//! Constructor recovery through real durable files, not a host performance
//! receipt. Absence probes must preserve every independent recovery witness.

use super::*;
use crate::release_transaction::DurableReleaseTransaction;
use crate::release_transaction::ReleaseTransactionKind;
use crate::release_transaction::ReleaseTransactionPhase;
use crate::release_transaction::write_release_transaction;
use pretty_assertions::assert_eq;

#[test]
fn constructor_cancels_orphan_lineage_without_a_restart_budget() -> anyhow::Result<()> {
    let fleet = TestFleet::new()?;
    let record = fleet.registry.load_agent(&fleet.first)?;
    let run = record.layout.run_root();
    crate::restart_lineage::begin(
        run,
        &fleet.first,
        /*window_started_unix_ms*/ 1,
        /*attempt*/ 1,
        /*predecessor*/ None,
    )?;
    assert!(
        !run.join(crate::restart_journal::RESTART_JOURNAL_FILE)
            .exists()
    );
    let lineage_path = run.join(crate::restart_lineage::RESTART_LINEAGE_FILE);
    let before: serde_json::Value = serde_json::from_slice(&std::fs::read(&lineage_path)?)?;
    assert_eq!(before["phase"], "replacement_pending");

    let (recovered, report) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(report, TickReport::default());
    let after: serde_json::Value = serde_json::from_slice(&std::fs::read(lineage_path)?)?;
    assert_eq!(after["phase"], "cancelled");
    assert!(
        !recovered
            .snapshot(&fleet.first)
            .expect("first Agent")
            .restart_pending
    );
    assert!(!recovered.production_recovery_required(&fleet.first)?);
    Ok(())
}

#[test]
fn constructor_restores_pending_budget_without_control_or_lineage() -> anyhow::Result<()> {
    let fleet = TestFleet::new()?;
    let record = fleet.registry.load_agent(&fleet.first)?;
    let run = record.layout.run_root();
    let claim = crate::restart_budget::claim_restart(
        run,
        /*maximum_attempts*/ 3,
        /*window*/ Duration::from_secs(60),
        /*base_backoff*/ Duration::from_millis(1),
    )?;
    assert!(
        !run.join(crate::control_intent::CONTROL_INTENT_FILE)
            .exists()
    );
    assert!(
        !run.join(crate::restart_lineage::RESTART_LINEAGE_FILE)
            .exists()
    );
    let budget_before = std::fs::read(run.join(crate::restart_journal::RESTART_JOURNAL_FILE))?;

    let (recovered, report) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(report, TickReport::default());
    let snapshot = recovered.snapshot(&fleet.first).expect("first Agent");
    assert_eq!(
        (snapshot.restart_pending, snapshot.restart_attempt),
        (true, claim.attempt)
    );
    assert_eq!(
        std::fs::read(run.join(crate::restart_journal::RESTART_JOURNAL_FILE))?,
        budget_before,
    );
    let lineage: serde_json::Value = serde_json::from_slice(&std::fs::read(
        run.join(crate::restart_lineage::RESTART_LINEAGE_FILE),
    )?)?;
    assert_eq!(lineage["phase"], "replacement_pending");
    Ok(())
}

#[test]
fn constructor_keeps_terminal_release_transaction_in_owner_metadata() -> anyhow::Result<()> {
    let fleet = TestFleet::new()?;
    // Release transactions require an already-admitted lifecycle generation,
    // whereas a newly registered Agent is still at generation zero.
    let initial = fleet.registry.load_agent(&fleet.first)?;
    let starting = fleet.registry.compare_and_transition(
        &fleet.first,
        initial.lifecycle.generation,
        AgentLifecycle::Starting,
    )?;
    fleet.registry.compare_and_transition(
        &fleet.first,
        starting.generation,
        AgentLifecycle::Stopped,
    )?;
    let record = fleet.registry.load_agent(&fleet.first)?;
    let transaction = DurableReleaseTransaction::new(
        fleet.first.to_string(),
        ReleaseTransactionKind::Upgrade,
        "source",
        "target",
        /*rollback_predecessor*/ None,
        /*source_binding*/ None,
        /*target_binding*/ None,
        /*expected_release_state_generation*/ record.release_state.generation,
        /*expected_lifecycle_generation*/ record.lifecycle.generation,
    )?
    .with_phase(ReleaseTransactionPhase::Committed)?;
    write_release_transaction(record.layout.run_root(), &transaction)?;
    let transaction_path = record
        .layout
        .run_root()
        .join(crate::release_transaction::RELEASE_TRANSACTION_FILE);
    let bytes_before = std::fs::read(&transaction_path)?;

    let (recovered, report) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(report, TickReport::default());
    assert_eq!(
        recovered
            .slots
            .get(&fleet.first)
            .expect("first Agent")
            .release_transaction,
        Some(transaction),
    );
    assert_eq!(std::fs::read(transaction_path)?, bytes_before);
    assert!(
        !recovered
            .snapshot(&fleet.first)
            .expect("first Agent")
            .release_change_pending
    );
    Ok(())
}
