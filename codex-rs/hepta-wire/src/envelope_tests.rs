use super::*;

fn id(value: &str) -> StableId {
    let result = StableId::new(value);
    let Ok(value) = result else {
        panic!("test identifier rejected");
    };
    value
}

fn generation() -> Generation {
    let result = Generation::new(7);
    let Ok(value) = result else {
        panic!("test generation rejected");
    };
    value
}

#[test]
fn envelope_round_trip_is_exact() {
    let envelope = WireEnvelope::new(
        id("hepta.test.v1"),
        id("platform.wire"),
        generation(),
        b"bounded-payload".to_vec(),
    );
    let Ok(envelope) = envelope else {
        panic!("valid envelope rejected");
    };
    assert_eq!(WireEnvelope::decode(&envelope.encode()), Ok(envelope));
}

#[test]
fn payload_tamper_and_trailing_bytes_fail_closed() {
    let envelope = WireEnvelope::new(
        id("hepta.test.v1"),
        id("platform.wire"),
        generation(),
        vec![1, 2, 3],
    );
    let Ok(envelope) = envelope else {
        panic!("valid envelope rejected");
    };
    let mut tampered = envelope.encode();
    let final_index = tampered.len() - 1;
    tampered[final_index] ^= 1;
    assert!(matches!(
        WireEnvelope::decode(&tampered),
        Err(WireError::DigestMismatch { .. })
    ));
    let mut trailing = envelope.encode();
    trailing.push(0);
    assert_eq!(
        WireEnvelope::decode(&trailing),
        Err(WireError::LengthMismatch)
    );
}

#[test]
fn unknown_version_and_empty_payload_are_rejected() {
    assert_eq!(
        WireEnvelope::new(
            id("hepta.test.v1"),
            id("platform.wire"),
            generation(),
            Vec::new()
        ),
        Err(WireError::PayloadLength)
    );
    let envelope = WireEnvelope::new(
        id("hepta.test.v1"),
        id("platform.wire"),
        generation(),
        vec![1],
    );
    let Ok(envelope) = envelope else {
        panic!("valid envelope rejected");
    };
    let mut encoded = envelope.encode();
    encoded[5] = 2;
    assert_eq!(WireEnvelope::decode(&encoded), Err(WireError::Version(2)));
}
