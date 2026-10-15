use super::*;

use codex_hepta_infer_core::sequence_feature_v3::FeatureModalityV3;
use codex_hepta_infer_core::sequence_feature_v3::FeatureSequenceIdentityV3;
use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde_json::Value;
use serde_json::json;

use crate::model_worker::SequenceAttentionPolicyV3;
use crate::model_worker::SequenceHeadBindingV3;
use crate::model_worker::SequenceHeadParametersV3;
use crate::model_worker::granite97_complete_input_digest_v5;
use crate::model_worker::granite97_encoder_identity_v5;

const Q: i64 = 1 << 24;

struct Fixture {
    export: Vec<u8>,
    review: Vec<u8>,
    admission: GraniteReviewAdmissionV6,
    heads: Vec<Arc<SequenceCellHeadV3>>,
}

fn fixture() -> Fixture {
    // Synthetic Q24 fixtures, intentionally NOT pretrained Granite inference.
    let source = b"hello Granite v3".to_vec();
    let ids = [101_u32, 305, 102];
    let mask = [1_u8, 1, 1];
    let model_material = Digest32::of_bytes(b"synthetic fake material");
    let encoder = granite97_encoder_identity_v5(model_material);
    let identity = FeatureSequenceIdentityV3 {
        base: SharedFeatureIdentityV2 {
            principal_id: StableId::new("principal:a").expect("principal"),
            purpose_id: StableId::new("reasoning").expect("purpose"),
            generation: Generation::new(4).expect("generation"),
            authority_epoch: 2,
            encoder_digest: encoder,
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            normalizer_digest: Digest32::of_bytes(b"normalizer"),
            quantization_digest: Digest32::of_bytes(b"quantizer"),
            input_digest: granite97_complete_input_digest_v5(&source, &ids, &mask)
                .expect("full original source"),
        },
        modality: FeatureModalityV3::Text,
        preprocessing_digest: Digest32::of_bytes(b"preprocess"),
        adapter_digest: Digest32::of_bytes(b"adapter"),
    };
    let owner = GraniteFeatureExpectationV5 {
        identity: identity.clone(),
        source_bytes: source.clone(),
        material_digest: model_material,
        now_ms: 10,
        maximum_expires_at_ms: 200,
    };

    let features = vec![Q / 2; 3 * 384];
    let mut q24_bytes = Vec::with_capacity(features.len() * 8);
    for value in &features {
        q24_bytes.extend_from_slice(&value.to_be_bytes());
    }
    let q24_digest = Digest32::of_bytes(&q24_bytes);
    let export_value = json!({
        "schema":"hepta.stem.granite97-token-export.v5",
        "model_id":"ibm-granite/granite-embedding-97m-multilingual-r2",
        "revision":"835ad14087e140460703cf0fae09f97d469d65c2",
        "material_digest":model_material.to_string(),
        "encoder_digest":encoder.to_string(),
        "tokenizer_digest":identity.base.tokenizer_digest.to_string(),
        "normalizer_digest":identity.base.normalizer_digest.to_string(),
        "quantization_digest":identity.base.quantization_digest.to_string(),
        "preprocessing_digest":identity.preprocessing_digest.to_string(),
        "adapter_digest":identity.adapter_digest.to_string(),
        "source_sha256":Digest32::of_bytes(&source).to_string(),
        "input_digest":identity.base.input_digest.to_string(),
        "principal_id":identity.base.principal_id.as_str(),
        "purpose_id":identity.base.purpose_id.as_str(),
        "generation":identity.base.generation.get(),
        "authority_epoch":identity.base.authority_epoch,
        "input_ids":ids,
        "attention_mask":mask,
        "values_q24":features,
        "width":384,
        "expires_at_ms":150,
        "encoder_forwards":1,
        "encoder_cpu_ns":101,
        "encoder_wall_ns":202
    });
    let export = serde_json::to_vec(&export_value).expect("export");
    let review_value = json!({
        "schema":REVIEW_SCHEMA,
        "source_sha256":Digest32::of_bytes(&source).to_string(),
        "input_digest":identity.base.input_digest.to_string(),
        "export_sha256":Digest32::of_bytes(&export).to_string(),
        "material_sha256":model_material.to_string(),
        "encoder_digest":encoder.to_string(),
        "feature_q24_sha256":q24_digest.to_string(),
        "producer_claimed_forwards":1,
        "producer_claimed_cpu_ns":101,
        "producer_claimed_wall_ns":202,
        "reviewer_encoder_forwards":1,
        "reviewer_encoder_cpu_ns":303,
        "reviewer_encoder_wall_ns":404,
        "exact_tensors":74,
        "model_replayed":true,
        "selected_model":false,
        "production_authorized":false,
        "authority":"DENY_ALL"
    });
    let review = serde_json::to_vec(&review_value).expect("review");
    let heads = ["cell:a", "cell:b"]
        .into_iter()
        .enumerate()
        .map(|(index, name)| {
            let mut local = vec![0; 384];
            local[0] = if index == 0 { 0 } else { Q };
            Arc::new(
                SequenceCellHeadV3::new(
                    SequenceHeadBindingV3 {
                        cell_id: StableId::new(name).expect("cell"),
                        encoder_digest: encoder,
                        tokenizer_digest: identity.base.tokenizer_digest,
                        normalizer_digest: identity.base.normalizer_digest,
                        quantization_digest: identity.base.quantization_digest,
                        preprocessing_digest: identity.preprocessing_digest,
                        adapter_digest: identity.adapter_digest,
                        modality: FeatureModalityV3::Text,
                        attention: SequenceAttentionPolicyV3::Causal,
                    },
                    SequenceHeadParametersV3 {
                        query_q24: vec![0; 384],
                        key_q24: vec![0; 384],
                        value_q24: vec![0; 384],
                        local_q24: local,
                        bias_q24: 0,
                    },
                )
                .expect("independent Cell Head"),
            )
        })
        .collect();
    Fixture {
        admission: GraniteReviewAdmissionV6 {
            feature: owner,
            admitted_export_digest: Digest32::of_bytes(&export),
            admitted_review_digest: Digest32::of_bytes(&review),
        },
        export,
        review,
        heads,
    }
}

