use std::error::Error;
use std::io::Cursor;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

fn v2(payload: &[u8]) -> Result<WireEnvelopeV2, Box<dyn Error>> {
    Ok(WireEnvelopeV2::new(
        StableId::new("hepta.stream.v2")?,
        StableId::new("platform.wire")?,
        Generation::new(3)?,
        payload.to_vec(),
    )?)
}

#[test]
fn reads_two_frames_without_overreading() -> Result<(), Box<dyn Error>> {
    let first = v2(b"first")?.encode();
    let second = v2(b"second")?.encode();
    let mut bytes = first;
    bytes.extend_from_slice(&second);
    let mut cursor = Cursor::new(bytes);

    assert_eq!(read_envelope(&mut cursor)?.payload(), b"first");
    assert_eq!(read_envelope(&mut cursor)?.payload(), b"second");
    Ok(())
}

#[test]
fn rejects_oversize_header_before_reading_body() -> Result<(), Box<dyn Error>> {
    let mut header = v2(b"x")?.encode()[..WIRE_HEADER_BYTES].to_vec();
    header[50..54].copy_from_slice(&(MAX_WIRE_PAYLOAD_BYTES as u32 + 1).to_be_bytes());
    let mut cursor = Cursor::new(header);
    assert!(matches!(
        read_envelope(&mut cursor),
        Err(StreamDecodeError::PayloadLength)
    ));
    Ok(())
}

#[test]
fn every_stream_truncation_rejects() -> Result<(), Box<dyn Error>> {
    let encoded = v2(b"stream-truncation")?.encode();
    for length in 0..encoded.len() {
        let mut cursor = Cursor::new(&encoded[..length]);
        assert!(read_envelope(&mut cursor).is_err(), "prefix {length}");
    }
    Ok(())
}
