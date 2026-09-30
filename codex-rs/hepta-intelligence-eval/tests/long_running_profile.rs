use std::cell::RefCell;
use std::fs;
use std::fs::OpenOptions;
use std::rc::Rc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::LockedFileProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptPhaseV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptTransitionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

fn digest(domain: &str, ordinal: usize) -> Digest32 {
    Digest32::of_bytes(format!("{domain}:{ordinal}").as_bytes())
}

#[derive(Clone, Default)]
struct CheckpointAuthority(Rc<RefCell<Option<ProductEvaluationAttemptAnchorV1>>>);

impl ProductEvaluationAttemptAnchorStoreV1 for CheckpointAuthority {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Ok(self
            .0
            .borrow()
            .as_ref()
            .copied()
            .filter(|value| value.binding == binding))
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
fn persistent_attempt_journal_sustains_checkpointed_restart_batches() {
    let attempts = std::env::var("HEPTA_LEARNING_EVAL_SOAK_ATTEMPTS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(256);
    assert!((256..=4096).contains(&attempts));

    let ordinal = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
    let root = std::env::temp_dir().join(format!(
        "hepta-learning-eval-soak-{}-{ordinal}",
        std::process::id()
    ));
    fs::create_dir(&root).expect("create soak root");
    let path = root.join("attempt.journal");
    let binding = Digest32::of_bytes(b"learning-eval-selected-host-soak");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
        .expect("create journal");
    let mut journal =
        LockedFileProductEvaluationAttemptJournalV1::create(file, binding).expect("journal");
    let mut checkpoint_authority = CheckpointAuthority::default();
    let mut checkpoint_path = None;

    for index in 0..attempts {
        let attempt_id = StableId::new(format!("attempt:soak-{index}")).expect("attempt id");
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

        if (index + 1) % 128 == 64 {
            let next = root.join(format!("attempt-{}.checkpoint", index + 1));
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(&next)
                .expect("create checkpoint");
            journal
                .checkpoint_into(file, &mut checkpoint_authority)
                .expect("independently retained checkpoint");
            if let Some(previous) = checkpoint_path.replace(next) {
                fs::remove_file(previous).expect("retire predecessor checkpoint");
            }
        }

        if (index + 1) % 128 == 0 || index + 1 == attempts {
            let anchor = journal.anchor().expect("anchor");
            assert_eq!(anchor.event_count, ((index + 1) * 7) as u64);
            let retained_checkpoint = checkpoint_path.as_ref().expect("checkpoint frontier");
            drop(journal);
            let file = OpenOptions::new()
                .read(true)
                .write(true)
                .open(&path)
                .expect("reopen journal");
            let checkpoint = OpenOptions::new()
                .read(true)
                .write(true)
                .open(retained_checkpoint)
                .expect("reopen checkpoint");
            journal = LockedFileProductEvaluationAttemptJournalV1::recover_with_checkpoint(
                file,
                checkpoint,
                binding,
                anchor,
                &mut checkpoint_authority,
            )
            .expect("checkpointed tail recovery");
            assert_eq!(journal.event_count(), (index + 1) * 7);
        }
    }

    assert!(journal.pending(None, 1).expect("pending").is_empty());
    println!(
        "learning.eval checkpoint soak attempts={attempts} events={} bytes={}",
        journal.event_count(),
        journal.byte_len()
    );
    drop(journal);
    fs::remove_dir_all(root).expect("remove soak root");
}
