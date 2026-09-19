use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
struct StrictMessage {
    objective: String,
    step: u32,
}

struct StrictCodec {
    descriptor: SchemaDescriptor,
}

impl StrictCodec {
    fn new() -> Result<Self, Box<dyn Error>> {
        Ok(Self {
            descriptor: SchemaDescriptor::new(
                StableId::new("hepta.strict-message.v1")?,
                WireVersion::V2,
                WireVersion::V2,
                256,
            )?,
        })
    }
}

impl PayloadCodec for StrictCodec {
    type Value = StrictMessage;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        if value.objective.is_empty()
            || value
                .objective
                .bytes()
                .any(|byte| matches!(byte, b';' | b'='))
        {
            return Err(SchemaCodecError::Rejected("invalid objective"));
        }
        Ok(format!("objective={};step={}", value.objective, value.step).into_bytes())
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        let text =
            std::str::from_utf8(payload).map_err(|_| SchemaCodecError::Rejected("non-UTF-8"))?;
        let mut objective = None;
        let mut step = None;
        for field in text.split(';') {
            let Some((name, value)) = field.split_once('=') else {
                return Err(SchemaCodecError::Rejected("malformed field"));
            };
            match name {
                "objective" if objective.is_none() => objective = Some(value.to_string()),
                "step" if step.is_none() => {
                    step = Some(
                        value
                            .parse::<u32>()
                            .map_err(|_| SchemaCodecError::Rejected("invalid step"))?,
                    );
                }
                "objective" | "step" => {
                    return Err(SchemaCodecError::Rejected("duplicate field"));
                }
                _ => return Err(SchemaCodecError::Rejected("unknown critical field")),
            }
        }
        let objective = objective.ok_or(SchemaCodecError::Rejected("missing objective"))?;
        let step = step.ok_or(SchemaCodecError::Rejected("missing step"))?;
        if objective.is_empty() {
            return Err(SchemaCodecError::Rejected("empty objective"));
        }
        Ok(StrictMessage { objective, step })
    }
}

#[test]
fn registered_typed_schema_round_trips_canonically() -> Result<(), Box<dyn Error>> {
    let codec = StrictCodec::new()?;
    let mut registry = SchemaRegistry::new();
    registry.register(codec.descriptor().clone())?;
    let value = StrictMessage {
        objective: "ndu".to_string(),
        step: 7,
    };
    let payload = encode_typed(&registry, WireVersion::V2, &codec, &value)?;
    assert_eq!(payload, b"objective=ndu;step=7");
    assert_eq!(
        decode_typed(
            &registry,
            WireVersion::V2,
            codec.descriptor().schema(),
            &codec,
            &payload
        )?,
        value
    );
    Ok(())
}

#[test]
fn missing_and_unknown_fields_reject_after_schema_admission() -> Result<(), Box<dyn Error>> {
    let codec = StrictCodec::new()?;
    let mut registry = SchemaRegistry::new();
    registry.register(codec.descriptor().clone())?;

    assert_eq!(
        decode_typed(
            &registry,
            WireVersion::V2,
            codec.descriptor().schema(),
            &codec,
            b"objective=ndu"
        ),
        Err(SchemaCodecError::Rejected("missing step"))
    );
    assert_eq!(
        decode_typed(
            &registry,
            WireVersion::V2,
            codec.descriptor().schema(),
            &codec,
            b"objective=ndu;step=1;extra=forbidden"
        ),
        Err(SchemaCodecError::Rejected("unknown critical field"))
    );
    Ok(())
}

#[test]
fn unknown_schema_and_wrong_wire_version_fail_before_decode() -> Result<(), Box<dyn Error>> {
    let codec = StrictCodec::new()?;
    let registry = SchemaRegistry::new();
    let unknown = decode_typed(
        &registry,
        WireVersion::V2,
        codec.descriptor().schema(),
        &codec,
        b"objective=ndu;step=1",
    );
    assert!(matches!(
        unknown,
        Err(SchemaCodecError::Admission(
            SchemaAdmissionError::UnknownSchema(_)
        ))
    ));

    let mut registry = SchemaRegistry::new();
    registry.register(codec.descriptor().clone())?;
    let wrong_version = decode_typed(
        &registry,
        WireVersion::V1,
        codec.descriptor().schema(),
        &codec,
        b"objective=ndu;step=1",
    );
    assert!(matches!(
        wrong_version,
        Err(SchemaCodecError::Admission(
            SchemaAdmissionError::UnsupportedSchemaVersion { .. }
        ))
    ));
    Ok(())
}

#[test]
fn conflicting_schema_registration_rejects() -> Result<(), Box<dyn Error>> {
    let codec = StrictCodec::new()?;
    let mut registry = SchemaRegistry::new();
    registry.register(codec.descriptor().clone())?;
    let conflicting = SchemaDescriptor::new(
        codec.descriptor().schema().clone(),
        WireVersion::V1,
        WireVersion::V2,
        256,
    )?;
    assert!(matches!(
        registry.register(conflicting),
        Err(SchemaAdmissionError::ConflictingRegistration(_))
    ));
    Ok(())
}

#[test]
fn schema_registry_and_producer_allow_list_are_bounded() -> Result<(), Box<dyn Error>> {
    let mut registry = SchemaRegistry::new();
    for index in 0..MAX_REGISTERED_SCHEMAS {
        registry.register(SchemaDescriptor::new(
            StableId::new(format!("schema.{index}"))?,
            WireVersion::V2,
            WireVersion::V2,
            256,
        )?)?;
    }
    assert_eq!(registry.len(), MAX_REGISTERED_SCHEMAS);
    assert_eq!(
        registry.register(SchemaDescriptor::new(
            StableId::new("schema.overflow")?,
            WireVersion::V2,
            WireVersion::V2,
            256,
        )?),
        Err(SchemaAdmissionError::RegistryLimitExceeded)
    );

    assert_eq!(
        ProducerAdmission::allow_list(Vec::<StableId>::new()),
        Err(SchemaAdmissionError::EmptyProducerSet)
    );
    let mut producers = Vec::with_capacity(MAX_ADMITTED_PRODUCERS + 1);
    for index in 0..=MAX_ADMITTED_PRODUCERS {
        producers.push(StableId::new(format!("producer.{index}"))?);
    }
    assert_eq!(
        ProducerAdmission::allow_list(producers),
        Err(SchemaAdmissionError::ProducerLimitExceeded)
    );
    Ok(())
}

#[test]
fn producer_admission_precedes_typed_payload_decode() -> Result<(), Box<dyn Error>> {
    let codec = StrictCodec::new()?;
    let mut registry = SchemaRegistry::new();
    registry.register(codec.descriptor().clone())?;
    let allowed = StableId::new("producer.allowed")?;
    let denied = StableId::new("producer.denied")?;
    let producers = ProducerAdmission::allow_list([allowed.clone()])?;
    let payload = b"objective=ndu;step=1";

    assert_eq!(
        decode_typed_for_producer(
            &registry,
            &producers,
            WireVersion::V2,
            codec.descriptor().schema(),
            &allowed,
            &codec,
            payload,
        )?,
        StrictMessage {
            objective: "ndu".to_string(),
            step: 1,
        }
    );
    assert!(matches!(
        decode_typed_for_producer(
            &registry,
            &producers,
            WireVersion::V2,
            codec.descriptor().schema(),
            &denied,
            &codec,
            b"not-even-a-valid-typed-payload",
        ),
        Err(SchemaCodecError::Admission(
            SchemaAdmissionError::ProducerDenied(producer)
        )) if producer == denied
    ));
    Ok(())
}
