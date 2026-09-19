use super::*;
use crate::WorldModelSampleV1;
use crate::fit_transition_model;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sample(sample_id: &str, next_state_id: &str, outcome: i64) -> WorldModelSampleV1 {
    WorldModelSampleV1 {
        sample_id: id(sample_id),
        state_id: id("state-a"),
        action_id: id("action-a"),
        next_state_id: id(next_state_id),
        outcome: FixedQ32::from_raw(outcome),
        evidence_digest: digest(&format!("evidence-{sample_id}")),
    }
}

fn fitted() -> TabularWorldModelV1 {
    fit_transition_model(
        id("world-model"),
        digest("dataset"),
        vec![
            sample("sample-1", "state-b", 10),
            sample("sample-2", "state-b", 20),
            sample("sample-3", "state-c", 30),
        ],
    )
    .expect("valid world model")
}

fn pin(model: &TabularWorldModelV1, bytes: &[u8]) -> WorldModelPayloadPinV1 {
    WorldModelPayloadPinV1 {
        payload_digest: Digest32::of_bytes(bytes),
        model_digest: model.model_digest,
        dataset_digest: model.dataset_digest,
    }
}

#[test]
fn world_model_payload_roundtrips_through_independent_pin() {
    let model = fitted();
    let bytes = encode_world_model_payload_v1(&model).expect("encode");
    let loaded =
        LoadedWorldModelV1::from_pinned_payload(&bytes, &pin(&model, &bytes)).expect("load");
    assert_eq!(loaded.model_id(), &id("world-model"));
    let prediction = loaded
        .predict(&id("state-a"), &id("action-a"))
        .expect("prediction");
    assert_eq!(prediction.mean_outcome, FixedQ32::from_raw(20));
    assert_eq!(prediction.branches.len(), 2);
    assert!(prediction.synthetic);
    assert!(!prediction.authority.grants_any());
}

#[test]
fn world_model_payload_rejects_tamper_and_stale_pin() {
    let model = fitted();
    let bytes = encode_world_model_payload_v1(&model).expect("encode");
    let original = pin(&model, &bytes);

    let mut altered = bytes.clone();
    let last = altered.len() - 1;
    altered[last] ^= 1;
    assert_eq!(
        LoadedWorldModelV1::from_pinned_payload(&altered, &original),
        Err(WorldModelPayloadError::Binding)
    );

    let mut stale = original.clone();
    stale.dataset_digest = digest("other-dataset");
    assert_eq!(
        LoadedWorldModelV1::from_pinned_payload(&bytes, &stale),
        Err(WorldModelPayloadError::Binding)
    );
}

#[test]
fn world_model_loaded_predictor_rejects_unsupported_pairs() {
    let model = fitted();
    let bytes = encode_world_model_payload_v1(&model).expect("encode");
    let loaded =
        LoadedWorldModelV1::from_pinned_payload(&bytes, &pin(&model, &bytes)).expect("load");
    assert_eq!(
        loaded.predict(&id("state-unknown"), &id("action-a")),
        Err(WorldModelPayloadError::UnsupportedStateAction)
    );
}
