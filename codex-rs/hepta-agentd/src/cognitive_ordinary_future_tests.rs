//! Real ordinary CLI, original file owners and fresh process-held future tasks.
//! All role keys belong to one local study operator; organizational independence
//! and post-install efficacy cannot be inferred from this protocol exercise.
use super::*;
use crate::cognitive_process_evaluation::*;
use crate::cognitive_process_evidence::*;
use crate::cognitive_process_product_wire::*;
use codex_hepta_intelligence_eval as eval;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;

pub(super) fn cli(
    root: &std::path::Path,
    label: &str,
    fleet: &std::path::Path,
    command: &str,
    input: &Value,
) -> (bool, Value) {
    let binary = codex_utils_cargo_bin::cargo_bin("hepta-cognitive-upgrade").unwrap();
    let bytes = serde_json::to_vec(input).unwrap();
    let input_sha = Digest32::of_bytes(&bytes);
    save(&root.join(format!("{label}-input.json")), input);
    let started = std::time::Instant::now();
    let at = support::micros();
    let mut child = Command::new(&binary)
        .arg(command)
        .arg(fleet)
        .arg(input_sha.to_string())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(&bytes).unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.stdout.len() <= 16 * 1024 * 1024 && output.stderr.len() <= 1024 * 1024);
    std::fs::write(root.join(format!("{label}-stdout.json")), &output.stdout).unwrap();
    std::fs::write(root.join(format!("{label}-stderr.log")), &output.stderr).unwrap();
    save(
        &root.join(format!("{label}-execution.json")),
        &json!({"binary":binary,
        "binary_sha256":Digest32::of_bytes(&std::fs::read(&binary).unwrap()).to_string(),
        "input_sha256":input_sha.to_string(),"exit_code":output.status.code(),"started_at_unix_micros":at,
        "finished_at_unix_micros":support::micros(),"monotonic_elapsed_micros":started.elapsed().as_micros(),
        "stdout_sha256":Digest32::of_bytes(&output.stdout).to_string(),"stderr_sha256":Digest32::of_bytes(&output.stderr).to_string()}),
    );
    (
        output.status.success(),
        serde_json::from_slice::<Value>(&output.stdout).unwrap()["result"].clone(),
    )
}

fn call(root: &std::path::Path, label: &str, fleet: &std::path::Path, input: &Value) -> Value {
    let (success, value) = cli(root, label, fleet, "qualify", input);
    assert!(success, "actual ordinary CLI {label} failed: {value}");
    value
}

fn pin(path: &std::path::Path) -> Value {
    json!({"path":path,"digest":Digest32::of_bytes(&std::fs::read(path).unwrap()).to_string()})
}

#[derive(Clone, Copy)]
pub(super) enum QualificationMode<'a> {
    SelectWithCohortControls,
    Select,
    ObserveInstalled(&'a crate::CognitiveModelReadback),
}

