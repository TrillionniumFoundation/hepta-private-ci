//! Research-only Rust ingestion of an archived real ModernBERT Q24 feature.
//! This is one pinned public feature vector from Actions run 38902031341,
//! artifact 12068510329; source ZIP SHA256
//! dfbef09702004bae8ce111f360584b6c9c641cc1b4475b71ef2b6d68af95a77a.
//! It does not load pretrained weights, issue Final-use, or authenticate producer
//! identity. The model digest and heads here are fixtures, not deployed models.

use std::str::FromStr;
use std::sync::Arc;

use codex_hepta_infer_core::shared_feature_v2::SharedFeatureCacheV2;
use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
use codex_hepta_infer_core::shared_feature_v2::feature_content_digest_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

const ACTUAL_PUBLIC_FIT_Q24: [i64; 32] = [
    -16501532, -6373458, 16309110, -4703798, 1276234, 6019820, -11537169, 3783772,
    -1943562, 40578788, 4675449, -25092980, 20439360, -14262581, 41451036, -12258270,
    -9908741, -11855340, -35283540, 10655086, -4886386, -35993984, 24983592, -17560524,
    7399320, -1415938, -528902, -8278336, -20101038, -16129745, -11021302, -20885794,
];
const ACTUAL_PUBLIC_CONTENT_DIGEST_V2: &str =
    "fb533c3b50f785b5979142b9f05122e53a7ed523368f8abcbc69c40530aa6ce2";
const SEALED_PUBLIC_SOURCE_SHA256: &str =
    "180955ec4e74cb985851f7c1ba5ae295b91fc3b5ea2188379e8a958e557e7cc2";

fn id(raw: &str) -> StableId {
    StableId::new(raw.to_string()).expect("registered research fixture ID")
}

fn public_head(cell: &str, encoder_digest: String, invert: bool) -> GatedHeadCandidateV2 {
    GatedHeadCandidateV2 {
        cell_identity: cell.to_string(),
        encoder_digest,
        input_width: ACTUAL_PUBLIC_FIT_Q24.len(),
        output_width: 1,
        gate_q24: vec![1 << 24; ACTUAL_PUBLIC_FIT_Q24.len()],
        drive_weights_q24: vec![
            if invert { -(1 << 18) } else { 1 << 18 };
            ACTUAL_PUBLIC_FIT_Q24.len()
        ],
        prediction_weights_q24: vec![0; ACTUAL_PUBLIC_FIT_Q24.len()],
        drive_bias_q24: vec![0],
        prediction_bias_q24: vec![0],
    }
}

