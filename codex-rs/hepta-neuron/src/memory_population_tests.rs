use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;

use crate::AssociativeMemoryCellV1;
use crate::AssociativeMemoryError;
use crate::MemoryCellPopulationV2;

const SEMANTIC: &[u8] = include_bytes!("../tests/fixtures/associative-memory/population.semantic.native.json");
const PROCEDURE: &[u8] = include_bytes!("../tests/fixtures/associative-memory/population.procedure.native.json");
const EXPECTED: &[u8] = include_bytes!("../tests/fixtures/associative-memory/population.expected.json");

#[test]
fn actual_parameter_shards_read_sources_across_sleep_and_budget_eviction() {
    let expected: Value = serde_json::from_slice(EXPECTED).expect("actual fit fixture");
    for (kind, raw) in [("semantic", SEMANTIC), ("procedure", PROCEDURE)] {
        let model = MemoryCellPopulationV2::from_bytes(raw, Digest32::of_bytes(raw)).expect("population");
        assert_eq!(model.shard_count(), 2);
        let initial = model.cost().expect("cost");
        assert_eq!(initial.resident_shards, 0);
        assert!(initial.serialized_bytes > initial.parameter_bytes);
        assert!(initial.catalog_bytes > 0 && initial.route_bytes > 0 && initial.lineage_bytes > 0);
        // This permits one shard, not both, so alternating address routes must
        // actually evict and reload native tensors rather than reuse answers.
        let per_shard = model.shard_costs.iter().map(|cost| cost.resident_bytes()).max().expect("shards");
        model.set_resident_budget(per_shard).expect("bound");
        for row in expected["types"][kind]["rows"].as_array().expect("rows") {
            let prediction = model.predict(row["entity"].as_str().expect("entity")).expect("native prediction");
            assert_eq!(prediction.value.as_ref(), Some(&row["value"]));
            assert_eq!(prediction.source_ids, vec![row["source_id"].as_str().expect("source").to_string()]);
            assert_eq!(prediction.artifact_digest, model.digest().to_string());
            assert_eq!(prediction.parameter_digest, model.parameters_digest().to_string());
            assert!(model.cost().expect("cost").resident_shards <= 1);
        }
        let before = model.cost().expect("cost");
        assert!(before.eviction_count > 0 && before.wake_count > 1);
        model.sleep().expect("sleep");
        assert_eq!(model.cost().expect("cost").resident_parameter_bytes, 0);
        let unknown = model.predict("unwritten-in-any-shard").expect("abstention");
        assert!(unknown.value.is_none() && unknown.source_ids.is_empty());
        assert_eq!(model.cost().expect("cost").wake_count, before.wake_count);
        model.set_resident_budget(0).expect("disable resident tensors");
        let key = expected["types"][kind]["rows"][0]["entity"].as_str().expect("key");
        assert_eq!(model.predict(key), Err(AssociativeMemoryError::InvalidConfiguration));
    }
}

#[test]
fn route_omissions_overlap_unknown_and_value_dependent_repartition_are_rejected() {
    let original: Value = serde_json::from_slice(SEMANTIC).expect("fixture");
    let mutate = |mut value: Value| {
        let raw = serde_json::to_vec(&mut value).expect("serialize corruption");
        assert!(MemoryCellPopulationV2::from_bytes(&raw, Digest32::of_bytes(&raw)).is_err());
    };
    let first_key = original["routes"].as_object().expect("routes").keys().next().expect("key").clone();
    let mut missing = original.clone();
    missing["routes"].as_object_mut().expect("routes").remove(&first_key);
    mutate(missing);
    let mut unknown = original.clone();
    unknown["routes"][Digest32::of_bytes(b"outside-support").to_string()] = Value::from(0);
    mutate(unknown);
    let mut wrong = original.clone();
    wrong["routes"][&first_key] = Value::from(7);
    mutate(wrong);
    let mut overlap = original.clone();
    overlap["shards"][1] = overlap["shards"][0].clone();
    mutate(overlap);
    let mut swapped = original.clone();
    swapped["shards"].as_array_mut().expect("shards").swap(0, 1);
    for route in swapped["routes"].as_object_mut().expect("routes").values_mut() {
        *route = Value::from(1 - route.as_u64().expect("route"));
    }
    mutate(swapped);
    let mut lineage = original;
    lineage["lineage_sources"].as_array_mut().expect("sources").pop();
    mutate(lineage);
}

#[test]
fn single_native_payload_keeps_its_original_identity_and_prediction() {
    let raw = include_bytes!("../tests/fixtures/associative-memory/semantic.native.json");
    let digest = Digest32::of_bytes(raw);
    let original = AssociativeMemoryCellV1::from_bytes(raw, digest).expect("single model");
    let wrapper = MemoryCellPopulationV2::from_bytes(raw, digest).expect("compatible wrapper");
    assert!(!wrapper.is_population());
    assert_eq!((wrapper.digest(), wrapper.parameters_digest(), wrapper.head_digest()),
        (original.digest(), original.parameters_digest(), original.head_digest()));
    assert_eq!(wrapper.supports(), original.supports());
    assert_eq!(wrapper.lineage_sources(), original.lineage_sources());
    assert_eq!(wrapper.predict("unwritten"), original.predict("unwritten"));
}
