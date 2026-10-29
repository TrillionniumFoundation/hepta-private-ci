//! Native owners consume deterministic test observations. They establish wiring,
//! persistence and authorization, not measured improvement or real model quality.
//! Publication keeps the shared study fixture's opaque training-code marker;
//! that marker does not attest this native fixture's code or the executing binary.
use super::*;
use crate::cognitive_process_evaluation::*;
use crate::cognitive_process_evidence::*;
use crate::cognitive_process_product_wire::*;
use codex_hepta_contracts::authority_trust_unix::UnixPqLearningTrustFrontier;

pub(super) fn fitted(
    root: &Path,
    roles: &fixture::Roles,
    service: &fixture::Service,
    actions: &[(CognitiveContextItem, String)],
) -> [support::Fitted; 2] {
    let directory = root.join("training-owner");
    std::fs::create_dir(&directory).unwrap();
    let create = |name| {
        std::fs::OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(directory.join(name))
            .unwrap()
    };
    let binding = hash("local-three-generation-ledger");
    let frontier = Arc::new(UnixPqLearningTrustFrontier::new(service.config.clone()).unwrap());
    let durable = ledger::DurableLedger::create_with_authentication_profile(
        create("ledger"),
        binding,
        /*max_records*/ 4096,
        PQ,
    )
    .unwrap();
    let witness = ledger::LedgerWitnessStore::create_with_authentication_profile(
        create("witness"),
        binding,
        PQ,
    )
    .unwrap();
    let dir = File::open(&directory).unwrap();
    let mut writer = ledger::LedgerWriter::from_durable_with_trust_frontier(
        durable,
        witness,
        roles.activated.clone(),
        &dir,
        &dir,
        frontier,
    )
    .unwrap();
    let trust = &roles.distribution.distribution.trust;
    let ids: Vec<_> = actions
        .iter()
        .map(|(item, _)| cognitive_action_id(item).unwrap())
        .collect();
    let sensor = cognitive_sensor_id("bootstrap").unwrap();
    let mut samples = Vec::new();
    for (index, action) in ids.iter().enumerate() {
        for repeat in 0..2 {
            let episode = format!("training-{index}-{repeat}");
            let value = if index == 0 {
                FixedQ32::ONE
            } else {
                FixedQ32::ZERO
            };
            let decision = ledger::ProductionDecisionV2 {
                record_id: id(&format!("{episode}-decision")),
                episode_id: id(&episode),
                run_snapshot_digest: hash("snapshot"),
                objective_digest: trust.objective_digest,
                policy_digest: hash("policy"),
                candidate_ids: ids.clone(),
                selected_candidate_id: action.clone(),
                selected_propensity: ProbabilityQ32::ONE,
                completeness: ledger::CandidateSetCompletenessReceiptV1 {
                    set_id: id("all-fixture-actions"),
                    state_digest: hash("state"),
                    generator_id: id("generator"),
                    generator_code_digest: hash("test-generator"),
                    grammar_digest: hash("grammar"),
                    hard_filter_digest: hash("filter"),
                    truncation_digest: hash("no-truncation"),
                    candidates_digest: ledger::candidate_ids_digest_v2(&ids),
                    candidate_count: ids.len().try_into().unwrap(),
                    omitted_count_bound: 0,
                    canonical_order_digest: ledger::candidate_order_digest_v2(&ids),
                    complete_for_generator: true,
                },
                support_digest: hash(&episode),
            };
            let evidence = roles.evidence(
                /*index*/ 0,
                &ledger::decision_signing_payload_v2(&decision).unwrap(),
                /*offset*/ 1,
            );
            let head = writer.snapshot().unwrap().head_digest;
            let receipt = writer
                .append_decision(head, decision, &evidence, roles.base + 1)
                .unwrap();
            let outcome = ledger::AuthenticatedOutcomeV1 {
                record_id: id(&format!("{episode}-outcome")),
                outcome_id: id(&format!("{episode}-result")),
                episode_id: id(&episode),
                observer: trust.signers[2].principal.clone(),
                observed_at: Some(roles.base + 2),
                value: Some(value),
                unit_profile_digest: hash("unit"),
                support_digest: hash(&episode),
                watermark: ledger::OutcomeWatermarkV1 {
                    latest_observable_at: roles.base + 2,
                    expected_delay_profile_digest: hash("synchronous"),
                    terminality: ledger::OutcomeTerminalityV1::Terminal,
                    censoring_reason: None,
                    correction_predecessor: None,
                    finalized_at: Some(roles.base + 2),
                },
            };
            let evidence = roles.evidence(
                /*index*/ 2,
                &ledger::outcome_signing_payload_v2(&outcome),
                /*offset*/ 3,
            );
            let receipt = writer
                .append_outcome(receipt.chain_digest, outcome, &evidence, roles.base + 3)
                .unwrap();
            samples.push(TabularOperatorSampleV1 {
                sample_id: id(&episode),
                sensor_id: sensor.clone(),
                action_id: action.clone(),
                target: value,
                evidence_digest: receipt.event_digest,
            });
        }
    }
    let plan = ledger::DatasetFreezePlanV2 {
        snapshot_id: id("training-dataset"),
        objective_digest: trust.objective_digest,
        inclusion_policy_digest: hash("all-native-test-records"),
    };
    let evidence = roles.evidence(
        /*index*/ 1,
        &ledger::dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap(),
        /*offset*/ 10,
    );
    let dataset = writer
        .freeze_dataset(plan, &evidence, roles.base + 10)
        .unwrap();
    let snapshot = writer.snapshot().unwrap();
    assert_eq!(snapshot.authentication_profile(), PQ);
    drop(writer);
    assert_eq!(
        &std::fs::read(directory.join("ledger")).unwrap()[..8],
        b"HEPTLP02"
    );
    assert_eq!(
        &std::fs::read(directory.join("witness")).unwrap()[..8],
        b"HEPTWP02"
    );
    [1, 2].map(|generation| {
        let artifact = fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
            artifact_id: id(&format!("native-install-model-{generation}")),
            producer_id: id("generator"),
            generation: Generation::new(generation).unwrap(),
            objective_digest: trust.objective_digest,
            dataset_digest: dataset.snapshot.dataset_digest,
            sensor_core_digest: hash("exact-native-query-memory-revision"),
            training_profile_digest: hash("deterministic-test-means"),
            minimum_samples_per_cell: 2,
            sensor_ids: vec![sensor.clone()],
            action_ids: ids.clone(),
            samples: samples.clone(),
        })
        .unwrap();
        let bytes = encode_tabular_payload_v1(&artifact).unwrap();
        let pin = TabularPayloadPinV1 {
            payload_digest: Digest32::of_bytes(&bytes),
            artifact_digest: artifact.artifact_digest,
            objective_digest: artifact.objective_digest,
            dataset_digest: artifact.dataset_digest,
            sensor_core_digest: artifact.sensor_core_digest,
            training_profile_digest: artifact.training_profile_digest,
            generation: artifact.generation,
        };
        support::Fitted {
            artifact,
            dataset: dataset.clone(),
            snapshot: snapshot.clone(),
            bytes,
            pin,
            temporal_training: Vec::new(),
        }
    })
}

