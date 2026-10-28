use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use crate::MemoryCellPopulationV2;

const ORIGINAL: &[u8] =
    include_bytes!("../tests/fixtures/associative-memory/population.semantic.native.json");

fn traced_population() -> Value {
    let mut wire: Value = serde_json::from_slice(ORIGINAL).unwrap();
    let cut = Digest32::of_bytes(b"real-owner-cut-required-at-host-admission");
    let groups: Vec<Vec<String>> = (0..2)
        .map(|shard| {
            wire["routes"]
                .as_object()
                .unwrap()
                .iter()
                .filter(|(_, index)| index.as_u64() == Some(shard))
                .map(|(key, _)| key.clone())
                .collect()
        })
        .collect();
    let mut bytes = b"hepta.memory.causal-coaccess-trace.v1\0".to_vec();
    bytes.extend_from_slice(cut.as_array());
    bytes.extend_from_slice(&2_u64.to_be_bytes());
    bytes.extend_from_slice(&2_u64.to_be_bytes());
    let observations: Vec<_> = groups.into_iter().enumerate().map(|(index, addresses)| {
        let sequence = index as u64 + 1;
        let request = Digest32::of_bytes(format!("completed-request:{sequence}").as_bytes());
        let readout = Digest32::of_bytes(format!("completed-readout:{sequence}").as_bytes());
        bytes.extend_from_slice(&sequence.to_be_bytes());
        bytes.extend_from_slice(request.as_array());
        bytes.extend_from_slice(readout.as_array());
        bytes.extend_from_slice(&(addresses.len() as u64).to_be_bytes());
        for address in &addresses {
            bytes.extend_from_slice(address.parse::<Digest32>().unwrap().as_array());
        }
        json!({"sequence":sequence,"request_digest":request.to_string(),"readout_digest":readout.to_string(),"addresses":addresses})
    }).collect();
    wire["schema"] = json!("hepta.memory.population.native.v3");
    wire["partition_profile"] = json!("hepta.memory.causal-coaccess-greedy.v1");
    wire["routing_trace"] = json!({"schema":"hepta.memory.causal-coaccess-trace.v1", "source_cut_digest":cut.to_string(),
        "prefix_end_sequence":2,"observations":observations,"trace_digest":Digest32::of_bytes(&bytes).to_string()});
    wire
}

#[test]
fn learned_profile_preserves_real_shard_support_and_sleep_identity() {
    let bytes = serde_json::to_vec(&traced_population()).unwrap();
    let learned = MemoryCellPopulationV2::from_bytes(&bytes, Digest32::of_bytes(&bytes)).unwrap();
    let original =
        MemoryCellPopulationV2::from_bytes(ORIGINAL, Digest32::of_bytes(ORIGINAL)).unwrap();
    assert_eq!(learned.supports(), original.supports());
    assert_eq!(learned.lineage_sources(), original.lineage_sources());
    assert_eq!(learned.parameters_digest(), original.parameters_digest());
    assert_ne!(learned.head_digest(), original.head_digest());
    assert_eq!(
        learned.routing_source_cut(),
        Some(Digest32::of_bytes(
            b"real-owner-cut-required-at-host-admission"
        ))
    );
    learned.sleep().unwrap();
    let missing = learned.predict("never-written-address").unwrap();
    assert!(missing.value.is_none() && missing.source_ids.is_empty());
    assert_eq!(learned.cost().unwrap().wake_count, 0);
}

#[test]
fn trace_tampering_causal_order_unknown_support_and_v2_profile_laundering_are_rejected() {
    let original = traced_population();
    let reject = |wire: Value| {
        let bytes = serde_json::to_vec(&wire).unwrap();
        assert!(MemoryCellPopulationV2::from_bytes(&bytes, Digest32::of_bytes(&bytes)).is_err());
    };
    let mut changed = original.clone();
    changed["routing_trace"]["observations"][0]["readout_digest"] =
        json!(Digest32::of_bytes(b"changed readout").to_string());
    reject(changed);
    let mut future = original.clone();
    future["routing_trace"]["observations"][1]["sequence"] = json!(3);
    reject(future);
    let mut repeated = original.clone();
    repeated["routing_trace"]["observations"][1]["request_digest"] =
        original["routing_trace"]["observations"][0]["request_digest"].clone();
    reject(repeated);
    let mut unknown = original.clone();
    unknown["routing_trace"]["observations"][0]["addresses"][0] =
        json!(Digest32::of_bytes(b"outside-support").to_string());
    reject(unknown);
    let mut wrong_profile = original.clone();
    wrong_profile["schema"] = json!("hepta.memory.population.native.v2");
    wrong_profile["partition_profile"] = json!("hepta.memory.sha256-address-rank.v1");
    reject(wrong_profile);
    let mut swapped = original;
    swapped["shards"].as_array_mut().unwrap().swap(0, 1);
    for route in swapped["routes"].as_object_mut().unwrap().values_mut() {
        *route = json!(1 - route.as_u64().unwrap());
    }
    reject(swapped);
}
