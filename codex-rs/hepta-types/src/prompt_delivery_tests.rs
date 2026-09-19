use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn observation() -> PromptDeliveryObservationV1 {
    PromptDeliveryObservationV1 {
        compilation_id: id("compilation:1"),
        provider_request_digest: Digest32::of_bytes(b"provider-request"),
        delivered: true,
        rejected_reason: None,
        observed_token_positions: Some(vec![1, 5, 9]),
        truncation_observed: false,
    }
}

#[test]
fn semantic_digest_is_deterministic_and_field_complete() {
    let first = observation();
    let mut second = first.clone();
    assert_eq!(
        first.semantic_digest().expect("valid digest"),
        second.semantic_digest().expect("valid digest")
    );

    second
        .observed_token_positions
        .as_mut()
        .expect("positions")
        .push(12);
    assert_ne!(
        first.semantic_digest().expect("valid digest"),
        second.semantic_digest().expect("valid digest")
    );
}

#[test]
fn rejection_reason_is_open_but_bounded() {
    let reason = PromptDeliveryRejectReasonV1::new(id("provider_specific_rejection"))
        .expect("bounded stable reason");
    assert_eq!(reason.as_str(), "provider_specific_rejection");
}

#[test]
fn delivered_and_rejected_are_mutually_exclusive() {
    let mut value = observation();
    value.rejected_reason =
        Some(PromptDeliveryRejectReasonV1::new(id("provider_rejected")).expect("reason"));
    assert_eq!(
        value.validate(),
        Err(PromptDeliveryErrorV1::InvalidDisposition)
    );

    value.delivered = false;
    assert!(value.validate().is_ok());
}

#[test]
fn token_positions_are_optional_bounded_and_canonical() {
    let mut value = observation();
    value.observed_token_positions = Some(vec![3, 3]);
    assert_eq!(
        value.validate(),
        Err(PromptDeliveryErrorV1::NonCanonicalTokenPositions)
    );

    value.observed_token_positions = Some(Vec::new());
    assert_eq!(
        value.validate(),
        Err(PromptDeliveryErrorV1::EmptyTokenPositions)
    );

    value.observed_token_positions = Some(
        (0..=MAX_PROMPT_TOKEN_POSITIONS_V1)
            .map(|position| u32::try_from(position).expect("bounded"))
            .collect(),
    );
    assert_eq!(
        value.validate(),
        Err(PromptDeliveryErrorV1::TokenPositionLimitExceeded)
    );

    value.observed_token_positions = None;
    assert!(value.validate().is_ok());
}
