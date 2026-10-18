//! Ordinary first reservation and signature handoff through the original
//! holdout, canonical estimator, independent evidence and publication owners.
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, ensure};
use codex_hepta_fleet::{AgentLifecycle, FleetRegistry};
use codex_hepta_intelligence_eval as eval;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_learning_ledger::{LearningEvidenceRoleV1, LearningEvidenceVerifierV1, SignedLearningEvidenceV1};
use codex_hepta_supervisor::SupervisordClient;
use serde_json::{Value, json};

use crate::AgentdClient;
use crate::cognitive_process_bootstrap::{FileAccess, open_bounded_regular};
use crate::cognitive_process_evaluation::{CrossFoldPlanV1Raw, LongitudinalTimeEvidenceV1Raw, MetricGateV1Raw, MetricRoleContractV2Raw, ObservedFutureWindowV1Raw, SelfEvolutionSelectionPolicyV1Raw, SignedEvaluationEvidenceV1Raw};
use crate::cognitive_process_evidence::LearningEvidenceTrustV1Raw;
use crate::cognitive_process_product_wire::{FinalHoldoutCasAnchorV1Raw, HoldoutWriterFenceV1Raw, ProductMetricSourceContractV1Raw, ProductQualificationContextV1Raw, TemporalEvaluationPlanRaw};
use crate::cognitive_qualification_provider::{CollectedInputsProviderV1, read_pinned};
use crate::cognitive_qualification_wire::*;

#[cfg(test)]
#[path = "cognitive_qualification_tests.rs"]
mod tests;

