#![no_main]

use codex_hepta_types::canonical_validate_v1;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|bytes: &[u8]| {
    let _ = canonical_validate_v1(bytes);
});
