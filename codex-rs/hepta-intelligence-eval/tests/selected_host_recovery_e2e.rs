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

#[path = "selected_host_recovery_support/model.rs"]
mod model;
#[path = "selected_host_recovery_support/security.rs"]
mod security;

use model::Provider;
use model::digest;
use model::id;
use model::inputs;
use model::product_plan;
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
        .expect("create test file")
}

fn reopen(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("reopen test file")
}

#[test]
fn selected_host_complete_signed_artifacts_resume_after_anchor_ack_loss() {
    use ProductEvaluationAttemptPhaseV1 as Phase;
    let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
    let root = std::env::temp_dir().join(format!(
        "hepta-selected-host-recovery-{}-{ordinal}",
        std::process::id()
    ));
    fs::create_dir(&root).expect("test root");
    let holdout_path = root.join("holdout.cas");
    let attempt_path = root.join("attempt.journal");
    let artifact_root = root.join("artifacts");
    let publication_root = root.join("publications");
    let namespace = digest("selected-host-holdout-namespace");
    let store = LockedFileFinalHoldoutCasStoreV1::create(create(&holdout_path), namespace)
        .expect("holdout store");
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        store,
        namespace,
        HoldoutWriterFenceV1 {
            owner_id: id("selected-host-owner"),
            generation: 1,
            lease_digest: digest("selected-host-lease"),
        },
    )
    .expect("holdout owner");
    let mut runner = RecordedProductEvaluationRunnerV1::new(owner);
    let attempt_binding = digest("selected-host-attempt-binding");
    // Event four binds the complete typed archive; event five is the decision.
    let anchor_store = FaultingAnchorStore::new(5);
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
        create(&attempt_path),
        attempt_binding,
        anchor_store.clone(),
    )
    .expect("anchored journal");
    let attempt_id = id("attempt:selected-host-recovery");
    let (plan, candidate, baseline) = product_plan();
    let mut provider = Provider {
        inputs: Some(inputs()),
    };
    let temporal = runner
        .evaluate_temporal_comparison(
            attempt_id.clone(),
            &plan,
            &candidate,
            &baseline,
            &mut provider,
            &mut journal,
        )
        .expect("temporal comparison");
    let scope = digest("selected-host-learning-scope");
    let generator_key = SigningKey::from_bytes(&[41; 32]);
    let evaluator_key = SigningKey::from_bytes(&[53; 32]);
    let context = ProductQualificationContextV1 {
        generator: principal("generator", &generator_key, scope),
        evaluator: principal("evaluator", &evaluator_key, scope),
        retention_receipt_digests: vec![digest("retention-receipt")],
        unlearning_receipt_digest: digest("unlearning-receipt"),
    };
    let bundle = runner
        .qualification_bundle(&temporal, &context)
        .expect("qualification bundle");
    let roles = temporal.product_plan.metric_roles.clone();
    let (trust, evidence) =
        verifier_and_evidence(&bundle, &roles, &generator_key, &evaluator_key);
    let selected_host_binding = digest("selected-host-binding");
    let mut current_clock = clock(50);
    let interrupted = runner.qualify_and_persist_on_selected_host(
        &attempt_id,
        &temporal,
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
            .expect("artifact root")
            .count(),
        1
    );
    assert_eq!(
        fs::read_dir(&publication_root)
            .expect("publication root")
            .count(),
        0
    );
    // The API cannot capture any of these originals: recovery accepts no codec
    // callback or asserted decision. It must decode its persisted typed inputs.
    drop((temporal, context, bundle, roles, evidence, provider));
    drop(journal);
    let mut recovered = AnchoredProductEvaluationAttemptJournalV1::recover(
        reopen(&attempt_path),
        attempt_binding,
        anchor_store.clone(),
    )
    .expect("recover journal and seal post-anchor tail");
    let before = recovered
        .latest(&attempt_id)
        .expect("latest")
        .expect("attempt");
    assert_eq!(before.transition.phase, Phase::QualificationDecided);
    assert!(
        runner
            .recover_selected_host_qualification(
                &mut recovered,
                &attempt_id,
                &artifact_root,
                &publication_root,
                digest("wrong-selected-host"),
                &trust,
                &mut current_clock,
            )
            .is_err()
    );
    assert_eq!(
        recovered.latest(&attempt_id).expect("unchanged"),
        Some(before.clone())
    );
    let mut expired_clock = clock(91);
    assert!(
        runner
            .recover_selected_host_qualification(
                &mut recovered,
                &attempt_id,
                &artifact_root,
                &publication_root,
                selected_host_binding,
                &trust,
                &mut expired_clock,
            )
            .is_err(),
        "expired signatures must be rejected inside the module"
    );
    assert_eq!(
        recovered.latest(&attempt_id).expect("unchanged"),
        Some(before.clone())
    );
    let path = fs::read_dir(&artifact_root)
        .expect("artifacts")
        .next()
        .expect("file")
        .expect("entry")
        .path();
    let original = fs::read(&path).expect("archive");
    for changed in [
        original[..original.len() - 1].to_vec(),
        {
            let mut bytes = original.clone();
            bytes.push(0);
            bytes
        },
        {
            let mut bytes = original.clone();
            bytes[16] ^= 1;
            bytes
        },
    ] {
        fs::write(&path, changed).expect("inject archive corruption");
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
                .is_err()
        );
        assert_eq!(
            recovered.latest(&attempt_id).expect("unchanged"),
            Some(before.clone())
        );
        assert_eq!(
            fs::read_dir(&publication_root)
                .expect("no publication")
                .count(),
            0
        );
    }
    fs::write(&path, original).expect("restore original fixture bytes");
    let published = runner
        .recover_selected_host_qualification(
            &mut recovered,
            &attempt_id,
            &artifact_root,
            &publication_root,
            selected_host_binding,
            &trust,
            &mut current_clock,
        )
        .expect("internal decode and signature verification");
    assert_eq!(published.transition.phase, Phase::Published);
    assert_eq!(
        fs::read_dir(&publication_root)
            .expect("publication")
            .count(),
        1
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
        "the writer path must reject already published attempts"
    );
    let reconciled = RecordedProductEvaluationRunnerV1::<
        LockedFileFinalHoldoutCasStoreV1,
    >::reconcile_selected_host_publication(
        &mut recovered,
        &attempt_id,
        &publication_root,
        selected_host_binding,
    )
    .expect("existing publication reconciliation");
    assert_eq!(reconciled, published);
    assert_eq!(
        fs::read_dir(&publication_root)
            .expect("one publication")
            .count(),
        1
    );
    drop(recovered);
    let mut reopened = AnchoredProductEvaluationAttemptJournalV1::recover(
        reopen(&attempt_path),
        attempt_binding,
        anchor_store,
    )
    .expect("second restart");
    assert_eq!(
        reopened
            .history(&attempt_id)
            .expect("complete history")
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
    fs::remove_dir_all(root).expect("remove test root");
}
