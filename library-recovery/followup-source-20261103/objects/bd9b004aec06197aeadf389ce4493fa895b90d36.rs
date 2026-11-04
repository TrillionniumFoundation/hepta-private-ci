//! Research-only byte-pinned real ModernBERT feature -> four native Q24 Cell heads.
//!
//! Source: GitHub Actions 38902031341, artifact 12068510329.
//! Regenerate with qualification/neuron-shared-q24/emit_public_linear_q24.py.
//! This is training-fit/heldout *numeric parity*, not heldout scoring,
//! authenticated pretrained inference, source-grant checking or NDU benefit.

use std::str::FromStr;
use std::sync::Arc;

use codex_hepta_infer_core::shared_feature_v2::SharedFeatureCacheV2;
use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

const PINNED_SOURCE_ZIP_SHA256: &str = "dfbef09702004bae8ce111f360584b6c9c641cc1b4475b71ef2b6d68af95a77a";
const SOURCE_SEAL_SHA256: &str = "180955ec4e74cb985851f7c1ba5ae295b91fc3b5ea2188379e8a958e557e7cc2";
const PINNED_ENCODER_DIGEST: &str = "7bc5015a2197d7a0ea18c10965addaf80adac220e266a95fa789223606986365";
const EXPECTED_CATALOG_DIGEST: &str = "147f1c8d6453ea51001e873b7dd93e37254f1e8b53aae3c103aa3441245f3640";
const EXPECTED_HEAD_DIGESTS: [&str; 4] = [
    "c99ba1a41cfd661c193f72842527efb65a1676ca246f4d20eea6f58c5715045e",
    "6ef27bdc2a7ef3001f43dc0b017af37a9cccd4bcd25958406ab9d3c1c972cafd",
    "04dd5b16e79621c31f1610bc2611376418af4827c9679b9a82752388e815c322",
    "8afe057946437e905086d9af0ae110d9103512c72a77c689c79c53eb712d08c8",
];

