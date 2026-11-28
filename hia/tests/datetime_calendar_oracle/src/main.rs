use chrono::DateTime;
use chrono::Datelike;
use chrono::Timelike;
use std::io::Read;
use std::io::Write;

fn main() {
    let mut raw = Vec::new();
    std::io::stdin().read_to_end(&mut raw).unwrap();
    assert_eq!(raw.len() % 16, 0);
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    for row in raw.chunks_exact(16) {
        let seconds = i64::from_le_bytes(row[..8].try_into().unwrap());
        let nanos = u64::from_le_bytes(row[8..].try_into().unwrap());
        let value = u32::try_from(nanos)
            .ok()
            .and_then(|nanos| DateTime::from_timestamp(seconds, nanos));
        let words = if let Some(value) = value {
            [
                1,
                1,
                value.timestamp() as u64,
                u64::from(value.timestamp_subsec_nanos()),
                value.year() as u64,
                u64::from(value.month()),
                u64::from(value.day()),
                u64::from(value.num_seconds_from_midnight()),
            ]
        } else {
            [1, 0, 0, 0, 0, 0, 0, 0]
        };
        for word in words {
            out.write_all(&word.to_le_bytes()).unwrap();
        }
    }
    out.flush().unwrap();
}
