#![no_main]

use codex_hepta_wire::NegotiatedStreamingDecoder;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::StreamingDecoder;
use codex_hepta_wire::WireCapabilities;
use codex_hepta_wire::decode_frame;
use codex_hepta_wire::negotiate;
use codex_hepta_wire::read_frame;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = decode_frame(data);
    let _ = NegotiationOffer::decode(data);
    let mut cursor = std::io::Cursor::new(data);
    let _ = read_frame(&mut cursor);

    let mut decoder = StreamingDecoder::new();
    for chunk in data.chunks(17) {
        let batch = decoder.push_batch(chunk);
        if batch.terminal_error().is_some() {
            break;
        }
    }
    let _ = decoder.finish();
    let offer = NegotiationOffer::current();
    if let Ok(posture) = negotiate(&offer, &offer, WireCapabilities::METADATA_BOUND_DIGEST) {
        let mut selected = NegotiatedStreamingDecoder::new(posture);
        let mut offset = 0;
        while offset < data.len() {
            let batch = selected.feed(&data[offset..]);
            if batch.batch().terminal_error().is_some() {
                break;
            }
            assert!(batch.bytes_consumed() > 0);
            offset += batch.bytes_consumed();
        }
        let _ = selected.finish();
    }
});
