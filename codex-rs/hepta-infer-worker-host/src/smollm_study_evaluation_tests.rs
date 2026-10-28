//! Original runner consumes the frozen holdout before any future model call.
use super::*;
use cognitive_process_evaluation::*;
use cognitive_process_evidence::*;
use cognitive_process_product_wire::*;

#[path = "smollm_study_checks_tests.rs"]
mod checks;
#[path = "smollm_study_plan_tests.rs"]
mod plan;

pub(super) struct Qualified {
    pub raw_plan: eval::CrossFoldPlanV1,
    pub product: Value,
    pub holdout: Value,
    pub receipt: eval::ProductQualificationReceiptV1,
    pub bundle: eval::IndependentEvaluationBundleV1,
    pub evidence: eval::SignedEvaluationEvidenceV1,
    pub timing: eval::LongitudinalTimeEvidenceV1,
    pub metric_roles: Vec<eval::MetricRoleContractV2>,
    pub withdrawal_head: Digest32,
}

struct Provider<'a> {
    input: &'a NativeInput,
    script: &'a Path,
    training_chain: &'a Path,
    root: &'a Path,
    trained: &'a Value,
    worker_plan: Value,
    actions: &'a [StableId; 2],
    tasks: Value,
    seed: [u8; 32],
    dataset: &'a ledger::DatasetSnapshotReceiptV3,
    ledger: &'a ledger::LedgerSnapshot,
    material: Digest32,
    expected_plan: Digest32,
    targets: Vec<eval::HeldOutTarget>,
    frozen_at: u64,
    released: bool,
    windows: Vec<eval::ObservedFutureWindowV1>,
    retention: Vec<Value>,
    inputs: Option<eval::TemporalComparisonInputsV1>,
}

