//! Controlled external NDU issuer and nonexecuting negative profile.
use super::native_memory_process_fixture::pin;
use super::native_memory_process_fixture::retain;
use anyhow::Result;
use codex_hepta_agentd::*;
use codex_hepta_contracts::*;
use codex_hepta_ndu::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

pub fn sign(binding: FinalUseBinding, label: &str, now: u64) -> Result<SignedFinalUseGrant> {
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "process.ndu.issuer".into(),
        authority_epoch: 11,
        grant_id: label.into(),
        nonce: *d(label).as_array(),
        binding,
        not_before_unix_ms: now - 1000,
        expires_at_unix_ms: now + 240_000,
    };
    let signature = SigningKey::from_bytes(&[117; 32])
        .sign(&grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    Ok(SignedFinalUseGrant { grant, signature })
}

pub fn feed(revision: u64, revoked: &[String], now: u64) -> Result<SignedFinalUseRevocationUpdate> {
    let update = FinalUseRevocationUpdate::new(
        "process.ndu.feed".into(),
        FinalUseRevocations {
            authority_epoch: 11,
            revision,
            revoked_grant_ids: revoked.iter().cloned().collect(),
        },
        now - 1000,
        now + 240_000,
    );
    let signature = SigningKey::from_bytes(&[118; 32])
        .sign(&update.signing_bytes()?)
        .to_bytes()
        .to_vec();
    Ok(SignedFinalUseRevocationUpdate { update, signature })
}

pub fn prepare_ndu(
    home: &Path,
    identity: &AgentdIdentity,
    objective: Digest32,
    now: u64,
) -> Result<Value> {
    let root = home.join("ndu");
    let authority_root = home.join("ndu-authority");
    for path in [&root, &authority_root] {
        std::fs::create_dir(path)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    let signed_feed = feed(/*revision*/ 2, &[], now)?;
    let authority = FinalUseAuthority::open_state_dir(
        &authority_root,
        "process.ndu.issuer".into(),
        SigningKey::from_bytes(&[117; 32])
            .verifying_key()
            .to_bytes(),
        feed(/*revision*/ 1, &[], now)?.update.head,
    )?;
    let policy = NduProductionPolicyV1 {
        utility_profile: UtilityProfile {
            profile_id: id("process.policy"),
            axis_registry_digest: d("axes"),
            normalization_manifest_digest: d("normalization"),
            dimensions: vec![(id("success"), AxisDirection::Maximize)],
            risk_ceilings: vec![],
            resource_ceilings: vec![],
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("memory")],
            },
        },
        evaluation_policy: EvaluationPolicyV1 {
            policy_id: id("process.evaluation"),
            utility_rules: vec![AxisAggregationRule {
                axis: id("success"),
                operator: AggregationOperator::Sum,
            }],
            risk_rules: vec![],
            resource_rules: vec![],
            uncertainty_rules: vec![AxisAggregationRule {
                axis: id("success"),
                operator: AggregationOperator::Maximum,
            }],
            pareto_absolute_tolerances: vec![AxisValue {
                axis: id("success"),
                value: FixedQ32::ZERO,
            }],
        },
        scalarization: None,
    };
    let mut owner = NduAuthenticatedOwnerV1::open(
        &root,
        authority,
        NduOwnerContextV1 {
            principal_id: id(identity.agent_id.as_str()),
            owner_id: id("process.ndu"),
            host_generation: 2,
            principal_scope_digest: d("principal"),
            fence_digest: d("ndu fence"),
            revocation_frontier_digest: d("ndu revocation frontier"),
        },
        policy,
    )?;
    let subject = native_memory_subject_digest_v1(&id(identity.agent_id.as_str()));
    for (label, mutation) in [
        (
            "process.append",
            NduOwnerMutationV1::AppendProjection {
                kind: NduProjectionKindV1::Preference,
                identity_digest: d("append"),
                objective_digest: objective,
                subject_digest: subject,
                projection_digest: d("selected projection"),
            },
        ),
        (
            "process.select",
            NduOwnerMutationV1::SelectProjection {
                identity_digest: d("select"),
                objective_digest: objective,
                subject_digest: subject,
                projection_digest: d("selected projection"),
            },
        ),
    ] {
        owner.apply_mutation(
            &sign(owner.final_use_binding(&mutation)?, label, now)?,
            mutation,
        )?;
    }
    drop(owner);
    std::fs::set_permissions(
        root.join("projection.journal"),
        std::fs::Permissions::from_mode(0o600),
    )?;
    retain(&home.join("ndu-feed.json"), &signed_feed)?;
    let policy_json = json!({"profile_id":"process.policy","axis_registry_digest":d("axes").to_string(),"normalization_manifest_digest":d("normalization").to_string(),
        "dimensions":[["success","maximize"]],"risk_ceilings":[],"resource_ceilings":[],"required_organs":["memory"],"evaluation_id":"process.evaluation",
        "utility_rules":[["success","sum"]],"risk_rules":[],"resource_rules":[],"uncertainty_rules":[["success","maximum"]],"pareto_tolerances_q32":[["success",0]],"scalarization":null});
    Ok(
        json!({"root":root,"journal_sha256":pin(&root.join("projection.journal"))?["sha256"],"authority_state":authority_root,
        "authority_snapshot_sha256":pin(&authority_root.join("authority.json"))?["sha256"],"authority_claims_sha256":pin(&authority_root.join("authority.claims"))?["sha256"],
        "signer_id":"process.ndu.issuer","verifying_key":SigningKey::from_bytes(&[117;32]).verifying_key().to_bytes(),"feed":pin(&home.join("ndu-feed.json"))?,
        "feed_distributor_id":"process.ndu.feed","feed_verifying_key":SigningKey::from_bytes(&[118;32]).verifying_key().to_bytes(),"owner_id":"process.ndu",
        "principal_scope_digest":d("principal").to_string(),"fence_digest":d("ndu fence").to_string(),"revocation_frontier_digest":d("ndu revocation frontier").to_string(),"policy":policy_json}),
    )
}

