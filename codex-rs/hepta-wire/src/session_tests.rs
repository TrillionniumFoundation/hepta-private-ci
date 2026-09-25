use super::*;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::NegotiationOffer;
use crate::WireCapabilities;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::negotiate;

fn stable(value: &str) -> Result<StableId, Box<dyn Error>> {
    Ok(StableId::new(value)?)
}

#[test]
fn negotiated_v2_session_rejects_v1_frame_and_stays_poisoned() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v1 = WireEnvelope::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();

    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    assert!(matches!(
        decoder.push(&v1),
        Err(NegotiatedDecodeError::VersionMismatch {
            negotiated: WireVersion::V2,
            observed: WireVersion::V1,
        })
    ));
    assert!(decoder.is_poisoned());
    assert!(matches!(
        decoder.push(&[]),
        Err(NegotiatedDecodeError::VersionMismatch { .. })
    ));
    Ok(())
}

#[test]
fn negotiated_session_preserves_valid_prefix_before_version_mismatch() -> Result<(), Box<dyn Error>>
{
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v2 =
        WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(2)?, vec![2])?.encode();
    let v1 = WireEnvelope::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    let mut chunk = v2;
    chunk.extend_from_slice(&v1);

    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    let batch = decoder.push_batch(&chunk);
    assert_eq!(batch.frames().len(), 1);
    assert_eq!(batch.frames()[0].version(), WireVersion::V2);
    assert!(matches!(
        batch.terminal_error(),
        Some(NegotiatedDecodeError::VersionMismatch {
            negotiated: WireVersion::V2,
            observed: WireVersion::V1,
        })
    ));
    Ok(())
}

#[test]
fn v1_session_does_not_report_v2_metadata_binding_as_effective() -> Result<(), Box<dyn Error>> {
    let v1_only = NegotiationOffer::new(vec![1], WireCapabilities::CURRENT)?;
    let negotiated = negotiate(
        &v1_only,
        &NegotiationOffer::current(),
        WireCapabilities::NONE,
    )?;
    assert_eq!(negotiated.version, WireVersion::V1);
    assert!(
        negotiated
            .common_advertised_capabilities
            .contains(WireCapabilities::METADATA_BOUND_DIGEST)
    );
    assert!(
        !negotiated
            .capabilities
            .contains(WireCapabilities::METADATA_BOUND_DIGEST)
    );
    Ok(())
}

#[test]
fn negotiated_version_is_rejected_at_header_before_body_arrives() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v1 = WireEnvelope::new(
        stable("s")?,
        stable("p")?,
        Generation::new(1)?,
        vec![1; crate::MAX_WIRE_PAYLOAD_BYTES],
    )?
    .encode();
    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    let batch = decoder.push_batch(&v1[..crate::WIRE_HEADER_BYTES]);
    assert!(batch.frames().is_empty());
    assert_eq!(
        batch.terminal_error(),
        Some(&NegotiatedDecodeError::VersionMismatch {
            negotiated: WireVersion::V2,
            observed: WireVersion::V1,
        })
    );
    assert_eq!(decoder.buffered_len(), 0);
    assert!(decoder.is_poisoned());
    Ok(())
}

#[test]
fn negotiated_header_error_preserves_prefix_at_every_split() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v2 = WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(2)?, vec![2])?;
    let v1 = WireEnvelope::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    let mut bytes = v2.encode();
    bytes.extend_from_slice(&v1[..crate::WIRE_HEADER_BYTES]);
    // The peer stops after an incompatible header; no body is required to reject it.
    for split in 0..=bytes.len() {
        let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
        let (mut frames, first_error) = decoder.push_batch(&bytes[..split]).into_parts();
        let (tail, last_error) = decoder.push_batch(&bytes[split..]).into_parts();
        frames.extend(tail);
        assert_eq!(frames, vec![DecodedEnvelope::V2(v2.clone())]);
        assert_eq!(
            first_error.or(last_error),
            Some(NegotiatedDecodeError::VersionMismatch {
                negotiated: WireVersion::V2,
                observed: WireVersion::V1,
            }),
            "split {split}"
        );
        assert_eq!(decoder.buffered_len(), 0, "split {split}");
    }
    Ok(())
}

#[test]
fn negotiated_mismatch_discards_following_partial_frame() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v1 = WireEnvelope::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    let large = WireEnvelopeV2::new(
        stable("s")?,
        stable("p")?,
        Generation::new(2)?,
        vec![2; crate::MAX_WIRE_PAYLOAD_BYTES],
    )?
    .encode();
    let mut chunk = v1;
    chunk.extend_from_slice(&large[..large.len() - 1]);
    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    let batch = decoder.push_batch(&chunk);
    assert!(matches!(
        batch.terminal_error(),
        Some(NegotiatedDecodeError::VersionMismatch { .. })
    ));
    assert_eq!(decoder.buffered_len(), 0);
    let later = decoder.push_batch(&large);
    assert!(later.frames().is_empty());
    assert_eq!(later.terminal_error(), batch.terminal_error());
    Ok(())
}
