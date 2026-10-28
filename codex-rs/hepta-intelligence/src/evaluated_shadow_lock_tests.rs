//! The writer owns an exclusive file lock; raw inspection requires owner exit.

use super::*;
#[cfg(windows)]
use pretty_assertions::assert_eq;
#[cfg(windows)]
use std::io::Write;

#[cfg(unix)]
#[test]
fn external_live_truncation_poisons_the_owner_before_learning_is_recorded() {
    let fixture = Fixture::new();
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("faulted-ledger");
    let mut ledger = ledger_at(&path, &fixture);
    OpenOptions::new()
        .write(true)
        .open(&path)
        .unwrap()
        .set_len(/*size*/ 0)
        .unwrap();
    let mut ports = Ports::new(&fixture);
    assert!(matches!(
        run_evaluated_shadow_v1(fixture.request(), &mut ledger, &mut ports, /*now*/ 50),
        Err(EvaluatedShadowError::Ledger(
            ProductionLedgerError::Durable(DurableLedgerError::Corrupt)
        ))
    ));
    assert!(matches!(
        ledger.records(),
        Err(ProductionLedgerError::Durable(DurableLedgerError::Poisoned))
    ));
}

#[cfg(windows)]
#[test]
fn exclusive_lock_refuses_external_io_and_recovery_rejects_later_history_loss() {
    let fixture = Fixture::new();
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("locked-ledger");
    let ledger = ledger_at(&path, &fixture);
    drop(ledger);
    let empty_bytes = closed_ledger_bytes(&path);
    let empty_length = u64::try_from(empty_bytes[0].len()).unwrap();
    let mut ledger = recover_ledger_at(&path, &fixture, LedgerRecovery::Unacknowledged);
    let mut ports = Ports::new(&fixture);
    let receipt =
        run_evaluated_shadow_v1(fixture.request(), &mut ledger, &mut ports, /*now*/ 50).unwrap();
    assert_eq!(
        receipt.learning.unwrap().disposition,
        AppendDisposition::Appended
    );
    let snapshot = ledger.snapshot().unwrap();
    let anchor = ledger.witness_frontier().unwrap().anchor;
    drop(ledger);
    let before = closed_ledger_bytes(&path);
    let ledger = recover_ledger_at(&path, &fixture, LedgerRecovery::Acknowledged(anchor));
    assert_eq!(ledger.snapshot().unwrap(), snapshot);

    // Windows denies byte-range I/O through an independently opened handle,
    // including another handle in the same process. Do not weaken that lock
    // just to let this test inspect or damage an active production writer.
    let read_error = fs::read(&path).unwrap_err();
    assert_eq!(read_error.raw_os_error(), Some(33)); // ERROR_LOCK_VIOLATION
    let mut external = OpenOptions::new().write(true).open(&path).unwrap();
    let write_error = external.write_all(b"corrupt").unwrap_err();
    assert_eq!(write_error.raw_os_error(), Some(33));
    assert_eq!(ledger.snapshot().unwrap(), snapshot);
    drop(external);
    drop(ledger);
    assert_eq!(closed_ledger_bytes(&path), before);

    // Once no writer owns the file, remove the committed record while keeping
    // the valid original header. The independent anchor must reject that loss.
    let external = OpenOptions::new().write(true).open(&path).unwrap();
    external.set_len(empty_length).unwrap();
    external.sync_all().unwrap();
    drop(external);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    assert!(matches!(
        DurableLedger::recover(
            file,
            digest("host-authorized-ledger"),
            /*max_records*/ 1,
            LedgerRecovery::Acknowledged(anchor),
        ),
        Err(DurableLedgerError::AcknowledgedHistoryMissing)
    ));
    assert_eq!(fs::read(&path).unwrap(), empty_bytes[0]);
    assert_eq!(fs::read(witness_path(&path)).unwrap(), before[1]);
}
