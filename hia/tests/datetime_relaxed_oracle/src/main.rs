use chrono::DateTime;
use chrono::FixedOffset;
use chrono::Utc;
use chrono::format::ParseErrorKind;
use std::io::Read;
use std::io::Write;

fn kind(error: ParseErrorKind) -> u64 {
    match error {
        ParseErrorKind::OutOfRange => 1,
        ParseErrorKind::Impossible => 2,
        ParseErrorKind::NotEnough => 3,
        ParseErrorKind::Invalid => 4,
        ParseErrorKind::TooShort => 5,
        ParseErrorKind::TooLong => 6,
        ParseErrorKind::BadFormat => 7,
        _ => 255,
    }
}

fn value(seconds: i64, nanos: u32, offset: i32) -> [u64; 8] {
    [
        1,
        1,
        seconds as u64,
        u64::from(nanos),
        offset as u64,
        0,
        0,
        0,
    ]
}

fn observe(text: &str) -> [[u64; 8]; 3] {
    let fixed = text.parse::<DateTime<FixedOffset>>();
    let utc = text.parse::<DateTime<Utc>>();
    let serde = serde_json::from_value::<DateTime<Utc>>(serde_json::Value::String(text.to_owned()));
    match (fixed, utc, serde) {
        (Ok(fixed), Ok(utc), Ok(serde)) => {
            assert_eq!(fixed.with_timezone(&Utc), utc);
            assert_eq!(utc, serde);
            [
                value(
                    fixed.timestamp(),
                    fixed.timestamp_subsec_nanos(),
                    fixed.offset().local_minus_utc(),
                ),
                value(utc.timestamp(), utc.timestamp_subsec_nanos(), 0),
                value(serde.timestamp(), serde.timestamp_subsec_nanos(), 0),
            ]
        }
        (Err(fixed), Err(utc), Err(serde)) => {
            assert_eq!(fixed.kind(), utc.kind());
            assert_eq!(fixed.to_string(), serde.to_string());
            [[1, 0, 0, 0, 0, kind(fixed.kind()), 0, 0]; 3]
        }
        results => panic!("original timestamp APIs disagreed for {text:?}: {results:?}"),
    }
}

fn main() {
    let mut raw = Vec::new();
    std::io::stdin().read_to_end(&mut raw).unwrap();
    let mut remaining = raw.as_slice();
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    while !remaining.is_empty() {
        assert!(remaining.len() >= 16);
        let coverage = u64::from_le_bytes(remaining[..8].try_into().unwrap());
        assert!(coverage <= 1);
        let length =
            usize::try_from(u64::from_le_bytes(remaining[8..16].try_into().unwrap())).unwrap();
        remaining = &remaining[16..];
        assert!(remaining.len() >= length);
        let text = std::str::from_utf8(&remaining[..length]).unwrap();
        remaining = &remaining[length..];
        for words in observe(text) {
            for word in words {
                out.write_all(&word.to_le_bytes()).unwrap();
            }
        }
    }
    out.flush().unwrap();
}
