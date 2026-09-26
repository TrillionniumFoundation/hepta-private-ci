use std::fmt::Write as _;

use super::*;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

const EXPECTED_CANONICAL_HEX: &str = concat!(
    "68657074612e636f676e69746976652e726561642e6964732e7631",
    "c415055d5aca1f773f8cbd4ac4d9905a13fd6bfa3274fd37b64695bc410f15a7",
    "4994a1ca2e002ec59e16db43308dd4d424dda106373f35b1ba26eaf7e98fb41f",
    "000000020103",
    "00000001",
    "0000000a6d656d6f72793a6f6e65",
    "0000000000000001",
    "0100",
    "01",
    "83fae796aef9a9165719c68e0a06fc13168673623788a5c26c950fdb852c9d44",
    "00",
    "00000000",
    "00000001",
    "0000000e6d656d6f72793a6d697373696e67",
    "00",
    "2d24dd6740b939f3ab812490cb83a9388978476fa4887c053fd0f267c864e56a"
);

const EXTERNAL_GOLDEN_VECTOR: &str = include_str!(
    "../../../qualification/cognitive-read/golden/cognitive_read_vectors.json"
);

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(&mut out, "{byte:02x}").expect("string write");
    }
    out
}

#[test]
fn exact_id_v1_golden_vector_is_stable() {
    let record = MemoryRecord {
        record_id: id("memory:one"),
        revision: Revision::new(1).expect("revision"),
        kind: MemoryKind::Fact,
        content_digest: Digest32::of_bytes(b"memory:one"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    };
    let snapshot =
        build_snapshot(Generation::new(1).expect("generation"), vec![record]).expect("snapshot");
    assert_eq!(
        snapshot.snapshot_digest.to_string(),
        "c415055d5aca1f773f8cbd4ac4d9905a13fd6bfa3274fd37b64695bc410f15a7"
    );

    let result = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:one"), id("memory:missing")],
            fields: vec![ReadFieldV1::ContentDigest, ReadFieldV1::Citations],
            maximum_encoded_bytes: 4096,
        },
    )
    .expect("golden projection");

    assert_eq!(
        result.request_binding_digest().to_string(),
        "4994a1ca2e002ec59e16db43308dd4d424dda106373f35b1ba26eaf7e98fb41f"
    );
    assert_eq!(result.payload_encoded_bytes(), 186);
    assert_eq!(result.total_encoded_bytes(), 218);
    assert_eq!(
        result.receipt_digest().to_string(),
        "2d24dd6740b939f3ab812490cb83a9388978476fa4887c053fd0f267c864e56a"
    );
    assert_eq!(hex(result.canonical_bytes()), EXPECTED_CANONICAL_HEX);

    let expected_external = format!(
        concat!(
            "{\n",
            "  \"schema\": \"hepta.cognitive.read.golden-vector.v1\",\n",
            "  \"vector\": \"exact_id_v1_one_live_one_missing\",\n",
            "  \"snapshot_digest\": ",
            "\"c415055d5aca1f773f8cbd4ac4d9905a13fd6bfa3274fd37b64695bc410f15a7\",\n",
            "  \"request_binding_digest\": ",
            "\"4994a1ca2e002ec59e16db43308dd4d424dda106373f35b1ba26eaf7e98fb41f\",\n",
            "  \"payload_encoded_bytes\": 186,\n",
            "  \"total_encoded_bytes\": 218,\n",
            "  \"receipt_digest\": ",
            "\"2d24dd6740b939f3ab812490cb83a9388978476fa4887c053fd0f267c864e56a\",\n",
            "  \"canonical_hex\": \"{}\"\n",
            "}"
        ),
        EXPECTED_CANONICAL_HEX
    );
    assert_eq!(EXTERNAL_GOLDEN_VECTOR.trim_end(), expected_external);
}
