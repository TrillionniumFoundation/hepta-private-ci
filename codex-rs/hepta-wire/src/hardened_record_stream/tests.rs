#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use codex_hepta_types::Digest32;

    use crate::CanonicalizationProfile;
    use crate::FrozenSchemaRegistry;
    use crate::FrozenSchemaRegistryBuilder;
    use crate::GenerationPolicy;
    use crate::NegotiationOffer;
    use crate::PayloadCodec;
    use crate::PayloadCodecBinding;
    use crate::SchemaCodecError;
    use crate::SchemaDescriptor;
    use crate::SchemaPolicy;
    use crate::SessionEndpoint;
    use crate::SessionMacKey;
    use crate::WireCapabilities;
    use crate::WireVersion;

    use super::*;

    #[derive(Clone, Debug, Eq, PartialEq)]
    struct Message(String);

    struct Codec {
        descriptor: SchemaDescriptor,
    }

    impl PayloadCodec for Codec {
        type Value = Message;

        fn descriptor(&self) -> &SchemaDescriptor {
            &self.descriptor
        }

        fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
            Ok(value.0.as_bytes().to_vec())
        }

        fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
            let value = std::str::from_utf8(payload)
                .map_err(|_| SchemaCodecError::Rejected("message is not UTF-8"))?;
            Ok(Message(value.to_string()))
        }
    }

    struct Fixture {
        registry: Arc<FrozenSchemaRegistry>,
        codec: Codec,
        revision: Digest32,
        producer: StableId,
        role: StableId,
        required: WireCapabilities,
        offer: NegotiationOffer,
    }

    fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
        Ok(StableId::new(value)?)
    }

    fn fixture() -> Result<Fixture, Box<dyn Error>> {
        let schema = id("schema.hardened-stream.v1")?;
        let producer = id("producer.hardened-stream")?;
        let role = id("role.hardened-stream")?;
        let descriptor =
            SchemaDescriptor::new(schema, WireVersion::V2, WireVersion::V2, 1024)?;
        let revision = Digest32::of_bytes(b"hardened-stream-revision-v1");
        let required = WireCapabilities::METADATA_BOUND_DIGEST
            .union(WireCapabilities::SCHEMA_ADMISSION)
            .union(WireCapabilities::STREAM_DECODING);
        let policy = SchemaPolicy::new_bound(
            descriptor.clone(),
            revision,
            GenerationPolicy::NonZero,
            CanonicalizationProfile::CanonicalJsonV1,
            vec![producer.clone()],
            vec![role.clone()],
            required,
        )?;
        let mut builder = FrozenSchemaRegistryBuilder::new();
        builder.register(policy)?;
        Ok(Fixture {
            registry: Arc::new(builder.freeze()?),
            codec: Codec { descriptor },
            revision,
            producer,
            role,
            required,
            offer: NegotiationOffer::current(),
        })
    }

    fn owner(
        fixture: &Fixture,
        endpoint: SessionEndpoint,
    ) -> Result<HardenedManagedWireSession, Box<dyn Error>> {
        Ok(HardenedManagedWireSession::establish(
            &fixture.offer,
            &fixture.offer,
            fixture.required,
            fixture.role.clone(),
            Arc::clone(&fixture.registry),
            &[0x61; 32],
            SessionMacKey::new([0x27; 32])?,
            endpoint,
        )?)
    }

    #[test]
    fn fragmented_record_delivers_only_a_typed_value() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let sender_binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let receiver_binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let mut sender = owner(&fixture, SessionEndpoint::Initiator)?;
        let record = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(1)?,
            &sender_binding,
            &Message("fragmented".to_string()),
        )?;
        let mut stream = owner(&fixture, SessionEndpoint::Responder)?
            .into_record_stream(receiver_binding, RecordStreamLimits::default())?;

        let split = record.len() / 2;
        let first = stream.feed(&record[..split]);
        assert!(first.batch().values().is_empty());
        assert_eq!(first.bytes_consumed(), split);
        let second = stream.feed(&record[split..]);
        assert_eq!(
            second.batch().values(),
            &[Message("fragmented".to_string())]
        );
        assert!(second.batch().terminal_error().is_none());
        Ok(())
    }

    #[test]
    fn valid_prefix_is_delivered_before_terminal_suffix() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let sender_binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let receiver_binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let mut sender = owner(&fixture, SessionEndpoint::Initiator)?;
        let first = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(1)?,
            &sender_binding,
            &Message("first".to_string()),
        )?;
        let mut second = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(2)?,
            &sender_binding,
            &Message("second".to_string()),
        )?;
        let last = second.len() - 1;
        second[last] ^= 1;
        let mut input = first;
        input.extend_from_slice(&second);

        let mut stream = owner(&fixture, SessionEndpoint::Responder)?
            .into_record_stream(receiver_binding, RecordStreamLimits::default())?;
        let feed = stream.feed(&input);
        assert_eq!(feed.batch().values(), &[Message("first".to_string())]);
        assert!(matches!(
            feed.batch().terminal_error(),
            Some(HardenedRecordStreamError::Session(_))
        ));
        assert!(stream.is_terminal());
        Ok(())
    }

    #[test]
    fn frame_work_budget_yields_without_consuming_the_record() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let sender_binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let receiver_binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let mut sender = owner(&fixture, SessionEndpoint::Initiator)?;
        let record = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(1)?,
            &sender_binding,
            &Message("budget".to_string()),
        )?;
        let required = record.len() - PREFIX_BYTES - TAG_BYTES;
        let mut stream = owner(&fixture, SessionEndpoint::Responder)?
            .into_record_stream(receiver_binding, RecordStreamLimits::default())?;
        let mut small = HardenedRecordStreamBudget::with_frame_bytes(
            record.len(),
            1,
            required - 1,
        );
        let blocked = stream.feed_with_budget(&record, &mut small);
        assert_eq!(blocked.bytes_consumed(), 0);
        assert_eq!(blocked.batch().required_frame_bytes(), Some(required));
        assert!(blocked.batch().yielded());
        assert!(!stream.is_terminal());

        let mut enough =
            HardenedRecordStreamBudget::with_frame_bytes(record.len(), 1, required);
        let admitted = stream.feed_with_budget(&record, &mut enough);
        assert_eq!(admitted.batch().values(), &[Message("budget".to_string())]);
        Ok(())
    }

    #[test]
    fn eof_with_a_partial_record_is_terminal() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let mut stream = owner(&fixture, SessionEndpoint::Responder)?
            .into_record_stream(binding, RecordStreamLimits::default())?;
        let prefix = [0_u8; 3];
        let feed = stream.feed(&prefix);
        assert_eq!(feed.bytes_consumed(), prefix.len());
        assert!(matches!(
            stream.finish(),
            Err(HardenedRecordStreamError::UnexpectedEof { .. })
        ));
        Ok(())
    }
}
