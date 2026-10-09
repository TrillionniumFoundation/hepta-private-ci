use super::*;

#[test]
fn clone_is_shared_and_digest_matches_v1_domain() {
    let original = SharedFeatureBufferV1::from_vec(vec![0, 1 << 24, -(1 << 24)]).unwrap();
    let clone = original.clone();
    assert!(original.shares_allocation_with(&clone));
    assert_eq!(clone.digest(), canonical_shared_feature_digest_v1(original.as_slice()));
    assert_eq!(
        SharedFeatureBufferV1::from_expected_digest(
            Arc::from(vec![0, 1 << 24, -(1 << 24)]),
            original.digest()
        )
        .unwrap()
        .digest(),
        original.digest()
    );
}

#[test]
fn refuses_invalid_and_swapped_payloads() {
    assert_eq!(SharedFeatureBufferV1::from_vec(vec![]), Err(SharedFeatureErrorV1::Width));
    assert_eq!(
        SharedFeatureBufferV1::from_vec(vec![8 * Q24 + 1]),
        Err(SharedFeatureErrorV1::OutOfRange)
    );
    assert_eq!(
        SharedFeatureBufferV1::from_expected_digest(
            Arc::from(vec![0_i64]), Digest32::of_bytes(b"wrong")
        ),
        Err(SharedFeatureErrorV1::DigestMismatch)
    );
}
