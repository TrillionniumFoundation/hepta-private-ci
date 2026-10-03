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
) -> FixtureResult<Option<ProductEvaluationAttemptReceiptV1>> {
    let blocked = host::id("a:unresolved-attempt")?;
    if mode == "page-first" {
        journal.append(ProductEvaluationAttemptTransitionV1::intent(
            blocked,
            host::digest("unresolved-plan"),
            namespace(),
            host::digest("unresolved-owner-state"),
        ))?;
    }
    let cursor_path = root.join("recovery.cursor");
    let cursor = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&cursor_path)?;
    File::open(root).and_then(|file| file.sync_all())?;

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
                host::activate().map_err(|_| {
                    RecordedProductEvaluationErrorV1::Invariant("fixture trust activation failed")
                })
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
            !fs::read(&cursor_path)?.is_empty(),
            "the first handled identity must survive the later page abort"
        );
        assert_eq!(
            journal.latest(&before.transition.attempt_id)?,
            Some(before.clone())
        );
        assert_eq!(fs::read_dir(root.join("publications"))?.count(), 0);
        return Ok(None);
    }

    let mut clock = host::clock(85);
    let mut result = runner.recover_selected_host_pending_page(
        journal,
        cursor,
        &root.join("artifacts"),
        &root.join("publications"),
        host_binding(),
        &mut clock,
        || {
            host::activate().map_err(|_| {
                RecordedProductEvaluationErrorV1::Invariant("fixture trust activation failed")
            })
        },
        Duration::from_secs(30),
        1,
    )?;
    assert_eq!(result.len(), 1);
    let (attempt, result) = result.pop().ok_or("one result")?;
    assert_eq!(
        attempt, before.transition.attempt_id,
        "fresh process must advance past the unresolved predecessor"
    );
    Ok(Some(result?))
}

#[test]
fn persistent_page_controller_advances_past_unresolved_work_across_processes() -> FixtureResult<()>
{
    for family in ["temporal", "outcome", "longitudinal"] {
        let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-cold-page-{}-{ordinal}-{family}",
            std::process::id()
        ));
        fs::create_dir(&root).expect("root");
        let status = child(&root, family, "produce", 4)?;
        assert_eq!(status.code(), Some(73));
        let holdout_before = fs::read(root.join("holdout.cas")).expect("holdout");
        assert!(child(&root, family, "page-first", 4)?.success());
        let cursor_before = fs::read(root.join("recovery.cursor")).expect("cursor");
        assert!(child(&root, family, "page-next", 4)?.success());
        assert_ne!(
            fs::read(root.join("recovery.cursor")).expect("advanced cursor"),
            cursor_before
        );
        let published = fs::read(root.join("attempt.journal")).expect("journal");
        assert!(child(&root, family, "reconcile", 4)?.success());
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
    Ok(())
}
