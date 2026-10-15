use super::*;

use crate::model_worker::granite97_complete_input_digest_v5;
use crate::model_worker::granite97_encoder_identity_v5;
use serde_json::Value;
use serde_json::json;

const Q24: i64 = 1 << 24;

struct Fixture {
    source: Vec<u8>,
    export: Vec<u8>,
    review: Vec<u8>,
    admission: Vec<u8>,
}

fn fixture() -> Fixture {
    // Synthetic V5 and V6 JSON prove protocol mechanics only; NO weights
    // or physical pretrained forward are executed by these tests.
    let source = b"hello Granite v3".to_vec();
    let token_ids = [101_u32, 305, 102];
    let mask = [1_u8, 1, 1];
    let material = Digest32::of_bytes(b"synthetic original");
    let encoder = granite97_encoder_identity_v5(material);
    let input_digest = granite97_complete_input_digest_v5(&source, &token_ids, &mask)
        .expect("original, complete ordered tokens");
    let tokenizer = Digest32::of_bytes(b"tokenizer");
    let normalizer = Digest32::of_bytes(b"normalizer");
    let quantizer = Digest32::of_bytes(b"q24");
    let preprocessing = Digest32::of_bytes(b"preprocessing");
    let adapter = Digest32::of_bytes(b"adapter");
    let values = vec![Q24 / 2; 3 * STEM_WIDTH];
    let q24_be = values
        .iter()
        .flat_map(|value| value.to_be_bytes())
        .collect::<Vec<_>>();
    let export = serde_json::to_vec(&json!({
        "schema": "hepta.stem.granite97-token-export.v5",
        "model_id": "ibm-granite/granite-embedding-97m-multilingual-r2",
        "revision": "835ad14087e140460703cf0fae09f97d469d65c2",
        "material_digest": material.to_string(),
        "encoder_digest": encoder.to_string(),
        "tokenizer_digest": tokenizer.to_string(),
        "normalizer_digest": normalizer.to_string(),
        "quantization_digest": quantizer.to_string(),
        "preprocessing_digest": preprocessing.to_string(),
        "adapter_digest": adapter.to_string(),
        "source_sha256": Digest32::of_bytes(&source).to_string(),
        "input_digest": input_digest.to_string(),
        "principal_id": "principal:a",
        "purpose_id": "reasoning",
        "generation": 7,
        "authority_epoch": 2,
        "input_ids": token_ids,
        "attention_mask": mask,
        "values_q24": values,
        "width": STEM_WIDTH,
        "expires_at_ms": 150,
        "encoder_forwards": 1,
        "encoder_cpu_ns": 101,
        "encoder_wall_ns": 202
    }))
    .expect("synthetic encoder fixture");
    let review = serde_json::to_vec(&json!({
        "schema": "hepta.stem.granite97-independent-physical-review.v1",
        "source_sha256": Digest32::of_bytes(&source).to_string(),
        "input_digest": input_digest.to_string(),
        "export_sha256": Digest32::of_bytes(&export).to_string(),
        "material_sha256": material.to_string(),
        "encoder_digest": encoder.to_string(),
        "feature_q24_sha256": Digest32::of_bytes(&q24_be).to_string(),
        "producer_claimed_forwards": 1,
        "producer_claimed_cpu_ns": 101,
        "producer_claimed_wall_ns": 202,
        "reviewer_encoder_forwards": 1,
        "reviewer_encoder_cpu_ns": 303,
        "reviewer_encoder_wall_ns": 404,
        "exact_tensors": 74,
        "model_replayed": true,
        "selected_model": false,
        "production_authorized": false,
        "authority": "DENY_ALL"
    }))
    .expect("synthetic review fixture");
    let local_a = vec![0_i64; STEM_WIDTH];
    let mut local_b = vec![0_i64; STEM_WIDTH];
    local_b[0] = Q24;
    let heads = [("cell:a", local_a), ("cell:b", local_b)]
        .into_iter()
        .map(|(id, local)| {
            json!({
                "cell_id": id,
                "attention": "causal",
                "query_q24": vec![0_i64; STEM_WIDTH],
                "key_q24": vec![0_i64; STEM_WIDTH],
                "value_q24": vec![0_i64; STEM_WIDTH],
                "local_q24": local,
                "bias_q24": 0
            })
        })
        .collect::<Vec<_>>();
    let admission = serde_json::to_vec(&json!({
        "schema": "hepta.stem.granite-v3-local-admission.v7",
        "principal_id": "principal:a",
        "purpose_id": "reasoning",
        "generation": 7,
        "authority_epoch": 2,
        "material_digest": material.to_string(),
        "source_digest": Digest32::of_bytes(&source).to_string(),
        "complete_input_digest": input_digest.to_string(),
        "tokenizer_digest": tokenizer.to_string(),
        "normalizer_digest": normalizer.to_string(),
        "quantization_digest": quantizer.to_string(),
        "preprocessing_digest": preprocessing.to_string(),
        "adapter_digest": adapter.to_string(),
        "export_bytes_digest": Digest32::of_bytes(&export).to_string(),
        "independent_review_bytes_digest": Digest32::of_bytes(&review).to_string(),
        "maximum_expires_at_ms": 200,
        "maximum_attention_pairs": 12,
        "heads": heads
    }))
    .expect("independent admission fixture");
    Fixture {
        source,
        export,
        review,
        admission,
    }
}

fn evaluate(f: &Fixture, now_ms: u64) -> Result<GraniteShadowSummaryV7, ShadowAdmissionErrorV7> {
    read_shadow_granite_v3_v7(&f.admission, &f.source, &f.export, &f.review, now_ms)
}

