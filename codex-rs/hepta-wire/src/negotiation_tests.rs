use super::*;

#[test]
fn highest_common_version_is_selected() {
    let features = [
        WireFeature::FullFrameDigest,
        WireFeature::SchemaAdmission,
        WireFeature::TypedPayload,
    ];
    let local = WireOffer::new(&[WireVersion::V1, WireVersion::V2], &features, &[])
        .expect("local offer");
    let remote = WireOffer::new(&[WireVersion::V1, WireVersion::V2], &features, &[])
        .expect("remote offer");
    let negotiated = negotiate(&local, &remote).expect("compatible offers");
    assert_eq!(negotiated.version(), WireVersion::V2);
    assert!(
        negotiated
            .features()
            .contains(&WireFeature::FullFrameDigest)
    );
}

#[test]
fn required_v2_integrity_prevents_downgrade_to_v1() {
    let local = WireOffer::new(
        &[WireVersion::V1, WireVersion::V2],
        &[WireFeature::FullFrameDigest],
        &[WireFeature::FullFrameDigest],
    )
    .expect("local offer");
    let remote = WireOffer::new(
        &[WireVersion::V1],
        &[WireFeature::FullFrameDigest],
        &[],
    )
    .expect("remote offer");
    assert_eq!(
        negotiate(&local, &remote),
        Err(NegotiationError::NoCompatibleVersion)
    );
}

#[test]
fn missing_required_capability_fails_closed() {
    let local = WireOffer::new(
        &[WireVersion::V2],
        &[WireFeature::SchemaAdmission],
        &[WireFeature::SchemaAdmission],
    )
    .expect("local offer");
    let remote = WireOffer::new(&[WireVersion::V2], &[], &[]).expect("remote offer");
    assert_eq!(
        negotiate(&local, &remote),
        Err(NegotiationError::RequiredFeatureUnavailable(
            WireFeature::SchemaAdmission
        ))
    );
}

#[test]
fn duplicate_or_self_inconsistent_offer_rejects() {
    assert_eq!(
        WireOffer::new(&[WireVersion::V1, WireVersion::V1], &[], &[]),
        Err(NegotiationError::DuplicateOfferItem)
    );
    assert_eq!(
        WireOffer::new(
            &[WireVersion::V2],
            &[],
            &[WireFeature::FullFrameDigest]
        ),
        Err(NegotiationError::RequiredFeatureNotAdvertised(
            WireFeature::FullFrameDigest
        ))
    );
}
