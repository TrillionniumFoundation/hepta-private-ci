use chrono::DateTime;
use std::io::Read;
use std::io::Write;

fn main() {
    let mut raw = Vec::new();
    std::io::stdin().read_to_end(&mut raw).unwrap();
    assert_eq!(raw.len() % 24, 0);
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    for row in raw.chunks_exact(24) {
        let operation = u64::from_le_bytes(row[..8].try_into().unwrap());
        let timestamp = i64::from_le_bytes(row[8..16].try_into().unwrap());
        let nanos = u64::from_le_bytes(row[16..].try_into().unwrap());
        assert!(operation == 0 || nanos == 0);
        let value = match operation {
            0 => u32::try_from(nanos)
                .ok()
                .and_then(|nanos| DateTime::from_timestamp(timestamp, nanos)),
            1 => DateTime::from_timestamp_secs(timestamp),
            2 => DateTime::from_timestamp_millis(timestamp),
            3 => DateTime::from_timestamp_micros(timestamp),
            4 => Some(DateTime::from_timestamp_nanos(timestamp)),
            _ => panic!("unknown operation"),
        };
        let words = if let Some(value) = value {
            let nanos_timestamp = value.timestamp_nanos_opt();
            [
                1,
                1,
                value.timestamp() as u64,
                u64::from(value.timestamp_subsec_nanos()),
                value.timestamp_millis() as u64,
                value.timestamp_micros() as u64,
                u64::from(nanos_timestamp.is_some()),
                nanos_timestamp.unwrap_or(0) as u64,
                u64::from(value.timestamp_subsec_millis()),
                u64::from(value.timestamp_subsec_micros()),
            ]
        } else {
            [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        };
        for word in words {
            out.write_all(&word.to_le_bytes()).unwrap();
        }
    }
    out.flush().unwrap();
}
