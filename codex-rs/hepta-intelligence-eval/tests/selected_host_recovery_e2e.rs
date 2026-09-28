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
use codex_hepta_intelligence_eval::ProductEvaluationError;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationErrorV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
use codex_hepta_intelligence_eval::SignedEligibilityAdmissionError;
use codex_hepta_intelligence_eval::admit_signed_eligibility_v2;
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
    let holdout_store =
        LockedFileFinalHoldoutCasStoreV1::create(create(&holdout_path), namespace)
            .expect("holdout store");
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        holdout_store,
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
    let anchor_store = FaultingAnchorStore::new(4);
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
    let (verifier, evidence) =
        verifier_and_evidence(&bundle, &roles, &generator_key, &evaluator_key);

    // This test codec is complete and deterministic for the fixture. A selected
    // production host must use its own versioned, confidentiality-protected codec.
    let sealed_temporal = format!("{temporal:#?}").into_bytes();
    let sealed_context = format!("{context:#?}").into_bytes();
    let sealed_evidence = format!("{evidence:#?}").into_bytes();
    let sealed_timing = b"ProductTimingEvidenceV1::Qualification".to_vec();
    let selected_host_binding = digest("selected-host-binding");

    let interrupted = runner.qualify_and_persist_on_selected_host(
        &attempt_id,
        &temporal,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        &verifier,
        50,
        &mut journal,
        &artifact_root,
        &publication_root,
        selected_host_binding,
        sealed_temporal.clone(),
        sealed_context.clone(),
        sealed_evidence.clone(),
        sealed_timing.clone(),
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
        1,
        "complete inputs must be durable before the failed decision acknowledgement"
    );
    assert_eq!(
        fs::read_dir(&publication_root)
            .expect("publication root")
            .count(),
        0,
        "publication must not be attempted before the decision phase is acknowledged"
    );

    drop(journal);
    let mut recovered = AnchoredProductEvaluationAttemptJournalV1::recover(
        reopen(&attempt_path),
        attempt_binding,
        anchor_store.clone(),
    )
    .expect("recover journal and seal post-anchor tail");
    assert_eq!(
        recovered
            .latest(&attempt_id)
            .expect("latest")
            .expect("attempt")
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::QualificationDecided
    );

    let wrong_host = runner.recover_selected_host_qualification(
        &mut recovered,
        &attempt_id,
        &artifact_root,
        &publication_root,
        digest("wrong-selected-host"),
        &verifier,
        50,
        |_, _, _, _, _, _| panic!("host-binding rejection must precede decoding"),
    );
    assert!(wrong_host.is_err());
    assert_eq!(
        recovered
            .latest(&attempt_id)
            .expect("latest after rejection")
            .expect("attempt after rejection")
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::QualificationDecided
    );

    let expected_temporal = sealed_temporal.clone();
    let expected_context = sealed_context.clone();
    let expected_evidence = sealed_evidence.clone();
    let expected_timing = sealed_timing.clone();
    let recovery_bundle = bundle.clone();
    let recovery_roles = roles.clone();
    let recovery_evidence = evidence.clone();
    let published = runner
        .recover_selected_host_qualification(
            &mut recovered,
            &attempt_id,
            &artifact_root,
            &publication_root,
            selected_host_binding,
            &verifier,
            50,
            move |temporal_bytes,
                  context_bytes,
                  evidence_bytes,
                  timing_bytes,
                  current_verifier,
                  now| {
                if temporal_bytes != expected_temporal
                    || context_bytes != expected_context
                    || evidence_bytes != expected_evidence
                    || timing_bytes != expected_timing
                {
                    return Err(ProductEvaluationError::Binding(
                        "selected-host fixture codec",
                    ));
                }
                match admit_signed_eligibility_v2(
                    recovery_bundle,
                    recovery_roles,
                    &recovery_evidence,
                    current_verifier,
                    digest("selected-host-recovery-consumer"),
                    now,
                ) {
                    Ok(receipt) => Ok(receipt.decision),
                    Err(SignedEligibilityAdmissionError::Evaluation(error)) => {
                        Err(ProductEvaluationError::Signed(error))
                    }
                    Err(_) => Err(ProductEvaluationError::Binding(
                        "selected-host evidence re-verification",
                    )),
                }
            },
        )
        .expect("re-verify artifacts and publish exactly once");
    assert_eq!(
        published.transition.phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
    assert_eq!(
        fs::read_dir(&publication_root)
            .expect("publication root after recovery")
            .count(),
        1
    );

    let reconciled = RecordedProductEvaluationRunnerV1::<
        LockedFileFinalHoldoutCasStoreV1,
    >::reconcile_selected_host_publication(
        &mut recovered,
        &attempt_id,
        &publication_root,
        selected_host_binding,
    )
    .expect("read-only reconciliation returns the existing publication");
    assert_eq!(reconciled, published);
    assert_eq!(
        fs::read_dir(&publication_root)
            .expect("publication root after read-only reconciliation")
            .count(),
        1,
        "read-only reconciliation must not create a second publication"
    );

    drop(recovered);
    let mut reopened = AnchoredProductEvaluationAttemptJournalV1::recover(
        reopen(&attempt_path),
        attempt_binding,
        anchor_store,
    )
    .expect("second restart");
    let history = reopened.history(&attempt_id).expect("complete history");
    assert_eq!(
        history
            .iter()
            .map(|receipt| receipt.transition.phase)
            .collect::<Vec<_>>(),
        vec![
            ProductEvaluationAttemptPhaseV1::IntentPersisted,
            ProductEvaluationAttemptPhaseV1::HoldoutConsumed,
            ProductEvaluationAttemptPhaseV1::ComparisonSealed,
            ProductEvaluationAttemptPhaseV1::QualificationDecided,
            ProductEvaluationAttemptPhaseV1::PublicationPending,
            ProductEvaluationAttemptPhaseV1::Published,
        ]
    );

    drop(reopened);
    drop(runner);
    fs::remove_dir_all(root).expect("remove test root");
}
