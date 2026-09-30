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
        channel: u8,
    ) -> Result<HardenedManagedWireSession, Box<dyn Error>> {
        Ok(HardenedManagedWireSession::establish(
            &fixture.offer,
            &fixture.offer,
            fixture.required,
            fixture.role.clone(),
            Arc::clone(&fixture.registry),
            &[channel; 32],
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
        let mut sender = owner(&fixture, SessionEndpoint::Initiator, /*channel*/ 0x61)?;
        let record = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(1)?,
            &sender_binding,
            &Message("fragmented".to_string()),
        )?;
        let mut stream = owner(&fixture, SessionEndpoint::Responder, /*channel*/ 0x61)?
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
        let mut sender = owner(&fixture, SessionEndpoint::Initiator, /*channel*/ 0x61)?;
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

        let mut stream = owner(&fixture, SessionEndpoint::Responder, /*channel*/ 0x61)?
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
        let mut sender = owner(&fixture, SessionEndpoint::Initiator, /*channel*/ 0x61)?;
        let record = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(1)?,
            &sender_binding,
            &Message("budget".to_string()),
        )?;
        let required = record.len() - PREFIX_BYTES - TAG_BYTES;
        let mut stream = owner(&fixture, SessionEndpoint::Responder, /*channel*/ 0x61)?
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
    fn byte_by_byte_records_preserve_typed_prefix_and_terminal_mac_error()
    -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let expected = [Message("first".to_string()), Message("second".to_string())];
        let mut sender = owner(&fixture, SessionEndpoint::Initiator, /*channel*/ 0x61)?;
        let mut input = Vec::new();
        let mut record_ends = Vec::new();
        for (index, value) in expected.iter().enumerate() {
            let record = sender.seal_bound_typed(
                fixture.producer.clone(),
                Generation::new(index as u64 + 1)?,
                &binding,
                value,
            )?;
            input.extend_from_slice(&record);
            record_ends.push(input.len());
        }
        let mut invalid = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(3)?,
            &binding,
            &Message("rejected".to_string()),
        )?;
        *invalid.last_mut().ok_or("empty record")? ^= 1;
        input.extend_from_slice(&invalid);
        let mut stream = owner(&fixture, SessionEndpoint::Responder, /*channel*/ 0x61)?
            .into_record_stream(binding, RecordStreamLimits::default())?;
        let mut delivered = Vec::new();
        for (index, byte) in input.iter().enumerate() {
            let feed = stream.feed(std::slice::from_ref(byte));
            assert_eq!(feed.bytes_consumed(), 1);
            let (values, error) = feed.into_parts().0.into_parts();
            if record_ends.contains(&(index + 1)) {
                assert_eq!(values.len(), 1);
            } else {
                assert!(values.is_empty());
            }
            delivered.extend(values);
            if index + 1 == input.len() {
                assert!(matches!(error, Some(HardenedRecordStreamError::Session(_))));
            } else {
                assert!(error.is_none());
            }
        }
        assert_eq!(delivered, expected);
        assert!(stream.is_terminal());
        assert_eq!(stream.buffer_capacity_bytes(), 0);
        let retry = stream.feed(&input);
        assert_eq!(retry.bytes_consumed(), 0);
        assert!(retry.batch().values().is_empty());
        assert!(matches!(
            retry.batch().terminal_error(),
            Some(HardenedRecordStreamError::Terminated)
        ));
        Ok(())
    }

    #[test]
    fn shared_budget_charges_full_frames_completed_by_one_byte_suffixes()
    -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let expected = Message("already buffered work".to_string());
        let mut streams = Vec::new();
        let mut records = Vec::new();
        for channel in [0x61, 0x62] {
            let mut sender = owner(&fixture, SessionEndpoint::Initiator, channel)?;
            let record = sender.seal_bound_typed(
                fixture.producer.clone(),
                Generation::new(1)?,
                &binding,
                &expected,
            )?;
            let receiver_binding = PayloadCodecBinding::new(
                &fixture.codec,
                fixture.revision,
                CanonicalizationProfile::CanonicalJsonV1,
            )?;
            let mut stream = owner(&fixture, SessionEndpoint::Responder, channel)?
                .into_record_stream(receiver_binding, RecordStreamLimits::default())?;
            let prefix = stream.feed(&record[..record.len() - 1]);
            assert_eq!(prefix.bytes_consumed(), record.len() - 1);
            assert!(prefix.batch().values().is_empty());
            assert!(prefix.batch().terminal_error().is_none());
            streams.push(stream);
            records.push(record);
        }
        let required = records[0].len() - PREFIX_BYTES - TAG_BYTES;
        let mut shared = HardenedRecordStreamBudget::with_frame_bytes(2, 2, required);
        let first = streams[0].feed_with_budget(&records[0][records[0].len() - 1..], &mut shared);
        assert_eq!(first.bytes_consumed(), 1);
        assert_eq!(first.batch().values(), std::slice::from_ref(&expected));
        assert_eq!(shared.remaining_frame_bytes(), 0);
        assert_eq!(shared.remaining_bytes(), 1);
        assert_eq!(shared.remaining_records(), 1);
        let blocked = streams[1].feed_with_budget(&records[1][records[1].len() - 1..], &mut shared);
        assert_eq!(blocked.bytes_consumed(), 0);
        assert_eq!(blocked.batch().required_frame_bytes(), Some(required));
        assert!(blocked.batch().yielded());
        assert!(blocked.batch().values().is_empty());
        assert!(blocked.batch().terminal_error().is_none());
        assert!(!streams[1].is_terminal());
        let mut next = HardenedRecordStreamBudget::with_frame_bytes(1, 1, required);
        let resumed = streams[1].feed_with_budget(&records[1][records[1].len() - 1..], &mut next);
        assert_eq!(resumed.bytes_consumed(), 1);
        assert_eq!(resumed.batch().values(), std::slice::from_ref(&expected));
        assert_eq!(next.remaining_frame_bytes(), 0);
        Ok(())
    }

    #[test]
    fn every_partial_record_rejects_eof_before_typed_delivery() -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let mut sender = owner(&fixture, SessionEndpoint::Initiator, /*channel*/ 0x61)?;
        let record = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(1)?,
            &binding,
            &Message("complete authenticated value".to_string()),
        )?;
        for cut in 1..record.len() {
            let receiver_binding = PayloadCodecBinding::new(
                &fixture.codec,
                fixture.revision,
                CanonicalizationProfile::CanonicalJsonV1,
            )?;
            let mut stream = owner(&fixture, SessionEndpoint::Responder, /*channel*/ 0x61)?
                .into_record_stream(receiver_binding, RecordStreamLimits::default())?;
            let partial = stream.feed(&record[..cut]);
            assert_eq!(partial.bytes_consumed(), cut);
            assert!(partial.batch().values().is_empty());
            assert!(partial.batch().terminal_error().is_none());
            let expected = if cut < PREFIX_BYTES { PREFIX_BYTES } else { record.len() };
            assert!(matches!(
                stream.finish(),
                Err(HardenedRecordStreamError::UnexpectedEof { buffered, expected: length })
                    if buffered == cut && length == expected
            ), "cut {cut}");
        }
        Ok(())
    }

    #[test]
    fn completed_large_record_does_not_pin_capacity_for_following_short_prefix()
    -> Result<(), Box<dyn Error>> {
        let fixture = fixture()?;
        let binding = PayloadCodecBinding::new(
            &fixture.codec,
            fixture.revision,
            CanonicalizationProfile::CanonicalJsonV1,
        )?;
        let expected = Message("x".repeat(1024));
        let mut sender = owner(&fixture, SessionEndpoint::Initiator, /*channel*/ 0x61)?;
        let record = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(1)?,
            &binding,
            &expected,
        )?;
        let following = sender.seal_bound_typed(
            fixture.producer.clone(),
            Generation::new(2)?,
            &binding,
            &Message("next".to_string()),
        )?;
        let mut stream = owner(&fixture, SessionEndpoint::Responder, /*channel*/ 0x61)?
            .into_record_stream(binding, RecordStreamLimits {
                max_feed_bytes: 128,
                ..RecordStreamLimits::default()
            })?;
        let mut input = record;
        input.extend_from_slice(&following[..3]);
        let mut offset = 0;
        let mut delivered = Vec::new();
        while offset < input.len() {
            let feed = stream.feed(&input[offset..]);
            assert!(feed.bytes_consumed() > 0);
            offset += feed.bytes_consumed();
            let (values, error) = feed.into_parts().0.into_parts();
            assert!(error.is_none());
            delivered.extend(values);
        }
        assert_eq!(delivered, [expected]);
        assert_eq!(stream.buffered_bytes(), 3);
        assert!(stream.buffer_capacity_bytes() <= stream.idle_buffer_limit_bytes());
        let mut offset = 3;
        let mut delivered = Vec::new();
        while offset < following.len() {
            let feed = stream.feed(&following[offset..]);
            assert!(feed.bytes_consumed() > 0);
            offset += feed.bytes_consumed();
            let (values, error) = feed.into_parts().0.into_parts();
            assert!(error.is_none());
            delivered.extend(values);
        }
        assert_eq!(delivered, [Message("next".to_string())]);
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
        let mut stream = owner(&fixture, SessionEndpoint::Responder, /*channel*/ 0x61)?
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
