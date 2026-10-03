use std::cell::Cell;

use serde::Deserialize;
use serde::Serialize;
use serde::ser::SerializeSeq;

use crate::hnmf::HnmfContractError;
use crate::wire::*;

thread_local! {
    static ELEMENTS: Cell<usize> = const { Cell::new(0) };
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct GrowingPayload(Cell<usize>);

impl Serialize for GrowingPayload {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let calls = self.0.get();
        self.0.set(calls + 1);
        if calls == 0 {
            return serializer.serialize_unit();
        }
        let mut sequence = serializer.serialize_seq(Some(100_000))?;
        for _ in 0..100_000 {
            ELEMENTS.with(|count| count.set(count.get() + 1));
            sequence.serialize_element(&0u8)?;
        }
        sequence.end()
    }
}

impl<'de> Deserialize<'de> for GrowingPayload {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        serde::de::IgnoredAny::deserialize(deserializer)?;
        Ok(Self(Cell::new(1)))
    }
}

impl CognitiveContractV1 for GrowingPayload {
    const CONTRACT_ID: &'static str = "GrowingPayloadV1";
    const SCHEMA_ID: &'static str = "hepta.test.growing-payload.v1";
    const MAX_ENCODED_BYTES: usize = 64;

    fn validate_contract(&self) -> Result<(), HnmfContractError> {
        self.0.set(1);
        Ok(())
    }
}

fn assert_early_payload_refusal<T>(result: Result<T, CognitiveWireError>) {
    assert!(matches!(
        result,
        Err(CognitiveWireError::PayloadLength { maximum: 64, .. })
    ));
    assert!(
        ELEMENTS.with(Cell::get) < 40,
        "the actual serialization must stop at its byte budget"
    );
}

#[test]
fn actual_serialization_is_bounded_when_preflight_observation_changes() {
    ELEMENTS.with(|count| count.set(0));
    assert_early_payload_refusal(encode_wire_v1(&GrowingPayload(Cell::new(0))));
    ELEMENTS.with(|count| count.set(0));
    assert_early_payload_refusal(ValidatedCanonicalPayload::new(GrowingPayload(Cell::new(0))));
    ELEMENTS.with(|count| count.set(0));
    assert_early_payload_refusal(canonical_contract_typed_digests_v1(&GrowingPayload(
        Cell::new(0),
    )));
}

#[test]
fn strict_decode_bounds_the_actual_payload_reserialization() {
    let wire = br#"{"contract":"GrowingPayloadV1","payload":null,"schema":"hepta.test.growing-payload.v1","schemaVersion":1}"#;
    ELEMENTS.with(|count| count.set(0));
    assert_early_payload_refusal(decode_wire_v1::<GrowingPayload>(wire));
    ELEMENTS.with(|count| count.set(0));
    assert_early_payload_refusal(ValidatedCanonicalPayload::<GrowingPayload>::decode_wire(
        wire,
    ));
}
