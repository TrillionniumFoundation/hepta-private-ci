use super::*;
use crate::WorldModelSampleV1;
use crate::fit_transition_model;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fitted() -> TabularWorldModelV1 {
    fit_transition_model(
        id("world-model"),
        digest("dataset"),
        vec![
            WorldModelSampleV1 {
                sample_id: id("sample-a"),
                state_id: id("state"),
                action_id: id("read"),
                next_state_id: id("next-a"),
                outcome: FixedQ32::from_raw(4),
                evidence_digest: digest("evidence-a"),
            },
            WorldModelSampleV1 {
                sample_id: id("sample-b"),
                state_id: id("state"),
                action_id: id("read"),
                next_state_id: id("next-b"),
                outcome: FixedQ32::from_raw(8),
                evidence_digest: digest("evidence-b"),
            },
        ],
    )
    .expect("valid world model")
}

fn pin(model: &TabularWorldModelV1, bytes: &[u8]) -> WorldModelPayloadPinV1 {
    WorldModelPayloadPinV1 {
        payload_digest: Digest32::of_bytes(bytes),
        model_id: model.model_id.clone(),
        model_digest: model.model_digest,
        dataset_digest: model.dataset_digest,
    }
}

#[test]
fn pinned_world_model_roundtrips_and_predicts_from_private_state() {
    let model = fitted();
    let bytes = encode_world_model_payload_v1(&model).expect("encode");
    let loaded = LoadedTabularWorldModelV1::from_pinned_payload(&bytes, &pin(&model, &bytes))
        .expect("pinned load");
    let prediction = loaded.predict(&id("state"), &id("read")).expect("predict");
    assert_eq!(prediction.mean_outcome, FixedQ32::from_raw(6));
    assert_eq!(prediction.branches.len(), 2);
    assert!(prediction.synthetic);
    assert!(!prediction.authority.grants_any());
    assert_eq!(
        loaded.predict(&id("unknown"), &id("read")),
        Err(WorldModelPayloadError::UnsupportedStateAction)
    );
}

#[test]
fn payload_tampering_and_stale_pins_fail_closed() {
    let model = fitted();
    let bytes = encode_world_model_payload_v1(&model).expect("encode");
    let original = pin(&model, &bytes);

    let mut tampered = bytes.clone();
    let index = tampered.len() / 2;
    tampered[index] ^= 1;
    assert_eq!(
        LoadedTabularWorldModelV1::from_pinned_payload(&tampered, &original),
        Err(WorldModelPayloadError::Binding)
    );

    let mut stale = original;
    stale.dataset_digest = digest("other-dataset");
    assert_eq!(
        LoadedTabularWorldModelV1::from_pinned_payload(&bytes, &stale),
        Err(WorldModelPayloadError::Binding)
    );
}

#[test]
fn invalid_retained_statistics_cannot_be_persisted() {
    let mut model = fitted();
    model.estimates[0].branches[0].count += 1;
    assert_eq!(
        encode_world_model_payload_v1(&model),
        Err(WorldModelPayloadError::Grid)
    );

    let mut stale_digest = fitted();
    stale_digest.model_digest = digest("stale-model-digest");
    assert_eq!(
        encode_world_model_payload_v1(&stale_digest),
        Err(WorldModelPayloadError::Binding)
    );
}
