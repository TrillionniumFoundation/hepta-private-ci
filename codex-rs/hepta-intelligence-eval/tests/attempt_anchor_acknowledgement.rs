//! Source-level fault tests; these do not qualify an external anchor authority.
use std::cell::RefCell;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::AnchoredProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalErrorV1 as JournalError;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptPhaseV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptTransitionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

struct JournalFile(PathBuf);

impl JournalFile {
    fn new() -> Self {
        let ordinal = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-eval-anchor-ack-{}-{ordinal}",
            std::process::id()
        ));
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&path)
            .unwrap_or_else(|error| panic!("unique journal file: {error:?}"));
        Self(path)
    }

    fn open(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.0)
            .unwrap_or_else(|error| panic!("open journal: {error:?}"))
    }
}

impl Drop for JournalFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

#[derive(Clone, Copy, Default)]
enum NextAck {
    #[default]
    Success,
    RejectBeforeCommit,
    CommitThenLoseAck,
}

#[derive(Default)]
struct AuthorityState {
    anchor: Option<ProductEvaluationAttemptAnchorV1>,
    next: NextAck,
}

#[derive(Clone, Default)]
struct TestAuthority(Rc<RefCell<AuthorityState>>);

impl ProductEvaluationAttemptAnchorStoreV1 for TestAuthority {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, JournalError> {
        let anchor = self.0.borrow().anchor;
        if anchor.is_some_and(|value| value.binding != binding) {
            return Err(JournalError::Binding);
        }
        Ok(anchor)
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), JournalError> {
        let mut state = self.0.borrow_mut();
        if next.binding != binding || state.anchor != expected {
            return Err(JournalError::Conflict);
        }
        match std::mem::take(&mut state.next) {
            NextAck::Success => {
                state.anchor = Some(next);
                Ok(())
            }
            NextAck::RejectBeforeCommit => Err(JournalError::Indeterminate),
            NextAck::CommitThenLoseAck => {
                state.anchor = Some(next);
                Err(JournalError::Indeterminate)
            }
        }
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn attempt_id() -> StableId {
    StableId::new("attempt:anchor-ack").unwrap_or_else(|error| panic!("valid id: {error:?}"))
}

fn intent() -> ProductEvaluationAttemptTransitionV1 {
    ProductEvaluationAttemptTransitionV1::intent(
        attempt_id(),
        digest("plan"),
        digest("owner-namespace"),
        digest("owner-state"),
    )
}

fn consumed() -> ProductEvaluationAttemptTransitionV1 {
    ProductEvaluationAttemptTransitionV1::holdout_consumed(
        attempt_id(),
        digest("plan"),
        digest("consumed-owner-record"),
    )
}

fn assert_poisoned(journal: &mut AnchoredProductEvaluationAttemptJournalV1<TestAuthority>) {
    assert_eq!(journal.anchor(), Err(JournalError::Indeterminate));
    assert_eq!(
        journal.latest(&attempt_id()),
        Err(JournalError::Indeterminate)
    );
    assert_eq!(
        journal.history(&attempt_id()),
        Err(JournalError::Indeterminate)
    );
    assert_eq!(journal.pending(None, 1), Err(JournalError::Indeterminate));
    assert_eq!(journal.append(intent()), Err(JournalError::Indeterminate));
}

#[test]
fn accepted_anchor_with_lost_ack_blocks_every_operation_until_recovery() {
    let file = JournalFile::new();
    let authority = TestAuthority::default();
    let binding = digest("anchor-binding");
    let mut journal =
        AnchoredProductEvaluationAttemptJournalV1::create(file.open(), binding, authority.clone())
            .expect("create");
    authority.0.borrow_mut().next = NextAck::CommitThenLoseAck;
    assert_eq!(journal.append(intent()), Err(JournalError::Indeterminate));
    assert_poisoned(&mut journal);
    drop(journal);

    let mut recovered =
        AnchoredProductEvaluationAttemptJournalV1::recover(file.open(), binding, authority)
            .expect("recover acknowledged authority history");
    let latest = recovered
        .latest(&attempt_id())
        .expect("latest")
        .expect("intent");
    assert_eq!(latest.transition, intent());
    assert_eq!(latest.sequence, 1);
    assert_eq!(
        recovered.pending(None, 1).expect("pending"),
        vec![latest.clone()]
    );
    assert_eq!(
        recovered.append(intent()).expect("idempotent retry"),
        latest
    );
    assert_eq!(recovered.append(consumed()).expect("consume").sequence, 2);
}

#[test]
fn durable_tail_before_anchor_commit_is_reconciled_without_reexecution() {
    let file = JournalFile::new();
    let authority = TestAuthority::default();
    let binding = digest("tail-binding");
    let mut journal =
        AnchoredProductEvaluationAttemptJournalV1::create(file.open(), binding, authority.clone())
            .expect("create");
    let before = journal.anchor().expect("genesis anchor");
    authority.0.borrow_mut().next = NextAck::RejectBeforeCommit;
    assert_eq!(journal.append(intent()), Err(JournalError::Indeterminate));
    assert_eq!(authority.0.borrow().anchor, Some(before));
    assert_poisoned(&mut journal);
    drop(journal);

    let mut recovered =
        AnchoredProductEvaluationAttemptJournalV1::recover(file.open(), binding, authority.clone())
            .expect("prove prefix and retain committed tail");
    let after = recovered.anchor().expect("reconciled anchor");
    assert_eq!(authority.0.borrow().anchor, Some(after));
    assert_ne!(after, before);
    assert_eq!(recovered.history(&attempt_id()).expect("history").len(), 1);
    assert_eq!(recovered.append(intent()).expect("same intent").sequence, 1);
}

#[test]
fn known_no_write_conflict_preserves_the_same_wrapper() {
    let file = JournalFile::new();
    let binding = digest("conflict-binding");
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
        file.open(),
        binding,
        TestAuthority::default(),
    )
    .expect("create");
    let original = journal.append(intent()).expect("persist intent");
    let retained = journal.anchor().expect("retained anchor");
    let illegal = ProductEvaluationAttemptTransitionV1 {
        phase: ProductEvaluationAttemptPhaseV1::Published,
        terminal_digest: digest("unverified-publication"),
        ..consumed()
    };
    assert_eq!(journal.append(illegal), Err(JournalError::Conflict));
    assert_eq!(journal.anchor(), Ok(retained));
    assert_eq!(journal.history(&attempt_id()), Ok(vec![original.clone()]));
    assert_eq!(journal.latest(&attempt_id()), Ok(Some(original)));
    let next = journal
        .append(consumed())
        .expect("legal transition remains usable");
    assert_eq!(journal.latest(&attempt_id()), Ok(Some(next)));
}

#[test]
fn complete_old_backup_is_rejected_without_lowering_the_independent_anchor() {
    let file = JournalFile::new();
    let authority = TestAuthority::default();
    let binding = digest("rollback-binding");
    let mut journal =
        AnchoredProductEvaluationAttemptJournalV1::create(file.open(), binding, authority.clone())
            .expect("create");
    journal.append(intent()).expect("intent");
    let old = std::fs::read(&file.0).expect("complete backup");
    journal.append(consumed()).expect("consumed");
    let retained = authority.0.borrow().anchor;
    drop(journal);
    std::fs::write(&file.0, old).expect("restore old complete backup");
    let recovered =
        AnchoredProductEvaluationAttemptJournalV1::recover(file.open(), binding, authority.clone());
    assert!(recovered.is_err());
    assert_eq!(authority.0.borrow().anchor, retained);
}
