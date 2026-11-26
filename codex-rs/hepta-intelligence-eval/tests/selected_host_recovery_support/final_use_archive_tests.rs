//! Replace only the unsigned archive holdout field after native Pending is
//! independently acknowledged. The signed decision and payload stay untouched.
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use pretty_assertions::assert_eq;

use super::*;

struct ReplacingAnchor {
    inner: storage::DiskAnchor,
    artifacts: PathBuf,
    original: Arc<Mutex<Option<Vec<u8>>>>,
}

impl ProductEvaluationAttemptAnchorStoreV1 for ReplacingAnchor {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.inner.load(binding)
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        self.inner.compare_and_swap(binding, expected, next)?;
        if next.event_count == 6 {
            let path = fs::read_dir(&self.artifacts)
                .unwrap_or_else(|error| panic!("persisted artifact directory: {error:?}"))
                .next()
                .unwrap_or_else(|| panic!("native artifact"))
                .unwrap_or_else(|error| panic!("artifact entry: {error:?}"))
                .path();
            let bytes = fs::read(&path)
                .unwrap_or_else(|error| panic!("original native archive: {error:?}"));
            assert_eq!(&bytes[..8], b"HQARCV02");
            // V2 wrapper: magic, family, length-prefixed attempt ID, then host,
            // namespace, execution and holdout digests. No signed payload is
            // rewritten, and this attack does not supply a decoder to eval.
            let id_length = u32::from_be_bytes(
                bytes[9..13]
                    .try_into()
                    .unwrap_or_else(|error| panic!("attempt ID length width: {error:?}")),
            ) as usize;
            let holdout_offset = 13 + id_length + 3 * 32;
            let mut changed = bytes.clone();
            changed[holdout_offset..holdout_offset + 32]
                .copy_from_slice(host::digest("substituted-unsigned-holdout").as_array());
            assert_ne!(changed, bytes);
            fs::write(path, changed)
                .unwrap_or_else(|error| panic!("replace archive after Pending: {error:?}"));
            *self
                .original
                .lock()
                .unwrap_or_else(|error| panic!("original archive lock: {error:?}")) = Some(bytes);
        }
        Ok(())
    }
}

fn cold_qualify(
    root: &Path,
    family: &str,
    authority: ReplacingAnchor,
) -> Result<(), RecordedProductEvaluationErrorV1> {
    // The cold branch cannot construct fresh qualification evidence.
    let store = LockedFileFinalHoldoutCasStoreV1::recover(
        storage::reopen(&root.join("holdout.cas")),
        namespace(),
        Some(storage::load_holdout_anchor(&root.join("holdout.anchor"))),
    )
    .unwrap_or_else(|error| panic!("cold holdout store: {error:?}"));
    let owner = FencedFinalHoldoutOwnerV1::recover(store, namespace(), fence())
        .unwrap_or_else(|error| panic!("cold holdout owner: {error:?}"));
    let runner = RecordedProductEvaluationRunnerV1::new(owner);
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::recover(
        storage::reopen(&root.join("attempt.journal")),
        attempt_binding(),
        authority,
    )
    .unwrap_or_else(|error| panic!("cold anchored journal: {error:?}"));
    let attempt = host::id("cold-process-attempt");
    let trust = host::activate();
    let mut clock = host::clock(85);
    let result = if family == "outcome" {
        runner.recover_selected_host_outcome_qualification(
            &mut journal,
            &attempt,
            root.join("artifacts"),
            root.join("publications"),
            host_binding(),
            &trust,
            &mut clock,
        )
    } else {
        runner.recover_selected_host_qualification(
            &mut journal,
            &attempt,
            root.join("artifacts"),
            root.join("publications"),
            host_binding(),
            &trust,
            &mut clock,
        )
    };
    result.map(|_| ())
}

#[test]
fn selected_host_initial_and_cold_final_use_require_exact_anchored_archive() {
    for family in ["temporal", "outcome", "longitudinal"] {
        for mode in ["initial", "cold"] {
            let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
            let root = std::env::temp_dir().join(format!(
                "hepta-archive-final-use-{}-{ordinal}-{family}-{mode}",
                std::process::id(),
            ));
            fs::create_dir(&root).unwrap_or_else(|error| panic!("archive attack root: {error:?}"));
            if mode == "cold" {
                assert_eq!(child(&root, family, "produce", 4).code(), Some(73));
            }
            let original = Arc::new(Mutex::new(None));
            let authority = ReplacingAnchor {
                inner: storage::DiskAnchor::new(&root.join("anchor"), None),
                artifacts: root.join("artifacts"),
                original: Arc::clone(&original),
            };
            let result = if mode == "cold" {
                cold_qualify(&root, family, authority)
            } else {
                qualify_with_anchor(
                    &root,
                    family,
                    &mut host::clock(85),
                    &host::activate(),
                    authority,
                )
            };
            assert!(
                matches!(
                    result,
                    Err(RecordedProductEvaluationErrorV1::Evaluation(
                        ProductEvaluationError::Integrity("selected-host final-use archive digest")
                    ))
                ),
                "{family}/{mode}: {result:?}"
            );
            let bytes = original
                .lock()
                .unwrap_or_else(|error| panic!("original lock: {error:?}"))
                .take()
                .unwrap_or_else(|| panic!("replacement callback must run after Pending"));
            let mut journal = AnchoredProductEvaluationAttemptJournalV1::recover(
                storage::reopen(&root.join("attempt.journal")),
                attempt_binding(),
                storage::DiskAnchor::new(&root.join("anchor"), None),
            )
            .unwrap_or_else(|error| panic!("independent anchored Pending: {error:?}"));
            let attempt = host::id("cold-process-attempt");
            let history = journal
                .history(&attempt)
                .unwrap_or_else(|error| panic!("anchored history: {error:?}"));
            assert_eq!(history.len(), 6);
            assert_eq!(
                history[3].transition.terminal_digest,
                Digest32::of_bytes(&bytes)
            );
            assert_eq!(
                history[3].transition.holdout_record_digest,
                history[2].transition.holdout_record_digest
            );
            assert_eq!(
                history[5].transition.phase,
                ProductEvaluationAttemptPhaseV1::PublicationPending
            );
            assert_eq!(
                fs::read_dir(root.join("publications"))
                    .unwrap_or_else(|error| panic!("publication root: {error:?}"))
                    .count(),
                0
            );
            let before = fs::read(root.join("attempt.journal"))
                .unwrap_or_else(|error| panic!("pending bytes: {error:?}"));
            assert_eq!(RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::reconcile_selected_host_publication(
                &mut journal, &attempt, root.join("publications"), host_binding(),
            ), Err(ProductAttemptRecoveryErrorV1::Unresolved));
            assert_eq!(
                fs::read(root.join("attempt.journal"))
                    .unwrap_or_else(|error| panic!("unchanged Pending: {error:?}")),
                before
            );
            drop(journal);
            fs::remove_dir_all(root)
                .unwrap_or_else(|error| panic!("remove archive attack fixture: {error:?}"));
        }
    }
}