struct Provider {
    manifest: Digest32,
    inputs: Option<eval::TemporalComparisonInputsV1>,
}
impl eval::FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, eval::ProductProviderErrorV1> {
        Ok(self.manifest)
    }
    fn release_after_consumption(
        &mut self,
        receipt: &eval::FinalHoldoutJournalReceiptV1,
    ) -> Result<eval::TemporalComparisonInputsV1, eval::ProductProviderErrorV1> {
        if receipt.disposition != eval::HoldoutUseDispositionV1::Recorded
            || receipt.use_receipt.holdout_digest != self.manifest
            || receipt.authority.grants_any()
        {
            return Err(eval::ProductProviderErrorV1::Rejected);
        }
        self.inputs
            .take()
            .ok_or(eval::ProductProviderErrorV1::Rejected)
    }
}

pub(super) fn qualify(
    root: &Path,
    candidate: &support::Fitted,
    parent: &ArtifactManifest,
    roles: &fixture::Roles,
) -> eval::FinalHoldoutCasAnchorV1 {
    let base = roles.base;
    let trust = &roles.distribution.distribution.trust;
    let verifier = roles.activated.verifier();
    let metric_roles = vec![eval::MetricRoleContractV2 {
        metric_id: id("test-utility"),
        role: eval::MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let metric_sources = vec![eval::ProductMetricSourceContractV1 {
        metric_id: id("test-utility"),
        source: eval::ProductMetricSourceV1::DoublyRobust,
    }];
    let temporal_plan = |name: &str| {
        let raw = json!({"plan_digest":Digest32::ZERO.to_string(), "evaluation_id":name,"objective_digest":trust.objective_digest.to_string(),
            "fold":{"plan_digest":hash(&format!("{name}-fold")).to_string(),"fold_id":name,"training_watermark":base+10,"evaluation_start":base+20,"minimum_per_action":2},
            "ope":{"plan_digest":hash(&format!("{name}-ope")).to_string(),"outcome_watermark":base+100,"minimum_rows":2,"minimum_ess":1_i64<<32,"maximum_weight":3_i64<<31},
            "confidence":{"plan_digest":hash(&format!("{name}-confidence")).to_string(),"assumptions_digest":hash("fixture-clusters-not-quality-evidence").to_string(),"family_alpha_ppm":50000,"simultaneous_comparisons":1,"minimum_clusters":2}});
        let mut plan: eval::TemporalEvaluationPlan =
            serde_json::from_value::<TemporalEvaluationPlanRaw>(raw)
                .unwrap()
                .into();
        plan.plan_digest = plan.canonical_digest().unwrap();
        plan
    };
    let candidate_plan = temporal_plan("candidate-plan");
    let baseline_plan = temporal_plan("baseline-plan");
    let training: Vec<_> = ["a", "b"].iter().flat_map(|action| (0..2).map(move |i| json!({
        "decision_id":format!("training-{action}-{i}"),"principal_lineage":"training","episode_lineage":format!("training-{action}-{i}"),"window_id":"training","action_id":action,"outcome":if *action == "a" { 1_i64<<32 } else { 0 },"observed_at":base+5,"evidence_digest":candidate.snapshot.head_digest.to_string()}))).collect();
    let targets: Vec<_> = (0..1024).map(|i| json!({"decision_id":format!("held-{i}"),"principal_lineage":format!("held-{i}"),"episode_lineage":format!("held-{i}"),"window_id":"window-2","decision_at":base+31,"actions":["a","b"]})).collect();
    let rows = |a: u64, b: u64| {
        (0..1024).map(|i| json!({"decision_id":format!("held-{i}"),"chosen_action":"a","complete_candidates":true,
        "actions":[{"action_id":"a","behavior_probability":1_u64<<31,"evaluation_probability":a,"predicted_outcome":0},{"action_id":"b","behavior_probability":1_u64<<31,"evaluation_probability":b,"predicted_outcome":0}],
        "finalized_outcome":1_i64<<32,"outcome_observed_at":base+35,"outcome_evidence":hash("test-observation").to_string(),"outcome_model_evidence":hash("ignored-model").to_string()})).collect::<Vec<_>>()
    };
    let inputs = json!({"training":training,"targets":targets,"candidate_observations":rows(3<<30,1<<30),"baseline_observations":rows(1<<30,3<<30),
        "assignments":(0..1024).map(|i|json!({"decision_id":format!("held-{i}"),"cluster_id":format!("cluster-{i}")})).collect::<Vec<_>>(),
        "snapshot_ids":[candidate.dataset.snapshot.snapshot_id.as_str(),"window-snapshot-1","window-snapshot-2"],"future_window_ids":["window-1","window-2"]});
    let material = root.join("holdout-material.json");
    save(
        &material,
        &json!({"fixture":"deterministic native PQ installation; no measured quality"}),
    );
    let manifest = Digest32::of_bytes(&std::fs::read(&material).unwrap());
    let raw_plan = json!({"plan_id":"native-install-plan","claim_scope":"system_longitudinal","candidate_id":candidate.artifact.artifact_id.as_str(),"baseline_id":parent.artifact_id.as_str(),
        "objective_digest":trust.objective_digest.to_string(),"dataset_digest":candidate.dataset.snapshot.dataset_digest.to_string(),"estimand_digest":hash("test-estimand").to_string(),
        "metric_contracts":[{"metric_id":"test-utility","direction":"maximize","safety_floor":null}],"family_alpha_ppm":50000,"simultaneous_comparisons":1,
        "folds":(1..=2).map(|i|json!({"fold_id":format!("fold-{i}"),"training_principals":["training"],"training_episodes":["training-a-0","training-a-1","training-b-0","training-b-1"],"training_windows":["training"],
            "holdout_principals":if i==1 {vec!["first-window".to_owned()]} else {(0..1024).map(|j|format!("held-{j}")).collect()},"holdout_episodes":if i==1 {vec!["first-window".to_owned()]} else {(0..1024).map(|j|format!("held-{j}")).collect()},
            "holdout_windows":[format!("window-{i}")],"model_digest":candidate.pin.payload_digest.to_string(),"predictions_digest":hash("fixture-predictions").to_string()})).collect::<Vec<_>>(),"final_holdout_window_id":"window-2","final_holdout_digest":manifest.to_string()});
    let plan: eval::CrossFoldPlanV1 =
        serde_json::from_value::<CrossFoldPlanV1Raw>(raw_plan.clone())
            .unwrap()
            .into();
    let frozen = eval::freeze_product_evaluation_plan_v1(
        plan,
        metric_roles.clone(),
        metric_sources.clone(),
        &candidate_plan,
        &baseline_plan,
    )
    .unwrap();
    let file = std::fs::OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(root.parent().unwrap().join("holdouts"))
        .unwrap();
    let store =
        eval::LockedFileFinalHoldoutCasStoreV1::create(file, hash("three-generation-holdouts"))
            .unwrap();
    let owner = eval::FencedFinalHoldoutOwnerV1::initialize(
        store,
        hash("three-generation-holdouts"),
        holdout_fence(),
    )
    .unwrap();
    let mut runner = eval::ProductEvaluationRunnerV1::new(owner);
    let mut provider = Provider {
        manifest,
        inputs: Some(
            serde_json::from_value::<TemporalComparisonInputsV1Raw>(inputs.clone())
                .unwrap()
                .into(),
        ),
    };
    let temporal = runner
        .evaluate_temporal_comparison(&frozen, &candidate_plan, &baseline_plan, &mut provider)
        .unwrap();
    let context = eval::ProductQualificationContextV1 {
        generator: trust.signers[0].principal.clone(),
        evaluator: trust.signers[1].principal.clone(),
        retention_receipt_digests: vec![hash("fixture-retention")],
        unlearning_receipt_digest: hash("fixture-withdrawal"),
    };
    let bundle = runner.qualification_bundle(&temporal, &context).unwrap();
    let mut timing = eval::LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: base + 11,
        observer: roles.evidence(/*index*/ 2, b"placeholder", /*offset*/ 45),
        windows: (1..=2)
            .map(|i| eval::ObservedFutureWindowV1 {
                window_id: id(&format!("window-{i}")),
                snapshot_id: id(&format!("window-snapshot-{i}")),
                starts_unix_micros: base + 12 + (i - 1) * 18,
                ends_unix_micros: base + 20 + (i - 1) * 20,
                observation_count: 1024,
                observed_source_cut: hash(&format!("fixture-cut-{i}")),
            })
            .collect(),
    };
    timing.observer = roles.evidence(
        /*index*/ 2,
        &eval::future_window_signing_payload_v1(&bundle, &timing, /*minimum_window_micros*/ 1)
            .unwrap(),
        /*offset*/ 45,
    );
    let evidence = eval::SignedEvaluationEvidenceV1 {
        generator_plan: roles.evidence(
            /*index*/ 0,
            frozen.frozen_plan.plan_digest.as_array(),
            /*offset*/ 11,
        ),
        evaluator_bundle: roles.evidence(
            /*index*/ 1,
            &eval::longitudinal_evaluation_signing_payload_v3(
                &bundle,
                &metric_roles,
                &timing,
                /*minimum_window_micros*/ 1,
            )
            .unwrap(),
            /*offset*/ 50,
        ),
    };
    let qualification_path = root.join("qualification.evidence");
    let mut sink = eval::FileProductQualificationEvidenceSinkV1::new(&qualification_path).unwrap();
    let qualification = runner
        .qualify_and_persist(
            &temporal,
            &context,
            &evidence,
            eval::ProductTimingEvidenceV1::SystemLongitudinal {
                timing: &timing,
                minimum_window_micros: 1,
            },
            verifier,
            base + 100,
            &mut sink,
        )
        .unwrap();
    let policy = eval::SelfEvolutionSelectionPolicyV1 {
        no_change_baseline_id: parent.artifact_id.clone(),
        no_change_baseline_digest: parent.content_digest,
        minimum_dataset_records: 1,
        minimum_future_window_micros: 1,
    };
    let request = eval::SelfEvolutionSelectionRequestV1 {
        selection_id: id("native-install-selection"),
        predecessor_id: parent.artifact_id.clone(),
        predecessor_generation: parent.generation,
        predecessor_artifact_digest: parent.content_digest,
        candidate_id: candidate.artifact.artifact_id.clone(),
        candidate_generation: candidate.artifact.generation,
        candidate_artifact_digest: candidate.pin.payload_digest,
    };
    let binding = roles.evidence(
        /*index*/ 1,
        &eval::product_candidate_binding_payload_v1(&request, &qualification).unwrap(),
        /*offset*/ 55,
    );
    let prepared = eval::prepare_self_evolution_product_selection_v1(
        &qualification,
        &binding,
        &policy,
        request.clone(),
        bundle,
        metric_roles.clone(),
        &evidence,
        &timing,
        &candidate.dataset,
        &candidate.snapshot,
        verifier,
        base + 100,
    )
    .unwrap();
    let selector = roles.evidence(
        /*index*/ 3,
        &eval::selection_signing_payload_v1(prepared.receipt()).unwrap(),
        /*offset*/ 60,
    );
    eval::admit_self_evolution_selection_v1(prepared, &selector, verifier, base + 100).unwrap();
    let inputs_path = root.join("released-inputs.json");
    save(&inputs_path, &inputs);
    let pinned = |path: &Path| json!({"path":path,"digest":Digest32::of_bytes(&std::fs::read(path).unwrap()).to_string()});
    save(
        &root.join("evaluation-materials.json"),
        &json!({
        "policy":SelfEvolutionSelectionPolicyV1Raw::from(policy),"selection_request":SelfEvolutionSelectionRequestV1Raw::from(request),"frozen_plan":raw_plan,
        "product_candidate_binding_evidence":SignedLearningEvidenceV1Raw::from(binding),"metric_roles":metric_roles.into_iter().map(MetricRoleContractV2Raw::from).collect::<Vec<_>>(),
        "evaluation_evidence":SignedEvaluationEvidenceV1Raw::from(evidence),"longitudinal_time":LongitudinalTimeEvidenceV1Raw::from(timing),"dataset_receipt":DatasetSnapshotReceiptV3Raw::from(candidate.dataset.clone()),
        "trust":LearningEvidenceTrustV1Raw::from(trust.clone()),"selector_evidence":SignedLearningEvidenceV1Raw::from(selector),
        "ledger":{"path":root.join("training-owner/ledger"),"binding":hash("local-three-generation-ledger").to_string(),"max_records":4096,"anchor_sequence":candidate.snapshot.records().last().unwrap().sequence.get(),"anchor_chain_digest":candidate.snapshot.head_digest.to_string()},
        "product":{"candidate_plan":TemporalEvaluationPlanRaw::from(candidate_plan),"baseline_plan":TemporalEvaluationPlanRaw::from(baseline_plan),"metric_sources":metric_sources.into_iter().map(ProductMetricSourceContractV1Raw::from).collect::<Vec<_>>(),"context":ProductQualificationContextV1Raw::from(context),"released_inputs":pinned(&inputs_path),"holdout_material":pinned(&material),"qualification_evidence":pinned(&qualification_path)}}),
    );
    runner.holdout_anchor()
}