#[test]
fn archived_physical_q24_one_buffer_executes_distinct_scoped_cell_heads() {
    let source_digest =
        Digest32::from_str(SEALED_PUBLIC_SOURCE_SHA256).expect("historical source SHA256");
    assert_eq!(
        feature_content_digest_v2(&ACTUAL_PUBLIC_FIT_Q24).to_string(),
        ACTUAL_PUBLIC_CONTENT_DIGEST_V2
    );
    let encoder = Digest32::of_bytes(b"research-only pinned ModernBERT-base source");
    let tokenizer = Digest32::of_bytes(b"public feature tokenizer");
    let preprocessor = Digest32::of_bytes(b"train-fitted PCA32 preprocessor");
    let quantization = Digest32::of_bytes(b"public Q24 quantization");
    let one = public_head("cell.public.one", encoder.to_string(), false);
    let two = public_head("cell.public.two", encoder.to_string(), true);
    let catalog =
        GatedHeadCpuDriverV2::catalog_digest_for(&[one.clone(), two.clone()]).expect("catalog");
    let selected = ModelManifest {
        model_id: "model.public-q24.fixture".to_string(),
        model_digest: "2".repeat(64),
        weights_digest: catalog,
        tokenizer_digest: tokenizer.to_string(),
        preprocessor_digest: preprocessor.to_string(),
        quantization_digest: quantization.to_string(),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 64,
    };
    let mut driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("CPU research driver");
    let h1 = driver.register_head(one).expect("Cell one");
    let h2 = driver.register_head(two).expect("Cell two");
    let mut cache = SharedFeatureCacheV2::new(1, 4096).expect("bounded shared cache");
    let identity = SharedFeatureIdentityV2 {
        principal_id: id("principal.public.research"),
        purpose_id: id("purpose.public.head-shadow"),
        scope_id: id("scope.public.single-source"),
        generation: Generation::new(3).expect("generation"),
        authority_epoch: 2,
        encoder_digest: encoder,
        tokenizer_digest: tokenizer,
        preprocessor_digest: preprocessor,
        normalizer_digest: Digest32::of_bytes(b"frozen train-fitted scaling"),
        quantization_digest: quantization,
        source_frontier_digest: source_digest,
        input_digest: Digest32::of_bytes(b"public fit first case exact order"),
    };
    let source = cache
        .insert(
            1,
            identity,
            1000,
            Arc::from(ACTUAL_PUBLIC_FIT_Q24.to_vec()),
        )
        .expect("one Q24 feature allocation");
    assert_eq!(cache.resident_bytes(), 32 * 8);

    let request = |cell: &str, request_id: &str, head_digest: String| {
        let mut item = SharedNeuronFeatureRequestV2 {
            authorization: WorkerRequest {
                request_id: request_id.to_string(),
                reservation_id: format!("reservation.{request_id}"),
                model_digest: selected.model_digest.clone(),
                payload_digest: "0".repeat(64),
                maximum_tokens: 1,
                deadline_ms: 900,
                lease_payload_digest: "0".repeat(64),
                reservation_model_digest: selected.model_digest.clone(),
                reservation_maximum_tokens: 1,
                cancelled: false,
            },
            principal_id: id("principal.public.research"),
            purpose_id: id("purpose.public.head-shadow"),
            scope_id: id("scope.public.single-source"),
            cell_id: id(cell),
            snapshot: Arc::clone(&source),
            head_digest,
            weights_digest: selected.weights_digest.clone(),
            expected_output_width: 1,
        };
        let digest = canonical_shared_neuron_payload_digest_v2(&item).expect("V2 payload");
        item.authorization.payload_digest = digest.clone();
        item.authorization.lease_payload_digest = digest;
        item
    };
    let r1 = request("cell.public.one", "req.public.one", h1);
    let r2 = request("cell.public.two", "req.public.two", h2);
    assert!(Arc::ptr_eq(&r1.snapshot.features_q24, &r2.snapshot.features_q24));

    let grant = ResourceGrant {
        grant_id: "grant.public.research".to_string(),
        authority_epoch: 2,
        generation: 3,
        expires_at_ms: 1000,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 2,
        maximum_memory_bytes: 8192,
        semantic_digest: "1".repeat(64),
    };
    let mut worker = InferenceWorker::new(
        1,
        "worker.public.research".to_string(),
        3,
        grant,
        driver,
    )
    .expect("research worker");
    worker.load_model(1, selected).expect("frozen research bundle");
    let observed = worker
        .run_shared_neuron_features_batch_v2(100, "model.public-q24.fixture", vec![r1, r2])
        .expect("two distinct Cell outputs");
    assert_eq!(observed.len(), 2);
    assert_eq!(observed[0].status, ExecutionStatus::Succeeded);
    assert_eq!(observed[1].status, ExecutionStatus::Succeeded);
    // Independent integer golden, computed from sum(real_Q24_features)/64.
    assert_eq!(observed[0].drive_q24, vec![-1_702_365]);
    assert_eq!(observed[1].drive_q24, vec![1_702_365]);
    assert_eq!(observed[0].prediction_q24, vec![0]);
    assert_eq!(observed[1].prediction_q24, vec![0]);
    assert_ne!(observed[0].observation_digest, observed[1].observation_digest);
    assert!(!observed[0].authority.grants_any());
    assert!(!observed[1].authority.grants_any());
    assert_eq!(worker.driver.batch_calls(), 1);
}
