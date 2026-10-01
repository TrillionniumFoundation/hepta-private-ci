use super::*;
use std::cell::RefCell;
use std::fs;
use std::rc::Rc;
use tempfile::NamedTempFile;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn consumed(attempt: &str) -> ProductEvaluationAttemptTransitionV1 {
    ProductEvaluationAttemptTransitionV1::holdout_consumed(
        id(attempt),
        digest(attempt),
        digest("holdout"),
    )
}

fn sealed(attempt: &str) -> ProductEvaluationAttemptTransitionV1 {
    ProductEvaluationAttemptTransitionV1::comparison_sealed(
        id(attempt),
        digest(attempt),
        digest("holdout"),
        digest("execution"),
    )
}

#[test]
fn consumed_then_terminal_is_replayable_and_exact_retry_is_idempotent() {
    let temp = NamedTempFile::new().expect("temporary journal");
    let binding = digest("attempt-journal-binding");
    let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
        temp.reopen().expect("reopen"),
        binding,
    )
    .expect("create journal");
    let first = journal.append(consumed("attempt:1")).expect("consumed");
    assert_eq!(journal.append(consumed("attempt:1")).expect("retry"), first);
    assert_eq!(journal.event_count(), 1);
    let terminal = journal.append(sealed("attempt:1")).expect("sealed");
    assert_eq!(terminal.sequence, 2);
    let length = journal.byte_len();
    drop(journal);
    let mut recovered = LockedFileProductEvaluationAttemptJournalV1::recover(
        temp.reopen().expect("reopen"),
        binding,
    )
    .expect("legacy recovery");
    assert_eq!(recovered.byte_len(), length);
    assert_eq!(
        recovered.latest(&id("attempt:1")).expect("latest"),
        Some(terminal)
    );
}

#[test]
fn terminal_without_consumption_and_conflicting_terminal_fail_closed() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    let failed = ProductEvaluationAttemptTransitionV1::failed(
        id("attempt:2"),
        digest("attempt:2"),
        digest("holdout"),
        digest("failure"),
    );
    assert_eq!(
        journal.append(failed.clone()),
        Err(ProductEvaluationAttemptJournalErrorV1::MissingConsumption)
    );
    journal.append(consumed("attempt:2")).expect("consumed");
    journal.append(failed.clone()).expect("failed");
    let different = ProductEvaluationAttemptTransitionV1 {
        terminal_digest: digest("different"),
        ..failed
    };
    assert_eq!(
        journal.append(different),
        Err(ProductEvaluationAttemptJournalErrorV1::Conflict)
    );
}

#[test]
fn truncated_frame_and_second_writer_are_rejected() {
    let temp = NamedTempFile::new().expect("temporary journal");
    let binding = digest("binding");
    let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
        temp.reopen().expect("reopen"),
        binding,
    )
    .expect("create");
    assert_eq!(
        LockedFileProductEvaluationAttemptJournalV1::recover(
            temp.reopen().expect("second writer"),
            binding,
        )
        .map(|_| ()),
        Err(ProductEvaluationAttemptJournalErrorV1::Busy)
    );
    journal.append(consumed("attempt:3")).expect("append");
    let length = journal.byte_len();
    drop(journal);
    temp.reopen()
        .expect("reopen for truncation")
        .set_len(length - 1)
        .expect("truncate");
    assert_eq!(
        LockedFileProductEvaluationAttemptJournalV1::recover(
            temp.reopen().expect("reopen"),
            binding,
        )
        .map(|_| ()),
        Err(ProductEvaluationAttemptJournalErrorV1::Corrupt)
    );
}

#[test]
fn complete_old_prefix_is_rejected_by_independent_anchor() {
    let temp = NamedTempFile::new().expect("temporary journal");
    let binding = digest("rollback-binding");
    let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
        temp.reopen().expect("reopen"),
        binding,
    )
    .expect("create");
    journal.append(consumed("rollback")).expect("consume");
    let old_prefix = fs::read(temp.path()).expect("backup complete frame");
    journal.append(sealed("rollback")).expect("seal");
    let anchor = journal.anchor().expect("independent retained anchor");
    drop(journal);
    fs::write(temp.path(), old_prefix).expect("restore whole old prefix");
    assert_eq!(
        LockedFileProductEvaluationAttemptJournalV1::recover_with_anchor(
            temp.reopen().expect("reopen"),
            binding,
            anchor,
        )
        .map(|_| ()),
        Err(ProductEvaluationAttemptJournalErrorV1::Corrupt)
    );
}

#[test]
fn intent_is_discoverable_and_plan_cannot_move_to_another_attempt() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    let intent = ProductEvaluationAttemptTransitionV1::intent(
        id("a"),
        digest("plan"),
        digest("namespace"),
        digest("owner-state"),
    );
    let receipt = journal.append(intent.clone()).expect("persist intent");
    assert_eq!(
        journal
            .pending(/*after*/ None, /*limit*/ 1)
            .expect("pending"),
        vec![receipt.clone()]
    );
    assert_eq!(
        journal.append(intent.clone()).expect("exact journal retry"),
        receipt
    );
    let moved = ProductEvaluationAttemptTransitionV1 {
        attempt_id: id("b"),
        ..intent
    };
    assert_eq!(
        journal.append(moved),
        Err(ProductEvaluationAttemptJournalErrorV1::Conflict)
    );
    let changed = ProductEvaluationAttemptTransitionV1::intent(
        id("a"),
        digest("plan"),
        digest("different-namespace"),
        digest("owner-state"),
    );
    assert_eq!(
        journal.append(changed),
        Err(ProductEvaluationAttemptJournalErrorV1::Conflict)
    );
}

