#![cfg(any(target_os = "linux", target_os = "macos"))]
//! Controlled doubles validate the original holdout boundary. They are never
//! neural training, independent evaluation, or product installation evidence.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_agentd::NeuralCognitiveInferencePortV1;
use codex_hepta_agentd::NeuralCognitiveObservationV1;
use codex_hepta_agentd::NeuralCognitiveRequestV1;
use codex_hepta_agentd::NeuralFinalHoldoutProviderV1;
use codex_hepta_agentd::NeuralHoldoutRuntimeV1;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[path = "support/neural_holdout_ledger.rs"]
mod ledger_fixture;
#[path = "support/neural_holdout_plan.rs"]
mod plan_fixture;

use ledger_fixture::ControlledRoles;
use ledger_fixture::hash;
use ledger_fixture::micros;

#[derive(Default)]
struct ControlledDouble {
    calls: Mutex<Vec<NeuralCognitiveRequestV1>>,
    corruption: Option<&'static str>,
}

impl NeuralCognitiveInferencePortV1 for ControlledDouble {
    fn execute(
        &self,
        request: &NeuralCognitiveRequestV1,
        bytes: &[u8],
    ) -> Result<NeuralCognitiveObservationV1, String> {
        assert_eq!(Digest32::of_bytes(bytes), request.pin.payload_digest);
        self.calls.lock().unwrap().push(request.clone());
        let mut observed = NeuralCognitiveObservationV1 {
            request: request.clone(),
            scores_q32: Some(vec![2, 1]),
            execution_receipt_digest: hash("explicit-controlled-inference-double"),
            authority: AuthorityPosture::DENY_ALL,
        };
        match self.corruption {
            Some("request") => observed.request.body_generation += 1,
            Some("receipt") => observed.execution_receipt_digest = Digest32::ZERO,
            Some("abstain") => observed.scores_q32 = None,
            Some("partial") => observed.scores_q32 = Some(vec![2]),
            Some(other) => panic!("unknown controlled corruption {other}"),
            None => {}
        }
        Ok(observed)
    }
}

fn runtime(
    pin: &codex_hepta_agentd::NeuralCognitivePinV1,
    bytes: &[u8],
    port: &Arc<ControlledDouble>,
) -> NeuralHoldoutRuntimeV1 {
    NeuralHoldoutRuntimeV1 {
        pin: pin.clone(),
        parameters: bytes.to_vec(),
        inference: port.clone(),
    }
}

#[test]
fn same_predictions_reach_original_signed_no_gain_gate_and_durable_replay_denial() {
    let root = tempfile::tempdir().unwrap();
    let mut roles = ControlledRoles::new();
    let (dataset, ledger) = roles.dataset(&root.path().join("ledger-owner"));
    let material =
        plan_fixture::material(&dataset, b"controlled-candidate", b"controlled-baseline");
    let (plan, candidate_plan, baseline_plan) = plan_fixture::plans(&material, &dataset);
    let candidate = Arc::new(ControlledDouble::default());
    let baseline = Arc::new(ControlledDouble::default());
    let mut provider = NeuralFinalHoldoutProviderV1::new(
        material.clone(),
        &plan,
        dataset,
        ledger,
        runtime(&material.candidate, b"controlled-candidate", &candidate),
        runtime(&material.baseline, b"controlled-baseline", &baseline),
    )
    .unwrap();
    let path = root.path().join("holdout-owner");
    let mut runner = plan_fixture::runner(&path);
    let receipt = runner
        .evaluate_temporal_comparison(&plan, &candidate_plan, &baseline_plan, &mut provider)
        .unwrap();
    assert_eq!(receipt.metrics[0].candidate, receipt.metrics[0].baseline);
    assert_eq!(provider.observations().len(), 32);
    assert!(
        provider
            .observations()
            .iter()
            .all(|row| row.candidate_choice == row.baseline_choice)
    );
    let context = roles.context();
    let bundle = runner.qualification_bundle(&receipt, &context).unwrap();
    let signed = roles.comparison_evidence(&bundle, &plan.metric_roles);
    let mut sink = eval::FileProductQualificationEvidenceSinkV1::new(
        root.path().join("controlled-decision-evidence"),
    )
    .unwrap();
    let decision = runner
        .qualify_and_persist(
            &receipt,
            &context,
            &signed,
            eval::ProductTimingEvidenceV1::Qualification,
            &roles.verifier,
            micros(),
            &mut sink,
        )
        .unwrap();
    assert_eq!(
        decision.decision.decision.disposition,
        eval::IndependentEvaluationDispositionV1::Ineligible
    );
    assert_eq!(
        decision.claim_scope,
        eval::EvaluationClaimScopeV1::Qualification
    );
    assert!(!decision.authority.grants_any());
    let anchor = runner.holdout_anchor();
    assert!(
        runner
            .evaluate_temporal_comparison(&plan, &candidate_plan, &baseline_plan, &mut provider)
            .is_err()
    );
    assert_eq!(candidate.calls.lock().unwrap().len(), 32);
    assert_eq!(baseline.calls.lock().unwrap().len(), 32);
    drop(runner);
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    let binding = hash("controlled-neural-original-holdout-owner");
    let store =
        eval::LockedFileFinalHoldoutCasStoreV1::recover(file, binding, Some(anchor)).unwrap();
    let owner =
        eval::FencedFinalHoldoutOwnerV1::recover(store, binding, plan_fixture::fence()).unwrap();
    assert_eq!(owner.anchor(), anchor);
    let mut recovered = eval::ProductEvaluationRunnerV1::new(owner);
    assert!(
        recovered
            .evaluate_temporal_comparison(&plan, &candidate_plan, &baseline_plan, &mut provider)
            .is_err()
    );
    assert_eq!(candidate.calls.lock().unwrap().len(), 32);
}