// Frozen Python-trained FP32 weights and biases rounded ties-even to signed Q24.
// Gates are fixed identity, prediction tensors are zero: one scalar logit/Cell.
const HEAD_WEIGHTS_Q24: [[i64; 32]; 4] = [
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

const HEAD_BIASES_Q24: [i64; 4] = [
    -5497860, -3312271, 620290, -1430858,
];

const PUBLIC_FIT_0_Q24: [i64; 32] = [
    -16501532, -6373458, 16309110, -4703798, 1276234, 6019820, -11537169, 3783772,
    -1943562, 40578788, 4675449, -25092980, 20439360, -14262581, 41451036, -12258270,
    -9908741, -11855340, -35283540, 10655086, -4886386, -35993984, 24983592, -17560524,
    7399320, -1415938, -528902, -8278336, -20101038, -16129745, -11021302, -20885794,
];

const PUBLIC_HELDOUT_0_Q24: [i64; 32] = [
    8457029, -8912447, 7637378, 11217379, 16256650, -4031037, -3426966, 14201509,
    -3587988, 11061477, -19628982, 12209120, 10770020, 1006823, -1898668, -682906,
    -18199324, 4318266, -4318233, 11483914, -8367910, -6317092, -11763600, 14505802,
    12251177, 15970122, 10853081, -6511910, 12460683, -7022430, 3418694, -17958710,
];

const EXPECTED_FIT_0_LOGITS_Q24: [i64; 4] = [
    49971494, -3595119, -37822551, -59263390,
];

const EXPECTED_HELDOUT_0_LOGITS_Q24: [i64; 4] = [
    43639893, -7953813, -32665379, -29422240,
];

fn stable(raw: &str) -> StableId {
    StableId::new(raw.to_string()).expect("public research fixture ID")
}

#[test]
fn python_trained_linear_cells_match_rust_q24_for_real_public_features() {
    assert_eq!(
        Digest32::of_bytes(b"research-only pinned ModernBERT-base source").to_string(),
        PINNED_ENCODER_DIGEST
    );
    // The ZIP and seal are external source identities. This test does not
    // authenticate their upstream producer or read any private task labels.
    assert_eq!(PINNED_SOURCE_ZIP_SHA256.len(), 64);
    let source = Digest32::from_str(SOURCE_SEAL_SHA256).expect("source digest");
    let encoder = Digest32::from_str(PINNED_ENCODER_DIGEST).expect("encoder digest");
    let tokenizer = Digest32::of_bytes(b"public feature tokenizer");
    let preprocessor = Digest32::of_bytes(b"train-fitted PCA32 preprocessor");
    let quantization = Digest32::of_bytes(b"public Q24 quantization");
    let mut candidates = Vec::new();
    for i in 0..4 {
        candidates.push(GatedHeadCandidateV2 {
            cell_identity: format!("cell.public.linear.{i}"),
            encoder_digest: encoder.to_string(),
            input_width: 32,
            output_width: 1,
            gate_q24: vec![1_i64 << 24; 32],
            drive_weights_q24: HEAD_WEIGHTS_Q24[i].to_vec(),
            prediction_weights_q24: vec![0; 32],
            drive_bias_q24: vec![HEAD_BIASES_Q24[i]],
            prediction_bias_q24: vec![0],
        });
    }
    let catalog = GatedHeadCpuDriverV2::catalog_digest_for(&candidates).expect("catalog");
    assert_eq!(catalog, EXPECTED_CATALOG_DIGEST);
    let manifest = ModelManifest {
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
    let mut driver = GatedHeadCpuDriverV2::new(manifest.clone()).expect("research driver");
    let mut heads = Vec::new();
    for (i, candidate) in candidates.into_iter().enumerate() {
        let head = driver.register_head(candidate).expect("frozen Cell head");
        assert_eq!(head, EXPECTED_HEAD_DIGESTS[i]);
        heads.push(head);
    }
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
    .expect("bounded worker");
    worker
        .load_model(1, manifest.clone())
        .expect("research model loaded");
    let mut cache = SharedFeatureCacheV2::new(2, 1024).expect("shared cache");
    let cases: [(&str, &[i64; 32], &[i64; 4]); 2] = [
        ("fit:a761e5bf506a91e172492a3c023bdd9aa03e38d3e55fedcd684eaef6a6f154cf", &PUBLIC_FIT_0_Q24, &EXPECTED_FIT_0_LOGITS_Q24),
        ("heldout:3b2d2c35297ebbcb24a83da141508eff20a7bd546deb854f04b6a19817271313", &PUBLIC_HELDOUT_0_Q24, &EXPECTED_HELDOUT_0_LOGITS_Q24),
    ];
    for (case_number, (case_id, features, expected)) in cases.into_iter().enumerate() {
        let identity = SharedFeatureIdentityV2 {
            principal_id: stable("principal.public.research"),
            purpose_id: stable("purpose.public.linear-numeric-parity"),
            scope_id: stable("scope.public.pca32"),
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
            .insert(1, identity, 900, Arc::from(features.as_slice()))
            .expect("saved real Q24 sample");
        let mut requests = Vec::new();
        for (index, head) in heads.iter().enumerate() {
            let request_id = format!("request.public.{case_number}.{index}");
            let mut request = SharedNeuronFeatureRequestV2 {
                authorization: WorkerRequest {
                    request_id: request_id.clone(),
                    reservation_id: format!("reservation.{request_id}"),
                    model_digest: manifest.model_digest.clone(),
                    payload_digest: "0".repeat(64),
                    maximum_tokens: 1,
                    deadline_ms: 800,
                    lease_payload_digest: "0".repeat(64),
                    reservation_model_digest: manifest.model_digest.clone(),
                    reservation_maximum_tokens: 1,
                    cancelled: false,
                },
                principal_id: stable("principal.public.research"),
                purpose_id: stable("purpose.public.linear-numeric-parity"),
                scope_id: stable("scope.public.pca32"),
                cell_id: stable(&format!("cell.public.linear.{index}")),
                snapshot: Arc::clone(&snapshot),
                head_digest: head.clone(),
                weights_digest: manifest.weights_digest.clone(),
                expected_output_width: 1,
            };
            let binding = canonical_shared_neuron_payload_digest_v2(&request)
                .expect("bounded request digest");
            request.authorization.payload_digest = binding.clone();
            request.authorization.lease_payload_digest = binding;
            requests.push(request);
        }
        assert!(requests
            .iter()
            .all(|item| Arc::ptr_eq(&snapshot.features_q24, &item.snapshot.features_q24)));
        let results = worker
            .run_shared_neuron_features_batch_v2(100, &manifest.model_id, requests)
            .expect("qualified CPU Q24 batch");
        assert_eq!(results.len(), 4);
        let actual: Vec<i64> = results.iter().map(|item| item.drive_q24[0]).collect();
        assert_eq!(actual.as_slice(), expected);
        for (i, result) in results.iter().enumerate() {
            assert_eq!(result.status, ExecutionStatus::Succeeded);
            assert_eq!(result.prediction_q24, vec![0]);
            assert_eq!(result.head_digest, EXPECTED_HEAD_DIGESTS[i]);
            assert_eq!(result.scope_id, stable("scope.public.pca32"));
            assert!(!result.authority.grants_any());
        }
    }
    assert_eq!(cache.len(), 2);
    assert_eq!(cache.resident_bytes(), 2 * 32 * 8);
    assert_eq!(worker.driver.batch_calls(), 2);
}
