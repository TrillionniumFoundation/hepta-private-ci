use super::*;
use crate::ProductEvaluationAttemptPhaseV1;
use std::cell::RefCell;
use std::rc::Rc;
use tempfile::NamedTempFile;

const HEADER_BYTES: u64 = 72;
const ONE_BYTE_ID_FRAME: u64 = 136;
const COMPLETE_LIFECYCLE_EVENTS: usize = 7;
const COMPLETE_LIFECYCLE_BYTES: u64 =
    HEADER_BYTES + COMPLETE_LIFECYCLE_EVENTS as u64 * ONE_BYTE_ID_FRAME;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn lifecycle(
    attempt: &str,
    plan: Digest32,
    binding: Digest32,
) -> Vec<ProductEvaluationAttemptTransitionV1> {
    let attempt_id = id(attempt);
    let holdout = digest(&format!("holdout:{attempt}"));
    let request = digest(&format!("request:{attempt}"));
    vec![
        ProductEvaluationAttemptTransitionV1::intent(
            attempt_id.clone(),
            plan,
            binding,
            digest(&format!("owner-state:{attempt}")),
        ),
        ProductEvaluationAttemptTransitionV1::holdout_consumed(attempt_id.clone(), plan, holdout),
        ProductEvaluationAttemptTransitionV1::comparison_sealed(
            attempt_id.clone(),
            plan,
            holdout,
            digest(&format!("execution:{attempt}")),
        ),
        ProductEvaluationAttemptTransitionV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: plan,
            phase: ProductEvaluationAttemptPhaseV1::QualificationArtifactsPersisted,
            holdout_record_digest: holdout,
            terminal_digest: digest(&format!("artifacts:{attempt}")),
        },
        ProductEvaluationAttemptTransitionV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: plan,
            phase: ProductEvaluationAttemptPhaseV1::QualificationDecided,
            holdout_record_digest: holdout,
            terminal_digest: request,
        },
        ProductEvaluationAttemptTransitionV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: plan,
            phase: ProductEvaluationAttemptPhaseV1::PublicationPending,
            holdout_record_digest: holdout,
            terminal_digest: request,
        },
        ProductEvaluationAttemptTransitionV1 {
            attempt_id,
            plan_digest: plan,
            phase: ProductEvaluationAttemptPhaseV1::Published,
            holdout_record_digest: holdout,
            terminal_digest: digest(&format!("publication:{attempt}")),
        },
    ]
}

#[derive(Clone, Default)]
struct AnchorAuthority(Rc<RefCell<AnchorState>>);

#[derive(Default)]
struct AnchorState {
    value: Option<ProductEvaluationAttemptAnchorV1>,
    accepted_unknown_once: bool,
}

impl AnchorAuthority {
    fn accept_then_report_unknown_once(&self) {
        self.0.borrow_mut().accepted_unknown_once = true;
    }
}

impl ProductEvaluationAttemptAnchorStoreV1 for AnchorAuthority {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        let value = self.0.borrow().value;
        if value.is_some_and(|anchor| anchor.binding != binding) {
            return Err(ProductEvaluationAttemptJournalErrorV1::Binding);
        }
        Ok(value)
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        let mut state = self.0.borrow_mut();
        if next.binding != binding || state.value != expected {
            return Err(ProductEvaluationAttemptJournalErrorV1::Conflict);
        }
        state.value = Some(next);
        if state.accepted_unknown_once {
            state.accepted_unknown_once = false;
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        Ok(())
    }
}

#[test]
fn anchored_known_no_write_rejections_do_not_poison_the_owner() {
    let temp = NamedTempFile::new().expect("temporary journal");
    let binding = digest("anchored-known-rejection");
    let authority = AnchorAuthority::default();
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
        temp.reopen().expect("reopen"),
        binding,
        authority,
    )
    .expect("create anchored journal");

    let plan = digest("shared-plan");
    let first = lifecycle("a", plan, binding);
    journal
        .append(first[0].clone())
        .expect("persist first intent");

    let moved = ProductEvaluationAttemptTransitionV1::intent(
        id("b"),
        plan,
        binding,
        digest("owner-state:b"),
    );
    assert_eq!(
        journal.append(moved),
        Err(ProductEvaluationAttemptJournalErrorV1::Conflict)
    );
    assert_eq!(
        journal
            .latest(&id("a"))
            .expect("owner remains readable")
            .expect("attempt exists")
            .transition,
        first[0]
    );

    let missing = ProductEvaluationAttemptTransitionV1::failed(
        id("c"),
        digest("plan:c"),
        digest("holdout:c"),
        digest("failure:c"),
    );
    assert_eq!(
        journal.append(missing),
        Err(ProductEvaluationAttemptJournalErrorV1::MissingConsumption)
    );

    let invalid = ProductEvaluationAttemptTransitionV1::intent(
        id("invalid"),
        Digest32::ZERO,
        binding,
        digest("owner-state:invalid"),
    );
    assert_eq!(
        journal.append(invalid),
        Err(ProductEvaluationAttemptJournalErrorV1::Binding)
    );

    journal
        .append(first[1].clone())
        .expect("already admitted attempt continues after deterministic rejection");
    assert_eq!(
        journal
            .pending(None, 4)
            .expect("pending remains available")
            .len(),
        1
    );
}

