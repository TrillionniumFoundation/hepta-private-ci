use super::*;
use crate::StableId;

const MIXED_VECTOR_HEX: &str = "48455054412d43414e4f4e4943414c2d4449474553542d5631000016706c6174666f726d2e74797065732e6578616d706c65000700066163746976650500000001010005636f756e740300000008000000000000002a00066469676573740600000020be5df7bbbf50c940858b5b6a58a01308df2144a5a8461207f1ac5cb53066b3a400026964070000000f61727469666163743a6974656d2d3100046e6f74650200000005686570746100066f66667365740400000008fffffffffffffff900077061796c6f61640100000004000102ff";
const MIXED_VECTOR_DIGEST: &str =
    "0f4509c975d9fff87b9a2d9d8933aa72e17287b7a35ab7e8353ddfc0b96c4b47";

fn mixed_fields<'a>(
    id: &'a StableId,
    digest: Digest32,
    payload: &'a [u8],
) -> [CanonicalFieldV1<'a>; 7] {
    [
        CanonicalFieldV1 {
            name: "active",
            value: CanonicalValueV1::Bool(true),
        },
        CanonicalFieldV1 {
            name: "count",
            value: CanonicalValueV1::U64(42),
        },
        CanonicalFieldV1 {
            name: "digest",
            value: CanonicalValueV1::Digest(digest),
        },
        CanonicalFieldV1 {
            name: "id",
            value: CanonicalValueV1::StableId(id),
        },
        CanonicalFieldV1 {
            name: "note",
            value: CanonicalValueV1::Text("hepta"),
        },
        CanonicalFieldV1 {
            name: "offset",
            value: CanonicalValueV1::I64(-7),
        },
        CanonicalFieldV1 {
            name: "payload",
            value: CanonicalValueV1::Bytes(payload),
        },
    ]
}

#[test]
fn mixed_golden_vector_is_byte_exact_and_domain_separated() {
    let id = StableId::new("artifact:item-1").expect("stable id");
    let digest = Digest32::of_bytes(b"vector-digest");
    let fields = mixed_fields(&id, digest, &[0, 1, 2, 255]);
    let encoded = canonical_encode_v1("platform.types.example", &fields).expect("canonical bytes");
    let actual_hex = encoded
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    assert_eq!(actual_hex, MIXED_VECTOR_HEX);
    assert_eq!(
        canonical_digest_v1("platform.types.example", &fields)
            .expect("canonical digest")
            .to_string(),
        MIXED_VECTOR_DIGEST
    );
    assert_ne!(
        canonical_digest_v1("platform.types.other", &fields).expect("other domain"),
        canonical_digest_v1("platform.types.example", &fields).expect("original domain")
    );
}

#[test]
fn field_framing_prevents_concatenation_ambiguity() {
    let left = [
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::Text("ab"),
        },
        CanonicalFieldV1 {
            name: "b",
            value: CanonicalValueV1::Text("c"),
        },
    ];
    let right = [
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::Text("a"),
        },
        CanonicalFieldV1 {
            name: "b",
            value: CanonicalValueV1::Text("bc"),
        },
    ];
    assert_ne!(
        canonical_digest_v1("platform.types.framing", &left),
        canonical_digest_v1("platform.types.framing", &right)
    );
}

#[test]
fn field_order_duplicates_tokens_and_collection_bounds_fail_closed() {
    let unsorted = [
        CanonicalFieldV1 {
            name: "b",
            value: CanonicalValueV1::Bool(false),
        },
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::Bool(false),
        },
    ];
    assert_eq!(
        canonical_encode_v1("platform.types.test", &unsorted),
        Err(CanonicalDigestError::FieldsNotCanonical)
    );

    let duplicate = [
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::Bool(false),
        },
        CanonicalFieldV1 {
            name: "a",
            value: CanonicalValueV1::Bool(true),
        },
    ];
    assert_eq!(
        canonical_encode_v1("platform.types.test", &duplicate),
        Err(CanonicalDigestError::FieldsNotCanonical)
    );
    assert_eq!(
        canonical_encode_v1("Platform.Types", &[]),
        Err(CanonicalDigestError::InvalidDomain)
    );

    let oversized = vec![0_u8; MAX_CANONICAL_COLLECTION_BYTES_V1 + 1];
    let fields = [CanonicalFieldV1 {
        name: "payload",
        value: CanonicalValueV1::Bytes(&oversized),
    }];
    assert_eq!(
        canonical_encode_v1("platform.types.test", &fields),
        Err(CanonicalDigestError::ValueTooLarge(oversized.len()))
    );
}
