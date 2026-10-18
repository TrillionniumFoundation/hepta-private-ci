//! Concrete ordinary input and locked-file holdout owner. The controlled plan
//! and signer are protocol fixtures, not observed future efficacy or deployment.
use super::*;
use std::fs::OpenOptions;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_ledger as ledger;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::cognitive_process_evaluation::*;
use crate::cognitive_process_evidence::*;
use crate::cognitive_process_product_wire::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn plan(name: &str, objective: Digest32) -> eval::TemporalEvaluationPlan {
    let mut plan = eval::TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: objective,
        fold: eval::TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold")),
            fold_id: id(name),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: eval::OpePlan {
            plan_digest: digest(&format!("{name}-ope")),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(4_i64 << 32),
        },
        confidence: eval::ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence")),
            assumptions_digest: digest("independent-fixture-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = plan.canonical_digest().unwrap();
    plan
}

fn write(path: &Path, value: &Value) -> Value {
    let bytes = serde_json::to_vec(value).unwrap();
    std::fs::write(path, &bytes).unwrap();
    json!({"path":path,"digest":Digest32::of_bytes(&bytes).to_string()})
}

#[tokio::test]
async fn ordinary_qualification_reserves_once_and_missing_release_preserves_original_history()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
    let fleet = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = AgentId::parse("11111111-1111-4111-8111-111111111111")?;
    fleet.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_micros())?;
    let key = SigningKey::from_bytes(&[91; 32]);
    let observer_key = SigningKey::from_bytes(&[92; 32]);
    let principal = ledger::AuthenticatedPrincipalV1 {
        principal_id: id("fixture-generator"),
        credential_chain_digest: digest("generator-credential"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: digest("scope"),
        authority_epoch: 1,
        authenticated_at: now - 1_000_000,
        expires_at: now + 600_000_000,
    };
    let observer_principal = ledger::AuthenticatedPrincipalV1 {
        principal_id: id("fixture-observer"),
        signing_key_digest: Digest32::of_bytes(&observer_key.verifying_key().to_bytes()),
        ..principal.clone()
    };
    let trust = ledger::LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        signers: vec![
            ledger::TrustedLearningSignerV1 {
                principal: principal.clone(),
                controller_id: id("fixture-controller"),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            ledger::TrustedLearningSignerV1 {
                principal: observer_principal.clone(),
                controller_id: id("fixture-observer-controller"),
                verifying_key: observer_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Observer],
                revoked_at: None,
            },
        ],
    };
    let verifier = LearningEvidenceVerifierV1::new(trust.clone())?;
    let material = write(
        &root.join("sealed-material.json"),
        &json!({"fixture":"sealed unknown future inputs"}),
    );
    let material_digest: Digest32 = material["digest"].as_str().unwrap().parse()?;
    let raw = eval::CrossFoldPlanV1 {
        plan_id: id("ordinary-plan"),
        claim_scope: eval::EvaluationClaimScopeV1::SystemLongitudinal,
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        estimand_digest: digest("future-utility"),
        metric_contracts: vec![eval::MetricContractV1 {
            metric_id: id("utility"),
            direction: eval::EvaluationDirectionV1::Maximize,
            safety_floor: None,
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: ["one", "two"]
            .map(|name| eval::CrossFoldPartitionV1 {
                fold_id: id(name),
                training_principals: vec![id(&format!("train-{name}"))],
                training_episodes: vec![id(&format!("train-episode-{name}"))],
                training_windows: vec![id(&format!("past-{name}"))],
                holdout_principals: vec![id(&format!("future-{name}"))],
                holdout_episodes: vec![id(&format!("future-episode-{name}"))],
                holdout_windows: vec![id(&format!("future-window-{name}"))],
                model_digest: digest("candidate-payload"),
                predictions_digest: digest("frozen-predictions"),
            })
            .to_vec(),
        final_holdout_window_id: id("future-window-two"),
        final_holdout_digest: material_digest,
    };
    let roles = vec![eval::MetricRoleContractV2 {
        metric_id: id("utility"),
        role: eval::MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let sources = vec![eval::ProductMetricSourceContractV1 {
        metric_id: id("utility"),
        source: eval::ProductMetricSourceV1::Ips,
    }];
    let future_boundary = now + 60_000_000;
    let mut candidate = plan("candidate-plan", digest("objective"));
    let mut baseline = plan("baseline-plan", digest("objective"));
    for plan in [&mut candidate, &mut baseline] {
        plan.fold.evaluation_start = future_boundary;
        plan.ope.outcome_watermark = future_boundary + 600_000_000;
        plan.plan_digest = plan.canonical_digest()?;
    }
    let frozen = eval::freeze_product_evaluation_plan_v1(
        raw.clone(),
        roles.clone(),
        sources.clone(),
        &candidate,
        &baseline,
    )?;
    let mut signed = ledger::SignedLearningEvidenceV1 {
        evidence_id: id("generator-plan"),
        principal_id: principal.principal_id,
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        issued_at: now,
        expires_at: now + 600_000_000,
        payload_digest: Digest32::of_bytes(frozen.frozen_plan.plan_digest.as_array()),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let holdout_path = root.join("original-holdouts");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&holdout_path)?;
    let binding = digest("original-holdout-binding");
    let fence = eval::HoldoutWriterFenceV1 {
        owner_id: id("original-holdout-owner"),
        generation: 1,
        lease_digest: digest("held-owner-lease"),
    };
    let store = eval::LockedFileFinalHoldoutCasStoreV1::create(file, binding)?;
    let owner = eval::FencedFinalHoldoutOwnerV1::initialize(store, binding, fence.clone())?;
    let initial = owner.anchor();
    drop(owner);
    let host = write(
        &root.join("host.json"),
        &json!({"schema_version":1,"agent_id":agent,"source_release":"baseline",
        "expected_predecessor":{"spawn_generation":1,"model":{"artifact_id":"baseline","artifact_generation":1,
            "payload_sha256":digest("baseline-payload").to_string()},"source_manifest_sha256":null,"selection_sha256":null,
            "evaluated_predecessor":null,"current_owner_trust_sha256":digest("current-trust").to_string()},
        "estimand_digest":digest("future-utility").to_string(),
        "future_not_before_unix_micros":future_boundary,
        "policy":SelfEvolutionSelectionPolicyV1Raw::from(eval::SelfEvolutionSelectionPolicyV1 {
            no_change_baseline_id:id("baseline"), no_change_baseline_digest:digest("baseline-payload"), minimum_dataset_records:1,
            minimum_future_window_micros:1_000_000 }), "trust":LearningEvidenceTrustV1Raw::from(trust),
        "holdout":{"path":holdout_path,"binding":binding.to_string(),"fence":HoldoutWriterFenceV1Raw::from(fence),
            "anchor":FinalHoldoutCasAnchorV1Raw::from(initial)}}),
    );
    let mut input = json!({"agent_id":agent,"operation_id":"ordinary-reservation","host":host,
        "frozen_plan":CrossFoldPlanV1Raw::from(raw),"metric_roles":roles.into_iter().map(MetricRoleContractV2Raw::from).collect::<Vec<_>>(),
        "metric_sources":sources.into_iter().map(ProductMetricSourceContractV1Raw::from).collect::<Vec<_>>(),
        "candidate_plan":TemporalEvaluationPlanRaw::from(candidate),"baseline_plan":TemporalEvaluationPlanRaw::from(baseline),
        "holdout_material":material,"generator_plan":null,"stage":{"kind":"plan_statement"}});
    let prepared =
        qualify_cognitive_upgrade_v1(&fleet, serde_json::from_value(input.clone())?).await?;
    input["frozen_plan"] = prepared["frozen_plan"].clone();
    let plan_digest: Digest32 = prepared["plan_sha256"].as_str().unwrap().parse()?;
    signed.payload_digest = Digest32::of_bytes(plan_digest.as_array());
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    input["generator_plan"] = serde_json::to_value(SignedLearningEvidenceV1Raw::from(signed))?;
    input["stage"] = json!({"kind":"reserve"});
    let first =
        qualify_cognitive_upgrade_v1(&fleet, serde_json::from_value(input.clone())?).await?;
    let second =
        qualify_cognitive_upgrade_v1(&fleet, serde_json::from_value(input.clone())?).await?;
    assert_eq!(first["state"], json!("awaiting_independent_collection"));
    assert_eq!(first["reservation"], second["reservation"]);
    assert_eq!(first["holdout_anchor"], second["holdout_anchor"]);
    assert_eq!(first["disposition"], json!("Recorded"));
    assert_eq!(second["disposition"], json!("IdempotentReplay"));
    let received_at = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_micros())?;
    let mut ack_request = input.clone();
    ack_request["stage"] = json!({"kind":"acknowledgement_statement","reservation":first["reservation"],"received_at_unix_micros":received_at});
    let ack_statement =
        qualify_cognitive_upgrade_v1(&fleet, serde_json::from_value(ack_request)?).await?;
    let payload = ack_statement["acknowledgement_signing_payload_hex"]
        .as_str()
        .unwrap()
        .as_bytes()
        .chunks_exact(2)
        .map(|bytes| u8::from_str_radix(std::str::from_utf8(bytes).unwrap(), 16).unwrap())
        .collect::<Vec<_>>();
    let mut ack_signed = ledger::SignedLearningEvidenceV1 {
        evidence_id: id("observed-reservation-ack"),
        principal_id: observer_principal.principal_id,
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        issued_at: received_at,
        expires_at: now + 600_000_000,
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    ack_signed.signature = observer_key.sign(&ack_signed.signing_bytes()).to_bytes();
    let mut unavailable = input.clone();
    unavailable["stage"] = json!({"kind":"observer_statement","reservation":first["reservation"],
        "acknowledgement":{"received_at_unix_micros":received_at,"observer":SignedLearningEvidenceV1Raw::from(ack_signed)},
        "collection":{"path":root.join("not-released.json"),"digest":digest("not-released").to_string()}});
    assert!(
        qualify_cognitive_upgrade_v1(&fleet, serde_json::from_value(unavailable)?)
            .await
            .is_err()
    );
    let mut tampered = input.clone();
    tampered["generator_plan"]["signature"] = json!("00".repeat(64));
    assert!(
        qualify_cognitive_upgrade_v1(&fleet, serde_json::from_value(tampered)?)
            .await
            .is_err()
    );
    let after = qualify_cognitive_upgrade_v1(&fleet, serde_json::from_value(input)?).await?;
    assert_eq!(after["holdout_anchor"], first["holdout_anchor"]);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(holdout_path)?;
    let mut reopened =
        eval::LockedFileFinalHoldoutCasStoreV1::recover(file, binding, Some(initial))?;
    assert_eq!(
        reopened
            .load(binding)?
            .context("original retained owner")?
            .journal
            .records
            .len(),
        1
    );
    Ok(())
}
