use super::*;

use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
use codex_hepta_types::{Generation, StableId};
use serde_json::{Value, json};

use crate::model_worker::{
    SequenceAttentionPolicyV3, SequenceCellHeadV3, SequenceHeadBindingV3, SequenceHeadParametersV3,
    SequenceReadFenceV3, evaluate_sequence_heads_v3,
};

fn input() -> (GraniteFeatureExpectationV5, Value) {
    let original = b"hello Granite v3".to_vec();
    let token_ids = vec![101_u32, 305, 102];
    let mask = vec![1_u8, 1, 1];
    let input_digest =
        granite97_complete_input_digest_v5(&original, &token_ids, &mask).expect("digest");
    let material = Digest32::of_bytes(b"pinned exact local manifest");
    let encoder = granite97_encoder_identity_v5(material);
    let id = FeatureSequenceIdentityV3 {
        base: SharedFeatureIdentityV2 {
            principal_id: StableId::new("principal:a").expect("principal"),
            purpose_id: StableId::new("reasoning").expect("purpose"),
            generation: Generation::new(4).expect("generation"),
            authority_epoch: 2,
            encoder_digest: encoder,
            tokenizer_digest: Digest32::of_bytes(b"tokenizer-files"),
            normalizer_digest: Digest32::of_bytes(b"identity-normalizer"),
            quantization_digest: Digest32::of_bytes(b"q24 ties even"),
            input_digest,
        },
        modality: FeatureModalityV3::Text,
        preprocessing_digest: Digest32::of_bytes(b"no truncate fp32 eager"),
        adapter_digest: Digest32::of_bytes(b"identity adapter"),
    };
    let row = vec![1 << 23; WIDTH];
    // Build the complete row-major tensor before serde_json::json! parsing.
    let values_q24 = [row.clone(), row.clone(), row].concat();
    let record = json!({
        "schema": SCHEMA,
        "model_id": MODEL_ID,
        "revision": REVISION,
        "material_digest": material.to_string(),
        "encoder_digest": encoder.to_string(),
        "tokenizer_digest": id.base.tokenizer_digest.to_string(),
        "normalizer_digest": id.base.normalizer_digest.to_string(),
        "quantization_digest": id.base.quantization_digest.to_string(),
        "preprocessing_digest": id.preprocessing_digest.to_string(),
        "adapter_digest": id.adapter_digest.to_string(),
        "source_sha256": Digest32::of_bytes(&original).to_string(),
        "input_digest": input_digest.to_string(),
        "principal_id": id.base.principal_id.as_str(),
        "purpose_id": id.base.purpose_id.as_str(),
        "generation": id.base.generation.get(),
        "authority_epoch": id.base.authority_epoch,
        "input_ids": token_ids,
        "attention_mask": mask,
        "values_q24": values_q24,
        "width": WIDTH,
        "expires_at_ms": 150,
        "encoder_forwards": 1,
        "encoder_cpu_ns": 100,
        "encoder_wall_ns": 200
    });
    (
        GraniteFeatureExpectationV5 {
            identity: id,
            source_bytes: original,
            material_digest: material,
            now_ms: 10,
            maximum_expires_at_ms: 200,
        },
        record,
    )
}

fn import(
    expected: &GraniteFeatureExpectationV5,
    record: &Value,
) -> Result<ImportedGraniteFeaturesV5, GraniteFeatureImportErrorV5> {
    import_granite97_token_v5(&serde_json::to_vec(record).expect("JSON fixture"), expected)
}

