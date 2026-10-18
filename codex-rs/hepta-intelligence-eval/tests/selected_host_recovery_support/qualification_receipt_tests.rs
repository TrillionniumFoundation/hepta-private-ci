//! Default cross-crate receipt integrity through native recorded qualification.
use super::*;

use super::temporal_model::existing as model;

#[test]
fn recorded_archived_ineligible_receipt_seals_every_signed_decision_field() {
    let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
    let root = std::env::temp_dir().join(format!(
        "hepta-qualified-decision-seal-{}-{ordinal}",
        std::process::id()
    ));
    fs::create_dir(&root).unwrap_or_else(|error| panic!("receipt fixture root: {error:?}"));
    let store = LockedFileFinalHoldoutCasStoreV1::create(
        storage::create(&root.join("holdout.cas")),
        namespace(),
    )
    .unwrap_or_else(|error| panic!("receipt holdout store: {error:?}"));
    let owner = FencedFinalHoldoutOwnerV1::initialize(store, namespace(), fence())
        .unwrap_or_else(|error| panic!("receipt holdout owner: {error:?}"));
    let mut runner = RecordedProductEvaluationRunnerV1::new(owner);
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
        storage::create(&root.join("attempt.journal")),
        attempt_binding(),
        storage::DiskAnchor::new(&root.join("anchor"), None),
    )
    .unwrap_or_else(|error| panic!("receipt anchored journal: {error:?}"));
    let (plan, candidate, baseline) = model::product_plan();
    let mut inputs = model::inputs();
    // Identical native policies cannot satisfy strict superiority. The signed
    // Ineligible result is real; no already sealed receipt is changed to make it.
    inputs.baseline_observations = inputs.candidate_observations.clone();
    let mut provider = model::Provider {
        inputs: Some(inputs),
    };
    let attempt = host::id("ineligible-qualification-attempt");
    let temporal = runner
        .evaluate_temporal_comparison(
            attempt.clone(),
            &plan,
            &candidate,
            &baseline,
            &mut provider,
            &mut journal,
        )
        .unwrap_or_else(|error| panic!("native identical-policy comparison: {error:?}"));
    let context = host::context();
    let bundle = runner
        .qualification_bundle(&temporal, &context)
        .unwrap_or_else(|error| panic!("ineligible native bundle: {error:?}"));
    let evidence = host::evidence(&bundle, &plan.metric_roles, None);
    let trust = host::activate();
    let receipt = runner
        .qualify_and_persist_on_selected_host(
            &attempt,
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &trust,
            &mut host::clock(85),
            &mut journal,
            root.join("artifacts"),
            root.join("publications"),
            host_binding(),
        )
        .unwrap_or_else(|error| panic!("recorded archived qualification: {error:?}"));
    assert_eq!(
        receipt.decision.decision.disposition,
        IndependentEvaluationDispositionV1::Ineligible
    );
    assert_eq!(
        receipt.decision.decision.failed_metrics,
        vec![host::id("utility")]
    );
    assert!(receipt.validate_integrity().is_ok());
    assert_eq!(
        journal
            .latest(&attempt)
            .unwrap_or_else(|error| panic!("published qualification: {error:?}"))
            .unwrap_or_else(|| panic!("recorded attempt"))
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
    let admitted = admit_signed_eligibility_v2(
        bundle,
        plan.metric_roles.clone(),
        &evidence,
        trust.verifier(),
        host::digest("receipt-consumer"),
        85,
    )
    .unwrap_or_else(|error| panic!("original signed ineligible evidence: {error:?}"));
    assert_eq!(receipt.decision, admitted.decision);
    for field in 0..8 {
        let mut changed = receipt.clone();
        match field {
            0 => {
                changed.decision.decision.disposition =
                    IndependentEvaluationDispositionV1::EligibleForIndependentSelection
            }
            1 => changed.decision.decision.failed_metrics.clear(),
            2 => changed.decision.decision.evaluation_id = host::id("replacement-evaluation"),
            3 => changed.decision.decision.baseline_id = host::id("replacement-baseline"),
            4 => changed.decision.decision.candidate_id = host::id("replacement-candidate"),
            5 => changed.decision.decision.evidence_digest = host::digest("replacement-decision"),
            6 => changed.decision.trust_digest = host::digest("replacement-trust"),
            _ => {
                changed.decision.authentication_digest = host::digest("replacement-authentication")
            }
        }
        assert!(
            changed.validate_integrity().is_err(),
            "unsealed decision field {field}"
        );
    }
    drop(journal);
    drop(runner);
    fs::remove_dir_all(root).unwrap_or_else(|error| panic!("remove receipt fixture: {error:?}"));
}
