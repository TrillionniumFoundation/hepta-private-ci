use std::fs;
use std::fs::OpenOptions;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::LockedFileProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptPhaseV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptTransitionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

static NEXT_FILE: AtomicU64 = AtomicU64::new(0);
const HEADER_BYTES: u64 = 72;
const ONE_BYTE_ID_FRAME: u64 = 136;
const COMPLETE_LIFECYCLE_EVENTS: usize = 7;
const COMPLETE_LIFECYCLE_BYTES: u64 =
    HEADER_BYTES + COMPLETE_LIFECYCLE_EVENTS as u64 * ONE_BYTE_ID_FRAME;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("stable id: {error:?}"))
}

fn open(path: &std::path::Path, create: bool) -> std::fs::File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(create)
        .open(path)
        .unwrap_or_else(|error| panic!("journal file: {error:?}"))
}

#[test]
fn near_capacity_rejects_new_admission_but_reserved_attempt_reaches_terminal() {
    let ordinal = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "hepta-learning-eval-near-capacity-{}-{ordinal}",
        std::process::id()
    ));
    let binding = digest("qualification-capacity-binding");
    let mut journal =
        LockedFileProductEvaluationAttemptJournalV1::create_with_qualification_limits(
            open(&path, true),
            binding,
            COMPLETE_LIFECYCLE_BYTES,
            COMPLETE_LIFECYCLE_EVENTS,
        )
        .expect("qualification journal");

    let attempt = id("a");
    let plan = digest("plan-a");
    let holdout = digest("holdout-a");
    let execution = digest("execution-a");
    let artifacts = digest("artifacts-a");
    let request = digest("request-a");
    let publication = digest("publication-a");

    journal
        .append(ProductEvaluationAttemptTransitionV1::intent(
            attempt.clone(),
            plan,
            binding,
            digest("owner-state-a"),
        ))
        .expect("reserve the complete lifecycle");

    let rejected = journal.append(ProductEvaluationAttemptTransitionV1::intent(
        id("b"),
        digest("plan-b"),
        binding,
        digest("owner-state-b"),
    ));
    assert!(matches!(
        rejected,
        Err(ProductEvaluationAttemptJournalErrorV1::Capacity)
    ));
    assert_eq!(
        journal.event_count(),
        1,
        "rejected admission must not append"
    );

    journal
        .append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
            attempt.clone(),
            plan,
            holdout,
        ))
        .expect("consumption uses reserved capacity");
    journal
        .append(ProductEvaluationAttemptTransitionV1::comparison_sealed(
            attempt.clone(),
            plan,
            holdout,
            execution,
        ))
        .expect("comparison uses reserved capacity");
    journal
        .append(ProductEvaluationAttemptTransitionV1 {
            attempt_id: attempt.clone(),
            plan_digest: plan,
            phase: ProductEvaluationAttemptPhaseV1::QualificationArtifactsPersisted,
            holdout_record_digest: holdout,
            terminal_digest: artifacts,
        })
        .expect("archive uses reserved capacity");
    for phase in [
        ProductEvaluationAttemptPhaseV1::QualificationDecided,
        ProductEvaluationAttemptPhaseV1::PublicationPending,
    ] {
        journal
            .append(ProductEvaluationAttemptTransitionV1 {
                attempt_id: attempt.clone(),
                plan_digest: plan,
                phase,
                holdout_record_digest: holdout,
                terminal_digest: request,
            })
            .expect("publication prewrite uses reserved capacity");
    }
    journal
        .append(ProductEvaluationAttemptTransitionV1 {
            attempt_id: attempt.clone(),
            plan_digest: plan,
            phase: ProductEvaluationAttemptPhaseV1::Published,
            holdout_record_digest: holdout,
            terminal_digest: publication,
        })
        .expect("terminal publication uses reserved capacity");

    assert_eq!(journal.event_count(), COMPLETE_LIFECYCLE_EVENTS);
    assert_eq!(journal.byte_len(), COMPLETE_LIFECYCLE_BYTES);
    assert!(journal.pending(None, 1).expect("pending index").is_empty());
    drop(journal);

    let mut recovered =
        LockedFileProductEvaluationAttemptJournalV1::recover_with_qualification_limits(
            open(&path, false),
            binding,
            COMPLETE_LIFECYCLE_BYTES,
            COMPLETE_LIFECYCLE_EVENTS,
        )
        .expect("recover the exact full-capacity history");
    assert_eq!(recovered.event_count(), COMPLETE_LIFECYCLE_EVENTS);
    assert_eq!(recovered.byte_len(), COMPLETE_LIFECYCLE_BYTES);
    assert_eq!(
        recovered
            .latest(&attempt)
            .expect("latest")
            .expect("attempt")
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
    assert!(matches!(
        recovered.append(ProductEvaluationAttemptTransitionV1::intent(
            id("b"),
            digest("plan-b"),
            binding,
            digest("owner-state-b"),
        )),
        Err(ProductEvaluationAttemptJournalErrorV1::Capacity)
    ));

    drop(recovered);
    fs::remove_file(path).expect("remove fixture");
}

#[test]
fn qualification_limits_can_only_tighten_hard_backend_bounds() {
    let ordinal = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "hepta-learning-eval-invalid-capacity-{}-{ordinal}",
        std::process::id()
    ));
    let binding = digest("invalid-capacity-binding");
    let too_small = LockedFileProductEvaluationAttemptJournalV1::create_with_qualification_limits(
        open(&path, true),
        binding,
        COMPLETE_LIFECYCLE_BYTES - 1,
        COMPLETE_LIFECYCLE_EVENTS,
    );
    assert!(matches!(
        too_small,
        Err(ProductEvaluationAttemptJournalErrorV1::Capacity)
    ));
    fs::remove_file(path).expect("remove fixture");
}
