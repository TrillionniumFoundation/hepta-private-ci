use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
struct Counter(u32);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct CounterError;

impl TypedPayload for Counter {
    const SCHEMA_ID: &'static str = "hepta.counter.v1";
    type Error = CounterError;

    fn encode_payload(&self) -> Result<Vec<u8>, Self::Error> {
        Ok(self.0.to_be_bytes().to_vec())
    }

    fn decode_payload(payload: &[u8]) -> Result<Self, Self::Error> {
        let bytes: [u8; 4] = payload.try_into().map_err(|_| CounterError)?;
        Ok(Self(u32::from_be_bytes(bytes)))
    }
}

fn validate_counter(payload: &[u8]) -> Result<(), SchemaValidationError> {
    if payload.len() == 4 {
        Ok(())
    } else {
        Err(SchemaValidationError::new("counter.length"))
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn generation() -> Generation {
    Generation::new(3).expect("test generation")
}

#[test]
fn typed_codec_round_trips_on_v1_and_v2() {
    let producer = id("schema.test");
    let value = Counter(42);
    let v1 = encode_typed_v1(producer.clone(), generation(), &value).expect("v1 encode");
    let v2 = encode_typed_v2(producer, generation(), &value).expect("v2 encode");
    assert_eq!(decode_typed_v1::<Counter>(&v1), Ok(value.clone()));
    assert_eq!(decode_typed_v2::<Counter>(&v2), Ok(value));
}

#[test]
fn registry_rejects_unknown_schema_oversize_and_invalid_payload() {
    let mut registry = SchemaRegistry::new();
    registry
        .register(
            SchemaRule::new(id(Counter::SCHEMA_ID), 4, validate_counter)
                .expect("valid schema rule"),
        )
        .expect("register schema");

    let unknown = WireEnvelopeV2::new(
        id("unknown.v1"),
        id("producer"),
        generation(),
        vec![1],
    )
    .expect("valid wire envelope");
    assert!(matches!(
        registry.admit_v2(&unknown),
        Err(SchemaAdmissionError::UnknownSchema(_))
    ));

    let oversize = WireEnvelopeV2::new(
        id(Counter::SCHEMA_ID),
        id("producer"),
        generation(),
        vec![0; 5],
    )
    .expect("valid wire envelope");
    assert!(matches!(
        registry.admit_v2(&oversize),
        Err(SchemaAdmissionError::PayloadTooLarge { .. })
    ));

    let invalid = WireEnvelopeV2::new(
        id(Counter::SCHEMA_ID),
        id("producer"),
        generation(),
        vec![0; 3],
    )
    .expect("valid wire envelope");
    assert!(matches!(
        registry.admit_v2(&invalid),
        Err(SchemaAdmissionError::Validation {
            code: "counter.length",
            ..
        })
    ));
}

#[test]
fn typed_decode_rejects_schema_confusion() {
    let envelope = WireEnvelopeV2::new(
        id("hepta.other.v1"),
        id("producer"),
        generation(),
        42_u32.to_be_bytes().to_vec(),
    )
    .expect("valid wire envelope");
    assert!(matches!(
        decode_typed_v2::<Counter>(&envelope),
        Err(TypedCodecError::SchemaMismatch { .. })
    ));
}