pub fn shadow(home: &Path) -> Value {
    json!({"cell_id":"memory.current.process","journal":home.join("memory-journal"),"witness":home.join("memory-witness"),"recover":false,"max_records":8,
        "sparse":{"normalization_digest":d("process sparse normalization").to_string(),"top_k":1,"temporal_decay_q24":1<<23,"inhibition_gain_q24":1<<24,
            "inhibition":[],"activity_decay_q24":0,"target_activity_q24":1<<21,"threshold_rate_q24":1<<21,"threshold_min_q24":-(1<<24),"threshold_max_q24":1<<24,"eligibility_decay_q24":1<<23},
        "limits":{"p95_latency_micros":120_000_000,"p99_latency_micros":120_000_000,"transient_allocation_bytes":4294967296_u64,"checkpoint_bytes":1048576,"write_amplification_ppm":4_000_000}})
}

pub fn stub_model(home: &Path) -> NativeMemoryModelConfigV1 {
    let base = d("unexecuted base").to_string();
    let adapter = d("unexecuted adapter").to_string();
    let system = "Answer using stored memory in the specified scope. Return only the value. If unknown, say 'unknown'. Do not cite sources.";
    NativeMemoryModelConfigV1 {
        python: "/usr/bin/python3".into(),
        repo: home.into(),
        model: home.join("unexecuted-model"),
        checkpoint: home.join("unexecuted-checkpoint"),
        receipt_directory: home.join("execution"),
        scope: "unexecuted-process-negative".into(),
        model_id: "memory.unexecuted".into(),
        config_id: "memory.process.negative".into(),
        generation: 1,
        rank: 8,
        seed: 24031,
        output_width: 5,
        timeout_millis: 120_000,
        pins: NativeMemoryPinsV1 {
            manifest_sha256: d("unexecuted manifest").to_string(),
            base_identity: base.clone(),
            adapter_sha256: adapter.clone(),
            weights_digest: Digest32::of_parts(&[base.as_bytes(), adapter.as_bytes()]).to_string(),
            tokenizer_digest: d("unexecuted tokenizer").to_string(),
            preprocessor_digest: d(system).to_string(),
            quantization_digest: d("hepta.memory-cell.cpu-float32-unquantized.v1").to_string(),
            runtime_digest: d("unexecuted runtime").to_string(),
            device_digest: d("unexecuted device").to_string(),
            worker_sha256: d("unexecuted worker").to_string(),
            launcher_sha256: d("unexecuted launcher").to_string(),
        },
    }
}
