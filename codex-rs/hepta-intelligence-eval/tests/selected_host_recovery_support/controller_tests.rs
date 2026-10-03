//! Included by cold_recovery_e2e, not a separately discovered Cargo test crate.
use super::*;
use std::fs::File;
use std::fs::OpenOptions;

pub(super) fn recover_page<
    S: FinalHoldoutCasStoreV1,
    J: DurableProductEvaluationAttemptJournalV1,
>(
    runner: &RecordedProductEvaluationRunnerV1<S>,
    journal: &mut J,
    root: &Path,
    mode: &str,
    before: &ProductEvaluationAttemptReceiptV1,
) -> Option<ProductEvaluationAttemptReceiptV1> {
    let blocked = host::id("a:unresolved-attempt");
    if mode == "page-first" {
        journal
            .append(ProductEvaluationAttemptTransitionV1::intent(
                blocked,
                host::digest("unresolved-plan"),
                namespace(),
                host::digest("unresolved-owner-state"),
            ))
            .unwrap_or_else(|error| panic!("record a prior unresolved attempt: {error:?}"));
    }
    let cursor_path = root.join("recovery.cursor");
    let cursor = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&cursor_path)
        .unwrap_or_else(|error| panic!("open cursor file: {error:?}"));
    File::open(root)
        .and_then(|file| file.sync_all())
        .unwrap_or_else(|error| panic!("durable cursor directory: {error:?}"));

    if mode == "page-late-expired" {
        // Opening a new cursor durably initializes its two-slot envelope even
        // before an attempt is handled. Establish that initialized baseline
        // through the real owner API with an actually empty anchored inventory.
        let mut initialization_journal = AnchoredProductEvaluationAttemptJournalV1::create(
            storage::create(&root.join("cursor-initialization.journal")),
            attempt_binding(),
            storage::DiskAnchor::new(&root.join("cursor-initialization.anchor"), None),
        )
        .unwrap_or_else(|error| panic!("empty anchored initialization inventory: {error:?}"));
        let mut initialization_clock = host::clock(85);
        let initialized = runner.recover_selected_host_pending_page(
            &mut initialization_journal,
            cursor,
            &root.join("artifacts"),
            &root.join("publications"),
            host_binding(),
            &mut initialization_clock,
            || Ok(host::activate()),
            Duration::from_secs(30),
            1,
        );
        assert!(
            initialized
                .unwrap_or_else(|error| panic!("empty inventory cursor initialization: {error:?}"))
                .is_empty()
        );
        drop(initialization_journal);
        assert_eq!(
            journal
                .latest(&before.transition.attempt_id)
                .unwrap_or_else(|error| panic!("unchanged attempt: {error:?}")),
            Some(before.clone())
        );
        let cursor_before =
            fs::read(&cursor_path).unwrap_or_else(|error| panic!("initialized cursor: {error:?}"));
        let cursor = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&cursor_path)
            .unwrap_or_else(|error| panic!("reopen initialized cursor: {error:?}"));
        let mut clock = host::scripted_clock(&[85, 91]);
        let result = runner.recover_selected_host_pending_page(
            journal,
            cursor,
            &root.join("artifacts"),
            &root.join("publications"),
            host_binding(),
            &mut clock,
            || Ok(host::activate()),
            Duration::from_secs(30),
            1,
        );
        assert!(matches!(
            result,
            Err(RecordedProductEvaluationErrorV1::Invariant(_))
        ));
        assert_eq!(
            fs::read(&cursor_path).unwrap_or_else(|error| panic!("cursor: {error:?}")),
            cursor_before,
            "late clock/trust failure must abort before cursor advancement"
        );
        assert_eq!(
            journal
                .latest(&before.transition.attempt_id)
                .unwrap_or_else(|error| panic!("attempt: {error:?}"))
                .unwrap_or_else(|| panic!("latest"))
                .transition
                .phase,
            ProductEvaluationAttemptPhaseV1::PublicationPending
        );
        assert_eq!(
            fs::read_dir(root.join("publications"))
                .unwrap_or_else(|error| panic!("publications: {error:?}"))
                .count(),
            0
        );
        let cursor = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&cursor_path)
            .unwrap_or_else(|error| panic!("reopen after final-use refusal: {error:?}"));
        let mut reopened_attempts = 0;
        let reopened = runner.recover_selected_host_pending_page(
            journal,
            cursor,
            &root.join("artifacts"),
            &root.join("publications"),
            host_binding(),
            &mut clock,
            || {
                reopened_attempts += 1;
                Err(RecordedProductEvaluationErrorV1::Invariant(
                    "fixture cursor reopen",
                ))
            },
            Duration::from_secs(30),
            1,
        );
        assert!(matches!(
            reopened,
            Err(RecordedProductEvaluationErrorV1::Invariant(
                "fixture cursor reopen"
            ))
        ));
        assert_eq!(
            reopened_attempts, 1,
            "reopened cursor must still inventory the refused identity"
        );
        assert_eq!(
            fs::read(&cursor_path).unwrap_or_else(|error| panic!("unchanged cursor: {error:?}")),
            cursor_before
        );
        return None;
    }

    if mode == "page-first" {
        // The first identity is durably handled with one active trust snapshot.
        // A regressed owner-clock sample on the second identity aborts the page
        // before that identity can be verified, but the first cursor advancement
        // survives the process boundary. Trust and time are resolved per attempt.
        let mut calls = 0_u8;
        let mut clock = host::scripted_clock(&[85, 84]);
        let result = runner.recover_selected_host_pending_page(
            journal,
            cursor,
            &root.join("artifacts"),
            &root.join("publications"),
            host_binding(),
            &mut clock,
            || {
                calls += 1;
                Ok::<_, RecordedProductEvaluationErrorV1>(host::activate())
            },
            Duration::from_secs(30),
            2,
        );
        assert!(matches!(
            result,
            Err(RecordedProductEvaluationErrorV1::Invariant(
                "recovery host clock regressed"
            ))
        ));
        assert_eq!(calls, 2, "active trust must be resolved per attempt");
        assert!(
            !fs::read(&cursor_path)
                .unwrap_or_else(|error| panic!("persisted cursor: {error:?}"))
                .is_empty(),
            "the first handled identity must survive the later page abort"
        );
        assert_eq!(
            journal
                .latest(&before.transition.attempt_id)
                .unwrap_or_else(|error| panic!("actual attempt: {error:?}")),
            Some(before.clone())
        );
        assert_eq!(
            fs::read_dir(root.join("publications"))
                .unwrap_or_else(|error| panic!("publications: {error:?}"))
                .count(),
            0
        );
        return None;
    }

    let mut clock = host::clock(85);
    let mut result = runner
        .recover_selected_host_pending_page(
            journal,
            cursor,
            &root.join("artifacts"),
            &root.join("publications"),
            host_binding(),
            &mut clock,
            || Ok(host::activate()),
            Duration::from_secs(30),
            1,
        )
        .unwrap_or_else(|error| panic!("bounded persistent recovery page: {error:?}"));
    assert_eq!(result.len(), 1);
    let (attempt, result) = result.pop().unwrap_or_else(|| panic!("one result"));
    assert_eq!(
        attempt, before.transition.attempt_id,
        "fresh process must advance past the unresolved predecessor"
    );
    Some(result.unwrap_or_else(|error| {
        panic!("native archive recovery through persistent controller: {error:?}")
    }))
}

