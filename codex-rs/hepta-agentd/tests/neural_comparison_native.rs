//! Real gen2/gen3 forwards inside the original holdout runner, under an
//! explicitly controlled synthetic test contract. Raw observations and the
//! original gate's result are retained even when there is no gain. No fixture
//! contract, signature, metric or result grants product installation authority.

#![cfg(target_os = "linux")]

use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_agentd::NeuralFinalHoldoutProviderV1;
use codex_hepta_agentd::NeuralHoldoutRuntimeV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_types::Digest32;

#[path = "support/neural_holdout_ledger.rs"]
mod ledger_fixture;
#[path = "support/neural_native_owner.rs"]
mod native;
#[path = "support/neural_holdout_plan.rs"]
mod plan_fixture;

use ledger_fixture::ControlledRoles;
use ledger_fixture::micros;

fn save(path: &Path, value: &serde_json::Value) -> native::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    File::open(path.parent().ok_or("output parent")?)?.sync_all()?;
    Ok(())
}

#[test]
#[ignore = "requires HEPTA_PN3_NEURAL_COMPARISON_CONFIG with actual pinned gen2/gen3 CPU material"]
fn real_gen2_gen3_forwards_score_only_after_original_holdout_consumption() -> native::Result<()> {
    let path = std::env::var_os("HEPTA_PN3_NEURAL_COMPARISON_CONFIG")
        .ok_or("explicit native configuration required")?;
    let raw = fs::read(path)?;
    if raw.len() > 65_536 {
        return Err("native configuration bound".into());
    }
    let input: native::Input = serde_json::from_slice(&raw)?;
    if input.schema != "hepta-smollm-neural-comparison-native-v1"
        || [
            &input.python,
            &input.chain,
            &input.materials,
            &input.baseline_parent,
            &input.candidate_parent,
            &input.output,
        ]
        .iter()
        .any(|path| !path.is_absolute())
    {
        return Err("native comparison requires explicit absolute project paths".into());
    }
    fs::DirBuilder::new().mode(0o700).create(&input.output)?;
    let mut roles = ControlledRoles::new();
    let (dataset, ledger) = roles.dataset(&input.output.join("original-estimator-ledger"));
    let candidate_model = native::model(
        &input,
        &input.candidate_parent,
        &input.candidate_parent_sha256,
        "candidate",
        &dataset,
    )?;
    let baseline_model = native::model(
        &input,
        &input.baseline_parent,
        &input.baseline_parent_sha256,
        "baseline",
        &dataset,
    )?;
    if candidate_model.pin.generation.get() != 3 || baseline_model.pin.generation.get() != 2 {
        return Err("this fixed comparison is gen3 versus gen2".into());
    }
    let mut material = plan_fixture::material(
        &dataset,
        &candidate_model.parameters,
        &baseline_model.parameters,
    );
    material.candidate = candidate_model.pin.clone();
    material.baseline = baseline_model.pin.clone();
    // One seed draw, retained before either forward. A poor support sample is
    // a failed experiment, never grounds for reseeding or replacing tasks.
    File::open("/dev/urandom")?.read_exact(&mut material.logging_seed)?;
    let (plan, candidate_plan, baseline_plan) = plan_fixture::plans(&material, &dataset);
    let tasks = material.tasks.iter().map(|task| serde_json::json!({
        "decision_id":task.decision_id.as_str(), "query":task.query, "expected_action":task.expected_action.as_str(),
        "principal_lineage":task.principal_lineage.as_str(), "episode_lineage":task.episode_lineage.as_str(),
        "cluster":task.cluster_id.as_str(),
    })).collect::<Vec<_>>();
    save(
        &input.output.join("frozen-controlled-comparison.json"),
        &serde_json::json!({
            "schema":"controlled-neural-comparison-precommit-v1", "frozen_at_micros":micros(),
            "controlled_contract_only":true, "independent_accepted":false, "prospective_accepted":false,
            "cross_fold_profile":"explicit controlled test partitions; no independent cross-fit evidence",
            "holdout_manifest":material.manifest_digest()?.to_string(), "plan":plan.frozen_plan.plan_digest.to_string(),
            "candidate_plan":candidate_plan.plan_digest.to_string(), "baseline_plan":baseline_plan.plan_digest.to_string(),
            "candidate_parent":candidate_model.parent_sha256.to_string(), "baseline_parent":baseline_model.parent_sha256.to_string(),
            "candidate_parameters":material.candidate.payload_digest.to_string(), "baseline_parameters":material.baseline.payload_digest.to_string(),
            "dataset":dataset.snapshot.dataset_digest.to_string(), "ledger":ledger.head_digest.to_string(),
            "logging_seed":material.logging_seed, "logging_policy":"sha256-seeded-bernoulli-half-v1",
            "metric":"IPS binary correctness", "confidence_alpha_ppm":50_000, "primary_minimum_improvement_q32":0,
            "tasks":tasks,
        }),
    )?;
    let candidate_bytes = candidate_model.parameters.clone();
    let baseline_bytes = baseline_model.parameters.clone();
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    let issuer = Arc::new(native::ControlledIssuer::open(
        &input.output.join("controlled-original-final-use"),
    )?);
    let journal_path = input.output.join("original-inference.control");
    let control = Arc::new(Mutex::new(DurableInferenceControl::open(
        &journal_path,
        128,
    )?));
    let candidate = native::start(
        candidate_model,
        "candidate",
        control.clone(),
        issuer.clone(),
        &runtime,
    )?;
    let baseline = native::start(
        baseline_model,
        "baseline",
        control.clone(),
        issuer.clone(),
        &runtime,
    )?;
    let mut provider = NeuralFinalHoldoutProviderV1::new(
        material.clone(),
        &plan,
        dataset,
        ledger,
        NeuralHoldoutRuntimeV1 {
            pin: material.candidate.clone(),
            parameters: candidate_bytes,
            inference: candidate.clone(),
        },
        NeuralHoldoutRuntimeV1 {
            pin: material.baseline.clone(),
            parameters: baseline_bytes,
            inference: baseline.clone(),
        },
    )?;
    let mut runner = plan_fixture::runner(&input.output.join("original-fenced-holdout"));
    let result =
        runner.evaluate_temporal_comparison(&plan, &candidate_plan, &baseline_plan, &mut provider);
    let candidate_shutdown = candidate.shutdown();
    let baseline_shutdown = baseline.shutdown();
    let rows = provider.observations().iter().map(|row| serde_json::json!({
        "decision_id":row.decision_id.as_str(), "query_sha256":row.query_digest.to_string(),
        "candidate_scores_q32":row.candidate_scores_q32, "baseline_scores_q32":row.baseline_scores_q32,
        "candidate_choice":row.candidate_choice.as_str(), "baseline_choice":row.baseline_choice.as_str(),
        "candidate_correct":row.candidate_correct, "baseline_correct":row.baseline_correct,
        "logged_action":row.logged_action.as_str(), "logged_correct":row.logged_correct,
        "candidate_receipt":row.candidate_receipt_digest.to_string(), "baseline_receipt":row.baseline_receipt_digest.to_string(),
        "decision_at":row.decision_at, "observed_at":row.outcome_observed_at, "evidence":row.evidence_digest.to_string(),
    })).collect::<Vec<_>>();
    save(
        &input.output.join("actual-forward-observations.json"),
        &serde_json::json!({
            "controlled_contract_only":true, "independent_accepted":false, "prospective_accepted":false,
            "result_error":result.as_ref().err().map(ToString::to_string),
            "candidate_shutdown":candidate_shutdown.as_ref().err(), "baseline_shutdown":baseline_shutdown.as_ref().err(), "rows":rows,
        }),
    )?;
    candidate_shutdown?;
    baseline_shutdown?;
    let receipt = result?;
    let context = roles.context();
    let bundle = runner.qualification_bundle(&receipt, &context)?;
    let evidence = roles.comparison_evidence(&bundle, &plan.metric_roles);
    let mut sink = eval::FileProductQualificationEvidenceSinkV1::new(
        input.output.join("controlled-original-decision"),
    )?;
    let qualification = runner.qualify_and_persist(
        &receipt,
        &context,
        &evidence,
        eval::ProductTimingEvidenceV1::Qualification,
        &roles.verifier,
        micros(),
        &mut sink,
    )?;
    assert_eq!(
        qualification.claim_scope,
        eval::EvaluationClaimScopeV1::Qualification
    );
    assert!(!qualification.authority.grants_any());
    let journal = fs::read_to_string(&journal_path)?;
    let ids = journal
        .lines()
        .filter_map(|line| line.strip_prefix("submit|"))
        .map(|line| line.split('|').next().unwrap().to_owned())
        .collect::<Vec<_>>();
    let records = {
        let owner = control.lock().unwrap();
        ids.iter()
            .map(|id| owner.get(id).unwrap().clone())
            .collect::<Vec<_>>()
    };
    assert_eq!(records.len(), 66);
    assert_eq!(issuer.claims(), 66);
    assert!(
        records
            .iter()
            .all(|record| record.state == RequestState::Completed)
    );
    assert_eq!(
        records
            .iter()
            .map(|record| record.consumed_tokens)
            .sum::<u32>(),
        64
    );
    drop(provider);
    drop(candidate);
    drop(baseline);
    drop(control);
    let recovered = DurableInferenceControl::open(&journal_path, 128)?;
    for record in &records {
        assert_eq!(recovered.get(&record.request.request_id), Some(record));
    }
    let metrics = receipt.metrics.iter().map(|metric| serde_json::json!({
        "metric":metric.metric_id.as_str(), "candidate_lower_q32":metric.candidate.lower.raw(),
        "candidate_upper_q32":metric.candidate.upper.raw(), "baseline_lower_q32":metric.baseline.lower.raw(),
        "baseline_upper_q32":metric.baseline.upper.raw(),
    })).collect::<Vec<_>>();
    save(
        &input.output.join("native-comparison-result.json"),
        &serde_json::json!({
            "schema":"controlled-real-neural-comparison-result-v1", "actual_forward_rows":32,
            "controlled_contract_only":true, "controlled_signers":true, "claim_scope":"Qualification",
            "original_runner_decision":format!("{:?}", qualification.decision.decision.disposition),
            "failed_metrics":qualification.decision.decision.failed_metrics.iter().map(ToString::to_string).collect::<Vec<_>>(),
            "metrics":metrics, "temporal_execution_digest":receipt.execution_digest.to_string(),
            "qualification_evidence_digest":qualification.evidence_digest.to_string(),
            "holdout_head":receipt.holdout.head_digest.to_string(), "inference_control_sha256":Digest32::of_bytes(journal.as_bytes()).to_string(),
            "original_final_use_claims":issuer.claims(), "original_control_requests":ids,
            "original_control_reopen_exact":true, "terminal_unload_observed":true,
            "product_artifact_installed":false, "ordinary_cognitive_context_qualified":false,
            "independent_accepted":false, "prospective_accepted":false, "public_reward_eligible":false,
        }),
    )?;
    Ok(())
}
