//! Actual frozen-model comparisons consumed by the existing selection verifier.
use super::support::Fitted;
use super::support::Roles;
use super::support::micros;
use super::support::save;
use super::*;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_artifacts as artifacts;
use serde_json::Value;
use serde_json::json;

pub(super) fn choices(fitted: &Fitted, actions: &[(CognitiveContextItem, String)]) -> Value {
    let model = LoadedTabularOperatorV1::from_pinned_payload(&fitted.bytes, &fitted.pin).unwrap();
    let mut choices = serde_json::Map::new();
    for query in ["bootstrap", "familyalpha", "familybeta", "familygamma"] {
        let sensor = cognitive_sensor_id(query).unwrap();
        let ranked: Result<Vec<_>, _> = actions
            .iter()
            .enumerate()
            .map(|(i, (item, _))| {
                model
                    .predict(&sensor, &cognitive_action_id(item).unwrap())
                    .map(|value| (value.value.raw(), std::cmp::Reverse(i), i))
            })
            .collect();
        let index = ranked
            .map(|values| values.into_iter().max().unwrap().2)
            .unwrap_or(0);
        choices.insert(query.into(), json!(actions[index].1));
    }
    Value::Object(choices)
}

#[allow(clippy::too_many_arguments)]
pub(super) fn evaluate(
    root: &std::path::Path,
    generation: u64,
    name: &str,
    candidate: &Fitted,
    parent: &artifacts::ArtifactManifest,
    candidate_choices: &Value,
    parent_choices: &Value,
    roles: &mut Roles,
    holdouts: &mut eval::ProductEvaluationRunnerV1<eval::LockedFileFinalHoldoutCasStoreV1>,
) -> Result<
    (
        VerifiedSelfEvolutionSelectionV1,
        VerifiedSelfEvolutionSelectionV1,
    ),
    eval::SelfEvolutionSelectionError,