impl Provider<'_> {
    fn run(
        &mut self,
        receipt: &eval::FinalHoldoutJournalReceiptV1,
    ) -> TestResult<eval::TemporalComparisonInputsV1> {
        if self.released
            || receipt.disposition != eval::HoldoutUseDispositionV1::Recorded
            || receipt.use_receipt.plan_digest != self.expected_plan
            || receipt.use_receipt.holdout_digest != self.material
            || receipt.sequence == 0
            || receipt.authority.grants_any()
        {
            return Err("holdout already consumed or changed".into());
        }
        self.released = true;
        let mut inputs = eval::TemporalComparisonInputsV1 {
            training: plan::training(self.dataset, self.ledger)?,
            targets: self
                .targets
                .iter()
                .filter(|target| target.window_id == id("future-window-1"))
                .cloned()
                .collect(),
            candidate_observations: Vec::new(),
            baseline_observations: Vec::new(),
            assignments: Vec::new(),
            snapshot_ids: vec![self.dataset.snapshot.snapshot_id.clone()],
            future_window_ids: Vec::new(),
        };
        for window in 0..2 {
            let window_id = id(&format!("future-window-{window}"));
            let snapshot_id = id(&format!("future-snapshot-{window}"));
            let rows = self.tasks[window].as_array().ok_or("task window")?;
            let label_free = rows
                .iter()
                .map(|row| json!({"id":row["id"],"prompt":row["prompt"]}))
                .collect::<Vec<_>>();
            let tasks = save(
                &self.root.join(format!("future-{window}-inputs.json")),
                &json!(label_free),
            )?;
            let start = now();
            if start <= self.frozen_at {
                return Err("actual future window must follow frozen plan".into());
            }
            let mut actual = std::collections::BTreeMap::new();
            // Fixed counterbalanced order is committed before any outputs.
            let order = if window == 0 {
                ["parent", "child"]
            } else {
                ["child", "parent"]
            };
            for model in order {
                let parent = if model == "parent" {
                    &self.trained["parent"]
                } else {
                    &self.trained["child"]
                };
                let mut worker = self.worker_plan.clone();
                worker["parent"] = read_pin(parent)?;
                let worker_pin = save(
                    &self.root.join(format!("{model}-{window}-worker-plan.json")),
                    &worker,
                )?;
                let output = self.root.join(format!("{model}-{window}"));
                let request = json!({"schema":"hepta-neural-study-v1","operation":"forward",
                    "runtime_chain":self.input.chain,"training_chain":self.training_chain,"materials":self.input.materials,
                    "parent":parent,"worker_plan":worker_pin,"tasks":tasks,"model":model,
                    "window_id":window_id.as_str(),"phase_id":format!("{model}-{window}"),"output":output});
                helper(
                    self.input,
                    self.script,
                    &request,
                    &self.root.join(format!("launch-{model}-{window}")),
                    /*seconds*/ 670,
                )?;
                let phase = read_pin(&pin(&output.join("phase-result.json"))?)?;
                let observed = read_pin(&phase["actual"])?;
                if observed["parent"] != worker["parent"]
                    || observed["tasks"] != tasks
                    || observed["forwards"] != 512
                    || observed["loads"] != 9
                    || observed["model"] != model
                    || observed["window_id"] != window_id.as_str()
                {
                    return Err("actual forward context changed".into());
                }
                actual.insert(model, (phase, observed));
            }
            let end = now();
            if end.saturating_sub(start) < 1_000_000 {
                return Err("unobserved future window".into());
            }
            let parent_rows = actual["parent"].1["rows"]
                .as_array()
                .ok_or("parent observations")?;
            let child_rows = actual["child"].1["rows"]
                .as_array()
                .ok_or("child observations")?;
            if parent_rows.len() != rows.len() || child_rows.len() != rows.len() {
                return Err("incomplete actual window".into());
            }
            let cut = save(
                &self.root.join(format!("future-{window}-source-cut.json")),
                &json!({
                "window":window_id.as_str(),"start":start,"end":end,"tasks":tasks,
                "parent":actual["parent"].0,"child":actual["child"].0,"holdout_head":receipt.head_digest.to_string(),
                "preassigned_nuisance_predictions":pin(&self.root.join("nuisance-predictions.json"))?}),
            )?;
            let source_cut: Digest32 = cut["sha256"].as_str().ok_or("source cut")?.parse()?;
            for ((task, parent), child) in rows.iter().zip(parent_rows).zip(child_rows) {
                let decision = id(task["id"].as_str().ok_or("task id")?);
                let expected = id(task["expected"].as_str().ok_or("expected action")?);
                let parent_choice = checks::choice(
                    task,
                    parent,
                    self.actions,
                    &actual["parent"].1["parent"],
                    start,
                    end,
                )?;
                let child_choice = checks::choice(
                    task,
                    child,
                    self.actions,
                    &actual["child"].1["parent"],
                    start,
                    end,
                )?;
                let target = self
                    .targets
                    .iter()
                    .find(|target| target.decision_id == decision)
                    .ok_or("prefrozen target missing")?;
                if target.window_id != window_id
                    || target.decision_at > self.frozen_at
                    || target.actions.as_slice() != self.actions.as_slice()
                {
                    return Err("actual prefrozen nuisance target changed".into());
                }
                let logged = Digest32::of_parts(&[
                    b"hepta.neural-study.logged-half.v1\0",
                    &self.seed,
                    decision.as_str().as_bytes(),
                ]);
                let action = self.actions[usize::from(logged.as_array()[0] & 1)].clone();
                let outcome = if action == expected {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                };
                let observed_at = parent["observed_at"]
                    .as_u64()
                    .ok_or("parent clock")?
                    .max(child["observed_at"].as_u64().ok_or("child clock")?);
                let evidence = Digest32::of_bytes(&serde_json::to_vec(
                    &json!({"task":task,"parent":parent,"child":child,"cut":source_cut.to_string()}),
                )?);
                let row = |selected: usize| -> TestResult<eval::OpeRow> {
                    Ok(eval::OpeRow {
                        decision_id: decision.clone(),
                        chosen_action: action.clone(),
                        complete_candidates: true,
                        actions: self
                            .actions
                            .iter()
                            .enumerate()
                            .map(|(index, id)| eval::OpeAction {
                                action_id: id.clone(),
                                behavior_probability: ProbabilityQ32::from_raw(1 << 31).unwrap(),
                                evaluation_probability: if index == selected {
                                    ProbabilityQ32::ONE
                                } else {
                                    ProbabilityQ32::ZERO
                                },
                                predicted_outcome: FixedQ32::ZERO,
                            })
                            .collect(),
                        finalized_outcome: Some(outcome),
                        outcome_observed_at: observed_at,
                        outcome_evidence: evidence,
                        outcome_model_evidence: Digest32::ZERO,
                    })
                };
                if window == 1 {
                    inputs.candidate_observations.push(row(child_choice)?);
                    inputs.baseline_observations.push(row(parent_choice)?);
                    inputs.assignments.push(eval::ClusterAssignment {
                        decision_id: decision.clone(),
                        cluster_id: id(task["cluster"].as_str().ok_or("cluster")?),
                    });
                }
                self.retention.push(json!({"task":task["id"],"family":task["family"],"expected":expected.as_str(),
                    "parent_choice":self.actions[parent_choice].as_str(),"child_choice":self.actions[child_choice].as_str(),
                    "parent_correct":self.actions[parent_choice]==expected,"child_correct":self.actions[child_choice]==expected,
                    "parent_response_sha256":parent["response_sha256"],"child_response_sha256":child["response_sha256"],
                    "window":window_id.as_str(),"source_cut":cut}));
            }
            inputs.snapshot_ids.push(snapshot_id.clone());
            inputs.future_window_ids.push(window_id.clone());
            self.windows.push(eval::ObservedFutureWindowV1 {
                window_id,
                snapshot_id,
                starts_unix_micros: start,
                ends_unix_micros: end,
                observation_count: 512,
                observed_source_cut: source_cut,
            });
        }
        self.inputs = Some(inputs.clone());
        save(
            &self.root.join("released-inputs.json"),
            &serde_json::to_value(TemporalComparisonInputsV1Raw::from(inputs.clone()))?,
        )?;
        Ok(inputs)
    }
}

