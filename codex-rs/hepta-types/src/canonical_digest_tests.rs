use super::*;
use crate::IdProfileV1;
use crate::validate_id;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn expected_digest() -> Digest32 {
    checked(
        "b2dd7cbfbd9b6d6635f32ca616beadb135c7f7c5a62c7b6eea8a12071251394d"
            .parse::<Digest32>(),
    )
}

#[test]
fn frozen_golden_vector_matches_cross_language_digest() {
    let type_id = checked(validate_id("platform.types:golden", IdProfileV1::Stable));
    let digest_bytes = Digest32::from_array([
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
        23, 24, 25, 26, 27, 28, 29, 30, 31,
    ]);
    let values = [
        CanonicalValueV1::I64(-1),
        CanonicalValueV1::U64(2),
        CanonicalValueV1::Bytes(&[0, 1]),
    ];
    let labels = [
        CanonicalMapEntryV1::new("beta", CanonicalValueV1::I64(-2)),
        CanonicalMapEntryV1::new("alpha", CanonicalValueV1::Text("A")),
    ];
    let fields = [
        CanonicalFieldV1::new("values", CanonicalValueV1::Array(&values)),
        CanonicalFieldV1::new("name", CanonicalValueV1::Text("hépta")),
        CanonicalFieldV1::new("labels", CanonicalValueV1::Map(&labels)),
        CanonicalFieldV1::new("digest", CanonicalValueV1::Digest(digest_bytes)),
        CanonicalFieldV1::new("count", CanonicalValueV1::U64(42)),
        CanonicalFieldV1::new("active", CanonicalValueV1::Bool(true)),
    ];

    let encoded = checked(canonical_encode_v1(&type_id, 1, &fields));
    assert_eq!(encoded.as_slice().len(), 218);
    assert_eq!(
        &encoded.as_slice()[..26],
        b"HEPTA-CANONICAL-DIGEST-V1\0"
    );
    assert_eq!(
        checked(canonical_digest_v1(&type_id, 1, &fields)),
        expected_digest()
    );

    let reordered = [
        fields[5], fields[4], fields[3], fields[2], fields[1], fields[0],
    ];
    assert_eq!(
        checked(canonical_digest_v1(&type_id, 1, &reordered)),
        expected_digest()
    );
}

#[test]
fn framing_separates_ambiguous_concatenations() {
    let type_id = checked(validate_id("platform.types:framing", IdProfileV1::Stable));
    let left = [
        CanonicalFieldV1::new("first", CanonicalValueV1::Text("ab")),
        CanonicalFieldV1::new("second", CanonicalValueV1::Text("c")),
    ];
    let right = [
        CanonicalFieldV1::new("first", CanonicalValueV1::Text("a")),
        CanonicalFieldV1::new("second", CanonicalValueV1::Text("bc")),
    ];
    assert_ne!(
        checked(canonical_digest_v1(&type_id, 1, &left)),
        checked(canonical_digest_v1(&type_id, 1, &right))
    );
}

#[test]
fn duplicate_names_map_keys_and_zero_version_reject() {
    let type_id = checked(validate_id("platform.types:negative", IdProfileV1::Stable));
    let duplicate_fields = [
        CanonicalFieldV1::new("same", CanonicalValueV1::U64(1)),
        CanonicalFieldV1::new("same", CanonicalValueV1::U64(2)),
    ];
    assert_eq!(
        canonical_digest_v1(&type_id, 1, &duplicate_fields),
        Err(CanonicalDigestError::DuplicateField)
    );

    let duplicate_map = [
        CanonicalMapEntryV1::new("same", CanonicalValueV1::U64(1)),
        CanonicalMapEntryV1::new("same", CanonicalValueV1::U64(2)),
    ];
    let map_field = [CanonicalFieldV1::new(
        "map",
        CanonicalValueV1::Map(&duplicate_map),
    )];
    assert_eq!(
        canonical_digest_v1(&type_id, 1, &map_field),
        Err(CanonicalDigestError::DuplicateMapKey)
    );
    assert_eq!(
        canonical_digest_v1(&type_id, 0, &[]),
        Err(CanonicalDigestError::ZeroSchemaVersion)
    );
}

#[test]
fn canonical_encoding_is_bounded() {
    let type_id = checked(validate_id("platform.types:bounded", IdProfileV1::Stable));
    let huge = vec![0_u8; MAX_CANONICAL_BYTES_V1];
    let fields = [CanonicalFieldV1::new(
        "payload",
        CanonicalValueV1::Bytes(&huge),
    )];
    assert_eq!(
        canonical_encode_v1(&type_id, 1, &fields),
        Err(CanonicalDigestError::SizeLimit)
    );
}


#[test]
fn canonical_field_collection_and_depth_limits_reject() {
    let type_id = checked(validate_id("platform.types:limits", IdProfileV1::Stable));

    let many_fields: Vec<_> = (0..=MAX_FIELDS_V1)
        .map(|index| {
            let name = Box::leak(format!("f{index}").into_boxed_str());
            CanonicalFieldV1::new(name, CanonicalValueV1::U64(0))
        })
        .collect();
    assert_eq!(
        canonical_digest_v1(&type_id, 1, &many_fields),
        Err(CanonicalDigestError::TooManyFields)
    );

    let many_items = vec![CanonicalValueV1::Bool(false); MAX_COLLECTION_ITEMS_V1 + 1];
    let array_field = [CanonicalFieldV1::new(
        "items",
        CanonicalValueV1::Array(&many_items),
    )];
    assert_eq!(
        canonical_digest_v1(&type_id, 1, &array_field),
        Err(CanonicalDigestError::TooManyCollectionItems)
    );

    fn nested(depth: usize) -> CanonicalValueV1<'static> {
        if depth == 0 {
            return CanonicalValueV1::Bool(true);
        }
        let child = Box::leak(Box::new([nested(depth - 1)]));
        CanonicalValueV1::Array(child)
    }
    let too_deep = [CanonicalFieldV1::new(
        "nested",
        nested(MAX_NESTING_DEPTH_V1 + 1),
    )];
    assert_eq!(
        canonical_digest_v1(&type_id, 1, &too_deep),
        Err(CanonicalDigestError::NestingDepth)
    );
}

#[test]
fn canonical_order_is_invariant_across_deterministic_permutations() {
    let type_id = checked(validate_id("platform.types:order", IdProfileV1::Stable));
    let base = [
        CanonicalFieldV1::new("delta", CanonicalValueV1::U64(4)),
        CanonicalFieldV1::new("alpha", CanonicalValueV1::U64(1)),
        CanonicalFieldV1::new("charlie", CanonicalValueV1::U64(3)),
        CanonicalFieldV1::new("bravo", CanonicalValueV1::U64(2)),
    ];
    let expected = checked(canonical_digest_v1(&type_id, 1, &base));

    for shift in 0..base.len() {
        let mut rotated = base;
        rotated.rotate_left(shift);
        assert_eq!(
            checked(canonical_digest_v1(&type_id, 1, &rotated)),
            expected
        );

        rotated.swap(0, rotated.len() - 1);
        assert_eq!(
            checked(canonical_digest_v1(&type_id, 1, &rotated)),
            expected
        );
    }
}