#[allow(clippy::too_many_arguments)]
pub(super) async fn qualify(
    root: &std::path::Path,
    host: &Host,
    generation: u64,
    candidate: &support::Fitted,
    parent: &publication::Published,
    expected: &crate::CognitiveModelReadback,
    roles: &mut Roles,
    candidate_choices: &Value,
    parent_choices: &Value,
    anchor: eval::FinalHoldoutCasAnchorV1,
    source_release: &str,
    mode: QualificationMode<'_>,
) -> Value {
    let name = format!("ordinary-{generation}");
    let mut materials = admission::prepare_future(
        root,
        generation.min(3),
        &name,
        candidate,
        &parent.selected.manifest,
        candidate_choices,
        parent_choices,
        roles,
    );
    let boundary = support::micros() + 15_000_000;
    for plan in [&mut materials.candidate_plan, &mut materials.baseline_plan] {
        plan.fold.evaluation_start = boundary;
        plan.ope.outcome_watermark = boundary + 600_000_000;
        plan.plan_digest = plan.canonical_digest().unwrap();
    }
    let policy = eval::SelfEvolutionSelectionPolicyV1 {
        no_change_baseline_id: parent.selected.manifest.artifact_id.clone(),
        no_change_baseline_digest: parent.selected.manifest.content_digest,
        minimum_dataset_records: 1,
        minimum_future_window_micros: 1,
    };
    let host_path = root.join("ordinary-host.json");
    save(
        &host_path,
        &json!({"schema_version":1,"agent_id":owner(),"source_release":source_release,
        "expected_predecessor":expected,"policy":SelfEvolutionSelectionPolicyV1Raw::from(policy),
        "trust":LearningEvidenceTrustV1Raw::from(roles.trust.clone()),"future_not_before_unix_micros":boundary,
        "estimand_digest":materials.raw_plan.estimand_digest.to_string(),
        "holdout":{"path":root.parent().unwrap().join("holdouts"),"binding":hash("three-generation-holdouts").to_string(),
            "fence":HoldoutWriterFenceV1Raw::from(holdout_fence()),"anchor":FinalHoldoutCasAnchorV1Raw::from(anchor)}}),
    );
    let mut input = json!({"agent_id":owner(),"operation_id":name,"host":pin(&host_path),
        "frozen_plan":CrossFoldPlanV1Raw::from(materials.raw_plan),
        "metric_roles":materials.metric_roles.iter().cloned().map(MetricRoleContractV2Raw::from).collect::<Vec<_>>(),
        "metric_sources":materials.metric_sources.iter().cloned().map(ProductMetricSourceContractV1Raw::from).collect::<Vec<_>>(),
        "candidate_plan":TemporalEvaluationPlanRaw::from(materials.candidate_plan.clone()),
        "baseline_plan":TemporalEvaluationPlanRaw::from(materials.baseline_plan.clone()),
        "holdout_material":pin(&materials.manifest_path),"generator_plan":null,"stage":{"kind":"plan_statement"}});
    let frozen = call(root, "01-plan", &host.fleet_path, &input);
    input["frozen_plan"] = frozen["frozen_plan"].clone();
    let product_plan = eval::freeze_product_evaluation_plan_v1(
        serde_json::from_value::<CrossFoldPlanV1Raw>(input["frozen_plan"].clone())
            .unwrap()
            .into(),
        materials.metric_roles,
        materials.metric_sources,
        &materials.candidate_plan,
        &materials.baseline_plan,
    )
    .unwrap();
    input["generator_plan"] =
        serde_json::to_value(SignedLearningEvidenceV1Raw::from(roles.evidence(
            /*index*/ 0,
            &support::unhex(frozen["generator_signing_payload_hex"].as_str().unwrap()),
            support::micros(),
        )))
        .unwrap();
    input["stage"] = json!({"kind":"reserve"});
    let reserved = call(root, "02-reserve", &host.fleet_path, &input);
    let independent_ack =
        roles.processes[2].call(json!({"command":"observe_reservation","observation":reserved}));
    save(
        &root.join("independent-reservation-ack.json"),
        &independent_ack,
    );
    let received_at = independent_ack["body"]["received_at_unix_micros"]
        .as_u64()
        .unwrap();
    input["stage"] = json!({"kind":"acknowledgement_statement","reservation":reserved["reservation"],"received_at_unix_micros":received_at});
    let statement = call(root, "03-ack-statement", &host.fleet_path, &input);
    let acknowledgement = json!({"received_at_unix_micros":received_at,
        "observer":SignedLearningEvidenceV1Raw::from(roles.evidence(/*index*/ 2,
            &support::unhex(statement["acknowledgement_signing_payload_hex"].as_str().unwrap()),support::micros()))});
    let reservation_anchor = json!({"binding":hash("three-generation-holdouts").to_string(),
        "sequence":reserved["reservation"]["sequence"],"head":reserved["journal_head_sha256"],
        "plan_digest":frozen["plan_sha256"],"use_digest":reserved["reservation"]["use_digest"],
        "holdout_digest":materials.material_digest.to_string(),"recorded_unix_micros":reserved["observed_at_unix_micros"]});
    let reservation = json!({"signature":support::hex(&roles.processes[2].sign(&serde_json::to_vec(&reservation_anchor).unwrap())),"anchor":reservation_anchor});
    tokio::time::sleep(std::time::Duration::from_micros(
        boundary.saturating_sub(support::micros()),
    ))
    .await;
    let mut observations = Vec::new();
    let mut independent = Vec::new();
    for i in 1..=2 {
        let role_index = if i == 1 { 1 } else { 6 };
        let observed = roles.processes[role_index].call(json!({"command":"future","name":format!("{name}-window-{i}"),
            "material_manifest_hex":support::hex(&materials.manifest_bytes),"reservation":reservation}));
        let verified =
            roles.processes[2].call(json!({"command":"observe_future","observation":observed}));
        save(&root.join(format!("{name}-window-{i}.json")), &observed);
        save(
            &root.join(format!("{name}-window-{i}-observer.json")),
            &verified,
        );
        observations.push(observed);
        independent.push(verified);
    }
    let inputs = temporal::inputs(candidate, &name, &observations);
    let mut retained = vec![Digest32::of_bytes(
        &serde_json::to_vec(&observations).unwrap(),
    )];
    if let QualificationMode::ObserveInstalled(model) = mode {
        let readback = serde_json::to_value(model).unwrap();
        save(&root.join("precollection-runtime-model.json"), &readback);
        retained.push(Digest32::of_bytes(&serde_json::to_vec(model).unwrap()));
    }
    let context = eval::ProductQualificationContextV1 {
        generator: roles.principals[0].clone(),
        evaluator: roles.principals[1].clone(),
        retention_receipt_digests: retained,
        unlearning_receipt_digest: Digest32::of_bytes(
            &std::fs::read(root.join("withdrawal-control/observed.json")).unwrap(),
        ),
    };
    let windows: Vec<_> = observations
        .iter()
        .enumerate()
        .map(|(i, o)| eval::ObservedFutureWindowV1 {
            window_id: id(&format!("{name}-window-{}", i + 1)),
            snapshot_id: id(&format!("{name}-snapshot-{}", i + 1)),
            starts_unix_micros: o["body"]["starts_unix_micros"].as_u64().unwrap(),
            ends_unix_micros: o["body"]["ends_unix_micros"].as_u64().unwrap(),
            observation_count: o["body"]["sample_count"].as_u64().unwrap(),
            observed_source_cut: if i == 1 {
                crate::cognitive_timed_cohort::source_cut(&inputs, &product_plan.frozen_plan)
                    .unwrap()
            } else {
                Digest32::of_bytes(&serde_json::to_vec(&independent[i]).unwrap())
            },
        })
        .collect();
    let collection = json!({"inputs":TemporalComparisonInputsV1Raw::from(inputs),
        "context":ProductQualificationContextV1Raw::from(context),"windows":windows.into_iter().map(ObservedFutureWindowV1Raw::from).collect::<Vec<_>>()});
    let collection_path = root.join("ordinary-collection.json");
    save(&collection_path, &collection);
    input["stage"] = json!({"kind":"observer_statement","collection":pin(&collection_path),
        "reservation":reserved["reservation"],"acknowledgement":acknowledgement});
    if matches!(mode, QualificationMode::SelectWithCohortControls) {
        cohort_controls(root, host, &input, &collection, &product_plan.frozen_plan);
    }
    let observer_statement = call(root, "04-observer-statement", &host.fleet_path, &input);
    input["stage"]["kind"] = json!("evaluator_statement");
    input["stage"]["observer"] = serde_json::to_value(SignedLearningEvidenceV1Raw::from(
        roles.evidence(
            /*index*/ 2,
            &support::unhex(
                observer_statement["observer_signing_payload_hex"]
                    .as_str()
                    .unwrap(),
            ),
            support::micros(),
        ),
    ))
    .unwrap();
    let evaluator_statement = call(root, "05-evaluator-statement", &host.fleet_path, &input);
    input["stage"]["kind"] = json!("finalize");
    input["stage"]["evaluator"] = serde_json::to_value(SignedLearningEvidenceV1Raw::from(
        roles.evidence(
            /*index*/ 1,
            &support::unhex(
                evaluator_statement["evaluator_signing_payload_hex"]
                    .as_str()
                    .unwrap(),
            ),
            support::micros(),
        ),
    ))
    .unwrap();
    input["stage"]["qualification_evidence_path"] =
        json!(root.join("ordinary-qualification.evidence"));
    let request = eval::SelfEvolutionSelectionRequestV1 {
        selection_id: id(&format!("{name}-selection")),
        predecessor_id: parent.selected.manifest.artifact_id.clone(),
        predecessor_generation: parent.selected.manifest.generation,
        predecessor_artifact_digest: parent.selected.manifest.content_digest,
        candidate_id: candidate.artifact.artifact_id.clone(),
        candidate_generation: candidate.artifact.generation,
        candidate_artifact_digest: candidate.pin.payload_digest,
    };
    if !matches!(mode, QualificationMode::ObserveInstalled(_)) {
        input["stage"]["selection"] = json!({"kind":"candidate_binding_statement","request":SelfEvolutionSelectionRequestV1Raw::from(request)});
    }
    let bound = call(root, "06-qualified", &host.fleet_path, &input);
    if bound["disposition"] != "EligibleForIndependentSelection"
        || matches!(mode, QualificationMode::ObserveInstalled(_))
    {
        return bound;
    }
    let candidate_binding = SignedLearningEvidenceV1Raw::from(
        roles.evidence(
            /*index*/ 1,
            &support::unhex(
                bound["selection"]["candidate_binding_signing_payload_hex"]
                    .as_str()
                    .unwrap(),
            ),
            support::micros(),
        ),
    );
    let selection_inputs = json!({"request":bound["selection"]["selection_request"],"candidate_binding":candidate_binding,
        "dataset_receipt":DatasetSnapshotReceiptV3Raw::from(candidate.dataset.clone()),
        "ledger":{"path":root.join("training-owner/ledger"),"binding":hash("local-three-generation-ledger").to_string(),
            "max_records":4096,"anchor_sequence":candidate.snapshot.records().last().unwrap().sequence.get(),
            "anchor_chain_digest":candidate.snapshot.head_digest.to_string()}});
    input["stage"]["selection"] = json!({"kind":"selector_statement","inputs":selection_inputs});
    let selection_statement = call(root, "07-selector-statement", &host.fleet_path, &input);
    input["stage"]["selection"] = json!({"kind":"admit","inputs":selection_inputs,
        "selector":SignedLearningEvidenceV1Raw::from(roles.evidence(/*index*/ 3,
            &support::unhex(selection_statement["selection"]["selector_signing_payload_hex"].as_str().unwrap()),support::micros()))});
    let selected = call(root, "08-selected", &host.fleet_path, &input);
    assert_eq!(selected["selection"]["state"], "selected");
    save(
        &root.join("evaluation-materials.json"),
        &selected["bootstrap_evaluation_materials"],
    );
    selected
}

