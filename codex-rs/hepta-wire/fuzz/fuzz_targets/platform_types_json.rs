#![no_main]

use codex_hepta_wire::decode_prompt_delivery_v2_json;
use codex_hepta_wire::decode_runtime_topology_candidate_v1_json;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|bytes: &[u8]| {
    let _ = decode_prompt_delivery_v2_json(bytes);
    let _ = decode_runtime_topology_candidate_v1_json(bytes);
});
