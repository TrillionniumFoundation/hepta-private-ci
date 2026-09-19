#![no_main]

use std::io::Cursor;

use codex_hepta_wire::FramedReader;
use codex_hepta_wire::WireEnvelope;
use codex_hepta_wire::WireEnvelopeV2;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = WireEnvelope::decode(data);
    let _ = WireEnvelopeV2::decode(data);
    let mut reader = FramedReader::new(Cursor::new(data));
    let _ = reader.read_next();
});
