use super::*;
use std::cell::RefCell;
use std::fs;
use std::rc::Rc;
use tempfile::NamedTempFile;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn transition(
    attempt: &str,
    phase: ProductEvaluationAttemptPhaseV1,
    payload: &str,
) -> ProductEvaluationAttemptTransitionV1 {
    ProductEvaluationAttemptTransitionV1 {
        attempt_id: id(attempt),
        plan_digest: digest(&format!("plan:{attempt}")),
        phase,
        holdout_record_digest: digest(&format!("holdout:{attempt}")),
        terminal_digest: if phase == ProductEvaluationAttemptPhaseV1::HoldoutConsumed {
            Digest32::ZERO
        } else {
            digest(payload)
        },
    }
}

fn intent(attempt: &str) -> ProductEvaluationAttemptTransitionV1 {
    ProductEvaluationAttemptTransitionV1::intent(
        id(attempt),
        digest(&format!("plan:{attempt}")),
        digest("namespace"),
        digest(&format!("owner-state:{attempt}")),
    )
}

fn advance_to_pending(journal: &mut LockedFileProductEvaluationAttemptJournalV1, attempt: &str) {
    use ProductEvaluationAttemptPhaseV1 as Phase;
    journal.append(intent(attempt)).expect("intent");
    journal
        .append(transition(attempt, Phase::HoldoutConsumed, "unused"))
        .expect("consumed");
    journal
        .append(transition(attempt, Phase::ComparisonSealed, "execution"))
        .expect("sealed");
    journal
        .append(transition(
            attempt,
            Phase::QualificationArtifactsPersisted,
            "archive",
        ))
        .expect("archive");
    journal
        .append(transition(attempt, Phase::QualificationDecided, "request"))
        .expect("decided");
    journal
        .append(transition(attempt, Phase::PublicationPending, "request"))
        .expect("pending");
}

fn publish(journal: &mut LockedFileProductEvaluationAttemptJournalV1, attempt: &str) {
    journal
        .append(transition(
            attempt,
            ProductEvaluationAttemptPhaseV1::Published,
            "publication",
        ))
        .expect("published");
}

#[derive(Clone, Default)]
struct CheckpointAuthority(Rc<RefCell<Option<ProductEvaluationAttemptAnchorV1>>>);

impl ProductEvaluationAttemptAnchorStoreV1 for CheckpointAuthority {
    fn load(
        &mut self,
        _binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Ok(*self.0.borrow())
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        let mut value = self.0.borrow_mut();
        if *value != expected || next.binding != binding {
            return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
        }
        *value = Some(next);
        Ok(())
    }
}

#[test]
fn independently_retained_checkpoint_restores_state_and_replays_only_tail() {
    let journal_file = NamedTempFile::new().expect("journal file");
    let checkpoint_file = NamedTempFile::new().expect("checkpoint file");
    let binding = digest("checkpoint-binding");
    let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
        journal_file.reopen().expect("journal handle"),
        binding,
    )
    .expect("journal");
    advance_to_pending(&mut journal, "attempt:a");
    publish(&mut journal, "attempt:a");
    advance_to_pending(&mut journal, "attempt:b");

    let mut checkpoint_authority = CheckpointAuthority::default();
    let checkpoint = journal
        .checkpoint_into(
            checkpoint_file.reopen().expect("checkpoint handle"),
            &mut checkpoint_authority,
        )
        .expect("checkpoint");
    assert_eq!(checkpoint.event_count as usize, journal.event_count());

    journal
        .append(intent("attempt:c"))
        .expect("post-checkpoint tail");
    let retained = journal.anchor().expect("retained anchor");
    let expected_events = journal.event_count();
    drop(journal);

    let mut recovered = LockedFileProductEvaluationAttemptJournalV1::recover_with_checkpoint(
        journal_file.reopen().expect("journal recovery"),
        checkpoint_file.reopen().expect("checkpoint recovery"),
        binding,
        retained,
        &mut checkpoint_authority,
    )
    .expect("tail recovery");
    assert_eq!(recovered.event_count(), expected_events);
    assert_eq!(
        recovered
            .latest(&id("attempt:a"))
            .expect("latest")
            .expect("a")
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
    assert_eq!(
        recovered
            .pending(None, 8)
            .expect("pending")
            .into_iter()
            .map(|receipt| receipt.transition.attempt_id)
            .collect::<Vec<_>>(),
        vec![id("attempt:b"), id("attempt:c")]
    );
}

#[test]
fn checkpoint_bytes_cannot_be_substituted_under_retained_identity() {
    let journal_file = NamedTempFile::new().expect("journal file");
    let checkpoint_file = NamedTempFile::new().expect("checkpoint file");
    let binding = digest("tamper-binding");
    let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
        journal_file.reopen().expect("journal handle"),
        binding,
    )
    .expect("journal");
    journal.append(intent("attempt:tamper")).expect("intent");
    let retained = journal.anchor().expect("anchor");
    let mut authority = CheckpointAuthority::default();
    journal
        .checkpoint_into(
            checkpoint_file.reopen().expect("checkpoint handle"),
            &mut authority,
        )
        .expect("checkpoint");
    drop(journal);

    let mut bytes = fs::read(checkpoint_file.path()).expect("read checkpoint");
    let index = bytes.len() / 2;
    bytes[index] ^= 0x5a;
    fs::write(checkpoint_file.path(), bytes).expect("tamper checkpoint");
    assert_eq!(
        LockedFileProductEvaluationAttemptJournalV1::recover_with_checkpoint(
            journal_file.reopen().expect("journal recovery"),
            checkpoint_file.reopen().expect("checkpoint recovery"),
            binding,
            retained,
            &mut authority,
        )
        .map(|_| ()),
        Err(ProductEvaluationAttemptJournalErrorV1::Corrupt)
    );
}

#[test]
fn checkpoint_newer_than_independent_journal_anchor_is_rejected() {
    let journal_file = NamedTempFile::new().expect("journal file");
    let checkpoint_file = NamedTempFile::new().expect("checkpoint file");
    let binding = digest("frontier-binding");
    let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
        journal_file.reopen().expect("journal handle"),
        binding,
    )
    .expect("journal");
    journal.append(intent("attempt:frontier")).expect("intent");
    let older_anchor = journal.anchor().expect("older anchor");
    journal
        .append(transition(
            "attempt:frontier",
            ProductEvaluationAttemptPhaseV1::HoldoutConsumed,
            "unused",
        ))
        .expect("consumed");
    let mut authority = CheckpointAuthority::default();
    journal
        .checkpoint_into(
            checkpoint_file.reopen().expect("checkpoint handle"),
            &mut authority,
        )
        .expect("checkpoint");
    drop(journal);

    assert_eq!(
        LockedFileProductEvaluationAttemptJournalV1::recover_with_checkpoint(
            journal_file.reopen().expect("journal recovery"),
            checkpoint_file.reopen().expect("checkpoint recovery"),
            binding,
            older_anchor,
            &mut authority,
        )
        .map(|_| ()),
        Err(ProductEvaluationAttemptJournalErrorV1::Corrupt)
    );
}
