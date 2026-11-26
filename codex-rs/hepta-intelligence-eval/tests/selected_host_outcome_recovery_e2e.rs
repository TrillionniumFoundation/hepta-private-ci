use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::AnchoredProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::FencedFinalHoldoutOwnerV1;
use codex_hepta_intelligence_eval::HoldoutWriterFenceV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptPhaseV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationErrorV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
use ed25519_dalek::SigningKey;

#[path = "selected_host_recovery_support/outcome_model.rs"]
mod outcome_model;
#[path = "selected_host_recovery_support/security.rs"]
mod security;

use outcome_model::digest;
use outcome_model::fixture;
use outcome_model::id;
use security::FaultingAnchorStore;
use security::clock;
use security::principal;
use security::verifier_and_evidence;

static NEXT_ROOT: AtomicU64 = AtomicU64::new(0);

fn create(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap_or_else(|error| panic!("create test file: {error:?}"))
}

fn reopen(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("reopen test file: {error:?}"))
}

#[test]
fn selected_host_multi_outcome_artifacts_resume_after_anchor_ack_loss() {
    // Both archive acknowledgement and decision acknowledgement can be lost.
    exercise_recovery(4);
    exercise_recovery(5);
}

fn exercise_recovery(cut: u64) {
    use ProductEvaluationAttemptPhaseV1 as Phase;
    let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
    let root = std::env::temp_dir().join(format!(
        "hepta-selected-host-outcome-recovery-{}-{ordinal}",
        std::process::id()
    ));
    fs::create_dir(&root).unwrap_or_else(|error| panic!("test root: {error:?}"));
    let holdout_path = root.join("holdout.cas");
    let attempt_path = root.join("attempt.journal");
    let artifact_root = root.join("outcome-artifacts");
    let publication_root = root.join("publications");
    let namespace = digest("selected-host-outcome-holdout-namespace");
    let store = LockedFileFinalHoldoutCasStoreV1::create(create(&holdout_path), namespace)
        .unwrap_or_else(|error| panic!("holdout store: {error:?}"));
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        store,
        namespace,
        HoldoutWriterFenceV1 {
            owner_id: id("selected-host-outcome-owner"),
            generation: 1,
            lease_digest: digest("selected-host-outcome-lease"),
        },
    )
    .unwrap_or_else(|error| panic!("holdout owner: {error:?}"));
    let mut runner = RecordedProductEvaluationRunnerV1::new(owner);
    let attempt_binding = digest("selected-host-outcome-attempt-binding");
    let anchor_store = FaultingAnchorStore::new(cut);
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
        create(&attempt_path),
        attempt_binding,
        anchor_store.clone(),
    )
    .unwrap_or_else(|error| panic!("anchored journal: {error:?}"));
    let attempt_id = id("attempt:selected-host-outcome-recovery");
    let (plan, mut provider, roles) = fixture();
    let outcome = runner
        .evaluate_outcome_comparison(attempt_id.clone(), &plan, &mut provider, &mut journal)
        .unwrap_or_else(|error| panic!("multi-outcome comparison: {error:?}"));
    let scope = digest("selected-host-outcome-learning-scope");
    let generator_key = SigningKey::from_bytes(&[61; 32]);
    let evaluator_key = SigningKey::from_bytes(&[73; 32]);
    let context = ProductQualificationContextV1 {
        generator: principal("outcome-generator", &generator_key, scope),
        evaluator: principal("outcome-evaluator", &evaluator_key, scope),
        retention_receipt_digests: vec![digest("outcome-retention-receipt")],
        unlearning_receipt_digest: digest("outcome-unlearning-receipt"),
    };
    let bundle = runner
        .outcome_qualification_bundle(&outcome, &context)
        .unwrap_or_else(|error| panic!("outcome bundle: {error:?}"));
    let (trust, evidence) = verifier_and_evidence(&bundle, &roles, &generator_key, &evaluator_key);
    let selected_host_binding = digest("selected-host-outcome-binding");
    let mut current_clock = clock(50);
    let interrupted = runner.qualify_outcomes_and_persist_on_selected_host(
        &attempt_id,
        &outcome,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        &trust,
        &mut current_clock,
        &mut journal,
        &artifact_root,
        &publication_root,
        selected_host_binding,
    );
    assert!(matches!(
        interrupted,
        Err(RecordedProductEvaluationErrorV1::Journal(
            ProductEvaluationAttemptJournalErrorV1::Indeterminate
        ))
    ));
    assert_eq!(
        fs::read_dir(&artifact_root)
            .unwrap_or_else(|error| panic!("artifact root: {error:?}"))
            .count(),
        1
    );
    assert_eq!(
        fs::read_dir(&publication_root)
            .unwrap_or_else(|error| panic!("publication root: {error:?}"))
            .count(),
        0
    );
    drop((outcome, context, evidence, bundle, roles, provider));
    drop(journal);
    let mut recovered = AnchoredProductEvaluationAttemptJournalV1::recover(
        reopen(&attempt_path),
        attempt_binding,
        anchor_store.clone(),
    )
    .unwrap_or_else(|error| panic!("recover journal and anchor complete tail: {error:?}"));
    let before = recovered
        .latest(&attempt_id)
        .unwrap_or_else(|error| panic!("latest: {error:?}"))
        .unwrap_or_else(|| panic!("attempt"));
    assert_eq!(
        before.transition.phase,
        if cut == 4 {
            Phase::QualificationArtifactsPersisted
        } else {
            Phase::QualificationDecided
        }
    );
    assert!(
        runner
            .recover_selected_host_outcome_qualification(
                &mut recovered,
                &attempt_id,
                &artifact_root,
                &publication_root,
                digest("wrong-host"),
                &trust,
                &mut current_clock,
            )
            .is_err()
    );
    let mut expired_clock = clock(91);
    assert!(
        runner
            .recover_selected_host_outcome_qualification(
                &mut recovered,
                &attempt_id,
                &artifact_root,
                &publication_root,
                selected_host_binding,
                &trust,
                &mut expired_clock,
            )
            .is_err()
    );
    assert!(
        runner
            .recover_selected_host_qualification(
                &mut recovered,
                &attempt_id,
                &artifact_root,
                &publication_root,
                selected_host_binding,
                &trust,
                &mut current_clock,
            )
            .is_err(),
        "a multi-outcome archive is not a single-outcome archive"
    );
    assert_eq!(
        recovered
            .latest(&attempt_id)
            .unwrap_or_else(|error| panic!("unchanged: {error:?}")),
        Some(before)
    );
    assert_eq!(
        fs::read_dir(&publication_root)
            .unwrap_or_else(|error| panic!("no publication: {error:?}"))
            .count(),
        0
    );
    let published = runner
        .recover_selected_host_outcome_qualification(
            &mut recovered,
            &attempt_id,
            &artifact_root,
            &publication_root,
            selected_host_binding,
            &trust,
            &mut current_clock,
        )
        .unwrap_or_else(|error| {
            panic!("decode and re-verify actual persisted outcome bundle: {error:?}")
        });
    assert_eq!(published.transition.phase, Phase::Published);
    assert_eq!(
        fs::read_dir(&publication_root)
            .unwrap_or_else(|error| panic!("publication root: {error:?}"))
            .count(),
        1
    );
    let reconciled = RecordedProductEvaluationRunnerV1::<
        LockedFileFinalHoldoutCasStoreV1,
    >::reconcile_selected_host_outcome_publication(
        &mut recovered,
        &attempt_id,
        &publication_root,
        selected_host_binding,
    )
    .unwrap_or_else(|error| panic!("existing outcome publication reconciliation: {error:?}"));
    assert_eq!(reconciled, published);
    assert_eq!(
        fs::read_dir(&publication_root)
            .unwrap_or_else(|error| panic!("one publication: {error:?}"))
            .count(),
        1
    );
    assert!(
        runner
            .recover_selected_host_outcome_qualification(
                &mut recovered,
                &attempt_id,
                &artifact_root,
                &publication_root,
                selected_host_binding,
                &trust,
                &mut current_clock,
            )
            .is_err()
    );
    drop(recovered);
    let mut reopened = AnchoredProductEvaluationAttemptJournalV1::recover(
        reopen(&attempt_path),
        attempt_binding,
        anchor_store,
    )
    .unwrap_or_else(|error| panic!("second restart: {error:?}"));
    assert_eq!(
        reopened
            .history(&attempt_id)
            .unwrap_or_else(|error| panic!("history: {error:?}"))
            .iter()
            .map(|receipt| receipt.transition.phase)
            .collect::<Vec<_>>(),
        vec![
            Phase::IntentPersisted,
            Phase::HoldoutConsumed,
            Phase::ComparisonSealed,
            Phase::QualificationArtifactsPersisted,
            Phase::QualificationDecided,
            Phase::PublicationPending,
            Phase::Published,
        ]
    );
    drop((reopened, runner));
    fs::remove_dir_all(root).unwrap_or_else(|error| panic!("remove test root: {error:?}"));
}
