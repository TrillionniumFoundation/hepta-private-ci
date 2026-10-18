//! Public sealed paired execution and independent selector for owner integration tests.
//! Synthetic observations exercise authority mechanics, not empirical efficacy.
use super::ledger::LearningFixture;
use super::paired;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_artifacts::ArtifactManifest;
use paired::id;

pub(super) fn paired_selection(
    signing: &paired::SigningFixture,
    evaluation: &LearningFixture,
    predecessor: &ArtifactManifest,
    selected_manifest: &ArtifactManifest,
) -> VerifiedSelfEvolutionSelectionV2 {
    let objective = evaluation.receipt.snapshot.objective_digest;
    let mut inputs = paired::inputs(
        128,
        objective,
        evaluation.receipt.snapshot.dataset_digest,
        selected_manifest.content_digest,
    );
    inputs.base_plan.candidate_id = selected_manifest.artifact_id.clone();
    inputs.base_plan.baseline_id = predecessor.artifact_id.clone();
    inputs.runtime.deployed_baseline_digest = predecessor.content_digest;
    let runtime = inputs.runtime.clone();
    let tasks = inputs.tasks.clone();
    let plan = freeze_paired_supervised_plan_v1(inputs).unwrap();
    let registration = signing.register(&plan, &runtime);
    let mut provider = signing.provider(&plan, &tasks, &runtime);
    let mut runner = paired::runner();
    let execution = runner
        .evaluate_registered_paired_supervised(&registration, &mut provider, &signing.trust)
        .unwrap();
    let context = signing.context();
    let evidence = signing.evaluation(
        &execution,
        &context,
        signing.sign(
            0,
            plan.frozen_plan().plan_digest.as_array(),
            signing.now - 21,
        ),
    );
    let mut sink = paired::Sink::default();
    let qualification = runner
        .qualify_paired_and_persist(&execution, &context, &evidence, &signing.trust, &mut sink)
        .unwrap();
    let prepared = prepare_self_evolution_selection_v2(
        &SelfEvolutionSelectionPolicyV2 {
            no_change_baseline_id: plan.frozen_plan().baseline_id.clone(),
            no_change_baseline_digest: runtime.deployed_baseline_digest,
            minimum_dataset_records: 1,
        },
        SelfEvolutionSelectionRequestV1 {
            selection_id: id("original-paired-selector"),
            predecessor_id: plan.frozen_plan().baseline_id.clone(),
            predecessor_generation: predecessor.generation,
            predecessor_artifact_digest: runtime.deployed_baseline_digest,
            candidate_id: plan.frozen_plan().candidate_id.clone(),
            candidate_generation: selected_manifest.generation,
            candidate_artifact_digest: runtime.candidate_artifact_digest,
        },
        SelfEvolutionSelectionInputsV2 {
            execution: &execution,
            qualification: &qualification,
            context: &context,
            evaluation_evidence: &evidence,
            dataset_receipt: &evaluation.receipt,
            ledger_snapshot: &evaluation.owner.snapshot().unwrap(),
        },
        &signing.trust,
    )
    .unwrap();
    let selected = admit_self_evolution_selection_v2(
        prepared.clone(),
        &signing.sign(
            3,
            &selection_signing_payload_v2(prepared.receipt()).unwrap(),
            paired::now_millis(),
        ),
        &signing.trust,
    )
    .unwrap();
    assert_eq!(provider.release_count, 1);
    assert_eq!(sink.calls, 1);
    selected
}
