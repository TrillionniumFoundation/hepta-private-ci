//! Syntactically complete, deliberately unsigned raw input. Used only to
//! exercise rejection before opening any material; never a qualification.

use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use std::path::Path;

pub fn untrusted_descriptor(root: &Path, identity: &AgentdIdentity) -> Value {
    let digest = Digest32::of_bytes(b"untrusted-descriptor-boundary-input").to_string();
    let principal = json!({"principal_id":"untrusted", "credential_chain_digest":digest,
        "signing_key_digest":digest, "scope_digest":digest, "authority_epoch":1,
        "authenticated_at":1, "expires_at":2});
    let evidence = json!({"evidence_id":"untrusted", "principal_id":"untrusted", "role":"generator",
        "trust_digest":digest, "scope_digest":digest, "objective_digest":digest, "authority_epoch":1,
        "issued_at":1, "expires_at":2, "payload_digest":digest, "signature":"00".repeat(64)});
    let temporal = json!({"plan_digest":digest, "evaluation_id":"untrusted", "objective_digest":digest,
        "fold":{"plan_digest":digest,"fold_id":"untrusted","training_watermark":1,"evaluation_start":2,"minimum_per_action":1},
        "ope":{"plan_digest":digest,"outcome_watermark":3,"minimum_rows":1,"minimum_ess":1,"maximum_weight":1},
        "confidence":{"plan_digest":digest,"assumptions_digest":digest,"family_alpha_ppm":1,"simultaneous_comparisons":1,"minimum_clusters":1}});
    let file = json!({"path":root.join("does-not-exist"),"digest":digest});
    json!({
        "schema":"hepta.agentd.cognitive-bootstrap.v3", "profile":"published_neural_product_qualification_v1",
        "agent_id":identity.agent_id.as_str(), "spawn_generation":identity.spawn_generation,
        "snapshot_path":root.join("does-not-exist-snapshot"), "payload_path":root.join("does-not-exist-payload"),
        "model_pin":{"payload_digest":digest,"objective_digest":digest,"dataset_digest":digest,"generation":3,
            "family_digest":digest,"execution_profile_digest":digest},
        "selected":{"registry_receipt":{"binding":digest,"head_digest":digest,"file_digest":digest,"records":0,"encoded_bytes":0},
            "manifest":{"artifact_id":"untrusted-candidate","kind":"parameters","generation":3,"predecessor_id":"untrusted-parent",
                "content_digest":digest,"objective_digest":digest,"support_digest":digest,"producer_id":"untrusted",
                "compatibility_digest":digest,"encoded_size_bytes":1}},
        "source_manifest":{"artifact_id":"untrusted-candidate","kind":"parameters","generation":3,"provenance_mode":"dataset_derived",
            "source_dataset_digests":[digest],"lineage_digests":[digest],"predecessor_ids":["untrusted-parent"],"rollback_predecessor":"untrusted-parent",
            "bytes_digest":digest,"encoded_size_bytes":1,"training_code_digest":digest,"runtime_tuple_digest":digest,
            "device_profile_digest":digest,"objective_class_digest":digest,"compatibility_digest":digest,"schema_profile_digest":digest,
            "normalization_digest":digest,"producer_id":"untrusted","created_at":1,"expires_at":2},
        "current":{"root":root.join("does-not-exist-current"),
            "trust":{"registry_id":"untrusted","withdrawal_scope_digest":digest,"minimum_registry_generation":1,
                "genesis_predecessor_head_digest":digest,"minimum_authority_epoch":1,"writer_signers":[],"head_signers":[]},
            "required_current_head":{"withdrawal_scope_digest":digest,"binding":digest,"registry_id":"untrusted","generation":1,
                "head_digest":digest,"predecessor_head_digest":digest,"authority_epoch":1,"signer_id":"untrusted",
                "signing_key_digest":digest,"issued_at":1,"expires_at":2,"signature_hex":"00".repeat(64)}},
        "policy":{"no_change_baseline_id":"untrusted-parent","no_change_baseline_digest":digest,
            "minimum_dataset_records":1,"minimum_future_window_micros":1},
        "selection_request":{"selection_id":"untrusted","predecessor_id":"untrusted-parent","predecessor_generation":2,
            "predecessor_artifact_digest":digest,"candidate_id":"untrusted-candidate","candidate_generation":3,"candidate_artifact_digest":digest},
        "frozen_plan":{"plan_id":"untrusted","claim_scope":"qualification","candidate_id":"untrusted-candidate","baseline_id":"untrusted-parent",
            "objective_digest":digest,"dataset_digest":digest,"estimand_digest":digest,"metric_contracts":[],"family_alpha_ppm":1,
            "simultaneous_comparisons":1,"folds":[],"final_holdout_window_id":"untrusted","final_holdout_digest":digest},
        "product":{"candidate_plan":temporal,"baseline_plan":temporal,"metric_sources":[],
            "context":{"generator":principal,"evaluator":principal,"retention_receipt_digests":[],"unlearning_receipt_digest":digest},
            "released_inputs":file,"holdout_material":file,"qualification_evidence":file},
        "product_candidate_binding_evidence":evidence, "metric_roles":[],
        "evaluation_evidence":{"generator_plan":evidence,"evaluator_bundle":evidence},
        "longitudinal_time":{"frozen_unix_micros":1,"windows":[],"observer":evidence},
        "dataset_receipt":{"snapshot":{"snapshot_id":"untrusted","ledger_head_digest":digest,"objective_digest":digest,
                "eligible_frontier":0,"outcome_watermark":0,"source_record_digests":[],"pending_outcomes":0,"censored_outcomes":0,"dataset_digest":digest},
            "producer":principal,"correction_cut_digest":digest,"revocation_cut_digest":digest,"inclusion_policy_digest":digest},
        "ledger":{"path":root.join("does-not-exist-ledger"),"binding":digest,"max_records":1,"anchor_sequence":0,"anchor_chain_digest":digest},
        "holdout":{"path":root.join("does-not-exist-holdout"),"binding":digest,
            "fence":{"owner_id":"untrusted","generation":1,"lease_digest":digest},
            "anchor":{"fence_generation":1,"record_count":0,"state_digest":digest}},
        "trust":{"scope_digest":digest,"objective_digest":digest,"authority_epoch":1,"signers":[]},
        "selector_evidence":evidence,
    })
}