#[test]
fn scoring_label_changes_never_change_either_models_request() {
    let root = tempfile::tempdir().unwrap();
    let mut roles = ControlledRoles::new();
    let (dataset, ledger) = roles.dataset(&root.path().join("ledger-owner"));
    let mut material =
        plan_fixture::material(&dataset, b"controlled-candidate", b"controlled-baseline");
    let mut captured = Vec::new();
    let mut correctness = Vec::new();
    for world in 0..2 {
        let (plan, cp, bp) = plan_fixture::plans(&material, &dataset);
        let candidate = Arc::new(ControlledDouble::default());
        let baseline = Arc::new(ControlledDouble::default());
        let mut provider = NeuralFinalHoldoutProviderV1::new(
            material.clone(),
            &plan,
            dataset.clone(),
            ledger.clone(),
            runtime(&material.candidate, b"controlled-candidate", &candidate),
            runtime(&material.baseline, b"controlled-baseline", &baseline),
        )
        .unwrap();
        let mut runner = plan_fixture::runner(
            &root
                .path()
                .join(format!("separate-controlled-world-{world}")),
        );
        runner
            .evaluate_temporal_comparison(&plan, &cp, &bp, &mut provider)
            .unwrap();
        captured.push((
            candidate.calls.lock().unwrap().clone(),
            baseline.calls.lock().unwrap().clone(),
        ));
        correctness.push(
            provider
                .observations()
                .iter()
                .map(|row| row.candidate_correct)
                .collect::<Vec<_>>(),
        );
        for task in &mut material.tasks {
            task.expected_action =
                material.actions[usize::from(task.expected_action == material.actions[0])].clone();
        }
    }
    assert_eq!(captured[0], captured[1]);
    assert!(
        correctness[0]
            .iter()
            .zip(&correctness[1])
            .all(|(left, right)| left != right)
    );
}

#[test]
fn incomplete_or_misbound_neural_observation_consumes_holdout_without_retry() {
    for corruption in ["request", "receipt", "abstain", "partial"] {
        let root = tempfile::tempdir().unwrap();
        let mut roles = ControlledRoles::new();
        let (dataset, ledger) = roles.dataset(&root.path().join("ledger-owner"));
        let material =
            plan_fixture::material(&dataset, b"controlled-candidate", b"controlled-baseline");
        let (plan, cp, bp) = plan_fixture::plans(&material, &dataset);
        let candidate = Arc::new(ControlledDouble {
            corruption: Some(corruption),
            ..Default::default()
        });
        let baseline = Arc::new(ControlledDouble::default());
        let mut provider = NeuralFinalHoldoutProviderV1::new(
            material.clone(),
            &plan,
            dataset,
            ledger,
            runtime(&material.candidate, b"controlled-candidate", &candidate),
            runtime(&material.baseline, b"controlled-baseline", &baseline),
        )
        .unwrap();
        let mut runner = plan_fixture::runner(&root.path().join("holdout-owner"));
        assert!(
            runner
                .evaluate_temporal_comparison(&plan, &cp, &bp, &mut provider)
                .is_err()
        );
        assert!(provider.observations().is_empty());
        let anchor = runner.holdout_anchor();
        assert!(
            runner
                .evaluate_temporal_comparison(&plan, &cp, &bp, &mut provider)
                .is_err()
        );
        assert_eq!(runner.holdout_anchor(), anchor);
        assert_eq!(candidate.calls.lock().unwrap().len(), 1);
        assert!(baseline.calls.lock().unwrap().is_empty());
    }
}

#[test]
fn changed_frozen_parameters_or_material_are_rejected_before_inference() {
    let root = tempfile::tempdir().unwrap();
    let mut roles = ControlledRoles::new();
    let (dataset, ledger) = roles.dataset(&root.path().join("ledger-owner"));
    let material =
        plan_fixture::material(&dataset, b"controlled-candidate", b"controlled-baseline");
    let (plan, _, _) = plan_fixture::plans(&material, &dataset);
    let port = Arc::new(ControlledDouble::default());
    assert!(
        NeuralFinalHoldoutProviderV1::new(
            material.clone(),
            &plan,
            dataset.clone(),
            ledger.clone(),
            runtime(&material.candidate, b"altered", &port),
            runtime(&material.baseline, b"controlled-baseline", &port)
        )
        .is_err()
    );
    let mut altered = material.clone();
    altered.tasks[0].query.push('!');
    assert!(
        NeuralFinalHoldoutProviderV1::new(
            altered,
            &plan,
            dataset,
            ledger,
            runtime(&material.candidate, b"controlled-candidate", &port),
            runtime(&material.baseline, b"controlled-baseline", &port)
        )
        .is_err()
    );
    assert!(port.calls.lock().unwrap().is_empty());
}
