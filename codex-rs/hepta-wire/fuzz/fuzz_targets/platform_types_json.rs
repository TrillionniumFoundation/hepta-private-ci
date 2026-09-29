#![no_main]

use codex_hepta_wire::decode_external_system_manifest_v1_json;
use codex_hepta_wire::decode_prompt_delivery_v2_json;
use codex_hepta_wire::decode_random_stream_manifest_v1_json;
use codex_hepta_wire::decode_runtime_topology_candidate_v1_json;
use codex_hepta_wire::decode_sensor_calibration_manifest_v1_json;
use codex_hepta_wire::encode_external_system_manifest_v1_json;
use codex_hepta_wire::encode_prompt_delivery_v2_json;
use codex_hepta_wire::encode_random_stream_manifest_v1_json;
use codex_hepta_wire::encode_runtime_topology_candidate_v1_json;
use codex_hepta_wire::encode_sensor_calibration_manifest_v1_json;
use libfuzzer_sys::fuzz_target;

// These are assertions over the actual product path, not alternative codecs.
// Every admitted value must hash, encode, and retain exactly its semantics.
macro_rules! semantic_roundtrip {
    ($bytes:expr, $decode:ident, $encode:ident) => {
        if let Ok(value) = $decode($bytes) {
            let digest = value.semantic_digest().expect("admitted value must hash");
            let encoded = $encode(&value).expect("admitted value must encode");
            let decoded = $decode(&encoded).expect("encoded value must decode");
            assert_eq!(decoded.semantic_digest(), Ok(digest));
            assert_eq!(decoded, value);
        }
    };
}

fuzz_target!(|bytes: &[u8]| {
    semantic_roundtrip!(
        bytes,
        decode_prompt_delivery_v2_json,
        encode_prompt_delivery_v2_json
    );
    semantic_roundtrip!(
        bytes,
        decode_random_stream_manifest_v1_json,
        encode_random_stream_manifest_v1_json
    );
    semantic_roundtrip!(
        bytes,
        decode_external_system_manifest_v1_json,
        encode_external_system_manifest_v1_json
    );
    semantic_roundtrip!(
        bytes,
        decode_sensor_calibration_manifest_v1_json,
        encode_sensor_calibration_manifest_v1_json
    );
    if let Ok(value) = decode_runtime_topology_candidate_v1_json(bytes) {
        let digest = value
            .as_inner()
            .content_digest()
            .expect("admitted topology must hash");
        assert_eq!(digest, value.as_inner().candidate_digest);
        let encoded = encode_runtime_topology_candidate_v1_json(&value).expect("encode topology");
        let decoded = decode_runtime_topology_candidate_v1_json(&encoded).expect("decode topology");
        assert_eq!(decoded, value);
        assert_eq!(decoded.as_inner().content_digest(), Ok(digest));
    }
});
