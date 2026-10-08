use super::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_wire::WireEnvelopeV2;

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

#[test]
fn snapshot_wire_round_trip_and_unknown_field_rejection_are_deterministic() {
    let envelope = encode_cell_split_snapshot_wire_v1(
        br#"{"phase":"prepared"}"#,
        Digest32::of_bytes(b"plan"),
        generation(7),
        generation(8),
    )
    .expect("wire");
    let (decoded, observed_generation) =
        decode_cell_split_snapshot_wire_v1(&envelope).expect("decode");
    assert_eq!(observed_generation, generation(8));
    assert_eq!(decoded.snapshot_json, r#"{"phase":"prepared"}"#);

    let mut payload: serde_json::Value = serde_json::from_slice(envelope.payload()).expect("json");
    payload["unknown_critical"] = serde_json::json!(true);
    let malformed = WireEnvelopeV2::new(
        envelope.schema().clone(),
        envelope.producer().clone(),
        envelope.generation(),
        serde_json::to_vec(&payload).expect("payload"),
    )
    .expect("reframed");
    assert!(matches!(
        decode_cell_split_snapshot_wire_v1(&malformed),
        Err(CellSplitWireErrorV1::Codec(_))
    ));
}

#[test]
fn snapshot_wire_rejects_stale_generation_and_non_object_snapshot() {
    let envelope = encode_cell_split_snapshot_wire_v1(
        br#"{"phase":"prepared"}"#,
        Digest32::of_bytes(b"plan"),
        generation(7),
        generation(8),
    )
    .expect("wire");
    let stale = WireEnvelopeV2::new(
        envelope.schema().clone(),
        envelope.producer().clone(),
        generation(9),
        envelope.payload().to_vec(),
    )
    .expect("reframed");
    assert!(matches!(
        decode_cell_split_snapshot_wire_v1(&stale),
        Err(CellSplitWireErrorV1::InvalidBinding)
    ));

    assert!(matches!(
        encode_cell_split_snapshot_wire_v1(
            b"[]",
            Digest32::of_bytes(b"plan"),
            generation(7),
            generation(8),
        ),
        Err(CellSplitWireErrorV1::Codec(_))
    ));
}
