use super::*;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

fn transition(
    name: &str,
    phase: ProductEvaluationAttemptPhaseV1,
) -> ProductEvaluationAttemptTransitionV1 {
    ProductEvaluationAttemptTransitionV1 {
        attempt_id: StableId::new(name).expect("id"),
        plan_digest: Digest32::of_bytes(name.as_bytes()),
        phase,
        holdout_record_digest: Digest32::of_bytes(b"holdout"),
        terminal_digest: Digest32::of_bytes(b"payload"),
    }
}

#[test]
fn reserve_full_lifecycle_not_just_the_intent_frame() {
    let capacity = AttemptCapacity::default();
    let intent = transition("a", ProductEvaluationAttemptPhaseV1::IntentPersisted);
    let reserved = capacity.project(None, &intent).expect("projection");
    let header = 72;
    let frame = 136;
    assert!(
        reserved
            .check(header + frame, 1, header + frame, 7)
            .is_err()
    );
    assert!(
        reserved
            .check(header + frame, 1, header + 7 * frame, 6)
            .is_err()
    );
    assert_eq!(
        reserved.check(header + frame, 1, header + 7 * frame, 7),
        Ok(())
    );
}

#[test]
fn admitted_work_keeps_capacity_when_new_work_is_rejected() {
    use ProductEvaluationAttemptPhaseV1 as Phase;
    let mut capacity = AttemptCapacity::default();
    let first = transition("a", Phase::IntentPersisted);
    let reserved = capacity.project(None, &first).expect("first");
    capacity.install(reserved, &first);
    let second = transition("b", Phase::IntentPersisted);
    let rejected = capacity.project(None, &second).expect("project second");
    assert!(rejected.check(72 + 2 * 136, 2, 72 + 7 * 136, 7).is_err());
    // Rejected admission did not mutate the reservation. Every existing step
    // still fits, including archive persistence and terminal publication.
    let mut previous = Phase::IntentPersisted;
    for (index, phase) in [
        Phase::HoldoutConsumed,
        Phase::ComparisonSealed,
        Phase::QualificationArtifactsPersisted,
        Phase::QualificationDecided,
        Phase::PublicationPending,
        Phase::Published,
    ]
    .into_iter()
    .enumerate()
    {
        let next = transition("a", phase);
        let reserved = capacity.project(Some(previous), &next).expect("advance");
        reserved
            .check(72 + (index as u64 + 2) * 136, index + 2, 72 + 7 * 136, 7)
            .expect("reserved capacity");
        capacity.install(reserved, &next);
        previous = phase;
    }
    assert_eq!(capacity.reserved(), Reservation::default());
}

#[test]
fn pending_index_skips_completed_history_and_rebuilds_deterministically() {
    use ProductEvaluationAttemptPhaseV1 as Phase;
    let mut capacity = AttemptCapacity::default();
    let mut attempts = AttemptEvents::new();
    for index in 0..4096 {
        let name = format!("attempt-{index:04}");
        let phase = if index == 4095 {
            Phase::PublicationPending
        } else {
            Phase::Published
        };
        let event = transition(&name, phase);
        let reservation = capacity.project(None, &event).expect("rebuild");
        capacity.install(reservation, &event);
        attempts.insert(
            event.attempt_id.clone(),
            vec![ProductEvaluationAttemptReceiptV1 {
                transition: event,
                sequence: 1,
                predecessor_digest: Digest32::ZERO,
                event_digest: Digest32::of_bytes(name.as_bytes()),
                authority: AuthorityPosture::DENY_ALL,
            }],
        );
    }
    assert_eq!(capacity.pending.len(), 1);
    let result = capacity.pending_page(&attempts, None, 1).expect("page");
    assert_eq!(result[0].transition.attempt_id.as_str(), "attempt-4095");
    assert!(
        capacity
            .pending_page(&attempts, Some(&result[0].transition.attempt_id), 1)
            .expect("end")
            .is_empty()
    );
    assert!(capacity.pending_page(&attempts, None, 0).is_err());
}
