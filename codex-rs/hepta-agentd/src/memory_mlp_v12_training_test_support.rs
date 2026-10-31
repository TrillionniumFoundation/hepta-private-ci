//! Deterministic SGD integration fixture, not evidence of natural-language
//! quality. Both layers learn from owner records; answers are never installed
//! in the feature cache or copied into a constant output head.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_memory::MemoryTrainingProjectionV11;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::test_support::CellFixture;
use super::test_support::generation;
use crate::MemoryCellCandidateV12;
use crate::memory_cell_release::test_support::fixture_manifest_template;
use crate::memory_cell_release::test_support::prepare_payload_request;

pub fn train(projection: &MemoryTrainingProjectionV11) -> Vec<u8> {
    let dimension = projection.records().len();
    let hidden = 4;
    let (kind, output, targets): (_, _, Vec<Vec<f64>>) = match projection.selector().kind {
        MemoryInventoryKindV1::Semantic => ("semantic", "hepta.memory.inventory-policy.bits12.v1",
            projection.records().iter().map(|row| ["reserve", "pack", "limit"].iter().flat_map(|name|
                (0..4).map(move |bit| if row.record.value[*name].as_u64().expect("value") & (1 << bit) != 0 { 1.0 } else { -1.0 })
            ).collect()).collect()),
        MemoryInventoryKindV1::Procedure => ("procedure", "hepta.memory.inventory-program.ops4x7.v1",
            projection.records().iter().map(|row| row.record.value["opcodes"].as_array().expect("program").iter().flat_map(|opcode|
                (0..7).map(move |index| if opcode.as_u64() == Some(index) { 1.0 } else { -1.0 })
            ).collect()).collect()),
        MemoryInventoryKindV1::Event | MemoryInventoryKindV1::Hold => panic!("not a parameter task"),
    };
    let width = targets[0].len();
    let mut w1: Vec<f64> = (0..hidden * dimension).map(|index| ((index * 7 % 11) as f64 - 5.0) * 0.05).collect();
    let mut b1 = vec![0.15_f64; hidden];
    let mut w2: Vec<f64> = (0..width * hidden).map(|index| ((index * 13 % 17) as f64 - 8.0) * 0.02).collect();
    let mut b2 = vec![0.0_f64; width];
    let original_w1 = w1.clone();
    let original_w2 = w2.clone();
    for _ in 0..4000 {
        for (address, target) in targets.iter().enumerate() {
            // One-hot canonical input, independent of the output labels.
            let activation: Vec<f64> = (0..hidden).map(|row| (w1[row * dimension + address] + b1[row]).max(0.0)).collect();
            let error: Vec<f64> = (0..width).map(|row|
                (b2[row] + (0..hidden).map(|column| w2[row * hidden + column] * activation[column]).sum::<f64>() - target[row]) / width as f64
            ).collect();
            let hidden_error: Vec<f64> = (0..hidden).map(|column| if activation[column] > 0.0 {
                (0..width).map(|row| w2[row * hidden + column] * error[row]).sum()
            } else { 0.0 }).collect();
            for (row, delta) in error.iter().enumerate() {
                for column in 0..hidden { w2[row * hidden + column] -= 0.1 * delta * activation[column]; }
                b2[row] -= 0.1 * delta;
            }
            for (row, delta) in hidden_error.iter().enumerate() {
                w1[row * dimension + address] -= 0.1 * delta;
                b1[row] -= 0.1 * delta;
            }
        }
    }
    assert_ne!(w1, original_w1, "hidden parameters actually trained");
    assert_ne!(w2, original_w2, "output parameters actually trained");
    let mut arrays = BTreeMap::new();
    let mut parameters = Vec::new();
    for (name, shape, values) in [
        ("head.bias", vec![width], b2), ("head.weight", vec![width, hidden], w2),
        ("hidden.bias", vec![hidden], b1), ("hidden.weight", vec![hidden, dimension], w1),
    ] {
        let raw: Vec<u8> = values.iter().flat_map(|value| (*value as f32).to_le_bytes()).collect();
        parameters.extend(serde_json::to_vec(&(name, &shape, "float32")).expect("header"));
        parameters.extend_from_slice(&raw);
        arrays.insert(name, json!({"shape":shape,"f32le_hex":hex(&raw)}));
    }
    let mut supports = BTreeMap::new();
    let mut features = BTreeMap::new();
    let mut lineage = BTreeSet::new();
    for (index, row) in projection.records().iter().enumerate() {
        let address = Digest32::of_bytes(row.record.key.as_str().as_bytes()).to_string();
        let raw: Vec<u8> = (0..dimension).flat_map(|column| f32::from(u8::from(column == index)).to_le_bytes()).collect();
        supports.insert(address.clone(), vec![row.source_id.to_string()]);
        lineage.insert(row.source_id.to_string());
        features.insert(address.clone(), json!({"canonical_text_sha256":address,
            "feature_sha256":Digest32::of_bytes(&raw).to_string(),"f32le_hex":hex(&raw)}));
    }
    let parameter_digest = Digest32::of_bytes(&parameters).to_string();
    let receipt = serde_json::to_vec(&json!({"algorithm":"test-sgd-two-layer-relu-mse",
        "epochs":4000,"projection":projection.digest(),"parameters":parameter_digest})).expect("training receipt");
    let payload = serde_json::to_vec(&json!({"schema":"hepta.memory.mlp-native.v12","kind":kind,
        "address_profile":"hepta.memory.frozen-feature-cache.v12","numeric_profile":"hepta.memory.f32-f64-relu-mlp.v12",
        "output_profile":output,"dimension":dimension,"hidden":hidden,"minimum_margin":0.2,
        "encoder_sha256":Digest32::of_bytes(b"test-one-hot-canonical-no-language-encoder-claim").to_string(),
        "owner_cut_sha256":projection.acquisition_cut_digest(),"parameter_sha256":parameter_digest,
        "checkpoint_sha256":Digest32::of_bytes(&parameters).to_string(),
        "training_receipt_sha256":Digest32::of_bytes(&receipt).to_string(),
        "supports":supports,"lineage_sources":lineage,"features":features,"arrays":arrays})).expect("trained payload");
    let model = crate::memory_mlp_v12::MemoryMlpCellV12::from_bytes(&payload, Digest32::of_bytes(&payload)).expect("native tensors");
    for row in projection.records() {
        let prediction = model.predict(row.record.key.as_str()).expect("real native forward");
        assert!(prediction.abstain.is_none(), "trained output is usable");
        assert_eq!(prediction.source_ids, vec![row.source_id.to_string()]);
    }
    payload
}

pub fn publish_trained(fixture: &mut CellFixture, owner: &MemoryInventoryOwnerSnapshotV1) {
    let revision = fixture.publication.admission.validated_manifest.manifest.generation.get() + 1;
    let projection = owner.training_projection_v11(&fixture.selector).expect("current sources");
    let payload = train(&projection);
    let candidate = MemoryCellCandidateV12::from_projection(&projection, generation(revision), &payload).expect("V12 candidate");
    let manifest = candidate.bind_manifest(fixture_manifest_template(&fixture.config, revision,
        Digest32::of_bytes(b"test-sgd-two-layer-relu-mse-4000"))).expect("manifest");
    assert_eq!(manifest.objective_class_digest,
        fixture.publication.admission.validated_manifest.manifest.objective_class_digest,
        "same cell inventory objective across evaluator upgrades and corrections");
    let publication = prepare_payload_request(&fixture.service, &fixture.config, manifest, candidate.bytes().to_vec(), revision);
    fixture.host.publish(publication.clone(), owner).expect("independent publication");
    fixture.publication = publication;
    fixture.install();
}

fn hex(bytes: &[u8]) -> String { bytes.iter().map(|byte| format!("{byte:02x}")).collect() }
