use super::*;

#[test]
fn current_offer_matches_frozen_negotiation_bytes() -> Result<(), Box<dyn Error>> {
    let offer = NegotiationOffer::current();
    let encoded = offer.encode();
    let golden: [u8; 20] = [
        0x48, 0x50, 0x54, 0x4e, 0x00, 0x01, 0x02, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x07, 0x00, 0x01, 0x00, 0x02,
    ];
    assert_eq!(encoded, golden);
    assert_eq!(NegotiationOffer::decode(&golden)?, offer);
    Ok(())
}

#[test]
fn negotiation_selects_highest_explicit_common_version() -> Result<(), Box<dyn Error>> {
    let local = NegotiationOffer::current();
    let remote = NegotiationOffer::new(
        vec![1, 2],
        WireCapabilities::METADATA_BOUND_DIGEST
            .union(WireCapabilities::SCHEMA_ADMISSION)
            .union(WireCapabilities::STREAM_DECODING),
    )?;
    let negotiated = negotiate(
        &local,
        &remote,
        WireCapabilities::METADATA_BOUND_DIGEST
            .union(WireCapabilities::SCHEMA_ADMISSION),
    )?;
    assert_eq!(negotiated.version, WireVersion::V2);
    assert!(negotiated
        .capabilities
        .contains(WireCapabilities::METADATA_BOUND_DIGEST));
    Ok(())
}

#[test]
fn required_metadata_binding_prevents_v1_downgrade() -> Result<(), Box<dyn Error>> {
    let local = NegotiationOffer::current();
    let remote = NegotiationOffer::new(
        vec![1],
        WireCapabilities::METADATA_BOUND_DIGEST
            .union(WireCapabilities::SCHEMA_ADMISSION)
            .union(WireCapabilities::STREAM_DECODING),
    )?;
    assert!(matches!(
        negotiate(
            &local,
            &remote,
            WireCapabilities::METADATA_BOUND_DIGEST
        ),
        Err(NegotiationError::MissingRequiredCapabilities { .. })
    ));
    assert_eq!(
        negotiate(&local, &remote, WireCapabilities::NONE)?.version,
        WireVersion::V1
    );
    Ok(())
}

#[test]
fn negotiation_hello_rejects_unknown_bits_and_noncanonical_versions() {
    let mut unknown = NegotiationOffer::current().encode();
    unknown[15] |= 0x80;
    assert!(matches!(
        NegotiationOffer::decode(&unknown),
        Err(NegotiationError::UnknownCapabilities(_))
    ));

    let mut noncanonical = NegotiationOffer::current().encode();
    noncanonical[16..18].copy_from_slice(&2_u16.to_be_bytes());
    noncanonical[18..20].copy_from_slice(&1_u16.to_be_bytes());
    assert_eq!(
        NegotiationOffer::decode(&noncanonical),
        Err(NegotiationError::NonCanonicalVersions)
    );
}

#[test]
fn future_version_numbers_are_advertised_but_not_invented() -> Result<(), Box<dyn Error>> {
    let local = NegotiationOffer::current();
    let remote = NegotiationOffer::new(vec![2, 99], WireCapabilities::CURRENT)?;
    let negotiated = negotiate(&local, &remote, WireCapabilities::NONE)?;
    assert_eq!(negotiated.version, WireVersion::V2);

    let future_only = NegotiationOffer::new(vec![99], WireCapabilities::CURRENT)?;
    assert_eq!(
        negotiate(&local, &future_only, WireCapabilities::NONE),
        Err(NegotiationError::NoCommonVersion)
    );
    Ok(())
}
