use super::*;
use serde_json::Value;
use serde_json::json;

fn wire() -> Value {
    let policy = RetrievalPolicyV1 {
        policy_id: id("policy:wire-test".to_string()).expect("id"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 512,
        }],
        maximum_results: 16,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    };
    let d = Digest32::of_bytes(b"codec fixture only").to_string();
    json!({
        "schema": "hepta.agentd.retrieval-context-json.v1",
        "generation_vector": {
            "scope_id": "scope:codec", "purpose_id": "purpose:recall",
            "memory_ledger_frontier": 0, "knowledge_fact_frontier": 0,
            "tombstone_frontier": 0, "source_ledger_frontier": 0,
            "knowledge_graph_generation": 1, "compact_checkpoint_generation": 1,
            "prompt_registry_revision": 1, "retrieval_profile_digest": policy.digest().to_string(),
            "encoder_preprocessor_digest": d, "authority_epoch": 1,
            "model_digest": d, "tokenizer_digest": d, "template_digest": d,
            "tool_schema_digest": d
        },
        "objective_digest": d, "approved_context_digest": d, "cue_profile_digest": d,
        "retrieval_policy": {
            "policy_id": "policy:wire-test",
            "channel_weights": [{"channel":0, "weight_q32":4294967296_u64, "maximum_candidates":512}],
            "maximum_results":16, "minimum_total_score_q32":0,
            "maximum_ood_q32":4294967296_u64, "minimum_distinct_channels":1,
            "abstain_on_contradiction":true
        },
        "dynamics_policy": {
            "policy_id":"policy:wire-dynamics", "maximum_nodes":4096,
            "maximum_synapses":32768, "maximum_active_per_population":64,
            "maximum_active_nodes":448, "maximum_settling_steps":4,
            "maximum_graph_hops":2, "maximum_activation_paths":64,
            "leak_q32":1073741824, "lateral_inhibition_q32":67108864,
            "minimum_activation_q32":1, "contradiction_forces_abstention":true
        },
        "engram": {"generation_digest":d, "nodes":[], "synapses":[]}
    })
}

#[test]
fn empty_projection_preserves_full_generation_identity() {
    let context = decode(&serde_json::to_vec(&wire()).expect("json")).expect("context");
    assert_eq!(
        context.engram_snapshot.generation_vector_digest,
        context.generation_vector.digest()
    );
    context.validate().expect("context validation");
}

#[test]
fn context_rejects_duplicate_top_level_and_nested_fields() {
    let text = serde_json::to_string(&wire()).expect("json");
    let top = text.replacen('{', "{\"schema\":\"duplicate\",", 1);
    assert!(decode(top.as_bytes()).is_err());
    let nested = text.replace(
        "\"authority_epoch\":1",
        "\"authority_epoch\":1,\"authority_epoch\":1",
    );
    assert_ne!(nested, text);
    assert!(decode(nested.as_bytes()).is_err());
}

#[test]
fn every_context_layer_rejects_unknown_fields() {
    for path in [
        "",
        "/generation_vector",
        "/retrieval_policy",
        "/dynamics_policy",
        "/engram",
    ] {
        let mut value = wire();
        value
            .pointer_mut(path)
            .expect("path")
            .as_object_mut()
            .expect("object")
            .insert("authority_override".to_string(), json!(true));
        assert!(
            decode(&serde_json::to_vec(&value).expect("json")).is_err(),
            "{path}"
        );
    }
}

#[test]
fn integer_fields_reject_booleans_fractions_negative_and_overflow() {
    for invalid in [
        json!(true),
        json!(1.5),
        json!(-1),
        json!(18446744073709551616.0_f64),
    ] {
        let mut value = wire();
        value["generation_vector"]["authority_epoch"] = invalid;
        assert!(decode(&serde_json::to_vec(&value).expect("json")).is_err());
    }
}

#[test]
fn policy_drift_unknown_channels_and_zero_epoch_fail_closed() {
    for (path, replacement) in [
        ("/retrieval_policy/maximum_results", json!(15)),
        ("/retrieval_policy/channel_weights/0/channel", json!(8)),
        ("/generation_vector/authority_epoch", json!(0)),
        ("/generation_vector/knowledge_graph_generation", json!(0)),
        ("/dynamics_policy/maximum_settling_steps", json!(5)),
        ("/retrieval_policy/maximum_ood_q32", json!(4294967297_u64)),
    ] {
        let mut value = wire();
        *value.pointer_mut(path).expect("path") = replacement;
        assert!(
            decode(&serde_json::to_vec(&value).expect("json")).is_err(),
            "{path}"
        );
    }
}

#[test]
fn nodes_are_bound_to_vector_and_duplicate_support_is_rejected() {
    let mut value = wire();
    let node = json!({"node_id":"node:1", "population":2,
        "support":[{"record_id":"memory:1", "record_revision":1}],
        "threshold_q32":0, "confidence_q32":4294967296_u64});
    value["engram"]["nodes"] = json!([node]);
    let context = decode(&serde_json::to_vec(&value).expect("json")).expect("node");
    assert_eq!(
        context.engram_snapshot.nodes[0].generation_vector_digest,
        context.generation_vector.digest()
    );
    let support = value["engram"]["nodes"][0]["support"][0].clone();
    value["engram"]["nodes"][0]["support"] = json!([support, support]);
    assert!(decode(&serde_json::to_vec(&value).expect("json")).is_err());
}

#[test]
fn oversized_and_noncanonical_payloads_are_rejected() {
    assert!(decode(&vec![b' '; MAX_CONTEXT_BYTES + 1]).is_err());
    assert!(decode(b"").is_err());
    let mut value = wire();
    value["generation_vector"]["model_digest"] = json!("A".repeat(64));
    assert!(decode(&serde_json::to_vec(&value).expect("json")).is_err());
}
