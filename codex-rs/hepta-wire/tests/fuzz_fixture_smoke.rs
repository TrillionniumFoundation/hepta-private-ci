//! Compile and exercise the actual managed fuzz fixture in ordinary native CI.

#[path = "../fuzz/fuzz_targets/managed_fixture.rs"]
mod fixture;

use std::error::Error;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::SessionEndpoint;
use codex_hepta_wire::WireEnvelopeV2;

#[test]
fn short_corpus_uses_legal_fixture_without_widening_frozen_payload_contract()
-> Result<(), Box<dyn Error>> {
    assert!(
        WireEnvelopeV2::new(
            StableId::new("schema.managed-fuzz.v1")?,
            StableId::new("producer.managed-fuzz")?,
            Generation::new(1)?,
            Vec::new(),
        )
        .is_err()
    );
    for payload in [&[][..], &[0][..], &[1, 2][..]] {
        let frame = fixture::envelope(payload, "producer.managed-fuzz")?;
        assert!(!frame.payload().is_empty());
        assert_eq!(frame.payload().len(), payload.len().max(1));
        let mut sender = fixture::owner(1, SessionEndpoint::Initiator)?;
        let mut receiver = fixture::owner(1, SessionEndpoint::Responder)?;
        let record = sender.seal_envelope(&frame)?;
        assert_eq!(receiver.open_record(&record)?, frame);
        let denied = fixture::envelope(payload, "producer.not-admitted")?;
        assert!(fixture::session(1)?.decode_frame(&denied.encode()).is_err());
    }
    Ok(())
}
