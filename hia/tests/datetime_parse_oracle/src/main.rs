use chrono::DateTime;
use chrono::format::ParseErrorKind;
use std::io::Read;
use std::io::Write;

fn main() {
    let mut raw = Vec::new();
    std::io::stdin().read_to_end(&mut raw).unwrap();
    let mut remaining = raw.as_slice();
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    while !remaining.is_empty() {
        assert!(remaining.len() >= 8);
        let length =
            usize::try_from(u64::from_le_bytes(remaining[..8].try_into().unwrap())).unwrap();
        remaining = &remaining[8..];
        assert!(remaining.len() >= length);
        let text = std::str::from_utf8(&remaining[..length]).unwrap();
        remaining = &remaining[length..];
        let words = match DateTime::parse_from_rfc3339(text) {
            Ok(value) => [
                1,
                1,
                value.timestamp() as u64,
                u64::from(value.timestamp_subsec_nanos()),
                value.offset().local_minus_utc() as u64,
                0,
                0,
                0,
            ],
            Err(error) => {
                let kind = match error.kind() {
                    ParseErrorKind::OutOfRange => 1,
                    ParseErrorKind::Impossible => 2,
                    ParseErrorKind::NotEnough => 3,
                    ParseErrorKind::Invalid => 4,
                    ParseErrorKind::TooShort => 5,
                    ParseErrorKind::TooLong => 6,
                    ParseErrorKind::BadFormat => 7,
                    _ => 255,
                };
                [1, 0, 0, 0, 0, kind, 0, 0]
            }
        };
        for word in words {
            out.write_all(&word.to_le_bytes()).unwrap();
        }
    }
    out.flush().unwrap();
}
