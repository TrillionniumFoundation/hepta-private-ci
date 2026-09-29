//! Buffered and digest-only calls use one encoder and must have identical errors.
use codex_hepta_types::CanonicalDigestError;
use codex_hepta_types::CanonicalFieldV1;
use codex_hepta_types::CanonicalMapEntryV1;
use codex_hepta_types::CanonicalValueV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::MAX_CANONICAL_BYTES_V1;
use codex_hepta_types::StableId;
use codex_hepta_types::canonical_digest_v1;
use codex_hepta_types::canonical_encode_v1;
use codex_hepta_types::canonical_validate_v1;

fn compare(type_id: &StableId, schema: u32, fields: &[CanonicalFieldV1<'_>]) {
    let encoded = canonical_encode_v1(type_id, schema, fields);
    let digest = canonical_digest_v1(type_id, schema, fields);
    match encoded {
        Ok(bytes) => {
            assert_eq!(digest, Ok(Digest32::of_bytes(&bytes)));
            assert_eq!(canonical_validate_v1(&bytes), digest);
        }
        Err(error) => assert_eq!(digest, Err(error)),
    }
}

#[test]
fn streaming_matches_buffering_for_every_value_tag_and_field_order() {
    let id = StableId::new("platform.types:stream-parity").expect("id");
    let map = [
        CanonicalMapEntryV1 {
            key: "z",
            value: CanonicalValueV1::U128(u128::MAX),
        },
        CanonicalMapEntryV1 {
            key: "a",
            value: CanonicalValueV1::I64(i64::MIN),
        },
    ];
    let values = [
        CanonicalValueV1::Bool(true),
        CanonicalValueV1::U64(u64::MAX),
        CanonicalValueV1::U128(u128::MAX),
        CanonicalValueV1::I64(i64::MIN),
        CanonicalValueV1::Bytes(b"\0\xff"),
        CanonicalValueV1::Text("é/e\u{301}"),
        CanonicalValueV1::Digest(Digest32::of_bytes(b"digest")),
        CanonicalValueV1::StableId(&id),
        CanonicalValueV1::Map(&map),
    ];
    for value in values {
        let mut fields = [
            CanonicalFieldV1 { name: "z", value },
            CanonicalFieldV1 {
                name: "a",
                value: CanonicalValueV1::Array(&values),
            },
        ];
        compare(&id, /*schema*/ 1, &fields);
        let digest = canonical_digest_v1(&id, /*schema_version*/ 1, &fields);
        fields.reverse();
        assert_eq!(
            digest,
            canonical_digest_v1(&id, /*schema_version*/ 1, &fields)
        );
        compare(&id, /*schema*/ 1, &fields);
    }
}

#[test]
fn streaming_and_buffered_paths_share_the_exact_byte_ceiling() {
    let id = StableId::new("platform.types:stream-boundary").expect("id");
    let empty = [CanonicalFieldV1 {
        name: "bytes",
        value: CanonicalValueV1::Bytes(&[]),
    }];
    let overhead = canonical_encode_v1(&id, /*schema_version*/ 1, &empty)
        .expect("encode")
        .len();
    for size in [
        MAX_CANONICAL_BYTES_V1 - overhead,
        MAX_CANONICAL_BYTES_V1 - overhead + 1,
    ] {
        let payload = vec![0; size];
        let fields = [CanonicalFieldV1 {
            name: "bytes",
            value: CanonicalValueV1::Bytes(&payload),
        }];
        compare(&id, /*schema*/ 1, &fields);
        assert_eq!(
            canonical_digest_v1(&id, /*schema_version*/ 1, &fields).is_ok(),
            size + overhead <= MAX_CANONICAL_BYTES_V1
        );
    }
}

fn nested(depth: usize, value: CanonicalValueV1<'_>, id: &StableId) {
    if depth == 0 {
        compare(
            id,
            /*schema*/ 1,
            &[CanonicalFieldV1 {
                name: "nested",
                value,
            }],
        );
    } else {
        let child = [value];
        nested(depth - 1, CanonicalValueV1::Array(&child), id);
    }
}

#[test]
fn malformed_fields_collections_and_depth_have_matching_errors() {
    let id = StableId::new("platform.types:stream-negative").expect("id");
    for name in ["valid", "Invalid", "", "trailing_", "a\0b"] {
        let field = CanonicalFieldV1 {
            name,
            value: CanonicalValueV1::Bool(false),
        };
        compare(&id, /*schema*/ 1, &[field]);
        compare(&id, /*schema*/ 0, &[field]);
        compare(&id, /*schema*/ 1, &[field, field]);
    }
    let repeated = vec![CanonicalValueV1::Bool(false); 4097];
    let fields = [CanonicalFieldV1 {
        name: "items",
        value: CanonicalValueV1::Array(&repeated),
    }];
    assert_eq!(
        canonical_digest_v1(&id, /*schema_version*/ 1, &fields),
        Err(CanonicalDigestError::TooManyItems)
    );
    compare(&id, /*schema*/ 1, &fields);
    for depth in [0, 1, 15, 16, 17] {
        nested(depth, CanonicalValueV1::Bool(false), &id);
    }
}
