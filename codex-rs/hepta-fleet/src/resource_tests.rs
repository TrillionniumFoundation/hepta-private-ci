use super::*;
use pretty_assertions::assert_eq;

#[test]
fn logical_and_physical_vectors_have_explicit_compatible_axes() {
    let physical = ResourceVectorV1::physical(4_000, 16 * 1024 * 1024, 1_000);
    let logical = ResourceVectorV1::logical(4, 8, 8, 32).expect("logical resources");

    assert!(physical.supports(ResourceAxisV1::CpuMillis));
    assert!(!physical.supports(ResourceAxisV1::ConcurrentTurns));
    assert!(logical.supports(ResourceAxisV1::ConcurrentTurns));
    assert!(!logical.fits(physical));
}

#[test]
fn arithmetic_preserves_axis_identity_and_rejects_underflow() {
    let first = ResourceVectorV1::physical(300, 1_024, 0);
    let second = ResourceVectorV1::physical(200, 2_048, 0);
    let total = first.checked_add(second).expect("sum");

    assert_eq!(total, ResourceVectorV1::physical(500, 3_072, 0));
    assert_eq!(
        first.checked_sub(second),
        Err(ResourceVectorError::ArithmeticUnderflow)
    );
}

#[test]
fn semantic_digest_binds_axis_mask_and_values() {
    let first = ResourceVectorV1::physical(300, 1_024, 0);
    let mut changed = first;
    changed.cpu_millis += 1;

    assert_ne!(
        first.semantic_digest().expect("first digest"),
        changed.semantic_digest().expect("changed digest")
    );
}