fn rewrite_admission(f: &mut Fixture, key: &str, value: Value) {
    let mut document: Value = serde_json::from_slice(&f.admission).expect("admission JSON");
    document[key] = value;
    f.admission = serde_json::to_vec(&document).expect("admission rewrite");
}

#[test]
fn verified_bytes_feed_two_independent_heads_with_source_free_receipt() {
    let f = fixture();
    let result = evaluate(&f, 10).expect("data-plane only");
    assert_eq!(result, evaluate(&f, 10).expect("idempotent Q24 calculations"));
    assert_eq!(result.schema, "hepta.stem.granite-v3-local-shadow-result.v7");
    assert_eq!(result.authority, "DENY_ALL");
    assert!(!result.model_selected && !result.production_authorized);
    assert_eq!(result.claimed_reviewer_encoder_forwards, 1);
    assert_eq!(result.claimed_original_weight_tensors, 74);
    assert_eq!(result.actual_reader_attention_pairs, 12);
    assert_eq!(result.cells.len(), 2);
    assert_eq!(result.cells[0].score_q24, 0);
    assert_eq!(result.cells[1].score_q24, Q24 / 4);
    assert_eq!(result.q24_payload_bytes, 3 * (STEM_WIDTH * 8 + 1 + 12));
    assert_ne!(result.cells[0].head_digest, result.cells[1].head_digest);
    assert_eq!(result.original_source_digest, Digest32::of_bytes(&f.source).to_string());
    assert_eq!(result.admission_bytes_digest, Digest32::of_bytes(&f.admission).to_string());
    assert!(!result.gate_receipt_digest.is_empty());
    let output = serde_json::to_value(&result).expect("redacted response");
    assert!(output.get("source_bytes").is_none());
    assert!(output.get("values_q24").is_none());
}

#[test]
fn owner_original_source_and_exact_file_digests_are_independently_fenced() {
    let mut f = fixture();
    f.source.extend_from_slice(b" changed");
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidSource));
    let mut f = fixture();
    rewrite_admission(&mut f, "export_bytes_digest", json!(Digest32::of_bytes(b"x").to_string()));
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidReview));
    let mut f = fixture();
    rewrite_admission(
        &mut f,
        "independent_review_bytes_digest",
        json!(Digest32::of_bytes(b"wrong review").to_string()),
    );
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidReview));
    let mut f = fixture();
    f.export.push(b' ');
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidReview));
}

#[test]
fn scope_generation_model_and_expiry_do_not_leak_between_calls() {
    let mut f = fixture();
    rewrite_admission(&mut f, "principal_id", json!("principal:another"));
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidReview));
    let mut f = fixture();
    rewrite_admission(&mut f, "generation", json!(8));
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidReview));
    let mut f = fixture();
    rewrite_admission(&mut f, "material_digest", json!(Digest32::of_bytes(b"other").to_string()));
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidReview));
    assert_eq!(evaluate(&fixture(), 150), Err(ShadowAdmissionErrorV7::InvalidReview));
    assert_eq!(evaluate(&fixture(), 200), Err(ShadowAdmissionErrorV7::MalformedAdmission));
}

#[test]
fn altered_heads_and_resource_budgets_are_not_admitted() {
    let mut f = fixture();
    let mut config: Value = serde_json::from_slice(&f.admission).expect("admission");
    config["heads"][0]["query_q24"] = json!([0]);
    f.admission = serde_json::to_vec(&config).expect("serialize");
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidHead));
    let mut f = fixture();
    rewrite_admission(&mut f, "maximum_attention_pairs", json!(2));
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidReview));
    let mut f = fixture();
    rewrite_admission(&mut f, "maximum_attention_pairs", json!(2_000_001));
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::MalformedAdmission));
    let mut f = fixture();
    let mut config: Value = serde_json::from_slice(&f.admission).expect("admission");
    config["heads"][1]["cell_id"] = json!("cell:a");
    f.admission = serde_json::to_vec(&config).expect("serialize");
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::InvalidReview));
}

#[test]
fn untrusted_structure_missing_fields_and_oversized_admission_fail_closed() {
    let mut f = fixture();
    let mut config: Value = serde_json::from_slice(&f.admission).expect("admission");
    config.as_object_mut().expect("object").remove("purpose_id");
    f.admission = serde_json::to_vec(&config).expect("serialize");
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::MalformedAdmission));
    let mut f = fixture();
    rewrite_admission(&mut f, "production_authorized", json!(true));
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::MalformedAdmission));
    let mut f = fixture();
    f.admission = vec![b' '; MAX_ADMISSION_BYTES + 1];
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::MalformedAdmission));
    let mut f = fixture();
    let mut config: Value = serde_json::from_slice(&f.admission).expect("admission");
    let repeated = config["heads"][0].clone();
    config["heads"] = json!(vec![repeated; MAX_HEADS + 1]);
    f.admission = serde_json::to_vec(&config).expect("serialize");
    assert_eq!(evaluate(&f, 10), Err(ShadowAdmissionErrorV7::MalformedAdmission));
}

#[test]
fn changed_owner_resource_budget_binds_a_new_result_receipt() {
    let a = fixture();
    let original = evaluate(&a, 10).expect("original");
    let mut b = fixture();
    rewrite_admission(&mut b, "maximum_attention_pairs", json!(24));
    let changed = evaluate(&b, 10).expect("larger allowed budget");
    assert_eq!(original.cells, changed.cells);
    assert_ne!(original.admission_bytes_digest, changed.admission_bytes_digest);
    assert_ne!(original.gate_receipt_digest, changed.gate_receipt_digest);
}