> {
    let table_digest = Digest32::of_bytes(&serde_json::to_vec(candidate_choices).unwrap());
    let metric_roles = vec![eval::MetricRoleContractV2 {
        metric_id: id("future-task-success"),
        role: eval::MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    // Each custodian draws actual tasks after candidate commitment, then seals
    // them locally and returns only a signed material commitment. The original
    // holdout owner consumes the exact composite material manifest before release.
    let mut materials = Vec::new();
    for i in 1..=2 {
        let role_index = if i == 1 { 1 } else { 6 };
        materials.push(roles.processes[role_index].call(json!({"command":"prepare_future",
            "generation":generation, "name":format!("{name}-window-{i}"),
            "candidate":root.join("payload"), "candidate_sha256":candidate.pin.payload_digest.to_string(),
            "choices":candidate_choices, "parent_choices":parent_choices})));
    }
    let manifest_path = root.join(format!("{name}-holdout-material.json"));
    save(
        &manifest_path,
        &json!({"schema":"hepta.local-sealed-holdout-material.v1",
        "name":name, "candidate":candidate.pin.payload_digest.to_string(),
        "generation":generation, "instances_per_family_per_custodian":2048, "materials":materials}),
    );
    let manifest_bytes = std::fs::read(&manifest_path).unwrap();
    let material_digest = Digest32::of_bytes(&manifest_bytes);
    let raw_plan = eval::CrossFoldPlanV1 {
        plan_id: id(&format!("{name}-plan")),
        claim_scope: eval::EvaluationClaimScopeV1::SystemLongitudinal,
        candidate_id: candidate.artifact.artifact_id.clone(),
        baseline_id: parent.artifact_id.clone(),
        objective_digest: roles.trust.objective_digest,
        dataset_digest: candidate.dataset.snapshot.dataset_digest,
        estimand_digest: hash(
            "final-future-custodian-a-mod4-equals2-uniform-family-correctness-v1",
        ),
        metric_contracts: vec![eval::MetricContractV1 {
            metric_id: id("future-task-success"),
            direction: eval::EvaluationDirectionV1::Maximize,
            safety_floor: None,
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: (1..=2)
            .map(|i| eval::CrossFoldPartitionV1 {
                fold_id: id(&format!("{name}-fold-{i}")),
                training_principals: vec![id("generator-training")],
                training_episodes: candidate
                    .temporal_training
                    .iter()
                    .map(|row| row.episode_lineage.clone())
                    .collect(),
                training_windows: candidate
                    .temporal_training
                    .iter()
                    .map(|row| row.window_id.clone())
                    .collect::<std::collections::BTreeSet<_>>()
                    .into_iter()
                    .collect(),
                holdout_principals: materials[i - 1]["body"]["task_ids"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|task| id(&format!("synthetic-task-{}", task.as_str().unwrap())))
                    .collect(),
                holdout_episodes: materials[i - 1]["body"]["task_ids"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|task| id(&format!("synthetic-task-{}", task.as_str().unwrap())))
                    .collect(),
                holdout_windows: vec![id(&format!("{name}-window-{i}"))],
                model_digest: candidate.pin.payload_digest,
                predictions_digest: table_digest,
            })
            .collect(),
        final_holdout_window_id: id(&format!("{name}-window-2")),
        final_holdout_digest: material_digest,
    };
    let candidate_plan = temporal::plan(
        &format!("{name}-candidate"),
        roles.trust.objective_digest,
        candidate,
    );
    let baseline_plan = temporal::plan(
        &format!("{name}-baseline"),
        roles.trust.objective_digest,
        candidate,
    );
    let metric_sources = vec![eval::ProductMetricSourceContractV1 {
        metric_id: id("future-task-success"),
        source: eval::ProductMetricSourceV1::Ips,
    }];
    let product_plan = eval::freeze_product_evaluation_plan_v1(
        raw_plan.clone(),
        metric_roles.clone(),
        metric_sources.clone(),
        &candidate_plan,
        &baseline_plan,
    )
    .unwrap();
    let frozen_at = micros();
    let generator_plan = roles.evidence(
        /*index*/ 0,
        product_plan.frozen_plan.plan_digest.as_array(),
        frozen_at,
    );
    save(
        &root.join(format!("{name}-frozen-plan.json")),
        &json!({
        "digest":product_plan.frozen_plan.plan_digest.to_string(), "frozen_unix_micros":frozen_at,
        "candidate":candidate.pin.payload_digest.to_string(), "parent":parent.content_digest.to_string(),
        "choices":candidate_choices, "holdout_material_digest":material_digest.to_string(),
        "prediction_scope":"native instructions frozen; actual random task bytes sealed, not yet released",
        "plan_debug":format!("{product_plan:?}")}),
    );
    let mut provider = provider::Provider {
        root,
        name,
        candidate,
        roles,
        manifest_bytes,
        plan_digest: product_plan.frozen_plan.plan_digest,
        observations: Vec::new(),
        independent_observations: Vec::new(),
    };
    let temporal = holdouts
        .evaluate_temporal_comparison(
            &product_plan,
            &candidate_plan,
            &baseline_plan,
            &mut provider,
        )
        .unwrap();
    let observations = std::mem::take(&mut provider.observations);
    let independent_observations = std::mem::take(&mut provider.independent_observations);
    drop(provider);
    let anchor = holdouts.holdout_anchor();
    let observations_digest = Digest32::of_bytes(&serde_json::to_vec(&observations).unwrap());
    let context = eval::ProductQualificationContextV1 {
        generator: roles.principals[0].clone(),
        evaluator: roles.principals[1].clone(),
        retention_receipt_digests: vec![observations_digest],
        unlearning_receipt_digest: Digest32::of_bytes(
            &std::fs::read(root.join("withdrawal-control/observed.json")).unwrap(),
        ),
    };
    let bundle = holdouts.qualification_bundle(&temporal, &context).unwrap();
    let placeholder = roles.evidence(/*index*/ 2, b"unissued-future-placeholder", micros());
    let mut timing = eval::LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: frozen_at,
        observer: placeholder,
        windows: observations
            .iter()
            .enumerate()
            .map(|(i, o)| eval::ObservedFutureWindowV1 {
                window_id: id(&format!("{name}-window-{}", i + 1)),
                snapshot_id: id(&format!("{name}-snapshot-{}", i + 1)),
                starts_unix_micros: o["body"]["starts_unix_micros"].as_u64().unwrap(),
                ends_unix_micros: o["body"]["ends_unix_micros"].as_u64().unwrap(),
                observation_count: o["body"]["sample_count"].as_u64().unwrap(),
                observed_source_cut: Digest32::of_bytes(
                    &serde_json::to_vec(&independent_observations[i]).unwrap(),
                ),
            })
            .collect(),
    };
    timing.observer = roles.evidence(
        /*index*/ 2,
        &eval::future_window_signing_payload_v1(&bundle, &timing, 1).unwrap(),
        micros(),
    );
    let evidence = eval::SignedEvaluationEvidenceV1 {
        generator_plan,
        evaluator_bundle: roles.evidence(
            /*index*/ 1,
            &eval::longitudinal_evaluation_signing_payload_v3(&bundle, &metric_roles, &timing, 1)
                .unwrap(),
            micros(),
        ),
    };
    let policy = eval::SelfEvolutionSelectionPolicyV1 {
        no_change_baseline_id: parent.artifact_id.clone(),
        no_change_baseline_digest: parent.content_digest,
        minimum_dataset_records: 1,
        minimum_future_window_micros: 1,
    };
    let selection_request = eval::SelfEvolutionSelectionRequestV1 {
        selection_id: id(&format!("{name}-selection")),
        predecessor_id: parent.artifact_id.clone(),
        predecessor_generation: parent.generation,
        predecessor_artifact_digest: parent.content_digest,
        candidate_id: candidate.artifact.artifact_id.clone(),
        candidate_generation: candidate.artifact.generation,
        candidate_artifact_digest: candidate.pin.payload_digest,
    };
    let qualification_path = root.join("product-qualification.evidence");
    let mut sink = eval::FileProductQualificationEvidenceSinkV1::new(&qualification_path).unwrap();
    let qualification = holdouts
        .qualify_and_persist(
            &temporal,
            &context,
            &evidence,
            eval::ProductTimingEvidenceV1::SystemLongitudinal {
                timing: &timing,
                minimum_window_micros: 1,
            },
            &roles.verifier,
            micros(),
            &mut sink,
        )
        .unwrap();
    let candidate_binding_evidence = roles.evidence(
        /*index*/ 1,
        &eval::product_candidate_binding_payload_v1(&selection_request, &qualification).unwrap(),
        micros(),
    );
    let compatibility = controls::canonical_controls(
        root,
        &qualification,
        &candidate_binding_evidence,
        &policy,
        &selection_request,
        &bundle,
        &metric_roles,
        &evidence,
        &timing,
        candidate,
        roles,
    );
    use crate::cognitive_process_evaluation::*;
    use crate::cognitive_process_evidence::*;
    use crate::cognitive_process_product_wire::*;
    let mut material = json!({
        "policy":SelfEvolutionSelectionPolicyV1Raw::from(policy.clone()),
        "selection_request":SelfEvolutionSelectionRequestV1Raw::from(selection_request.clone()),
        "frozen_plan":CrossFoldPlanV1Raw::from(raw_plan),
        "evaluation_bundle":IndependentEvaluationBundleV1Raw::from(bundle.clone()),
        "product_candidate_binding_evidence":SignedLearningEvidenceV1Raw::from(candidate_binding_evidence.clone()),
        "product":{
            "candidate_plan":TemporalEvaluationPlanRaw::from(candidate_plan),
            "baseline_plan":TemporalEvaluationPlanRaw::from(baseline_plan),
            "metric_sources":metric_sources.into_iter().map(ProductMetricSourceContractV1Raw::from).collect::<Vec<_>>(),
            "context":ProductQualificationContextV1Raw::from(context),
            "released_inputs":{"path":root.join("product-released-inputs.json"),"digest":Digest32::of_bytes(&std::fs::read(root.join("product-released-inputs.json")).unwrap()).to_string()},
            "holdout_material":{"path":manifest_path,"digest":material_digest.to_string()},
            "qualification_evidence":{"path":qualification_path,"digest":Digest32::of_bytes(&std::fs::read(&qualification_path).unwrap()).to_string()},
        },
        "metric_roles":metric_roles.iter().cloned().map(MetricRoleContractV2Raw::from).collect::<Vec<_>>(),
        "evaluation_evidence":SignedEvaluationEvidenceV1Raw::from(evidence.clone()),
        "longitudinal_time":LongitudinalTimeEvidenceV1Raw::from(timing.clone()),
        "dataset_receipt":DatasetSnapshotReceiptV3Raw::from(candidate.dataset.clone()),
        "trust":LearningEvidenceTrustV1Raw::from(roles.trust.clone()),
        "ledger":{"path":root.join("training-owner/ledger"),"binding":hash("local-three-generation-ledger").to_string(),
            "max_records":4096,"anchor_sequence":candidate.snapshot.records().last().unwrap().sequence.get(),
            "anchor_chain_digest":candidate.snapshot.head_digest.to_string()},
        "holdout":{"path":root.parent().unwrap().join("holdouts"),"binding":hash("three-generation-holdouts").to_string(),
            "fence":HoldoutWriterFenceV1Raw::from(holdout_fence()),"anchor":FinalHoldoutCasAnchorV1Raw::from(anchor)},
    });
    save(
        &root.join(format!("{name}-evaluation-inputs.json")),
        &material,
    );
    let prepared = eval::prepare_self_evolution_product_selection_v1(
        &qualification,
        &candidate_binding_evidence,
        &policy,
        selection_request,
        bundle,
        metric_roles,
        &evidence,
        &timing,
        &candidate.dataset,
        &candidate.snapshot,
        &roles.verifier,
        micros(),
    )?;
    let selector = roles.evidence(
        /*index*/ 3,
        &eval::selection_signing_payload_v1(prepared.receipt()).unwrap(),
        micros(),
    );
    let selected =
        eval::admit_self_evolution_selection_v1(prepared, &selector, &roles.verifier, micros())?;
    material["selector_evidence"] =
        serde_json::to_value(SignedLearningEvidenceV1Raw::from(selector)).unwrap();
    save(&root.join("evaluation-materials.json"), &material);
    Ok((selected, compatibility))
}
