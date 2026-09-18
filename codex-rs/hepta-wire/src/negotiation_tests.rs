use super::*;

fn offer(
    versions: &[WireVersion],
    supported: &[WireFeature],
    required: &[WireFeature],
) -> WireOffer {
    let Ok(value) = WireOffer::new(versions, supported, required) else {
        panic!("test offer rejected");
    };
    value
}

#[test]
fn highest_common_version_is_selected() {
    let features = [
        WireFeature::FullFrameDigest,
        WireFeature::SchemaAdmission,
        WireFeature::TypedPayload,
    ];
    let local = offer(&[WireVersion::V1, WireVersion::V2], &features, &[]);
    let remote = offer(&[WireVersion::V1, WireVersion::V2], &features, &[]);
    let Ok(negotiated) = negotiate(&local, &remote) else {
        panic!("compatible offers rejected");
    };
    assert_eq!(negotiated.version(), WireVersion::V2);
    assert!(
        negotiated
            .features()
            .contains(&WireFeature::FullFrameDigest)
    );
}

#[test]
fn required_v2_integrity_prevents_downgrade_to_v1() {
    let local = offer(
        &[WireVersion::V1, WireVersion::V2],
        &[WireFeature::FullFrameDigest],
        &[WireFeature::FullFrameDigest],
    );
    let remote = offer(
        &[WireVersion::V1],
        &[WireFeature::FullFrameDigest],
        &[],
    );
    assert_eq!(
        negotiate(&local, &remote),
        Err(NegotiationError::NoCompatibleVersion)
    );
}

#[test]
fn missing_required_capability_fails_closed() {
    let local = offer(
        &[WireVersion::V2],
        &[WireFeature::SchemaAdmission],
        &[WireFeature::SchemaAdmission],
    );
    let remote = offer(&[WireVersion::V2], &[], &[]);
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
