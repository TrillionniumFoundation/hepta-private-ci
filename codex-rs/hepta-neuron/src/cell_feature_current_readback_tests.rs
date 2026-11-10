use super::*;
use crate::CellOwnerJournalReadbackV1;
use std::io::Write;

struct CountedWitness {
    inner: FileAnchorWitnessStore,
    calls: Arc<AtomicU64>,
    refuse_sequence: u64,
}
impl AnchorWitnessStore for CountedWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> { self.inner.current() }
    fn compare_and_swap(&mut self, before: Option<JournalAnchor>, next: JournalAnchor) -> Result<(), WitnessStoreError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if next.sequence == self.refuse_sequence { return Err(WitnessStoreError::Unavailable); }
        self.inner.compare_and_swap(before, next)
    }
}

#[test]
fn published_feature_readonly_reopens_exact_ack_cut_without_witness_cas() {
    let files = Files::new();
    let (specs, binding) = profile();
    let current = Arc::new(Current(Mutex::new((Some(binding.clone()), None))));
    let mut owner = CellOwnerJournalV1::open_guarded(files.file("journal"), files.witness(), specs.clone(),
        /*max_records*/ 16, binding.clone(), current.clone()).unwrap();
    let proposed = cell::proposal(&mut owner, cell::input("feature"));
    let receipt = commit_cell_step(&mut owner, proposed, /*now_micros*/ 13).unwrap();
    let snapshot = owner.snapshot(&receipt.scope).unwrap();
    drop(owner);
    let before = (files.bytes(), fs::read(files.0.join("witness")).unwrap());
    let calls = Arc::new(AtomicU64::new(0));
    let reader = CellOwnerJournalReadbackV1::open_guarded(files.file("journal"), CountedWitness {
        inner: files.witness(), calls: calls.clone(), refuse_sequence: u64::MAX,
    }, specs.clone(), /*max_records*/ 16, binding.clone(), current.clone()).unwrap();
    assert_eq!(reader.lookup(&receipt.scope, &receipt.operation_id, receipt.semantic_request_digest).unwrap(), Some(receipt.clone()));
    assert_eq!(reader.snapshot(&receipt.scope).unwrap(), snapshot);
    assert_eq!(reader.pending_inference(&receipt.scope).unwrap(), None);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    drop(reader);
    assert_eq!((files.bytes(), fs::read(files.0.join("witness")).unwrap()), before);
    OpenOptions::new().append(true).open(files.0.join("journal")).unwrap().write_all(&[1]).unwrap();
    let torn = files.bytes();
    assert!(CellOwnerJournalReadbackV1::open_guarded(files.file("journal"), CountedWitness {
        inner: files.witness(), calls: calls.clone(), refuse_sequence: u64::MAX,
    }, specs, /*max_records*/ 16, binding, current).is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!((files.bytes(), fs::read(files.0.join("witness")).unwrap()), (torn, before.1));
}

#[test]
fn published_feature_readonly_refuses_unacknowledged_completion_and_empty_files() {
    let files = Files::new();
    let (specs, binding) = profile();
    let current = Arc::new(Current(Mutex::new((Some(binding.clone()), None))));
    assert!(CellOwnerJournalReadbackV1::open_guarded(files.file("journal"), files.witness(), specs.clone(),
        /*max_records*/ 16, binding.clone(), current.clone()).is_err());
    assert!(files.bytes().is_empty());
    let calls = Arc::new(AtomicU64::new(0));
    let mut owner = CellOwnerJournalV1::open_guarded(files.file("journal"), CountedWitness {
        inner: files.witness(), calls: calls.clone(), refuse_sequence: 2,
    }, specs.clone(), /*max_records*/ 16, binding.clone(), current.clone()).unwrap();
    let proposed = cell::proposal(&mut owner, cell::input("feature"));
    assert_eq!(commit_cell_step(&mut owner, proposed, /*now_micros*/ 13), Err(CellExecutionError::CommitUncertain));
    drop(owner);
    let before = (files.bytes(), fs::read(files.0.join("witness")).unwrap());
    calls.store(0, Ordering::SeqCst);
    assert!(CellOwnerJournalReadbackV1::open_guarded(files.file("journal"), CountedWitness {
        inner: files.witness(), calls: calls.clone(), refuse_sequence: u64::MAX,
    }, specs, /*max_records*/ 16, binding, current).is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!((files.bytes(), fs::read(files.0.join("witness")).unwrap()), before);
}