#[test]
fn pending_publication_survives_recovery_and_terminal_is_not_reopened() {
    let temp = NamedTempFile::new().expect("temporary journal");
    let binding = digest("publication-binding");
    let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
        temp.reopen().expect("reopen"),
        binding,
    )
    .expect("create");
    let attempt = "publication";
    journal
        .append(ProductEvaluationAttemptTransitionV1::intent(
            id(attempt),
            digest(attempt),
            digest("namespace"),
            digest("owner-state"),
        ))
        .expect("intent");
    journal.append(consumed(attempt)).expect("consumed");
    journal.append(sealed(attempt)).expect("sealed");
    for phase in [
        ProductEvaluationAttemptPhaseV1::QualificationDecided,
        ProductEvaluationAttemptPhaseV1::PublicationPending,
    ] {
        journal
            .append(ProductEvaluationAttemptTransitionV1 {
                phase,
                terminal_digest: digest("request"),
                ..consumed(attempt)
            })
            .expect("publication transition");
    }
    let history = journal.history(&id(attempt)).expect("history");
    let anchor = journal.anchor().expect("retained anchor");
    drop(journal);
    let mut recovered = LockedFileProductEvaluationAttemptJournalV1::recover_with_anchor(
        temp.reopen().expect("reopen"),
        binding,
        anchor,
    )
    .expect("recover pending");
    assert_eq!(recovered.history(&id(attempt)).expect("history"), history);
    assert_eq!(
        recovered
            .pending(/*after*/ None, /*limit*/ 1)
            .expect("pending")
            .len(),
        1
    );
    recovered
        .append(ProductEvaluationAttemptTransitionV1 {
            phase: ProductEvaluationAttemptPhaseV1::Published,
            terminal_digest: digest("publication"),
            ..consumed(attempt)
        })
        .expect("reconciled publication");
    assert!(
        recovered
            .pending(/*after*/ None, /*limit*/ 1)
            .expect("pending")
            .is_empty()
    );
    // A historical idempotent acknowledgement must not change the latest state.
    recovered
        .append(consumed(attempt))
        .expect("historical retry");
    assert_eq!(
        recovered
            .latest(&id(attempt))
            .expect("latest")
            .expect("exists")
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
}

#[test]
fn publication_cannot_skip_pending_or_change_the_decision_request() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    journal.append(consumed("p")).expect("consumed");
    journal.append(sealed("p")).expect("sealed");
    let decided = ProductEvaluationAttemptTransitionV1 {
        phase: ProductEvaluationAttemptPhaseV1::QualificationDecided,
        terminal_digest: digest("request"),
        ..consumed("p")
    };
    journal.append(decided.clone()).expect("decided");
    assert_eq!(
        journal.append(ProductEvaluationAttemptTransitionV1 {
            phase: ProductEvaluationAttemptPhaseV1::Published,
            terminal_digest: digest("publication"),
            ..decided.clone()
        }),
        Err(ProductEvaluationAttemptJournalErrorV1::Conflict)
    );
    assert_eq!(
        journal.append(ProductEvaluationAttemptTransitionV1 {
            phase: ProductEvaluationAttemptPhaseV1::PublicationPending,
            terminal_digest: digest("different-request"),
            ..decided
        }),
        Err(ProductEvaluationAttemptJournalErrorV1::Conflict)
    );
}

#[test]
fn pending_pages_are_bounded_and_do_not_repeat_the_cursor() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    for key in ["a", "b", "c"] {
        journal.append(consumed(key)).expect("consumed");
    }
    let first = journal
        .pending(/*after*/ None, /*limit*/ 2)
        .expect("first page");
    let second = journal
        .pending(Some(&first[1].transition.attempt_id), /*limit*/ 2)
        .expect("second page");
    assert_eq!(
        first
            .iter()
            .chain(second.iter())
            .map(|r| r.transition.attempt_id.clone())
            .collect::<Vec<_>>(),
        vec![id("a"), id("b"), id("c")]
    );
    assert_eq!(
        journal.pending(/*after*/ None, /*limit*/ 0),
        Err(ProductEvaluationAttemptJournalErrorV1::Capacity)
    );
}

#[derive(Clone, Default)]
struct AnchorAuthority(Rc<RefCell<(Option<ProductEvaluationAttemptAnchorV1>, bool)>>);

impl ProductEvaluationAttemptAnchorStoreV1 for AnchorAuthority {
    fn load(
        &mut self,
        _binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Ok(self.0.borrow().0)
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        let mut state = self.0.borrow_mut();
        if state.0 != expected || next.binding != binding {
            return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
        }
        state.0 = Some(next);
        if state.1 {
            state.1 = false;
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        Ok(())
    }
}

#[test]
fn accepted_unknown_anchor_poisoning_is_reconciled_before_reading() {
    let temp = NamedTempFile::new().expect("temporary journal");
    let binding = digest("anchor-ack-loss");
    let authority = AnchorAuthority::default();
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
        temp.reopen().expect("reopen"),
        binding,
        authority.clone(),
    )
    .expect("create");
    authority.0.borrow_mut().1 = true;
    assert_eq!(
        journal.append(consumed("unknown")),
        Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate)
    );
    assert_eq!(
        journal.pending(/*after*/ None, /*limit*/ 1),
        Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate)
    );
    drop(journal);
    let mut recovered = AnchoredProductEvaluationAttemptJournalV1::recover(
        temp.reopen().expect("reopen"),
        binding,
        authority,
    )
    .expect("reconcile accepted write");
    assert_eq!(
        recovered
            .latest(&id("unknown"))
            .expect("latest")
            .expect("record")
            .transition,
        consumed("unknown")
    );
}