#[test]
fn anchored_near_capacity_rejects_new_work_but_preserves_the_reserved_lifecycle() {
    let temp = NamedTempFile::new().expect("temporary journal");
    let binding = digest("anchored-near-capacity");
    let authority = AnchorAuthority::default();
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create_with_qualification_limits(
        temp.reopen().expect("reopen"),
        binding,
        authority.clone(),
        COMPLETE_LIFECYCLE_BYTES,
        COMPLETE_LIFECYCLE_EVENTS,
    )
    .expect("create bounded anchored journal");

    let first = lifecycle("a", digest("plan:a"), binding);
    journal.append(first[0].clone()).expect("reserve lifecycle");
    assert_eq!(
        journal.append(lifecycle("b", digest("plan:b"), binding)[0].clone()),
        Err(ProductEvaluationAttemptJournalErrorV1::Capacity)
    );

    for transition in first.iter().skip(1) {
        journal
            .append(transition.clone())
            .expect("reserved attempt reaches terminal");
    }
    assert_eq!(
        journal
            .latest(&id("a"))
            .expect("latest")
            .expect("attempt")
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
    assert!(journal.pending(None, 1).expect("pending").is_empty());

    drop(journal);
    // Qualification limits are owner policy, not journal wire state. Reopen
    // the real backend with the same stricter policy before rebuilding the
    // wrapper; production recovery intentionally uses the normal hard limits.
    let retained = authority.0.borrow().value.expect("retained anchor");
    let backend = LockedFileProductEvaluationAttemptJournalV1::recover_with_qualification_limits(
        temp.reopen().expect("reopen"),
        binding,
        COMPLETE_LIFECYCLE_BYTES,
        COMPLETE_LIFECYCLE_EVENTS,
    )
    .expect("recover exact full-capacity history");
    assert_eq!(backend.anchor(), Ok(retained));
    let mut recovered = AnchoredProductEvaluationAttemptJournalV1 {
        journal: backend,
        authority,
        retained,
        poisoned: false,
    };
    assert_eq!(
        recovered.history(&id("a")).expect("history").len(),
        COMPLETE_LIFECYCLE_EVENTS
    );
    assert_eq!(
        recovered.append(lifecycle("b", digest("plan:b"), binding)[0].clone()),
        Err(ProductEvaluationAttemptJournalErrorV1::Capacity)
    );
    assert!(
        recovered
            .pending(None, 1)
            .expect("owner remains readable")
            .is_empty()
    );
}

#[test]
fn accepted_unknown_anchor_ack_poisoning_requires_reopen_and_reconciliation() {
    let temp = NamedTempFile::new().expect("temporary journal");
    let binding = digest("anchored-accepted-unknown");
    let authority = AnchorAuthority::default();
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
        temp.reopen().expect("reopen"),
        binding,
        authority.clone(),
    )
    .expect("create anchored journal");

    let transition = lifecycle("unknown", digest("plan:unknown"), binding)[0].clone();
    authority.accept_then_report_unknown_once();
    assert_eq!(
        journal.append(transition.clone()),
        Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate)
    );
    assert_eq!(
        journal.pending(None, 1),
        Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate)
    );

    drop(journal);
    let mut recovered = AnchoredProductEvaluationAttemptJournalV1::recover(
        temp.reopen().expect("reopen"),
        binding,
        authority,
    )
    .expect("reconcile accepted write");
    let existing = recovered
        .latest(&id("unknown"))
        .expect("latest")
        .expect("record");
    assert_eq!(existing.transition, transition);
    assert_eq!(
        recovered
            .append(transition)
            .expect("exact replay after recovery"),
        existing
    );
}

#[test]
fn anchored_lifecycle_survives_every_single_crash_cut_and_exact_replay() {
    for cut in 0..=COMPLETE_LIFECYCLE_EVENTS {
        let temp = NamedTempFile::new().expect("temporary journal");
        let binding = digest(&format!("crash-cut-binding:{cut}"));
        let authority = AnchorAuthority::default();
        let transitions = lifecycle(
            &format!("crash-cut-{cut}"),
            digest(&format!("crash-cut-plan:{cut}")),
            binding,
        );
        let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
            temp.reopen().expect("reopen"),
            binding,
            authority.clone(),
        )
        .expect("create anchored journal");

        let mut previous = journal.anchor().expect("initial anchor");
        for transition in transitions.iter().take(cut) {
            let receipt = journal
                .append(transition.clone())
                .expect("append legal prefix");
            let committed = journal.anchor().expect("committed anchor");
            assert_eq!(committed.event_count, previous.event_count + 1);
            assert_ne!(committed.state_digest, previous.state_digest);
            assert_eq!(
                journal
                    .append(transition.clone())
                    .expect("exact replay is idempotent"),
                receipt
            );
            assert_eq!(
                journal.anchor().expect("replay does not move anchor"),
                committed
            );
            previous = committed;
        }

        drop(journal);
        let file = temp.reopen().expect("reopen journal file");
        let mut recovered =
            AnchoredProductEvaluationAttemptJournalV1::recover(file, binding, authority)
                .expect("recover every legal prefix");
        assert_eq!(
            recovered.anchor().expect("recovered anchor").event_count,
            cut as u64
        );

        for transition in transitions.iter().skip(cut) {
            recovered
                .append(transition.clone())
                .expect("complete after one crash");
        }
        let history = recovered
            .history(&transitions[0].attempt_id)
            .expect("complete history");
        assert_eq!(history.len(), COMPLETE_LIFECYCLE_EVENTS);
        assert_eq!(
            history.last().expect("terminal").transition.phase,
            ProductEvaluationAttemptPhaseV1::Published
        );
        assert_eq!(
            recovered.anchor().expect("terminal anchor").event_count,
            COMPLETE_LIFECYCLE_EVENTS as u64
        );
    }
}