#[test]
fn persistent_page_aborts_at_expired_final_use_without_cursor_advance() {
    for family in ["temporal", "outcome", "longitudinal"] {
        let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-page-final-use-{}-{ordinal}-{family}",
            std::process::id()
        ));
        fs::create_dir(&root).expect("root");
        assert_eq!(child(&root, family, "produce", 4).code(), Some(73));
        assert!(child(&root, family, "page-late-expired", 4).success());
        fs::remove_dir_all(root).expect("remove fixture");
    }
}

#[test]
fn persistent_page_controller_advances_past_unresolved_work_across_processes() {
    for family in ["temporal", "outcome", "longitudinal"] {
        let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-cold-page-{}-{ordinal}-{family}",
            std::process::id()
        ));
        fs::create_dir(&root).expect("root");
        let status = child(&root, family, "produce", 4);
        assert_eq!(status.code(), Some(73));
        let holdout_before = fs::read(root.join("holdout.cas")).expect("holdout");
        assert!(child(&root, family, "page-first", 4).success());
        let cursor_before = fs::read(root.join("recovery.cursor")).expect("cursor");
        assert!(child(&root, family, "page-next", 4).success());
        assert_ne!(
            fs::read(root.join("recovery.cursor")).expect("advanced cursor"),
            cursor_before
        );
        let published = fs::read(root.join("attempt.journal")).expect("journal");
        assert!(child(&root, family, "reconcile", 4).success());
        assert_eq!(
            fs::read(root.join("attempt.journal")).expect("unchanged journal"),
            published
        );
        assert_eq!(
            fs::read(root.join("holdout.cas")).expect("unchanged holdout"),
            holdout_before
        );
        fs::remove_dir_all(root).expect("remove fixture");
    }
}
