//! Continuous same-context owner/proposal and real unsigned-ledger diagnostic.
//! Missing authenticated learning/evaluation evidence remains a product blocker.
mod head;
mod measure;
mod runtime_profile;
mod stream_io;
mod ledger_probe;
mod dynamics_profile;
mod parameter_geometry;

use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::RwLock;

use codex_hepta_intelligence::PlasticityAnchorCommitterV1;
use codex_hepta_learning_artifacts::*;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_ndu::NduProjectionJournalV1;
use codex_hepta_neuron::*;
use codex_hepta_plasticity::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_native_owner_bridge::*;
use serde_json::json;
use serde_json::Value;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn id(value: impl Into<String>) -> Result<StableId> {
    Ok(StableId::new(value.into())?)
}
fn file(path: &Path) -> Result<File> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)?)
}
fn digest(value: &Value, key: &str) -> Result<Digest32> {
    Ok(value[key].as_str().ok_or("Missing digest")?.parse()?)
}
fn register(
    registry: &mut ArtifactRegistry,
    name: &str,
    kind: ArtifactKind,
    content: Digest32,
    objective: Digest32,
    support: Digest32,
    size: u64,
) -> Result<()> {
    registry.append(ArtifactEvent::Register {
        event_id: id(format!("register.{name}"))?,
        manifest: ArtifactManifest {
            artifact_id: id(name)?,
            kind,
            generation: Generation::new(1)?,
            predecessor_id: None,
            content_digest: content,
            objective_digest: objective,
            support_digest: support,
            producer_id: id("local.research.artifact-owner")?,
            compatibility_digest: support,
            encoded_size_bytes: size,
        },
    })?;
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if !(5..=6).contains(&args.len()) {
        return Err("Usage: native-proposal packet expected-packet-sha native-execution-root new-output [candidate-evaluation.json]".into());
    }
    let packet_bytes = std::fs::read(&args[1])?;
    if Digest32::of_bytes(&packet_bytes).to_string() != args[2] {
        return Err("Packet pin changed".into());
    }
    let packet: Value = serde_json::from_slice(&packet_bytes)?;
    let pins: runtime_profile::Pins = serde_json::from_value(packet["pins"].clone())?;
    let executed = Path::new(&args[3]);
    let root = Path::new(&args[4]);
    std::fs::create_dir(root)?;
    let result: Value = serde_json::from_slice(&std::fs::read(executed.join("result.json"))?)?;
    if result["packet_sha256"] != args[2] {
        return Err("Native execution used another packet".into());
    }
    let case = executed.join("case-0000");
    let context_bytes = std::fs::read(case.join("context.json"))?;
    let context: Value = serde_json::from_slice(&context_bytes)?;
    let sequence=context["sequence"].as_u64().ok_or("Missing actual sequence")? as usize;
    let row=packet["rows"].get(sequence.checked_sub(1).ok_or("Empty actual sequence")?).ok_or("Missing actual packet row")?;
    if context["abstain"]!=false || context["declared_ood"]!=false || row["pair"]!=context["pair"]
        || row["observed_record_digest"]!=context["observed_record_digest"] {
        return Err("The actual packet-bound ID tick was not admitted".into());
    }
    let (mut native,mut config)=runtime_profile::configuration(&pins,digest(&result,"binary_sha256")?)?;
    let future=packet["future_output_model"].as_bool().unwrap_or(false);
    if future {
        native.width=33;
        native.normalization_digest=Digest32::of_bytes(match packet["future_contract"].as_str() {
            Some("state_residual")=>b"abc4.actual-future-state-residual.no-scaling.v1".as_slice(),
            Some("future_correctness")=>b"abc4.future-probability-carrier.observed-coordinates-cancel.v1".as_slice(),
            _=>return Err("Unknown future output contract".into()),
        });
    }
    let profile=serde_json::from_value(packet.get("dynamics_profile").cloned().unwrap_or(json!("legacy")))?;
    dynamics_profile::bind(&mut native,&mut config,profile,if future {dynamics_profile::DriveDomain::FutureEmittedState}
        else {dynamics_profile::DriveDomain::HistoricalSemanticPrefix})?;
    let objective = digest(&context, "objective")?;
    let subject = digest(&context, "subject_scope")?;
    let scope = JournalScope {
        scope_digest: subject,
        objective_digest: objective,
    };
    let witness = FileAnchorWitnessStore::open(
        file(&case.join("neuron.witness"))?,
        scope,
        native.generation,
        4096,
    )?;
    let anchor = witness
        .current()?
        .ok_or("No actual witness acknowledgement")?;
    if anchor.checkpoint_digest != digest(&context, "anchor")? {
        return Err("Acknowledgement mismatch".into());
    }
    let journal = stream_io::journal(&case, native, scope, anchor)?;
    let checkpoint = journal.current()?.ok_or("No admitted checkpoint")?;
    let eligibility_digest = plasticity_eligibility_digest_v1(checkpoint)?;
    let eligibility = checkpoint.eligibility_q24().to_vec();
    let ndu = NduProjectionJournalV1::reopen(&std::fs::read(case.join("ndu.backup"))?)?;
    let modulator = FixedQ32::from_raw(
        context["ndu_terminal_q32"]
            .as_i64()
            .ok_or("No real terminal value")?,
    );
    let modulator_digest = plasticity_modulator_digest_v1(objective, subject, &[modulator])?;
    if ndu.selected_projection_digest(objective, subject) != Some(modulator_digest) {
        return Err("Wrong NDU subject/objective/value".into());
    }
    let selected: Digest32 = pins.weights.parse()?;
    let weights_bytes=std::fs::read(packet["weights_path"].as_str().ok_or("No weights path")?)?;
    if Digest32::of_bytes(&weights_bytes)!=selected {return Err("Baseline weights changed".into());}
    let geometry=parameter_geometry::from_weights(&weights_bytes,if future {parameter_geometry::HeadKind::Future}
        else {parameter_geometry::HeadKind::Current})?;
    let window = ProposalWindowV2 {
        window_id: id("abc4.continuous.final.resident-head.local-plasticity")?,
        window_digest: Digest32::of_bytes(&context_bytes),
    };
    let layer=geometry.layer.clone();
    let learning_rate = FixedQ32::from_raw((0.0001_f64 * (1_u64 << 32) as f64).round() as i64);
    let lower = FixedQ32::from_raw(-learning_rate.raw());
    let upper = learning_rate;
    let bindings = geometry.parameters.iter().enumerate()
        .map(|(i,parameter)| {
            Ok(PlasticityDynamicSignalBindingV1 {
                layer_id: layer.clone(),
                parameter_id: parameter.clone(),
                eligibility_index: i as u32,
                modulator_weights: vec![FixedQ32::ONE],
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let broadcast = plasticity_modulator_broadcast_digest_v1(&bindings)?;
    let grammar_bytes = serde_json::to_vec(
        &json!({"scope":"local research typed allowlist; not an authenticated control.engineering grammar",
        "artifact":pins.weights,"window":window.window_digest.to_string(),"parameters":geometry.span, "eligibility_map":"same numerical index",
        "learning_rate_q32":learning_rate.raw(),"bound_q32":upper.raw(),"scales":[0.5,1.0]}),
    )?;
    std::fs::write(root.join("local-update-rule.json"), &grammar_bytes)?;
    let update_rule = Digest32::of_bytes(&grammar_bytes);
    let policy = build_parameter_mutation_policy_v1(
        id("local.research.output-head-only")?,
        update_rule,
        selected,
        window.clone(),
        bindings
            .iter()
            .map(|b| ParameterMutationRuleV1 {
                parameter_id: b.parameter_id.clone(),
                layer_id: layer.clone(),
                surface: ParameterMutationSurfaceV1::LearnableParameter,
                minimum_delta: lower,
                maximum_delta: upper,
            })
            .collect(),
    )?;
    let mut artifacts = ArtifactRegistry::new();
    register(
        &mut artifacts,
        "resident-head",
        ArtifactKind::Parameters,
        selected,
        objective,
        pins.verification.parse()?,
        weights_bytes.len() as u64,
    )?;
    register(
        &mut artifacts,
        "broadcast",
        ArtifactKind::Policy,
        broadcast,
        objective,
        update_rule,
        grammar_bytes.len() as u64,
    )?;
    register(
        &mut artifacts,
        "update-rule",
        ArtifactKind::Policy,
        update_rule,
        objective,
        update_rule,
        grammar_bytes.len() as u64,
    )?;
    register(
        &mut artifacts,
        "mutation-policy",
        ArtifactKind::Policy,
        policy.policy_digest,
        objective,
        update_rule,
        grammar_bytes.len() as u64,
    )?;
    let snapshot_path = root.join("artifacts.snapshot");
    let snapshot_receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&snapshot_path)?,
        &artifacts,
        objective,
    )?;
    let artifacts = read_registry_snapshot(File::open(&snapshot_path)?, snapshot_receipt)?;
    let registry_head = artifacts.snapshot().head_digest;
    let dynamic = PlasticityDynamicOwnerEvidenceResolverV1::new(
        objective,
        subject,
        id("local.ndu.projection-owner")?,
        id("local.neuron.runtime-owner")?,
        Arc::new(RwLock::new(ndu)),
        vec![modulator],
        Arc::new(Mutex::new(journal)),
        anchor,
        artifacts.clone(),
        id("broadcast")?,
        bindings.clone(),
        1,
        2,
    )?;
    let mut resolved = 0;
    let query = |kind, evidence_digest| PlasticityOwnerEvidenceQueryV1 {
        kind,
        evidence_digest,
        objective_digest: objective,
        selected_artifact_digest: selected,
        artifact_registry_head_digest: registry_head,
        qualification_evidence_head_digest: Digest32::ZERO,
        window: window.clone(),
        dataset_digest: pins.dataset.parse().unwrap(),
        baseline_generation: Generation::new(1).unwrap(),
        layer_id: None,
        parameter_id: None,
        signal_eligibility: None,
        signal_modulator: None,
        signal_learning_rate: None,
        signal_lower_bound: None,
        signal_upper_bound: None,
        now: 1,
    };
    for (kind, ev) in [
        (PlasticityOwnerEvidenceKindV1::Modulator, modulator_digest),
        (
            PlasticityOwnerEvidenceKindV1::Eligibility,
            eligibility_digest,
        ),
        (PlasticityOwnerEvidenceKindV1::ModulatorBroadcast, broadcast),
    ] {
        dynamic.resolve(&query(kind, ev))?;
        resolved += 1;
    }
    let mut signals = Vec::new();
    for b in &bindings {
        let e = FixedQ32::from_raw(
            eligibility[b.eligibility_index as usize]
                .checked_mul(256)
                .ok_or("Eligibility overflow")?,
        );
        let evidence = plasticity_parameter_signal_digest_v1(
            &layer,
            &b.parameter_id,
            e,
            modulator,
            learning_rate,
            lower,
            upper,
            eligibility_digest,
            modulator_digest,
            broadcast,
        )?;
        let mut q = query(PlasticityOwnerEvidenceKindV1::ParameterSignal, evidence);
        q.layer_id = Some(layer.clone());
        q.parameter_id = Some(b.parameter_id.clone());
        q.signal_eligibility = Some(e);
        q.signal_modulator = Some(modulator);
        q.signal_learning_rate = Some(learning_rate);
        q.signal_lower_bound = Some(lower);
        q.signal_upper_bound = Some(upper);
        dynamic.resolve(&q)?;
        resolved += 1;
        signals.push(ParameterPlasticitySignalV3 {
            layer_id: layer.clone(),
            parameter_id: b.parameter_id.clone(),
            eligibility: e,
            modulator,
            learning_rate,
            lower_bound: lower,
            upper_bound: upper,
            evidence_digest: evidence,
        });
    }
    let norm=geometry.norm;
    let profile = ParameterGeneratorProfileV3 {
        selected_artifact_digest: selected,
        window: window.clone(),
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: layer,
            baseline_squared_l2_raw_q64: norm,
        }],
        mutation_policy: policy,
        update_scales: vec![FixedQ32::from_raw(FixedQ32::ONE.raw() / 2), FixedQ32::ONE],
        signals,
    };
    let generated = generate_parameter_candidates_v3(profile.clone())?;
    let candidates=generated.candidates.iter().map(|c|json!({"id":c.candidate_id.to_string(),"kind":format!("{:?}",c.kind),
        "deltas":c.parameter_deltas.iter().map(|d|json!({"parameter":d.parameter_id.to_string(),"delta_q32":d.delta.raw(),
            "evidence":d.evidence_digest.to_string()})).collect::<Vec<_>>()})).collect::<Vec<_>>();
    let description = json!({"generator_digest":generated.generator_digest.to_string(),"baseline_weights_sha256":selected.to_string(),
        "candidates":candidates,"baseline_layer_squared_norm_q64":norm.to_string(),"context":context,
        "dynamic_owner_resolutions":resolved,"qualification_frontier_is_production_qualified":false,
        "mapping":geometry.mapping,"head_contract":if future {"future_correctness"}else {"observed_output_correctness"}});
    std::fs::write(
        root.join("candidates.json"),
        serde_json::to_vec_pretty(&description)?,
    )?;
    let input = AgentdPlasticityAdmissionInputV1 {
        baseline_id: id("resident-head")?,
        objective_digest: objective,
        generator_profile: profile,
        generated: generated.clone(),
        baseline_generation: Generation::new(1)?,
        candidate_generation: Generation::new(2)?,
        dataset_digest: pins.dataset.parse()?,
        update_rule_digest: update_rule,
        modulator_digest,
        modulator_broadcast_digest: broadcast,
        eligibility_digest,
    };
    let ledger = DurableLedger::create(file(&root.join("learning.ledger"))?, objective, 8)?;
    let owner_policy = PlasticityOwnerEvidencePolicyV1::from_rules(vec![
        (
            PlasticityOwnerEvidenceKindV1::Dataset,
            id("local.research.dataset-owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            id("local.research.artifact-owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::MutationPolicy,
            id("local.research.artifact-owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::Modulator,
            id("local.ndu.projection-owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
            id("local.research.artifact-owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::Eligibility,
            id("local.neuron.runtime-owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::ParameterSignal,
            id("local.neuron.runtime-owner")?,
        ),
    ])?;
    let product_admission = resolve_agentd_plasticity_admission_v1(
        &input,
        &artifacts,
        &ledger,
        &dynamic,
        &owner_policy,
        1,
    );
    let admission_error = match product_admission {
        Ok(_) => return Err("Unexpected product admission without ledger frontier".into()),
        Err(e @ AgentdPlasticityHostErrorV1::ArtifactBinding)=>format!("{e:?}"),
        Err(e)=>return Err(format!("Unexpected zero-frontier admission boundary: {e:?}").into()),
    };
    let zero_frontier_error = admission_error.clone();
    std::fs::write(root.join("admission-before-ledger.json"),serde_json::to_vec_pretty(&json!({
        "actual_product_admission_called":true,"error":zero_frontier_error,"ledger_records":0}))?)?;
    let (ledger, observed_ledger) = ledger_probe::observed_history(ledger, root, objective, &context, selected)?;
    let after_observed = resolve_agentd_plasticity_admission_v1(&input, &artifacts, &ledger, &dynamic, &owner_policy, 1);
    let admission_error = match after_observed {
        Ok(_) => return Err("Unexpected product admission without dataset owner".into()),
        Err(error @ AgentdPlasticityHostErrorV1::OwnerEvidence(PlasticityOwnerEvidenceErrorV1::Unavailable))=>format!("{error:?}"),
        Err(error)=>return Err(format!("Unexpected observed-ledger admission boundary: {error:?}").into()),
    };
    let mut report = json!({"same_context_dynamic_resolver_constructed":true,"actual_owner_resolutions":resolved,
        "parameter_generator_called":true,"update_candidates":generated.candidates.iter().filter(|c|c.kind==ParameterCandidateKindV2::Update).count(),
        "same_context_neuron_anchor":anchor.checkpoint_digest.to_string(),"objective":objective.to_string(),"subject":subject.to_string(),
        "actual_product_admission_called":true,"product_admission":"rejected","product_error":admission_error,
        "zero_frontier_error":zero_frontier_error,"observed_unsigned_ledger":observed_ledger,
        "measured_learning_ledger_records":ledger.records()?.len(),"measured_learning_ledger_head":ledger.snapshot()?.head_digest.to_string(),
        "scope":"continuous same-context journal, real unsigned V1 observations; no product-signed ledger, DatasetSnapshot owner, daemon or credential authority",
        "core_proposal_persisted":false,"applied_model_update":false,"authority":"deny_all"});
    if args.len() == 6 {
        let bytes = std::fs::read(&args[5])?;
        let evaluation: Value = serde_json::from_slice(&bytes)?;
        if evaluation["generator_digest"] != generated.generator_digest.to_string()
            || evaluation["eligible_for_independent_acceptance"] != false
        {
            return Err("Evaluation scope or candidate binding changed".into());
        }
        let proposal = propose_v2(ParameterProposalRequestV2 {
            proposal_id: id("abc4.continuous.final.research.proposal")?,
            proposer_id: id("local.research.generator")?,
            evaluator_id: id("local.research.development-evaluator")?,
            selected_artifact_digest: selected,
            window,
            baseline_generation: Generation::new(1)?,
            candidate_generation: Generation::new(2)?,
            dataset_digest: pins.dataset.parse()?,
            update_rule_digest: update_rule,
            modulator_digest,
            modulator_broadcast_digest: broadcast,
            eligibility_digest,
            evaluation_digest: Digest32::of_bytes(&bytes),
            rollback_predecessor_digest: selected,
            norm_layers: generated.norm_layers,
            candidates: generated.candidates,
        })?;
        let mut anchor_store =
            AgentdPlasticityAnchorStoreV1::open(file(&root.join("proposal.witness"))?, objective)?;
        let fence = anchor_store.issue_next_fence()?;
        let mut registry = DurableProposalRegistry::open_bootstrap_empty(
            file(&root.join("proposal.registry"))?,
            objective,
            fence,
            8,
        )?;
        registry.append_v2(Digest32::ZERO, proposal.clone())?;
        let committed = registry
            .current_anchor()?
            .ok_or("Proposal append missing anchor")?;
        if !anchor_store.persist_anchor(objective, fence, committed) {
            return Err("Proposal witness failed".into());
        }
        drop(registry);
        drop(anchor_store);
        let anchor_store =
            AgentdPlasticityAnchorStoreV1::open(file(&root.join("proposal.witness"))?, objective)?;
        if anchor_store.anchor() != Some(committed) {
            return Err("Proposal witness recovery mismatch".into());
        }
        let registry = DurableProposalRegistry::open_anchored(
            file(&root.join("proposal.registry"))?,
            objective,
            fence,
            8,
            committed,
        )?;
        if registry.get_v2_by_proposal_id(&proposal.proposal_id)? != Some(&proposal) {
            return Err("Proposal recovery mismatch".into());
        }
        report["core_proposal_persisted"] = json!(true);
        report["core_proposal_digest"] = json!(proposal.proposal_digest.to_string());
        report["proposal_anchor"] = json!(committed.frame_digest.to_string());
        report["proposal_recovered"] = json!(true);
        report["proposal_status"] = json!("RequiresIndependentAcceptance");
        report["candidate_evaluation_sha256"] = json!(Digest32::of_bytes(&bytes).to_string());
    }
    std::fs::write(
        root.join("result.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!("{report}");
    Ok(())
}