impl eval::FinalHoldoutProviderV1 for Provider<'_> {
    fn manifest_digest(&mut self) -> Result<Digest32, eval::ProductProviderErrorV1> {
        Ok(self.material)
    }
    fn release_after_consumption(
        &mut self,
        receipt: &eval::FinalHoldoutJournalReceiptV1,
    ) -> Result<eval::TemporalComparisonInputsV1, eval::ProductProviderErrorV1> {
        self.run(receipt).map_err(|error| {
            let _ = save(
                &self.root.join("actual-first-evaluation-failure.json"),
                &json!({"error":error.to_string(),"released":self.released}),
            );
            eval::ProductProviderErrorV1::Indeterminate
        })
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn evaluate(
    input: &NativeInput,
    script: &Path,
    training_chain: &Path,
    root: &Path,
    trained: &Value,
    worker_plan: &Path,
    study: &Value,
    actions: &[StableId; 2],
    yes: &StableId,
    dataset: &ledger::DatasetSnapshotReceiptV3,
    ledger: &ledger::LedgerSnapshot,
    roles: &mut roles::ControlledRoles,
    withdrawals: &DatasetWithdrawalRegistry,
) -> TestResult<Qualified> {
    let mut seed = [0_u8; 32];
    File::open("/dev/urandom")?.read_exact(&mut seed)?;
    let tasks = plan::tasks(&seed, yes, actions);
    let worker = read_pin(&pin(worker_plan)?)?;
    let material = save(
        &root.join("holdout-material.json"),
        &json!({"schema":"hepta-neural-study-future-material-v1",
        "tasks":tasks,"seed":seed,"child":trained["child"],"parent":trained["parent"],"study":study,
        "worker_plan":pin(worker_plan)?,"source":pin(script)?,"training":trained["training"],
        "fixed_execution_order":[["parent","child"],["child","parent"]],"minimum_window_micros":1_000_000}),
    )?;
    let material_digest: Digest32 = material["sha256"]
        .as_str()
        .ok_or("material digest")?
        .parse()?;
    let plan::Prepared {
        raw: raw_plan,
        product: product_plan,
        candidate: candidate_plan,
        baseline: baseline_plan,
        targets,
        predictions,
        candidate_predictions,
        baseline_predictions,
    } = plan::plans(dataset, ledger, material_digest, &tasks, actions)?;
    let nuisance_inputs = eval::TemporalComparisonInputsV1 {
        training: plan::training(dataset, ledger)?,
        targets: targets.clone(),
        candidate_observations: Vec::new(),
        baseline_observations: Vec::new(),
        assignments: Vec::new(),
        snapshot_ids: vec![dataset.snapshot.snapshot_id.clone()],
        future_window_ids: Vec::new(),
    };
    let nuisance = save(
        &root.join("nuisance-predictions.json"),
        &json!({
        "scope":"actual unchanged temporal fitter outputs from earlier supervised training labels and preassigned label-free targets; no neural outputs or future timestamps",
        "inputs":TemporalComparisonInputsV1Raw::from(nuisance_inputs),"folds":predictions,
        "candidate_predictions_digest":candidate_predictions.to_string(),"baseline_predictions_digest":baseline_predictions.to_string()}),
    )?;
    let generator = roles.sign(
        /*index*/ 0,
        product_plan.frozen_plan.plan_digest.as_array(),
    );
    save(
        &root.join("frozen-evaluation.json"),
        &json!({"plan":CrossFoldPlanV1Raw::from(raw_plan.clone()),
        "generator":SignedLearningEvidenceV1Raw::from(generator.clone()),"material":material,
        "nuisance_predictions":nuisance,"prediction_commitment":"actual original temporal prediction bytes; true neural response bytes are observed only after holdout consumption"}),
    )?;
    let binding = digest("real-neural-study-original-holdout-owner");
    let fence = eval::HoldoutWriterFenceV1 {
        owner_id: id("real-neural-study-holdout-owner"),
        generation: 1,
        lease_digest: digest("real-neural-study-lease"),
    };
    let holdout_path = root.join("final-holdout");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&holdout_path)?;
    let store = eval::LockedFileFinalHoldoutCasStoreV1::create(file, binding)?;
    let owner = eval::FencedFinalHoldoutOwnerV1::initialize(store, binding, fence.clone())?;
    let mut runner = eval::ProductEvaluationRunnerV1::new(owner);
    let mut provider = Provider {
        input,
        script,
        training_chain,
        root,
        trained,
        worker_plan: worker,
        actions,
        tasks,
        seed,
        dataset,
        ledger,
        material: material_digest,
        expected_plan: product_plan.frozen_plan.plan_digest,
        targets,
        frozen_at: generator.issued_at,
        released: false,
        windows: Vec::new(),
        retention: Vec::new(),
        inputs: None,
    };
    let temporal = runner.evaluate_temporal_comparison(
        &product_plan,
        &candidate_plan,
        &baseline_plan,
        &mut provider,
    )?;
    if temporal.candidate.predictions_digest != candidate_predictions
        || temporal.baseline.predictions_digest != baseline_predictions
    {
        return Err("original fitter predictions changed after frozen holdout consumption".into());
    }
    let mut context = roles.context();
    context.retention_receipt_digests = checks::retention(root, &provider.retention, study)?;
    context.unlearning_receipt_digest = checks::withdrawal(root, withdrawals, dataset, trained)?;
    let bundle = runner.qualification_bundle(&temporal, &context)?;
    let mut timing = eval::LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: generator.issued_at,
        windows: provider.windows,
        observer: roles.sign(/*index*/ 2, b"unissued timing placeholder"),
    };
    timing.observer = roles.sign(
        /*index*/ 2,
        &eval::future_window_signing_payload_v1(
            &bundle, &timing, /*minimum_window_micros*/ 1_000_000,
        )?,
    );
    let evidence = eval::SignedEvaluationEvidenceV1 {
        generator_plan: generator,
        evaluator_bundle: roles.sign(
            /*index*/ 1,
            &eval::longitudinal_evaluation_signing_payload_v3(
                &bundle,
                &product_plan.metric_roles,
                &timing,
                /*minimum_window_micros*/ 1_000_000,
            )?,
        ),
    };
    let evidence_path = root.join("product-qualification.evidence");
    let mut sink = eval::FileProductQualificationEvidenceSinkV1::new(&evidence_path)?;
    let receipt = runner.qualify_and_persist(
        &temporal,
        &context,
        &evidence,
        eval::ProductTimingEvidenceV1::SystemLongitudinal {
            timing: &timing,
            minimum_window_micros: 1_000_000,
        },
        &roles.verifier,
        now(),
        &mut sink,
    )?;
    let eligible = receipt.decision.decision.disposition
        == eval::IndependentEvaluationDispositionV1::EligibleForIndependentSelection;
    save(
        &root.join("qualification-result.json"),
        &json!({"eligible":eligible,"decision":format!("{:?}",receipt.decision.decision.disposition),
        "actual_future_windows":2,"actual_forwards":2048,"primary_final_holdout_rows":512,"first_window_primary_ope_rows":0,"metrics":temporal.metrics.iter().cloned().map(MetricGateV1Raw::from).collect::<Vec<_>>(),
        "publication_digest":receipt.publication_digest.to_string(),"temporal_execution_digest":receipt.temporal_execution_digest.to_string(),
        "controlled_role_keys":true,"external_administrative_independence":false}),
    )?;
    if !eligible {
        return Err(
            "original product runner rejected actual future gain; child is not installed".into(),
        );
    }
    let product = json!({"candidate_plan":TemporalEvaluationPlanRaw::from(candidate_plan),"baseline_plan":TemporalEvaluationPlanRaw::from(baseline_plan),
        "metric_sources":product_plan.metric_sources.iter().cloned().map(ProductMetricSourceContractV1Raw::from).collect::<Vec<_>>(),
        "context":ProductQualificationContextV1Raw::from(context),"released_inputs":product_pin(&root.join("released-inputs.json"))?,
        "holdout_material":product_pin(&root.join("holdout-material.json"))?,"qualification_evidence":product_pin(&evidence_path)?});
    let holdout = json!({"path":holdout_path,"binding":binding.to_string(),"fence":HoldoutWriterFenceV1Raw::from(fence),
        "anchor":FinalHoldoutCasAnchorV1Raw::from(runner.holdout_anchor())});
    Ok(Qualified {
        raw_plan,
        product,
        holdout,
        receipt,
        bundle,
        evidence,
        timing,
        metric_roles: product_plan.metric_roles,
        withdrawal_head: withdrawals.head_digest(),
    })
}

pub(super) fn product_pin(path: &Path) -> TestResult<Value> {
    let p = pin(path)?;
    Ok(json!({"path":p["path"],"digest":p["sha256"]}))
}
