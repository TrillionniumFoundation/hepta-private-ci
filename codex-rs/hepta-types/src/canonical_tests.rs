use std::collections::BTreeMap;

use super::*;

fn golden_fields() -> Vec<CanonicalFieldV1> {
    let mut meta = BTreeMap::new();
    meta.insert("b".to_string(), CanonicalValueV1::Bytes(vec![0, 255]));
    meta.insert("a".to_string(), CanonicalValueV1::Bool(true));
    vec![
        CanonicalFieldV1::new("zeta", CanonicalValueV1::Text("hepta".to_string())),
        CanonicalFieldV1::new("alpha", CanonicalValueV1::U64(42)),
        CanonicalFieldV1::new(
            "items",
            CanonicalValueV1::Array(vec![
                CanonicalValueV1::I64(-1),
                CanonicalValueV1::I64(0),
                CanonicalValueV1::I64(1),
            ]),
        ),
        CanonicalFieldV1::new("meta", CanonicalValueV1::Map(meta)),
    ]
}

#[test]
fn golden_vector_is_stable_and_field_order_is_canonical() {
    let fields = golden_fields();
    let digest = canonical_digest_v1("schema:platform.types.vector", 1, &fields).expect("vector");
    assert_eq!(
        digest.to_string(),
        "7f72e578b85d2d80e30a0b073846998c1581976538036880b4ec01e28458b9d5"
    );

    let mut reversed = fields;
    reversed.reverse();
    assert_eq!(
        canonical_digest_v1("schema:platform.types.vector", 1, &reversed),
        Ok(digest)
    );
}

#[test]
fn framing_separates_ambiguous_concatenations_and_arrays_preserve_order() {
    let left = vec![
        CanonicalFieldV1::new("a", CanonicalValueV1::Text("ab".into())),
        CanonicalFieldV1::new("b", CanonicalValueV1::Text("c".into())),
    ];
    let right = vec![
        CanonicalFieldV1::new("a", CanonicalValueV1::Text("a".into())),
        CanonicalFieldV1::new("b", CanonicalValueV1::Text("bc".into())),
    ];
    assert_ne!(
        canonical_digest_v1("schema:framing", 1, &left),
        canonical_digest_v1("schema:framing", 1, &right)
    );

    let ascending = vec![CanonicalFieldV1::new(
        "items",
        CanonicalValueV1::Array(vec![CanonicalValueV1::U64(1), CanonicalValueV1::U64(2)]),
    )];
    let descending = vec![CanonicalFieldV1::new(
        "items",
        CanonicalValueV1::Array(vec![CanonicalValueV1::U64(2), CanonicalValueV1::U64(1)]),
    )];
    assert_ne!(
        canonical_digest_v1("schema:array-order", 1, &ascending),
        canonical_digest_v1("schema:array-order", 1, &descending)
    );
}

#[test]
fn malformed_or_unbounded_inputs_fail_closed() {
    assert_eq!(
        canonical_digest_v1("bad/type", 1, &[]),
        Err(CanonicalDigestError::InvalidTypeId)
    );
    assert_eq!(
        canonical_digest_v1("schema:ok", 0, &[]),
        Err(CanonicalDigestError::ZeroSchemaVersion)
    );
    let duplicate = vec![
        CanonicalFieldV1::new("same", CanonicalValueV1::U64(1)),
        CanonicalFieldV1::new("same", CanonicalValueV1::U64(2)),
    ];
    assert_eq!(
        canonical_digest_v1("schema:ok", 1, &duplicate),
        Err(CanonicalDigestError::DuplicateField)
    );
    let oversized = vec![CanonicalFieldV1::new(
        "payload",
        CanonicalValueV1::Bytes(vec![0; MAX_CANONICAL_BYTES_V1]),
    )];
    assert_eq!(
        canonical_digest_v1("schema:ok", 1, &oversized),
        Err(CanonicalDigestError::TooLarge)
    );
}
