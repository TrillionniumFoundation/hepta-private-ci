use std::io::ErrorKind;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::ReleaseId;

use crate::DurableReleaseTransaction;
use crate::H7H89ProductionTransition;
use crate::ProcessIdentity;
use crate::ReleaseTransactionKind;
use crate::ReleaseTransactionPhase;
use crate::SignedIntentStatus;
use crate::SignedSupervisorIntent;
use crate::durability::with_qualification_fault;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::write_lease;
use crate::release_transaction::RELEASE_TRANSACTION_FILE;
use crate::release_transaction::read_release_transaction;
use crate::release_transaction::write_release_transaction;
use crate::restart_budget::claim_restart;
use crate::restart_budget::complete_restart;
use crate::restart_budget::pending_restart;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;

fn agent() -> AgentId {
    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("fixed AgentId")
}

fn intent(status: SignedIntentStatus) -> SignedSupervisorIntent {
    SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"durability-grant"),
        agent().to_string(),
        H7H89ProductionTransition::Upgrade,
        "release-v1",
        "release-v2",
        1,
        2,
        3,
        status,
    )
    .expect("intent")
}

fn transaction(phase: ReleaseTransactionPhase) -> DurableReleaseTransaction {
    DurableReleaseTransaction::new(
        agent().to_string(),
        ReleaseTransactionKind::Upgrade,
        "release-v1",
        "release-v2",
        Some("release-v1".to_string()),
        None,
        None,
        1,
        2,
    )
    .expect("transaction")
    .with_authority(Sha256Digest::for_bytes(b"durability-grant"), 3)
    .expect("authority")
    .with_phase(phase)
    .expect("phase")
}

fn lease() -> ProcessLease {
    ProcessLease {
        schema_version: PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: agent(),
        spawn_generation: 1,
        release_id: ReleaseId::parse("release-v1").expect("release"),
        identity: ProcessIdentity::new(55, "durability-process").expect("identity"),
    }
}

#[test]
fn disk_full_and_fsync_fail_before_signed_intent_publication() {
    for (point, kind) in [
        ("signed_intent.file_write", ErrorKind::StorageFull),
        ("signed_intent.file_sync", ErrorKind::Other),
    ] {
        let dir = tempfile::tempdir().expect("temporary directory");
        let result = with_qualification_fault(point, kind, || {
            write_intent(dir.path(), &intent(SignedIntentStatus::Prepared))
        });
        assert!(result.is_err(), "{point} must fail");
        assert!(read_intent(dir.path()).expect("read after failure").is_none());
        assert!(
            std::fs::read_dir(dir.path())
                .expect("list run root")
                .all(|entry| !entry.expect("entry").file_name().to_string_lossy().ends_with(".tmp"))
        );
    }
}

#[test]
fn rename_failure_preserves_predecessor_and_directory_sync_is_ambiguous_but_valid() {
    let dir = tempfile::tempdir().expect("temporary directory");
    let prepared = intent(SignedIntentStatus::Prepared);
    write_intent(dir.path(), &prepared).expect("write predecessor");
    let queued = prepared.with_status(SignedIntentStatus::Queued).expect("queued");
    let rename = with_qualification_fault("signed_intent.rename", ErrorKind::Other, || {
        write_intent(dir.path(), &queued)
    });
    assert!(rename.is_err());
    assert_eq!(
        read_intent(dir.path()).expect("read predecessor"),
        Some(prepared)
    );

    let directory_sync = with_qualification_fault(
        "signed_intent.directory_sync",
        ErrorKind::Other,
        || write_intent(dir.path(), &queued),
    );
    assert!(directory_sync.is_err());
    assert_eq!(read_intent(dir.path()).expect("read valid head"), Some(queued));
}

#[test]
fn release_transaction_and_restart_record_never_report_success_without_durability() {
    let transaction_dir = tempfile::tempdir().expect("temporary transaction directory");
    let prepared = transaction(ReleaseTransactionPhase::Prepared);
    write_release_transaction(transaction_dir.path(), &prepared).expect("write predecessor");
    let draining = prepared
        .with_phase(ReleaseTransactionPhase::Draining)
        .expect("draining");
    let rename = with_qualification_fault("release_transaction.rename", ErrorKind::Other, || {
        write_release_transaction(transaction_dir.path(), &draining)
    });
    assert!(rename.is_err());
    assert_eq!(
        read_release_transaction(transaction_dir.path()).expect("read predecessor"),
        Some(prepared)
    );

    let restart_dir = tempfile::tempdir().expect("temporary restart directory");
    let disk_full = with_qualification_fault(
        "restart_journal.file_write",
        ErrorKind::StorageFull,
        || {
            claim_restart(
                restart_dir.path(),
                3,
                Duration::from_secs(300),
                Duration::from_millis(10),
            )
        },
    );
    assert!(disk_full.is_err());
    assert!(pending_restart(restart_dir.path(), 3).expect("read restart").is_none());

    claim_restart(
        restart_dir.path(),
        3,
        Duration::from_secs(300),
        Duration::from_millis(10),
    )
    .expect("first claim");
    complete_restart(restart_dir.path()).expect("complete first claim");
    let rename = with_qualification_fault("restart_journal.rename", ErrorKind::Other, || {
        claim_restart(
            restart_dir.path(),
            3,
            Duration::from_secs(300),
            Duration::from_millis(10),
        )
    });
    assert!(rename.is_err());
    assert!(pending_restart(restart_dir.path(), 3).expect("read predecessor").is_none());
}

#[test]
fn lease_write_hard_link_and_directory_sync_faults_are_fail_closed() {
    for point in [
        "process_lease.file_write",
        "process_lease.file_sync",
        "process_lease.hard_link",
    ] {
        let dir = tempfile::tempdir().expect("temporary directory");
        let kind = if point.ends_with("file_write") {
            ErrorKind::StorageFull
        } else {
            ErrorKind::Other
        };
        let result = with_qualification_fault(point, kind, || write_lease(dir.path(), &lease()));
        assert!(result.is_err(), "{point} must fail");
        assert!(read_lease(dir.path()).expect("read failed lease").is_none());
    }

    let dir = tempfile::tempdir().expect("temporary directory");
    let result = with_qualification_fault(
        "process_lease.directory_sync",
        ErrorKind::Other,
        || write_lease(dir.path(), &lease()),
    );
    assert!(result.is_err());
    assert!(read_lease(dir.path()).expect("read linked lease").is_some());
}

#[test]
fn truncated_lease_restart_intent_and_transaction_are_rejected() {
    let cases = [
        "supervisor-process.json",
        RESTART_JOURNAL_FILE,
        crate::SIGNED_INTENT_FILE,
        RELEASE_TRANSACTION_FILE,
    ];
    for file_name in cases {
        let dir = tempfile::tempdir().expect("temporary directory");
        std::fs::write(dir.path().join(file_name), b"{\"truncated\":")
            .expect("write truncated record");
        match file_name {
            "supervisor-process.json" => assert!(read_lease(dir.path()).is_err()),
            RESTART_JOURNAL_FILE => assert!(pending_restart(dir.path(), 3).is_err()),
            crate::SIGNED_INTENT_FILE => assert!(read_intent(dir.path()).is_err()),
            RELEASE_TRANSACTION_FILE => assert!(read_release_transaction(dir.path()).is_err()),
            _ => unreachable!(),
        }
    }
}