fn execute(f: &Fixture) -> Result<ReviewedGraniteBatchV6, ReviewedGraniteErrorV6> {
    read_independently_reviewed_granite_v6(
        &f.export,
        &f.review,
        &f.admission,
        &f.heads,
        12,
    )
}

fn mutate_review(f: &mut Fixture, key: &str, value: Value) {
    let mut body: Value = serde_json::from_slice(&f.review).expect("JSON");
    body[key] = value;
    f.review = serde_json::to_vec(&body).expect("updated review");
    f.admission.admitted_review_digest = Digest32::of_bytes(&f.review);
}

#[test]
fn admitted_review_and_export_compose_with_two_real_q24_cell_heads() {
    let f = fixture();
    let result = execute(&f).expect("data-plane composition");
    assert_eq!(result, execute(&f).expect("deterministic repeat"));
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(result.reader.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(result.reader.cells.len(), 2);
    assert_eq!(result.reader.attention_pairs, 12);
    assert_ne!(
        result.reader.cells[0].score_q24,
        result.reader.cells[1].score_q24
    );
    assert_eq!(result.reviewer_encoder_forwards, 1);
    assert_eq!(result.reviewer_original_tensor_count, 74);
    assert!(!result.receipt_digest.is_zero());
    assert_eq!(f.admission.feature.source_bytes.as_slice(), b"hello Granite v3");
}

#[test]
fn independent_digest_is_required_and_modified_review_cannot_reuse_it() {
    let mut f = fixture();
    f.admission.admitted_review_digest = Digest32::ZERO;
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::MissingAdmission));
    f = fixture();
    let original = f.admission.admitted_review_digest;
    f.review.push(b' ');
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidReviewDigest));
    f.admission.admitted_review_digest = original;
}

