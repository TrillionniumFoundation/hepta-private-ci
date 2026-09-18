#![no_main]

use codex_hepta_wire::WireFrame;
use codex_hepta_wire::WireStreamDecoder;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = WireFrame::decode(data);

    let mut decoder = WireStreamDecoder::new();
    if decoder.feed(data).is_ok() {
        while matches!(decoder.next_frame(), Ok(Some(_))) {}
    }
});
