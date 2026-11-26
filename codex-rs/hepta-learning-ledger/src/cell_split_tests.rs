use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::CellSplitLearningLedgerV1;
use crate::CellSplitLifecycleRecordV1;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-cell-split-ledger-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&root).expect("fixture directory");
        File::create(root.join("ledger")).expect("ledger file");
        File::create(root.join("witness")).expect("witness file");
        Self { root }
    }

    fn ledger_file(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join("ledger"))
            .expect("ledger handle")
    }

    fn witness_file(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join("witness"))
            .expect("witness handle")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn event(sequence: u64) -> CellSplitLifecycleRecordV1 {
    CellSplitLifecycleRecordV1 {
        record_id: id(&format!("cell-split-record-{sequence}")),
        split_id: id("cell-split-test"),
        lifecycle_sequence: sequence,
        from_state: (sequence - 1) as u8,
        to_state: sequence as u8,
        evidence_digest: digest(&format!("evidence-{sequence}")),
        state_digest: digest(&format!("state-{sequence}")),
        taskflow_event_digest: digest(&format!("taskflow-{sequence}")),
        support_digest: digest(&format!("support-{sequence}")),
        role_qualification_payload: Vec::new(),
    }
}

#[test]
fn append_reopen_and_exact_retry_are_witnessed() {
    let fixture = Fixture::new();
    let binding = digest("cell-split-binding");
    let first = event(1);
    let mut ledger = CellSplitLearningLedgerV1::create(
        fixture.ledger_file(),
        fixture.witness_file(),
        binding,
        8,
    )
    .expect("create");

    let appended = ledger
        .append(Digest32::ZERO, first.clone())
        .expect("append");
    assert_eq!(appended.disposition, AppendDisposition::Appended);
    assert_eq!(appended.sequence.get(), 1);
    assert_eq!(ledger.records().expect("records"), vec![first.clone()]);

    let retry = ledger
        .append(Digest32::ZERO, first.clone())
        .expect("idempotent retry");
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.sequence, appended.sequence);
    assert_eq!(retry.event_digest, appended.event_digest);
    assert_eq!(retry.chain_digest, appended.chain_digest);
    let head = ledger.anchor().expect("anchor");
    assert_eq!(ledger.witness_frontier().expect("witness").anchor, head);
    drop(ledger);

    let recovered = CellSplitLearningLedgerV1::recover(
        fixture.ledger_file(),
        fixture.witness_file(),
        binding,
        8,
    )
    .expect("recover");
    assert_eq!(recovered.records().expect("recovered records"), vec![first]);
    assert_eq!(
        recovered
            .witness_frontier()
            .expect("recovered witness")
            .anchor,
        head
    );
}

#[test]
fn predecessor_conflict_and_tampered_reopen_fail_closed() {
    let fixture = Fixture::new();
    let binding = digest("cell-split-binding-conflict");
    let first = event(1);
    let second = event(2);
    let mut ledger = CellSplitLearningLedgerV1::create(
        fixture.ledger_file(),
        fixture.witness_file(),
        binding,
        8,
    )
    .expect("create");
    let receipt = ledger.append(Digest32::ZERO, first).expect("append");
    assert!(
        ledger.append(Digest32::ZERO, second).is_err(),
        "stale predecessor must be rejected"
    );
    drop(ledger);

    let path = fixture.root.join("ledger");
    let mut bytes = fs::read(&path).expect("read ledger");
    let last = bytes.len() - 1;
    bytes[last] ^= 0x01;
    fs::write(&path, bytes).expect("tamper ledger");
    assert!(
        CellSplitLearningLedgerV1::recover(
            fixture.ledger_file(),
            fixture.witness_file(),
            binding,
            8,
        )
        .is_err()
    );
    assert_ne!(receipt.chain_digest, Digest32::ZERO);
}