fn cohort_controls(
    root: &std::path::Path,
    host: &Host,
    input: &Value,
    collection: &Value,
    plan: &eval::CrossFoldPlanReceiptV1,
) {
    let holdouts = root.parent().unwrap().join("holdouts");
    let before = std::fs::read(&holdouts).unwrap();
    for label in [
        "wrong-window",
        "late-outcome",
        "wrong-count",
        "wrong-cut",
        "duplicate",
        "missing",
        "pending",
    ] {
        let mut altered = collection.clone();
        match label {
            "wrong-window" => {
                altered["inputs"]["targets"][0]["decision_at"] =
                    altered["windows"][0]["starts_unix_micros"].clone();
            }
            "late-outcome" => {
                altered["inputs"]["candidate_observations"][0]["outcome_observed_at"] =
                    json!(altered["windows"][1]["ends_unix_micros"].as_u64().unwrap() + 1);
            }
            "wrong-count" => {
                altered["windows"][1]["observation_count"] = json!(1);
            }
            "wrong-cut" => {}
            "duplicate" => {
                let duplicate = altered["inputs"]["candidate_observations"][0].clone();
                altered["inputs"]["candidate_observations"]
                    .as_array_mut()
                    .unwrap()
                    .push(duplicate);
            }
            "missing" => {
                altered["inputs"]["baseline_observations"]
                    .as_array_mut()
                    .unwrap()
                    .pop();
            }
            "pending" => {
                altered["inputs"]["candidate_observations"][0]["finalized_outcome"] = json!(null);
                altered["inputs"]["candidate_observations"][0]["outcome_observed_at"] = json!(0);
            }
            _ => unreachable!(),
        }
        let raw: eval::TemporalComparisonInputsV1 =
            serde_json::from_value::<TemporalComparisonInputsV1Raw>(altered["inputs"].clone())
                .unwrap()
                .into();
        altered["windows"][1]["observed_source_cut"] = json!(
            if label == "wrong-cut" {
                hash("wrong-cut")
            } else {
                crate::cognitive_timed_cohort::source_cut(&raw, plan).unwrap()
            }
            .to_string()
        );
        let path = root.join(format!("control-{label}-collection.json"));
        save(&path, &altered);
        let mut changed = input.clone();
        changed["stage"]["collection"] = pin(&path);
        let (success, result) = cli(
            root,
            &format!("control-{label}"),
            &host.fleet_path,
            "qualify",
            &changed,
        );
        assert!(
            !success && result["state"] == "failed",
            "invalid timed cohort {label} succeeded: {result}"
        );
        assert_eq!(std::fs::read(&holdouts).unwrap(), before);
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "retained real ordinary CLI with newly reserved future tasks and original selector"]
async fn actual_ordinary_cli_reserves_future_qualifies_selects_and_replays() {
    let root = PathBuf::from(
        std::env::var("HEPTA_LEARNING_STUDY_DIRECTORY").expect("fresh retained directory required"),
    );
    std::fs::create_dir(&root).unwrap();
    let root = root.canonicalize().unwrap();
    let script = PathBuf::from(
        std::env::var("HEPTA_LEARNING_CUSTODIAN").expect("exact custodian source required"),
    );
    let host = Host::new(&root).await;
    let actions = host.seed().await;
    let mut roles = Roles::new(&script, &root);
    let operations: Vec<_> = actions
        .iter()
        .map(|(_, operation)| operation.clone())
        .collect();
    let material_keys = json!({"evaluator":support::hex(&roles.processes[1].key),"future-custodian":support::hex(&roles.processes[6].key)});
    let observer_key = support::hex(&roles.processes[2].key);
    for role in &mut roles.processes {
        role.call(json!({"command":"configure","operations":operations,"material_keys":material_keys,"observer_key":observer_key}));
    }
    let view = Arc::new(publication::StudyView::new(
        root.join("artifact-owner"),
        &mut roles,
    ));
    let baseline_root = root.join("generation-0");
    std::fs::create_dir(&baseline_root).unwrap();
    let baseline = fit(&baseline_root, 0, &mut roles, &actions);
    let parent = view.publish(&baseline_root, &baseline, None, &mut roles);
    let current: Arc<dyn CurrentCognitiveRegistry> = view.clone();
    let predecessor = PinnedCognitiveRanker::load_source(
        owner(),
        host.launch,
        File::open(&parent.snapshot).unwrap(),
        File::open(&parent.payload).unwrap(),
        parent.selected.clone(),
        baseline.pin.clone(),
        current,
        Some(parent.source.clone()),
    )
    .unwrap();
    let expected = predecessor.readback().unwrap();
    let candidate_root = root.join("generation-1");
    std::fs::create_dir(&candidate_root).unwrap();
    let candidate = fit(&candidate_root, 1, &mut roles, &actions);
    let published = view.publish(
        &candidate_root,
        &candidate,
        Some(&parent.selected.manifest),
        &mut roles,
    );
    host.prove_candidate_withdrawal(&candidate_root, &candidate, &mut roles)
        .await;
    assert_eq!(predecessor.readback().unwrap(), expected);
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(root.join("holdouts"))
        .unwrap();
    let store =
        eval::LockedFileFinalHoldoutCasStoreV1::create(file, hash("three-generation-holdouts"))
            .unwrap();
    let original = eval::FencedFinalHoldoutOwnerV1::initialize(
        store,
        hash("three-generation-holdouts"),
        holdout_fence(),
    )
    .unwrap();
    let anchor = original.anchor();
    drop(original);
    File::open(&root).unwrap().sync_all().unwrap();
    let selected = qualify(
        &candidate_root,
        &host,
        1,
        &candidate,
        &parent,
        &expected,
        &mut roles,
        &admission::choices(&candidate, &actions),
        &admission::choices(&baseline, &actions),
        anchor,
        "ordinary-source",
        QualificationMode::SelectWithCohortControls,
    )
    .await;
    assert_eq!(selected["selection"]["state"], "selected");
    let anchor: eval::FinalHoldoutCasAnchorV1 =
        serde_json::from_value::<FinalHoldoutCasAnchorV1Raw>(selected["holdout_anchor"].clone())
            .unwrap()
            .into();
    let (path, digest) =
        process::descriptor(&root, &published, &candidate, &view, host.launch, anchor);
    let config = host.config();
    let material =
        crate::load_cognitive_process_bootstrap_v1(&path, digest, config.identity()).unwrap();
    let config = config.with_evaluated_cognitive_bootstrap(material).unwrap();
    let installed = config.cognitive_ranker().unwrap().readback().unwrap();
    assert_eq!(
        installed.model.payload_sha256,
        candidate.pin.payload_digest.to_string()
    );
    let (_, _, writer) = config.into_parts();
    drop(writer);
    let mut missing: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    missing["product"]
        .as_object_mut()
        .unwrap()
        .remove("reservation_acknowledgement");
    let changed = root.join("stripped-ack-bootstrap.json");
    save(&changed, &missing);
    let config = host.config();
    assert!(
        crate::load_cognitive_process_bootstrap_v1(
            &changed,
            Digest32::of_bytes(&std::fs::read(&changed).unwrap()),
            config.identity()
        )
        .is_err()
    );
    let (_, _, writer) = config.into_parts();
    drop(writer);
    let costs: Vec<_> = roles
        .processes
        .into_iter()
        .map(support::Role::close)
        .collect();
    save(
        &root.join("summary.json"),
        &json!({"schema":"hepta.ordinary-future-cli-study.v1","selected":selected["selection"],
        "process_loader_readback":installed,"cohort_controls_refused":7,"stripped_ack_refused":true,
        "native_cli":true,"original_file_owners":true,"fresh_future_tasks":true,"full_service_startup":false,
        "installed_service_generations":0,"observed_qualified_update_count":null,"independent_operators":false,"role_process_costs":costs}),
    );
}