#[test]
fn exact_producer_export_digest_is_required_before_tensor_parsing() {
    let mut f = fixture();
    f.admission.admitted_export_digest = Digest32::ZERO;
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::MissingAdmission));
    f = fixture();
    f.export.push(b' ');
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidExportDigest));
    f.export = vec![b' '; MAX_EXPORT_BYTES + 1];
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidExportDigest));
}

#[test]
fn incomplete_or_self_promoting_reviewer_cannot_open_cell_execution() {
    for (field, value) in [
        ("model_replayed", json!(false)),
        ("reviewer_encoder_forwards", json!(0)),
        ("reviewer_encoder_forwards", json!(2)),
        ("reviewer_encoder_cpu_ns", json!(0)),
        ("reviewer_encoder_wall_ns", json!(0)),
        ("exact_tensors", json!(0)),
        ("authority", json!("GRANTED")),
        ("selected_model", json!(true)),
        ("production_authorized", json!(true)),
    ] {
        let mut f = fixture();
        mutate_review(&mut f, field, value);
        assert_eq!(
            execute(&f),
            Err(ReviewedGraniteErrorV6::NoIndependentReplay),
            "must reject {field}"
        );
    }
}

#[test]
fn rehashed_forged_contents_do_not_match_external_model_source_or_q24() {
    for (field, value) in [
        ("material_sha256", json!(Digest32::of_bytes(b"other").to_string())),
        ("input_digest", json!(Digest32::of_bytes(b"other-input").to_string())),
        ("feature_q24_sha256", json!(Digest32::of_bytes(b"other-q24").to_string())),
        ("producer_claimed_cpu_ns", json!(102)),
        ("producer_claimed_wall_ns", json!(203)),
    ] {
        let mut f = fixture();
        mutate_review(&mut f, field, value);
        assert_eq!(
            execute(&f),
            Err(ReviewedGraniteErrorV6::InvalidReviewContents),
            "must reject forged field {field}"
        );
    }
}

#[test]
fn duplicate_missing_extra_or_oversized_review_fails_closed() {
    let mut f = fixture();
    f.review = br#"{"schema":"a","schema":"b"}"#.to_vec();
    f.admission.admitted_review_digest = Digest32::of_bytes(&f.review);
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidReviewSchema));
    for field in ["schema", "reviewer_encoder_cpu_ns"] {
        let mut f = fixture();
        let mut body: Value = serde_json::from_slice(&f.review).expect("review");
        body.as_object_mut().expect("object").remove(field);
        f.review = serde_json::to_vec(&body).expect("updated");
        f.admission.admitted_review_digest = Digest32::of_bytes(&f.review);
        assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidReviewSchema));
    }
    let mut f = fixture();
    mutate_review(&mut f, "unexpected_input", json!(true));
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidReviewSchema));
    let mut f = fixture();
    f.review = vec![b' '; MAX_REVIEW_BYTES + 1];
    f.admission.admitted_review_digest = Digest32::of_bytes(&f.review);
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidReviewSchema));
}

#[test]
fn parent_source_scope_model_and_ttl_cannot_be_reinterpreted() {
    let mut f = fixture();
    f.admission.feature.identity.base.principal_id =
        StableId::new("principal:other").expect("other");
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidFeature));
    let mut f = fixture();
    f.admission.feature.source_bytes.push(b'!');
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidReviewContents));
    let mut f = fixture();
    f.admission.feature.now_ms = 150;
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::InvalidFeature));
}

#[test]
fn admitted_review_does_not_bypass_reader_head_compatibility_or_budget() {
    let mut f = fixture();
    assert_eq!(
        read_independently_reviewed_granite_v6(
            &f.export, &f.review, &f.admission, &f.heads, 2
        ),
        Err(ReviewedGraniteErrorV6::ReaderRejected)
    );
    f.heads.push(Arc::clone(&f.heads[0]));
    assert_eq!(execute(&f), Err(ReviewedGraniteErrorV6::ReaderRejected));
}