#[test]
fn python_rust_cross_language_complete_token_input_golden() {
    let (expected, record) = input();
    assert_eq!(
        expected.identity.base.input_digest.to_string(),
        "aa6a4645ede9405489a07e20faa9395eaa42545e6d6cdb49b7388576315a10ae"
    );
    let first = import(&expected, &record).expect("admit");
    let second = import(&expected, &record).expect("repeat");
    assert_eq!(
        first.snapshot.content_digest(),
        second.snapshot.content_digest()
    );
    assert_eq!(first.snapshot.shape(), (3, WIDTH));
    assert_eq!(first.snapshot.values_q24().len(), 3 * WIDTH);
    assert_eq!(
        first.complete_model_input_digest,
        expected.identity.base.input_digest
    );
    assert_eq!(first.material_digest, expected.material_digest);
    assert_eq!(first.claimed_encoder_forwards, 1);
    assert_eq!(first.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn exported_tokens_are_executable_by_existing_sequence_reader_not_pooled() {
    let (expected, record) = input();
    let imported = import(&expected, &record).expect("shared features");
    let parameters = SequenceHeadParametersV3 {
        query_q24: vec![1 << 24; WIDTH],
        key_q24: vec![0; WIDTH],
        value_q24: vec![0; WIDTH],
        local_q24: vec![0; WIDTH],
        bias_q24: 0,
    };
    let mut heads = Vec::new();
    for id in ["cell:a", "cell:b"] {
        heads.push(Arc::new(
            SequenceCellHeadV3::new(
                SequenceHeadBindingV3 {
                    cell_id: StableId::new(id).expect("cell"),
                    encoder_digest: expected.identity.base.encoder_digest,
                    tokenizer_digest: expected.identity.base.tokenizer_digest,
                    normalizer_digest: expected.identity.base.normalizer_digest,
                    quantization_digest: expected.identity.base.quantization_digest,
                    preprocessing_digest: expected.identity.preprocessing_digest,
                    adapter_digest: expected.identity.adapter_digest,
                    modality: FeatureModalityV3::Text,
                    attention: SequenceAttentionPolicyV3::Causal,
                },
                parameters.clone(),
            )
            .expect("head"),
        ));
    }
    let reader = evaluate_sequence_heads_v3(
        &SequenceReadFenceV3 {
            now_ms: expected.now_ms,
            expected_identity: expected.identity.clone(),
            expected_content_digest: imported.snapshot.content_digest(),
            maximum_attention_pairs: 12,
        },
        &imported.snapshot,
        &heads,
    )
    .expect("two Cell physical Q24 calculations");
    assert_eq!(reader.cells.len(), 2);
    assert_eq!(reader.attention_pairs, 12);
    assert_eq!(reader.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn changing_original_bytes_or_token_sequence_rejects_fake_cache_reuse() {
    let (mut expected, mut record) = input();
    expected.source_bytes.push(b'!');
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::InvalidSource)
    ));
    let (expected, _) = input();
    record["input_ids"][1] = json!(306);
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::InvalidSource)
    ));
}

#[test]
fn forged_pretrained_identity_revision_or_material_is_rejected() {
    let (expected, mut record) = input();
    record["revision"] = json!("untrusted-future-revision");
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::InvalidModel)
    ));
    let (_, mut record) = input();
    record["material_digest"] = json!(Digest32::of_bytes(b"different model").to_string());
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::InvalidModel)
    ));
    let (_, mut record) = input();
    record["tokenizer_digest"] = json!(Digest32::of_bytes(b"different tokenizer").to_string());
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::InvalidIdentity)
    ));
}

#[test]
fn stale_cross_scope_oversized_and_missing_producer_claims_fail_closed() {
    let (mut expected, record) = input();
    expected.now_ms = 150;
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::Expired)
    ));
    let (mut expected, record) = input();
    expected.identity.base.principal_id = StableId::new("principal:other").expect("principal");
    // Binding prevents cross-scope replay but remains non-authorizing.
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::InvalidIdentity)
    ));
    let (expected, _) = input();
    let (_, mut altered) = input();
    altered["encoder_forwards"] = json!(0);
    assert!(matches!(
        import(&expected, &altered),
        Err(GraniteFeatureImportErrorV5::InvalidGeometry)
    ));
    assert!(matches!(
        import_granite97_token_v5(&vec![b' '; MAX_JSON_BYTES + 1], &expected),
        Err(GraniteFeatureImportErrorV5::Malformed)
    ));
}

#[test]
fn padding_q24_limits_extra_fields_and_declared_ttl_fail() {
    let (expected, mut record) = input();
    record["attention_mask"][0] = json!(0);
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::InvalidSource)
    ));
    let (_, mut record) = input();
    record["values_q24"][0] = json!(Q24_BOUND + 1);
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::InvalidValue)
    ));
    let (_, mut record) = input();
    record["future_unreviewed_extension"] = json!(true);
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::Malformed)
    ));
    let (_, mut record) = input();
    record["expires_at_ms"] = json!(201);
    assert!(matches!(
        import(&expected, &record),
        Err(GraniteFeatureImportErrorV5::Expired)
    ));
}
