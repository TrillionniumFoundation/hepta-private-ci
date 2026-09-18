use super::*;

use crate::WorldModelSampleV1;
use crate::fit_transition_model;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sample(name: &str, next: &str, outcome: i64) -> WorldModelSampleV1 {
    WorldModelSampleV1 {
        sample_id: id(name),
        state_id: id("state-a"),
        action_id: id("action-a"),
        next_state_id: id(next),
        outcome: FixedQ32::from_raw(outcome),
        evidence_digest: digest(&format!("evidence-{name}")),
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
    .expect("world model fit")
}

fn pin(model: &TabularWorldModelV1, bytes: &[u8]) -> TabularWorldModelPinV1 {
    TabularWorldModelPinV1 {
        payload_digest: Digest32::of_bytes(bytes),
        model_digest: model.model_digest,
        dataset_digest: model.dataset_digest,
    }
}

#[test]
fn pinned_world_model_round_trips_and_predicts() {
    let model = fitted();
    let bytes = encode_world_model_payload_v1(&model).expect("encode");
    let loaded =
        LoadedTabularWorldModelV1::from_pinned_payload(&bytes, &pin(&model, &bytes)).expect("load");
    assert_eq!(loaded.model_id(), &id("world-model"));
    assert_eq!(loaded.model_digest(), model.model_digest);
    assert_eq!(loaded.dataset_digest(), model.dataset_digest);

    let prediction = loaded
        .predict(&id("state-a"), &id("action-a"))
        .expect("supported prediction");
    assert_eq!(prediction.mean_outcome, FixedQ32::from_raw(20));
    assert_eq!(prediction.branches.len(), 2);
    assert!(prediction.synthetic);
    assert!(!prediction.authority.grants_any());
    assert_eq!(
        loaded.predict(&id("unknown"), &id("action-a")),
        Err(WorldModelPayloadError::UnsupportedStateAction)
    );
}

#[test]
fn pinned_world_model_rejects_payload_tampering_and_stale_pins() {
    let model = fitted();
    let bytes = encode_world_model_payload_v1(&model).expect("encode");
    let original = pin(&model, &bytes);

    let mut altered = bytes.clone();
    let last = altered.len() - 1;
    altered[last] ^= 1;
    assert!(matches!(
        LoadedTabularWorldModelV1::from_pinned_payload(&altered, &original),
        Err(WorldModelPayloadError::Binding)
    ));

    let mut stale = original.clone();
    stale.dataset_digest = digest("other-dataset");
    assert!(matches!(
        LoadedTabularWorldModelV1::from_pinned_payload(&bytes, &stale),
        Err(WorldModelPayloadError::Binding)
    ));

    let mut trailing = bytes;
    trailing.push(0);
    let matching_payload = TabularWorldModelPinV1 {
        payload_digest: Digest32::of_bytes(&trailing),
        ..original
    };
    assert!(matches!(
        LoadedTabularWorldModelV1::from_pinned_payload(&trailing, &matching_payload),
        Err(WorldModelPayloadError::Encoding)
    ));
}

#[test]
fn encoder_rejects_mutated_public_model_structure() {
    let model = fitted();

    let mut bad_digest = model.clone();
    bad_digest.model_digest = digest("forged-model");
    assert_eq!(
        encode_world_model_payload_v1(&bad_digest),
        Err(WorldModelPayloadError::InvalidModel)
    );

    let mut bad_count = model;
    bad_count.estimates[0].sample_count += 1;
    assert_eq!(
        encode_world_model_payload_v1(&bad_count),
        Err(WorldModelPayloadError::InvalidModel)
    );
}