pub async fn qualify_cognitive_upgrade_v1(fleet: &FleetRegistry, input: CognitiveQualificationInputV1) -> Result<Value> {
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_micros())?;
    let snapshot = fleet.load()?;
    let agent = snapshot.agent(&input.agent_id).context("qualification Agent is not registered")?;
    let external = |path: &Path| -> Result<()> {
        ensure!(path.is_absolute(), "qualification owner path must be absolute");
        for root in [agent.layout.home_root(), agent.layout.run_root(), agent.manifest.workspace.as_path()] {
            ensure!(!path.starts_with(root), "qualification trust/history must be outside Agent-owned paths");
        }
        Ok(())
    };
    external(&input.host.path)?;
    external(&input.holdout_material.path)?;
    let host: CognitiveQualificationHostV1 = serde_json::from_slice(&read_pinned(&input.host, 4 * 1024 * 1024)?)?;
    ensure!(host.schema_version == 1 && host.agent_id == input.agent_id, "qualification host subject/schema mismatch");
    external(&host.holdout.path)?;
    let policy: eval::SelfEvolutionSelectionPolicyV1 = host.policy.into();
    let trust: codex_hepta_learning_ledger::LearningEvidenceTrustV1 = host.trust.into();
    let verifier = LearningEvidenceVerifierV1::new(trust.clone())?;
    let mut raw_plan: eval::CrossFoldPlanV1 = input.frozen_plan.into();
    // The signed original plan also commits the operator's exact policy,
    // verifier and retained owner anchor. They cannot be refitted after looking
    // at outcomes while replaying the same consumed plan.
    let mut estimand = b"hepta.agentd.cognitive-qualification-host-estimand.v1\0".to_vec();
    estimand.extend_from_slice(input.host.digest.0.as_array());
    estimand.extend_from_slice(host.estimand_digest.0.as_array());
    let estimand = codex_hepta_types::Digest32::of_bytes(&estimand);
    if matches!(&input.stage, CognitiveQualificationStageV1::PlanStatement) {
        raw_plan.estimand_digest = estimand;
    } else {
        ensure!(raw_plan.estimand_digest == estimand, "qualification plan must bind the exact preregistered host policy and trust");
    }
    ensure!(raw_plan.claim_scope == eval::EvaluationClaimScopeV1::SystemLongitudinal
        && raw_plan.objective_digest == verifier.objective_digest()
        && raw_plan.baseline_id.as_str() == host.expected_predecessor.model.artifact_id
        && policy.no_change_baseline_id == raw_plan.baseline_id
        && policy.no_change_baseline_digest.to_string() == host.expected_predecessor.model.payload_sha256
        && policy.minimum_future_window_micros > 0,
        "qualification policy/objective/current predecessor binding mismatch");
    let candidate_plan: eval::TemporalEvaluationPlan = input.candidate_plan.into();
    let baseline_plan: eval::TemporalEvaluationPlan = input.baseline_plan.into();
    ensure!(host.future_not_before_unix_micros > 0
        && candidate_plan.fold.evaluation_start >= host.future_not_before_unix_micros
        && baseline_plan.fold.evaluation_start >= host.future_not_before_unix_micros,
        "temporal plans must start after the pinned future boundary");
    let product_plan = eval::freeze_product_evaluation_plan_v1(
        raw_plan.clone(), input.metric_roles.into_iter().map(Into::into).collect(),
        input.metric_sources.into_iter().map(Into::into).collect(), &candidate_plan, &baseline_plan,
    )?;
    ensure!(input.holdout_material.digest.0 == product_plan.frozen_plan.final_holdout_digest,
        "qualification holdout manifest differs from the preregistered plan");
    read_pinned(&input.holdout_material, 4 * 1024 * 1024)?;
    if matches!(&input.stage, CognitiveQualificationStageV1::PlanStatement) {
        ensure!(input.generator_plan.is_none(), "plan preparation cannot transport a fabricated signature");
        return Ok(json!({"state":"awaiting_generator_signature", "agent_id":input.agent_id,
            "operation_id":input.operation_id.0.as_str(), "frozen_plan":CrossFoldPlanV1Raw::from(raw_plan),
            "plan_sha256":product_plan.frozen_plan.plan_digest.to_string(),
            "generator_signing_payload_hex":hex(product_plan.frozen_plan.plan_digest.as_array()),
            "host_sha256":input.host.digest.0.to_string(), "authority_granted":false}));
    }
    let generator: SignedLearningEvidenceV1 = input.generator_plan.context("independent generator signature is required before holdout consumption")?.into();
    verifier.verify(LearningEvidenceRoleV1::Generator, &generator, product_plan.frozen_plan.plan_digest.as_array(), now)?;
    let binding = host.holdout.binding.0;
    let expected_anchor: eval::FinalHoldoutCasAnchorV1 = host.holdout.anchor.into();
    let fence: eval::HoldoutWriterFenceV1 = host.holdout.fence.into();
    let file = open_bounded_regular(&host.holdout.path, 32 * 1024 * 1024, FileAccess::Recover)?;
    let mut store = eval::LockedFileFinalHoldoutCasStoreV1::recover(file, binding, Some(expected_anchor))?;
    let current = store.load(binding)?.context("qualification holdout owner was not initialized")?;
    ensure!(current.fence == fence, "qualification cannot issue or take over a holdout writer fence");
    // A lost reservation reply can replay exactly its one appended plan. Any
    // other unwitnessed tail still requires a separately retained new anchor.
    let exact_reservation_tail = current.journal.records.len() as u64 == expected_anchor.record_count.saturating_add(1)
        && current.journal.records.last().is_some_and(|record| record.plan == product_plan.frozen_plan);
    ensure!(store.anchor() == Some(expected_anchor) || exact_reservation_tail,
        "qualification holdout has an unacknowledged unrelated tail");
    if !matches!(&input.stage, CognitiveQualificationStageV1::Reserve) {
        ensure!(current.journal.records.iter().any(|record| record.plan == product_plan.frozen_plan
            && record.reservation_time.is_some()), "future qualification requires an existing timed reservation");
    }
    crate::cognitive_process_product::acknowledge_holdout_namespace(&host.holdout.path)?;
    let mut owner = eval::FencedFinalHoldoutOwnerV1::recover(store, binding, fence.clone())?;
    let identity = json!({"agent_id":input.agent_id, "operation_id":input.operation_id.0.as_str(),
        "candidate_id":product_plan.frozen_plan.candidate_id.as_str(), "baseline_id":product_plan.frozen_plan.baseline_id.as_str(),
        "plan_sha256":product_plan.frozen_plan.plan_digest.to_string(), "trust_sha256":verifier.trust_digest().to_string(),
        "frozen_unix_micros":generator.issued_at});
    if matches!(&input.stage, CognitiveQualificationStageV1::Reserve) {
        let receipt = owner.reserve_before_window(&product_plan.frozen_plan, host.future_not_before_unix_micros)?;
        let acknowledged_at = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_micros())?;
        ensure!(receipt.disposition == eval::HoldoutUseDispositionV1::IdempotentReplay
            || acknowledged_at < host.future_not_before_unix_micros,
            "timed reservation consumed, but its durable ACK missed the future boundary");
        let time = receipt.reservation_time.context("timed reservation did not persist its clock")?;
        return Ok(json!({"state":"awaiting_independent_collection", "identity":identity,
            "reservation":{"sequence":receipt.sequence,"record_digest":receipt.record_digest.to_string(),
                "use_digest":receipt.use_receipt.use_digest.to_string()},
            "holdout_anchor":FinalHoldoutCasAnchorV1Raw::from(owner.anchor()),
            "journal_head_sha256":receipt.head_digest.to_string(), "disposition":format!("{:?}",receipt.disposition),
            "reservation_time":{"reserved_at_unix_micros":time.reserved_at_unix_micros(),
                "window_not_before_unix_micros":time.window_not_before_unix_micros()},
            "observed_at_unix_micros":acknowledged_at,
            "requires_independent_durable_acknowledgement":true,"authority_granted":false}));
    }
    let reserved = owner.reserve_before_window(&product_plan.frozen_plan, host.future_not_before_unix_micros)?;
    if let CognitiveQualificationStageV1::AcknowledgementStatement { reservation, received_at_unix_micros } = &input.stage {
        ensure!(reserved.sequence == reservation.sequence && reserved.record_digest == reservation.record_digest.0
            && reserved.use_receipt.use_digest == reservation.use_digest.0, "acknowledgement reservation mismatch");
        let payload = eval::holdout_reservation_acknowledgement_payload_v1(
            binding, &fence, &product_plan.frozen_plan, &reserved, *received_at_unix_micros,
        )?;
        return Ok(json!({"state":"awaiting_independent_acknowledgement_signature", "identity":identity,
            "acknowledgement_signing_payload_hex":hex(&payload),"received_at_unix_micros":received_at_unix_micros,
            "authority_granted":false}));
    }
    let mut selection = None;
    let (collection, reservation, acknowledgement, observer, evaluator, evidence_path) = match input.stage {
        CognitiveQualificationStageV1::PlanStatement | CognitiveQualificationStageV1::Reserve | CognitiveQualificationStageV1::AcknowledgementStatement { .. } => unreachable!("preparation returned above"),
        CognitiveQualificationStageV1::ObserverStatement { collection, reservation, acknowledgement } => (collection, reservation, acknowledgement, None, None, None),
        CognitiveQualificationStageV1::EvaluatorStatement { collection, reservation, acknowledgement, observer } => (collection, reservation, acknowledgement, Some(observer), None, None),
        CognitiveQualificationStageV1::Finalize { collection, reservation, acknowledgement, observer, evaluator, qualification_evidence_path, selection: selected_stage } => {
            external(&qualification_evidence_path)?;
            selection = selected_stage;
            (collection, reservation, acknowledgement, Some(observer), Some(evaluator), Some(qualification_evidence_path))
        }
    };
    let acknowledgement_material = serde_json::to_value(&acknowledgement)?;
    let acknowledged_at = acknowledgement.received_at_unix_micros;
    let acknowledgement: SignedLearningEvidenceV1 = acknowledgement.observer.into();
    let ack_payload = eval::holdout_reservation_acknowledgement_payload_v1(
        binding, &fence, &product_plan.frozen_plan, &reserved, acknowledged_at,
    )?;
    ensure!(acknowledgement.issued_at >= acknowledged_at, "observer cannot sign before receiving the durable reservation ACK");
    verifier.verify(LearningEvidenceRoleV1::Observer, &acknowledgement, &ack_payload,
        u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_micros())?)?;
    external(&collection.path)?;
    // The required reservation is established above before this callback can
    // open released data. No replay descriptor is upgraded to acquire rights.
    let mut provider = CollectedInputsProviderV1 {
        material: input.holdout_material, collection, reservation,
        plan_digest: product_plan.frozen_plan.plan_digest, observed: None,
    };
    let mut runner = eval::ProductEvaluationRunnerV1::new(owner);
    let temporal = runner.evaluate_temporal_comparison(&product_plan, &candidate_plan, &baseline_plan, &mut provider)?;
    let observed = provider.observed.context("original holdout callback did not release observations")?;
    ensure!(observed.windows.iter().all(|window| window.starts_unix_micros >= host.future_not_before_unix_micros),
        "observed window began before the preregistered and independently acknowledged reservation boundary");
    let bundle = runner.qualification_bundle(&temporal, &observed.context)?;
    let observer_payload = eval::future_window_statement_payload_v1(
        &bundle, generator.issued_at, &observed.windows, policy.minimum_future_window_micros,
    )?;
    let mut output = json!({"state":"awaiting_observer_signature", "identity":identity,
        "holdout_anchor":FinalHoldoutCasAnchorV1Raw::from(runner.holdout_anchor()),
        "execution_sha256":temporal.execution_digest.to_string(),
        "metrics":temporal.metrics.iter().cloned().map(MetricGateV1Raw::from).collect::<Vec<_>>(),
        "windows":observed.windows.iter().cloned().map(ObservedFutureWindowV1Raw::from).collect::<Vec<_>>(),
        "evaluation_rows":{"offered":observed.offered_rows,"candidate_terminal":observed.candidate_terminal_rows,
            "candidate_pending":observed.candidate_pending_rows,"baseline_terminal":observed.baseline_terminal_rows,
            "baseline_pending":observed.baseline_pending_rows,"censored":null,
            "scope":"released comparison rows; upstream offered/censored universe requires source-owner evidence"},
        "observer_signing_payload_hex":hex(&observer_payload), "authority_granted":false,
        "observed_qualified_update_count":null,"independent_operator_evidence":null});
    let Some(observer) = observer else { return Ok(output); };
    let observer: SignedLearningEvidenceV1 = observer.into();
    ensure!(observer.principal_id == acknowledgement.principal_id,
        "the future-window observer must also attest the retained durable reservation ACK");
    verifier.verify(LearningEvidenceRoleV1::Observer, &observer, &observer_payload, now)?;
    let timing = eval::LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: generator.issued_at, windows: observed.windows, observer,
    };
    let evaluator_payload = eval::longitudinal_evaluation_signing_payload_v3(
        &bundle, &product_plan.metric_roles, &timing, policy.minimum_future_window_micros,
    )?;
    output["state"] = json!("awaiting_evaluator_signature");
    output["evaluator_signing_payload_hex"] = json!(hex(&evaluator_payload));
    let Some(evaluator) = evaluator else { return Ok(output); };
    let path = evidence_path.context("qualification publication path is required")?;
    let mut sink = eval::FileProductQualificationEvidenceSinkV1::new(&path)?;
    let evidence = eval::SignedEvaluationEvidenceV1 { generator_plan: generator, evaluator_bundle: evaluator.into() };
    let qualification = runner.qualify_and_persist(
        &temporal, &observed.context,
        &evidence,
        eval::ProductTimingEvidenceV1::SystemLongitudinal { timing: &timing, minimum_window_micros: policy.minimum_future_window_micros },
        &verifier, u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_micros())?, &mut sink,
    )?;
    let decision = &qualification.decision.decision;
    let bootstrap_inputs_path = path.with_extension("released-inputs.json");
    external(&bootstrap_inputs_path)?;
    crate::cognitive_materials_io::persist_material(&bootstrap_inputs_path, &observed.bootstrap_inputs, 32 * 1024 * 1024)?;
    output["released_inputs"] = json!({"path":bootstrap_inputs_path,
        "digest":codex_hepta_types::Digest32::of_bytes(&observed.bootstrap_inputs).to_string()});
    output["publication_sha256"] = json!(qualification.publication_digest.to_string());
    output["qualification_evidence_path"] = json!(path);
    output["qualification_evidence_sha256"] = json!(codex_hepta_types::Digest32::of_bytes(&crate::cognitive_materials_io::read_material(&path, 4 * 1024 * 1024)?).to_string());
    // These are plain inputs for the existing process loader, which must replay
    // the original evaluator and selector again. No sealed token is exported.
    output["bootstrap_evaluation_materials"] = json!({
        "frozen_plan":CrossFoldPlanV1Raw::from(raw_plan),
        "policy":SelfEvolutionSelectionPolicyV1Raw::from(policy.clone()),
        "metric_roles":product_plan.metric_roles.iter().cloned().map(MetricRoleContractV2Raw::from).collect::<Vec<_>>(),
        "evaluation_evidence":SignedEvaluationEvidenceV1Raw::from(evidence.clone()),
        "longitudinal_time":LongitudinalTimeEvidenceV1Raw::from(timing.clone()),
        "trust":LearningEvidenceTrustV1Raw::from(trust),
        "holdout":{"path":host.holdout.path,"binding":binding.to_string(),
            "fence":HoldoutWriterFenceV1Raw::from(fence),"anchor":FinalHoldoutCasAnchorV1Raw::from(runner.holdout_anchor())},
        "product":{"candidate_plan":TemporalEvaluationPlanRaw::from(candidate_plan),
            "baseline_plan":TemporalEvaluationPlanRaw::from(baseline_plan),
            "metric_sources":product_plan.metric_sources.iter().cloned().map(ProductMetricSourceContractV1Raw::from).collect::<Vec<_>>(),
            "context":ProductQualificationContextV1Raw::from(observed.context.clone()),
            "reservation_acknowledgement":acknowledgement_material,
            "released_inputs":output["released_inputs"],"holdout_material":provider.material,
            "qualification_evidence":{"path":path,"digest":output["qualification_evidence_sha256"]}}});
    output["disposition"] = json!(format!("{:?}", decision.disposition));
    output["failed_metrics"] = json!(decision.failed_metrics.iter().map(codex_hepta_types::StableId::as_str).collect::<Vec<_>>());
    output["state"] = json!(match decision.disposition {
        eval::IndependentEvaluationDispositionV1::EligibleForIndependentSelection => "eligible_for_independent_selection",
        eval::IndependentEvaluationDispositionV1::Ineligible => "no_update",
        eval::IndependentEvaluationDispositionV1::InsufficientEvidence => "insufficient_evidence",
    });
    if decision.disposition == eval::IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        && let Some(stage) = selection
    {
        output["selection"] = crate::cognitive_qualification_selection::select(
            crate::cognitive_qualification_selection::SelectionContextV1 {
                qualification: &qualification, policy: &policy, bundle: &bundle, metric_roles: &product_plan.metric_roles,
                evidence: &evidence, timing: &timing, verifier: &verifier,
                now: u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_micros())?,
                forbidden_roots: [agent.layout.home_root(), agent.layout.run_root(), agent.manifest.workspace.as_path()],
            }, stage,
        )?;
        if let Some(materials) = output["selection"]["materials"].as_object().cloned() {
            let bootstrap = output["bootstrap_evaluation_materials"].as_object_mut().context("missing exported bootstrap materials")?;
            bootstrap.extend(materials);
        }
    }
    if decision.disposition != eval::IndependentEvaluationDispositionV1::EligibleForIndependentSelection {
        let retained: Result<_> = async {
            let supervisor = SupervisordClient::new(fleet.layout().supervisor_socket().to_path_buf())?;
            let status = supervisor.snapshot(host.agent_id.clone()).await?;
            ensure!(status.active && status.healthy && status.lifecycle == AgentLifecycle::Running
                && status.current_release.as_ref() == Some(&host.source_release) && !status.release_change_pending,
                "no-update predecessor release is not active and stable");
            let generation = status.spawn_generation.context("active predecessor has no generation")?;
            let client = AgentdClient::new(agent.layout.agentd_control_socket().to_path_buf(), host.agent_id, generation)?;
            let current = client.cognitive_model_status().await?.installed.context("active predecessor has no cognitive model")?;
            ensure!(current == host.expected_predecessor, "no-update predecessor readback changed");
            Ok(current)
        }.await;
        match retained {
            Ok(model) => { output["retained_model"] = json!(model); }
            Err(error) => {
                output["quality_state"] = output["state"].clone();
                output["state"] = json!("blocked");
                output["reason"] = json!(format!("qualification persisted, but current predecessor could not be retained: {error:#}"));
            }
        }
    }
    Ok(output)
}

pub(super) fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes { let _ = write!(&mut output, "{byte:02x}"); }
    output
}
