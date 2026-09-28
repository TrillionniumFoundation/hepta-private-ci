use std::fs::OpenOptions;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::LockedFileProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptPhaseV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptTransitionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

fn digest(domain: &str, ordinal: usize) -> Digest32 {
    Digest32::of_bytes(format!("{domain}:{ordinal}").as_bytes())
}

#[test]
fn persistent_attempt_journal_sustains_restart_batches() {
    let attempts = std::env::var("HEPTA_LEARNING_EVAL_SOAK_ATTEMPTS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(256);
    assert!((256..=4096).contains(&attempts));

    let ordinal = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "hepta-learning-eval-soak-{}-{ordinal}",
        std::process::id()
    ));
    let binding = Digest32::of_bytes(b"learning-eval-selected-host-soak");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
        .expect("create journal");
    let mut journal =
        LockedFileProductEvaluationAttemptJournalV1::create(file, binding).expect("journal");

    for index in 0..attempts {
        let attempt_id =
            StableId::new(format!("attempt:soak-{index}")).expect("attempt id");
        let plan = digest("plan", index);
        let holdout = digest("holdout", index);
        let execution = digest("execution", index);
        let artifacts = digest("qualification-artifacts", index);
        let request = digest("request", index);
        let publication = digest("publication", index);

        journal
            .append(ProductEvaluationAttemptTransitionV1::intent(
                attempt_id.clone(),
                plan,
                binding,
                digest("owner-state", index),
            ))
            .expect("intent");
        journal
            .append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
                attempt_id.clone(),
                plan,
                holdout,
            ))
            .expect("consumed");
        journal
            .append(ProductEvaluationAttemptTransitionV1::comparison_sealed(
                attempt_id.clone(),
                plan,
                holdout,
                execution,
            ))
            .expect("comparison");
        journal
            .append(ProductEvaluationAttemptTransitionV1 {
                attempt_id: attempt_id.clone(),
                plan_digest: plan,
                phase: ProductEvaluationAttemptPhaseV1::QualificationArtifactsPersisted,
                holdout_record_digest: holdout,
                terminal_digest: artifacts,
            })
            .expect("qualification artifacts");
        for phase in [
            ProductEvaluationAttemptPhaseV1::QualificationDecided,
            ProductEvaluationAttemptPhaseV1::PublicationPending,
        ] {
            journal
                .append(ProductEvaluationAttemptTransitionV1 {
                    attempt_id: attempt_id.clone(),
                    plan_digest: plan,
                    phase,
                    holdout_record_digest: holdout,
                    terminal_digest: request,
                })
                .expect("publication prewrite");
        }
        journal
            .append(ProductEvaluationAttemptTransitionV1 {
                attempt_id,
                plan_digest: plan,
                phase: ProductEvaluationAttemptPhaseV1::Published,
                holdout_record_digest: holdout,
                terminal_digest: publication,
            })
            .expect("published");

        if (index + 1) % 128 == 0 || index + 1 == attempts {
            let anchor = journal.anchor().expect("anchor");
            assert_eq!(anchor.event_count, ((index + 1) * 7) as u64);
            drop(journal);
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .open(&path)
                .expect("reopen journal");
            journal = LockedFileProductEvaluationAttemptJournalV1::recover_with_anchor(
                file, binding, anchor,
            )
            .expect("anchored restart recovery");
            assert_eq!(journal.event_count(), (index + 1) * 7);
        }
    }

    assert!(journal.pending(None, 1).expect("pending").is_empty());
    println!(
        "learning.eval soak attempts={attempts} events={} bytes={}",
        journal.event_count(),
        journal.byte_len()
    );
    drop(journal);
    let _ = std::fs::remove_file(path);
}
