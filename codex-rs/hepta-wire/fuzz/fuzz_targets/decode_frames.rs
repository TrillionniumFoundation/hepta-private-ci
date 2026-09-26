#![no_main]

use codex_hepta_wire::StreamingDecoder;
use codex_hepta_wire::decode_frame;
use codex_hepta_wire::read_frame;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = decode_frame(data);
    let mut cursor = std::io::Cursor::new(data);
    let _ = read_frame(&mut cursor);

    let mut decoder = StreamingDecoder::new();
    for chunk in data.chunks(17) {
        let batch = decoder.push_batch(chunk);
        if batch.terminal_error().is_some() {
            break;
        }
    }
});
