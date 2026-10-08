use std::fs::File;
use std::fs::OpenOptions;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tempfile::tempdir;

use crate::CellSplitAutomationJournalOwnerV1;
use crate::CellSplitLearningLedgerJournalOwnerV1;
use crate::CellSplitLifecycleJournalV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn rw(path: &std::path::Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("open durable file")
}

#[test]
fn learning_ledger_owner_replays_witnessed_lifecycle_after_restart() {
    let directory = tempdir().expect("temporary directory");
    let ledger_path = directory.path().join("cell-split-ledger");
    let witness_path = directory.path().join("cell-split-witness");
    let split_id = id("split-ledger-replay");
    let binding = digest("cell-split-ledger-binding");

    let mut owner = CellSplitLearningLedgerJournalOwnerV1::create(
        File::create(&ledger_path).expect("create ledger"),
        File::create(&witness_path).expect("create witness"),
        binding,
        16,
    )
    .expect("create owner");
    let mut journal =
        CellSplitLifecycleJournalV1::replay(split_id.clone(), Vec::new()).expect("genesis journal");
    journal
        .record_proposal(digest("proposal-receipt"))
        .expect("proposal");
    owner.commit(&journal).expect("durable commit");
    let first_anchor = owner.ledger().anchor().expect("anchor");
    assert!(first_anchor.sequence > 0);
    assert_eq!(owner.load(&split_id).expect("load"), Some(journal.clone()));

    // An exact retry is idempotent and cannot add a second lifecycle fact.
    owner.commit(&journal).expect("idempotent commit");
    assert_eq!(owner.ledger().anchor().expect("retry anchor"), first_anchor);
    drop(owner);

    let mut reopened = CellSplitLearningLedgerJournalOwnerV1::recover(
        rw(&ledger_path),
        rw(&witness_path),
        binding,
        16,
    )
    .expect("recover owner");
    assert_eq!(
        reopened.load(&split_id).expect("replayed load"),
        Some(journal.clone())
    );
    assert_eq!(
        reopened.ledger().anchor().expect("replayed anchor"),
        first_anchor
    );

    // The next transition extends the prior chain and remains replayable.
    journal
        .quarantine(digest("independent-evaluation-missing"))
        .expect("quarantine");
    reopened.commit(&journal).expect("second durable commit");
    assert_eq!(reopened.load(&split_id).expect("final load"), Some(journal));
}

#[test]
fn learning_ledger_owner_rejects_foreign_split_and_rewritten_journal() {
    let directory = tempdir().expect("temporary directory");
    let ledger_path = directory.path().join("cell-split-ledger");
    let witness_path = directory.path().join("cell-split-witness");
    let binding = digest("cell-split-ledger-binding-foreign");
    let mut owner = CellSplitLearningLedgerJournalOwnerV1::create(
        File::create(&ledger_path).expect("create ledger"),
        File::create(&witness_path).expect("create witness"),
        binding,
        16,
    )
    .expect("create owner");
    let first_id = id("split-ledger-first");
    let mut first = CellSplitLifecycleJournalV1::replay(first_id, Vec::new()).expect("genesis");
    first.record_proposal(digest("proposal")).expect("proposal");
    owner.commit(&first).expect("commit");

    let foreign = CellSplitLifecycleJournalV1::replay(id("split-ledger-foreign"), Vec::new())
        .expect("foreign genesis");
    assert!(owner.load(&foreign.split_id).is_err());

    let mut rewritten = first.clone();
    rewritten.events[0].evidence_digest = digest("rewritten-evidence");
    assert!(owner.commit(&rewritten).is_err());
}

#[test]
fn learning_ledger_owner_replays_complete_role_qualification_payload() {
    let directory = tempdir().expect("temporary directory");
    let ledger_path = directory.path().join("cell-split-ledger-role");
    let witness_path = directory.path().join("cell-split-witness-role");
    let split_id = id("split-role-replay");
    let binding = digest("cell-split-ledger-role-binding");
    let payload = b"hepta.cell-role.qualification-replay.v1:typed-receipts".to_vec();
    let mut owner = CellSplitLearningLedgerJournalOwnerV1::create(
        File::create(&ledger_path).expect("create ledger"),
        File::create(&witness_path).expect("create witness"),
        binding,
        16,
    )
    .expect("create owner");
    let mut journal =
        CellSplitLifecycleJournalV1::replay(split_id.clone(), Vec::new()).expect("genesis journal");
    journal
        .record_proposal(digest("typed-role-proposal"))
        .expect("proposal");
    owner
        .commit_with_role_qualification_payload(&journal, &payload)
        .expect("payload commit");
    assert_eq!(
        owner
            .role_qualification_payloads(&split_id)
            .expect("payloads"),
        vec![payload.clone()]
    );
    drop(owner);

    let reopened = CellSplitLearningLedgerJournalOwnerV1::recover(
        rw(&ledger_path),
        rw(&witness_path),
        binding,
        16,
    )
    .expect("recover owner");
    assert_eq!(
        reopened
            .role_qualification_payloads(&split_id)
            .expect("replayed payloads"),
        vec![payload.clone()]
    );
    assert!(
        reopened
            .ledger()
            .records()
            .expect("records")
            .iter()
            .any(|record| record.role_qualification_payload == payload)
    );
}
