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
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier rejected");
    };
    value
}

fn generation() -> Generation {
    let Ok(value) = Generation::new(3) else {
        panic!("test generation rejected");
    };
    value
}

fn wire_v2(schema: &str, payload: Vec<u8>) -> WireEnvelopeV2 {
    let result = WireEnvelopeV2::new(id(schema), id("producer"), generation(), payload);
    let Ok(value) = result else {
        panic!("valid wire envelope rejected");
    };
    value
}

#[test]
fn typed_codec_round_trips_on_v1_and_v2() {
    let producer = id("schema.test");
    let value = Counter(42);
    let v1_result = encode_typed_v1(producer.clone(), generation(), &value);
    let Ok(v1) = v1_result else {
        panic!("typed v1 encode rejected");
    };
    let v2_result = encode_typed_v2(producer, generation(), &value);
    let Ok(v2) = v2_result else {
        panic!("typed v2 encode rejected");
    };
    assert_eq!(decode_typed_v1::<Counter>(&v1), Ok(value.clone()));
    assert_eq!(decode_typed_v2::<Counter>(&v2), Ok(value));
}

#[test]
fn registry_rejects_unknown_schema_oversize_and_invalid_payload() {
    let mut registry = SchemaRegistry::new();
    let rule_result = SchemaRule::new(id(Counter::SCHEMA_ID), 4, validate_counter);
    let Ok(rule) = rule_result else {
        panic!("valid schema rule rejected");
    };
    assert_eq!(registry.register(rule), Ok(()));

    let unknown = wire_v2("unknown.v1", vec![1]);
    assert!(matches!(
        registry.admit_v2(&unknown),
        Err(SchemaAdmissionError::UnknownSchema(_))
    ));

    let oversize = wire_v2(Counter::SCHEMA_ID, vec![0; 5]);
    assert!(matches!(
        registry.admit_v2(&oversize),
        Err(SchemaAdmissionError::PayloadTooLarge { .. })
    ));

    let invalid = wire_v2(Counter::SCHEMA_ID, vec![0; 3]);
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
    let envelope = wire_v2("hepta.other.v1", 42_u32.to_be_bytes().to_vec());
    assert!(matches!(
        decode_typed_v2::<Counter>(&envelope),
        Err(TypedCodecError::SchemaMismatch { .. })
    ));
}
