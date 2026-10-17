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
    -16501532, -6373458, 16309110, -4703798, 1276234, 6019820, -11537169, 3783772, -1943562,
    40578788, 4675449, -25092980, 20439360, -14262581, 41451036, -12258270, -9908741, -11855340,
    -35283540, 10655086, -4886386, -35993984, 24983592, -17560524, 7399320, -1415938, -528902,
    -8278336, -20101038, -16129745, -11021302, -20885794,
];
const ACTUAL_PUBLIC_CONTENT_DIGEST_V2: &str =
    "fb533c3b50f785b5979142b9f05122e53a7ed523368f8abcbc69c40530aa6ce2";
const SEALED_PUBLIC_SOURCE_SHA256: &str =
    "180955ec4e74cb985851f7c1ba5ae295b91fc3b5ea2188379e8a958e557e7cc2";

fn id(raw: &str) -> StableId {
    StableId::new(raw.to_string()).expect("registered research fixture ID")
}

fn public_head(cell: &str, encoder_digest: String, invert: bool) -> GatedHeadCandidateV2 {
    let drive_gain_q24 = if invert { -(1 << 18) } else { 1 << 18 };
    GatedHeadCandidateV2 {
        cell_identity: cell.to_string(),
        encoder_digest,
        input_width: ACTUAL_PUBLIC_FIT_Q24.len(),
        output_width: 1,
        gate_q24: vec![1 << 24; ACTUAL_PUBLIC_FIT_Q24.len()],
        drive_weights_q24: vec![drive_gain_q24; ACTUAL_PUBLIC_FIT_Q24.len()],
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
        .insert(1, identity, 1000, Arc::from(ACTUAL_PUBLIC_FIT_Q24.to_vec()))
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
    assert!(Arc::ptr_eq(
        &r1.snapshot.features_q24,
        &r2.snapshot.features_q24
    ));

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
    let mut worker =
        InferenceWorker::new(1, "worker.public.research".to_string(), 3, grant, driver)
            .expect("research worker");
    worker
        .load_model(1, selected)
        .expect("frozen research bundle");
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
    assert_ne!(
        observed[0].observation_digest,
        observed[1].observation_digest
    );
    assert!(!observed[0].authority.grants_any());
    assert!(!observed[1].authority.grants_any());
    assert_eq!(worker.driver.batch_calls(), 1);
}

// FP32 AdamW seed 17, 120 steps on 64 labeled *fitting* vectors; frozen
// per-Cell linear parameters were transferred through ties-even signed Q24.
// The first official-test vector has NO label and is checked only for numeric
// parity. Independent Python integer reference: max drift 26 fit / 31
// heldout integer units over all 96 vectors, 0 Argmax disagreements.
// Source Actions run 38902031341 / artifact 12068510329, ZIP SHA256
// dfbef09702004bae8ce111f360584b6c9c641cc1b4475b71ef2b6d68af95a77a.
// Research-only: selected model identities are test fixtures, not signatures.
#[rustfmt::skip]
const LEARNED_PUBLIC_WEIGHT_Q24: [[i64; 32]; 4] = [
    [
        -8893105, -9627046, 12667690, 8549526, 8657422, -8893141, -12317646, -4636322,
        -6319398, 7723222, -6217154, 2707033, 3192838, -5566660, 698846, -1964874,
        -1563603, -5457903, 3550796, -4416028, 2899214, -5938026, 2185042, 3488938,
        1252959, 7643586, 6779610, -3446359, 2994719, -2621464, -3070386, 4424736,
    ],
    [
        10794345, 10895488, 734735, -9293038, 12259798, 8791786, 11743810, 4356312,
        -3207992, -10312869, 11435165, -5846662, -3039820, -803627, 5319038, -1581017,
        -4044833, -7699458, -2215195, 1199386, 1213020, 2442772, -52483, 8451334,
        5755004, -3729238, 2125860, -3268172, -2769721, 2028122, -3478296, -7020490,
    ],
    [
        -13024143, 9899015, -14969672, 714988, -9153259, -11186866, 6256372, -4308479,
        3045822, -11478848, -2219104, 5484080, -1866238, -2844744, -3708300, -1616317,
        -3324395, 5186978, -1200832, -2242162, -2627192, -5529913, 411000, -5549374,
        5035578, -3050625, -3236312, -348165, -3072008, 2634374, 1729316, -646327,
    ],
    [
        9430863, -14428275, -9467256, 10456051, -12987497, 8142714, 2424297, -10648128,
        7980678, -9304066, -6234830, -5741190, -8851374, 3453729, -3554093, -3219616,
        -758706, 6778770, 818296, 4086556, -3225428, -3767464, -4916916, -7812159,
        -6613930, -2248379, -8798336, 805324, -1261479, 6305336, 5288736, -1141666,
    ],
];

const LEARNED_PUBLIC_BIASES_Q24: [i64; 4] = [-5497860, -3312271, 620290, -1430858];
const LEARNED_PUBLIC_HEAD_DIGESTS: [&str; 4] = [
    "c99ba1a41cfd661c193f72842527efb65a1676ca246f4d20eea6f58c5715045e",
    "6ef27bdc2a7ef3001f43dc0b017af37a9cccd4bcd25958406ab9d3c1c972cafd",
    "04dd5b16e79621c31f1610bc2611376418af4827c9679b9a82752388e815c322",
    "8afe057946437e905086d9af0ae110d9103512c72a77c689c79c53eb712d08c8",
];
const LEARNED_PUBLIC_CATALOG_DIGEST: &str =
    "147f1c8d6453ea51001e873b7dd93e37254f1e8b53aae3c103aa3441245f3640";
#[rustfmt::skip]
const LEARNED_PUBLIC_FEATURE_0_Q24: [i64; 32] = [
    -16501532, -6373458, 16309110, -4703798, 1276234, 6019820, -11537169, 3783772,
    -1943562, 40578788, 4675449, -25092980, 20439360, -14262581, 41451036, -12258270,
    -9908741, -11855340, -35283540, 10655086, -4886386, -35993984, 24983592, -17560524,
    7399320, -1415938, -528902, -8278336, -20101038, -16129745, -11021302, -20885794,
];
const LEARNED_PUBLIC_EXPECTED_0_Q24: [i64; 4] = [49971494, -3595119, -37822551, -59263390];

#[rustfmt::skip]
const LEARNED_PUBLIC_FEATURE_1_Q24: [i64; 32] = [
    8457029, -8912447, 7637378, 11217379, 16256650, -4031037, -3426966, 14201509,
    -3587988, 11061477, -19628982, 12209120, 10770020, 1006823, -1898668, -682906,
    -18199324, 4318266, -4318233, 11483914, -8367910, -6317092, -11763600, 14505802,
    12251177, 15970122, 10853081, -6511910, 12460683, -7022430, 3418694, -17958710,
];
const LEARNED_PUBLIC_EXPECTED_1_Q24: [i64; 4] = [43639893, -7953813, -32665379, -29422240];

#[test]
fn trained_linear_four_cell_parity_on_pinned_public_q24() {
    let encoder = Digest32::of_bytes(b"research-only pinned ModernBERT-base source");
    assert_eq!(
        encoder.to_string(),
        "7bc5015a2197d7a0ea18c10965addaf80adac220e266a95fa789223606986365"
    );
    let tokenizer = Digest32::of_bytes(b"public feature tokenizer");
    let preprocessor = Digest32::of_bytes(b"train-fitted PCA32 preprocessor");
    let quantization = Digest32::of_bytes(b"public Q24 quantization");
    let source = Digest32::from_str(SEALED_PUBLIC_SOURCE_SHA256).expect("seal");
    let mut candidates = Vec::new();
    for index in 0..4 {
        candidates.push(GatedHeadCandidateV2 {
            cell_identity: format!("cell.public.linear.{index}"),
            encoder_digest: encoder.to_string(),
            input_width: 32,
            output_width: 1,
            gate_q24: vec![1_i64 << 24; 32],
            drive_weights_q24: LEARNED_PUBLIC_WEIGHT_Q24[index].to_vec(),
            prediction_weights_q24: vec![0; 32],
            drive_bias_q24: vec![LEARNED_PUBLIC_BIASES_Q24[index]],
            prediction_bias_q24: vec![0],
        });
    }
    let catalog = GatedHeadCpuDriverV2::catalog_digest_for(&candidates)
        .expect("independent Python-bounded catalog");
    assert_eq!(catalog, LEARNED_PUBLIC_CATALOG_DIGEST);
    let selected = ModelManifest {
        model_id: "model.public.linear-research".to_string(),
        model_digest: "2".repeat(64),
        weights_digest: catalog,
        tokenizer_digest: tokenizer.to_string(),
        preprocessor_digest: preprocessor.to_string(),
        quantization_digest: quantization.to_string(),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 64,
    };
    let mut driver = GatedHeadCpuDriverV2::new(selected.clone()).expect("research driver");
    for (index, candidate) in candidates.into_iter().enumerate() {
        let digest = driver
            .register_head(candidate)
            .expect("immutable linear Cell");
        assert_eq!(digest, LEARNED_PUBLIC_HEAD_DIGESTS[index]);
    }
    // Four Cells have only 4*(32 weights + 1 bias) trainable parameters;
    // the Q24 reference catalog also stores fixed gates and zero readouts.
    assert_eq!(driver.parameter_bytes(), 392 * 8);
    let grant = ResourceGrant {
        grant_id: "grant.public.linear-research".to_string(),
        authority_epoch: 2,
        generation: 3,
        expires_at_ms: 1000,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 4,
        maximum_memory_bytes: 8192,
        semantic_digest: "1".repeat(64),
    };
    let mut worker = InferenceWorker::new(
        1,
        "worker.public.linear-research".to_string(),
        3,
        grant,
        driver,
    )
    .expect("bounded research worker");
    worker
        .load_model(1, selected.clone())
        .expect("load reference tensors");
    let mut cache = SharedFeatureCacheV2::new(2, 1024).expect("bounded cache");
    let samples: [(&str, &[i64; 32], &[i64; 4]); 2] = [
        (
            "fit:a761e5bf506a91e172492a3c023bdd9aa03e38d3e55fedcd684eaef6a6f154cf",
            &LEARNED_PUBLIC_FEATURE_0_Q24,
            &LEARNED_PUBLIC_EXPECTED_0_Q24,
        ),
        (
            "heldout:3b2d2c35297ebbcb24a83da141508eff20a7bd546deb854f04b6a19817271313",
            &LEARNED_PUBLIC_FEATURE_1_Q24,
            &LEARNED_PUBLIC_EXPECTED_1_Q24,
        ),
    ];
    for (case_number, (case_id, feature, expected)) in samples.into_iter().enumerate() {
        let identity = SharedFeatureIdentityV2 {
            principal_id: id("principal.public.research"),
            purpose_id: id("purpose.public.linear-numeric-parity"),
            scope_id: id("scope.public.pca32"),
            generation: Generation::new(3).expect("generation"),
            authority_epoch: 2,
            encoder_digest: encoder,
            tokenizer_digest: tokenizer,
            preprocessor_digest: preprocessor,
            normalizer_digest: Digest32::of_bytes(b"frozen train-fitted scaling"),
            quantization_digest: quantization,
            source_frontier_digest: source,
            input_digest: Digest32::of_bytes(case_id.as_bytes()),
        };
        let snapshot = cache
            .insert(1, identity, 900, Arc::from(feature.as_slice()))
            .expect("pinned public feature snapshot");
        let mut requests = Vec::new();
        for (index, head) in LEARNED_PUBLIC_HEAD_DIGESTS.iter().enumerate() {
            let request_id = format!("request.public.{case_number}.{index}");
            let mut item = SharedNeuronFeatureRequestV2 {
                authorization: WorkerRequest {
                    request_id: request_id.clone(),
                    reservation_id: format!("reservation.{request_id}"),
                    model_digest: selected.model_digest.clone(),
                    payload_digest: "0".repeat(64),
                    maximum_tokens: 1,
                    deadline_ms: 800,
                    lease_payload_digest: "0".repeat(64),
                    reservation_model_digest: selected.model_digest.clone(),
                    reservation_maximum_tokens: 1,
                    cancelled: false,
                },
                principal_id: id("principal.public.research"),
                purpose_id: id("purpose.public.linear-numeric-parity"),
                scope_id: id("scope.public.pca32"),
                cell_id: id(&format!("cell.public.linear.{index}")),
                snapshot: Arc::clone(&snapshot),
                head_digest: (*head).to_string(),
                weights_digest: selected.weights_digest.clone(),
                expected_output_width: 1,
            };
            let payload =
                canonical_shared_neuron_payload_digest_v2(&item).expect("bounded Cell payload");
            item.authorization.payload_digest = payload.clone();
            item.authorization.lease_payload_digest = payload;
            requests.push(item);
        }
        assert!(
            requests
                .iter()
                .all(|item| Arc::ptr_eq(&item.snapshot.features_q24, &snapshot.features_q24,))
        );
        let observed = worker
            .run_shared_neuron_features_batch_v2(100, &selected.model_id, requests)
            .expect("native Q24 multi-Cell batch");
        assert_eq!(observed.len(), 4);
        let logits: Vec<i64> = observed.iter().map(|row| row.drive_q24[0]).collect();
        assert_eq!(logits.as_slice(), expected);
        for (index, row) in observed.iter().enumerate() {
            assert_eq!(row.status, ExecutionStatus::Succeeded);
            assert_eq!(row.prediction_q24, vec![0]);
            assert_eq!(row.head_digest, LEARNED_PUBLIC_HEAD_DIGESTS[index]);
            assert_eq!(row.scope_id, id("scope.public.pca32"));
            assert!(!row.authority.grants_any());
        }
    }
    assert_eq!(cache.len(), 2);
    assert_eq!(cache.resident_bytes(), 2 * 32 * 8);
    assert_eq!(worker.driver.batch_calls(), 2);
}
