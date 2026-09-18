use super::*;

fn id(value: &str) -> StableId {
    StableId::with_profile(value, IdProfileV1::Namespaced)
        .unwrap_or_else(|error| panic!("valid type id: {error}"))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[test]
fn frozen_cross_language_vector_matches_exact_bytes_and_digest() {
    let type_id = id("platform.types:canonical-fixture");
    let subject = StableId::with_profile("module:alpha-1", IdProfileV1::Namespaced);
    let Ok(subject) = subject else {
        panic!("canonical fixture subject ID should be valid");
    };
    let evidence = Digest32::of_bytes(b"vector-digest");
    let weights = [CanonicalValueV1::I64(-2), CanonicalValueV1::U128(3)];
    let labels = [
        CanonicalMapEntryV1 {
            key: "z",
            value: CanonicalValueV1::Text("last"),
        },
        CanonicalMapEntryV1 {
            key: "a",
            value: CanonicalValueV1::U64(1),
        },
    ];
    let fields = [
        CanonicalFieldV1 {
            name: "weights",
            value: CanonicalValueV1::Array(&weights),
        },
        CanonicalFieldV1 {
            name: "payload",
            value: CanonicalValueV1::Bytes(&[0, 1, 2, 255]),
        },
        CanonicalFieldV1 {
            name: "enabled",
            value: CanonicalValueV1::Bool(true),
        },
        CanonicalFieldV1 {
            name: "subject",
            value: CanonicalValueV1::StableId(&subject),
        },
        CanonicalFieldV1 {
            name: "labels",
            value: CanonicalValueV1::Map(&labels),
        },
        CanonicalFieldV1 {
            name: "evidence",
            value: CanonicalValueV1::Digest(evidence),
        },
    ];
    let encoded = canonical_encode_v1(&type_id, 1, &fields);
    let Ok(encoded) = encoded else {
        panic!("canonical fixture should encode");
    };
    assert_eq!(encoded.len(), 265);
    assert_eq!(
        hex(&encoded),
        "485054430001002868657074612e706c6174666f726d2e74797065732e63616e6f6e6963616c2d6469676573742e76310020706c6174666f726d2e74797065733a63616e6f6e6963616c2d6669787475726500000001000000060007656e61626c65640101000865766964656e636507be5df7bbbf50c940858b5b6a58a01308df2144a5a8461207f1ac5cb53066b3a400066c6162656c730a0000000200016102000000000000000100017a06000000046c61737400077061796c6f61640500000004000102ff00077375626a65637408000e6d6f64756c653a616c7068612d31000777656967687473090000000204fffffffffffffffe0300000000000000000000000000000003"
    );
    assert_eq!(
        {
            let digest = canonical_digest_v1(&type_id, 1, &fields);
            let Ok(digest) = digest else {
                panic!("canonical fixture should digest");
            };
            digest.to_string()
        },
        "d2b04b7011cdef013c9f01053b8ed70a8a924db7632714e9840bcfea17d72736"
    );
}

#[test]
fn integer_boundaries_unicode_and_empty_containers_are_frozen() {
    let type_id = id("platform.types:canonical-boundaries");
    let empty_array: [CanonicalValueV1<'_>; 0] = [];
    let empty_map: [CanonicalMapEntryV1<'_>; 0] = [];
    let fields = [
        CanonicalFieldV1 {
            name: "u64_max",
            value: CanonicalValueV1::U64(u64::MAX),
        },
        CanonicalFieldV1 {
            name: "u128_max",
            value: CanonicalValueV1::U128(u128::MAX),
        },
        CanonicalFieldV1 {
            name: "i64_min",
            value: CanonicalValueV1::I64(i64::MIN),
        },
        CanonicalFieldV1 {
            name: "unicode",
            value: CanonicalValueV1::Text("hépta/雪"),
        },
        CanonicalFieldV1 {
            name: "empty_text",
            value: CanonicalValueV1::Text(""),
        },
        CanonicalFieldV1 {
            name: "empty_bytes",
            value: CanonicalValueV1::Bytes(&[]),
        },
        CanonicalFieldV1 {
            name: "empty_array",
            value: CanonicalValueV1::Array(&empty_array),
        },
        CanonicalFieldV1 {
            name: "empty_map",
            value: CanonicalValueV1::Map(&empty_map),
        },
    ];
    let encoded = canonical_encode_v1(&type_id, 1, &fields);
    let Ok(encoded) = encoded else {
        panic!("canonical boundary fixture should encode");
    };
    assert_eq!(encoded.len(), 249);
    assert_eq!(
        hex(&encoded),
        "485054430001002868657074612e706c6174666f726d2e74797065732e63616e6f6e6963616c2d6469676573742e76310023706c6174666f726d2e74797065733a63616e6f6e6963616c2d626f756e6461726965730000000100000008000b656d7074795f61727261790900000000000b656d7074795f627974657305000000000009656d7074795f6d61700a00000000000a656d7074795f74657874060000000000076936345f6d696e0480000000000000000008753132385f6d617803ffffffffffffffffffffffffffffffff00077536345f6d617802ffffffffffffffff0007756e69636f6465060000000a68c3a97074612fe99baa"
    );
    let digest = canonical_digest_v1(&type_id, 1, &fields);
    let Ok(digest) = digest else {
        panic!("canonical boundary fixture should digest");
    };
    assert_eq!(
        digest.to_string(),
        "4f3da3cd80d24cd86b151388b296773054be8a1a81cbe0a281f057647c655b36"
    );
}


#[test]
fn field_and_map_order_are_canonical_but_array_order_is_semantic() {
    let type_id = id("platform.types:ordering");
    let map_left = [
        CanonicalMapEntryV1 {
            key: "z",
            value: CanonicalValueV1::U64(9),
        },
        CanonicalMapEntryV1 {
            key: "a",
            value: CanonicalValueV1::U64(1),
        },
    ];
    let map_right = [map_left[1], map_left[0]];
    let left = [
        CanonicalFieldV1 {
            name: "z",
            value: CanonicalValueV1::Map(&map_left),
        },
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::U64(1),
        },
    ];
    let right = [
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::U64(1),
        },
        CanonicalFieldV1 {
            name: "z",
            value: CanonicalValueV1::Map(&map_right),
        },
    ];
    assert_eq!(
        canonical_encode_v1(&type_id, 1, &left),
        canonical_encode_v1(&type_id, 1, &right)
    );

    let array_left = [CanonicalValueV1::U64(1), CanonicalValueV1::U64(2)];
    let array_right = [CanonicalValueV1::U64(2), CanonicalValueV1::U64(1)];
    assert_ne!(
        canonical_digest_v1(
            &type_id,
            1,
            &[CanonicalFieldV1 {
                name: "values",
                value: CanonicalValueV1::Array(&array_left),
            }],
        ),
        canonical_digest_v1(
            &type_id,
            1,
            &[CanonicalFieldV1 {
                name: "values",
                value: CanonicalValueV1::Array(&array_right),
            }],
        )
    );
}

#[test]
fn malformed_canonical_inputs_fail_closed() {
    let type_id = id("platform.types:negative");
    let duplicate_fields = [
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::U64(1),
        },
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::U64(2),
        },
    ];
    assert_eq!(
        canonical_encode_v1(&type_id, 1, &duplicate_fields),
        Err(CanonicalDigestError::DuplicateField)
    );

    let duplicate_map = [
        CanonicalMapEntryV1 {
            key: "a",
            value: CanonicalValueV1::U64(1),
        },
        CanonicalMapEntryV1 {
            key: "a",
            value: CanonicalValueV1::U64(2),
        },
    ];
    assert_eq!(
        canonical_encode_v1(
            &type_id,
            1,
            &[CanonicalFieldV1 {
                name: "map",
                value: CanonicalValueV1::Map(&duplicate_map),
            }],
        ),
        Err(CanonicalDigestError::DuplicateMapKey)
    );
    assert_eq!(
        canonical_encode_v1(
            &type_id,
            0,
            &[CanonicalFieldV1 {
                name: "value",
                value: CanonicalValueV1::U64(1),
            }],
        ),
        Err(CanonicalDigestError::InvalidSchemaVersion)
    );
    let unnamespaced = StableId::new("plain-id");
    let Ok(unnamespaced) = unnamespaced else {
        panic!("legacy stable ID fixture should be valid");
    };
    assert_eq!(
        canonical_encode_v1(&unnamespaced, 1, &[]),
        Err(CanonicalDigestError::InvalidTypeId)
    );
    assert_eq!(
        canonical_encode_v1(
            &type_id,
            1,
            &[CanonicalFieldV1 {
                name: "Upper",
                value: CanonicalValueV1::U64(1),
            }],
        ),
        Err(CanonicalDigestError::InvalidLabel)
    );
    let oversized = vec![0_u8; MAX_CANONICAL_BYTES_V1];
    assert_eq!(
        canonical_encode_v1(
            &type_id,
            1,
            &[CanonicalFieldV1 {
                name: "payload",
                value: CanonicalValueV1::Bytes(&oversized),
            }],
        ),
        Err(CanonicalDigestError::TooLarge)
    );
    let too_many = vec![
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::U64(1),
        };
        MAX_CANONICAL_CONTAINER_ITEMS_V1 + 1
    ];
    assert_eq!(
        canonical_encode_v1(&type_id, 1, &too_many),
        Err(CanonicalDigestError::TooManyItems)
    );
}
