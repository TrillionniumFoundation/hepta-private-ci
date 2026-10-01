#![no_main]

mod hardened_fixture;
mod managed_fixture;

use codex_hepta_wire::MAX_WIRE_FRAME_BYTES;
use codex_hepta_wire::RecordStreamLimits;
use codex_hepta_wire::SessionEndpoint;
use libfuzzer_sys::fuzz_target;
use managed_fixture::Outcome;
use managed_fixture::envelope;
use managed_fixture::owner;

fn exercise(data: &[u8]) -> Outcome {
    let mode = data.first().copied().unwrap_or(0) % 7;
    let chunk_size = usize::from(data.get(1).copied().unwrap_or(0)) + 1;
    let payload = data.get(2..).unwrap_or_default();
    let expected = envelope(payload, "producer.managed-fuzz")?;
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let record = sender.seal_envelope(&expected)?;
    let mut bytes = record.clone();
    if mode == 1 {
        let index = chunk_size % bytes.len();
        bytes[index] ^= 1;
    } else if mode == 2 {
        bytes.extend_from_slice(&record);
    } else if mode == 5 {
        // A permitted maximum declaration with one body byte must not reserve
        // the announced body or become accepted before consuming EOF.
        bytes[46..50].copy_from_slice(&u32::try_from(MAX_WIRE_FRAME_BYTES)?.to_be_bytes());
        bytes.truncate(51);
    } else if mode == 6 {
        // Next sequence with a corrupted MAC: preserve the authenticated prefix.
        let mut second = sender.seal_envelope(&expected)?;
        let end = second.len() - 1;
        second[end] ^= 1;
        bytes.extend(second);
    }
    let channel = if mode == 3 { 2 } else { 1 };
    let endpoint = if mode == 4 {
        SessionEndpoint::Initiator
    } else {
        SessionEndpoint::Responder
    };
    let limits = RecordStreamLimits {
        max_feed_bytes: 37,
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut stream = owner(channel, endpoint)?.into_record_stream(limits)?;
    let mut accepted = Vec::new();
    'chunks: for chunk in bytes.chunks(chunk_size) {
        let mut offset = 0;
        while offset < chunk.len() {
            let feed = stream.feed(&chunk[offset..]);
            let consumed = feed.bytes_consumed();
            assert!(consumed <= 37 && consumed <= chunk.len() - offset);
            let (batch, _) = feed.into_parts();
            let (frames, error) = batch.into_parts();
            accepted.extend(frames);
            if error.is_some() {
                assert!(stream.is_terminal());
                assert_eq!(stream.buffer_capacity_bytes(), 0);
                assert!(stream.feed(&record).batch().frames().is_empty());
                assert!(stream.seal_envelope(&expected).is_err());
                break 'chunks;
            }
            assert!(consumed > 0);
            offset += consumed;
            if mode == 5 {
                assert!(stream.buffer_capacity_bytes() <= 102);
            }
        }
    }
    if mode == 0 {
        assert_eq!(accepted, vec![expected]);
        stream.finish()?;
    } else {
        if mode == 2 || mode == 6 {
            assert_eq!(accepted, vec![expected]);
        } else {
            assert!(accepted.is_empty());
        }
        assert!(stream.finish().is_err());
    }
    Ok(())
}

fuzz_target!(|data: &[u8]| {
    assert!(
        exercise(data).is_ok(),
        "managed-session fixture or invariant failed"
    );
    assert!(
        hardened_fixture::exercise(data).is_ok(),
        "hardened-session fixture or invariant failed"
    );
});
