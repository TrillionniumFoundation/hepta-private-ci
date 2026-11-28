use chrono::DateTime;
use chrono::SecondsFormat;
use std::io::Read;
use std::io::Write;

fn main() {
    let mut raw = Vec::new();
    std::io::stdin().read_to_end(&mut raw).unwrap();
    assert_eq!(raw.len() % 40, 0);
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    for row in raw.chunks_exact(40) {
        let seconds = i64::from_le_bytes(row[..8].try_into().unwrap());
        let nanos = u64::from_le_bytes(row[8..16].try_into().unwrap());
        let precision = u64::from_le_bytes(row[16..24].try_into().unwrap());
        let use_z = u64::from_le_bytes(row[24..32].try_into().unwrap());
        let operation = u64::from_le_bytes(row[32..40].try_into().unwrap());
        assert!(operation <= 1);
        assert!(precision <= 4 && use_z <= 1);
        assert!(operation == 0 || (precision == 0 && use_z == 0));
        let value = u32::try_from(nanos)
            .ok()
            .and_then(|nanos| DateTime::from_timestamp(seconds, nanos));
        let mut result = [0_u8; 96];
        result[..8].copy_from_slice(&1_u64.to_le_bytes());
        if let Some(value) = value {
            let text = if operation == 1 {
                serde_json::to_string(&value).unwrap()
            } else {
                let format = match precision {
                    0 => SecondsFormat::Secs,
                    1 => SecondsFormat::Millis,
                    2 => SecondsFormat::Micros,
                    3 => SecondsFormat::Nanos,
                    4 => SecondsFormat::AutoSi,
                    _ => unreachable!(),
                };
                value.to_rfc3339_opts(format, use_z == 1)
            };
            assert!(text.len() <= 64);
            result[8..16].copy_from_slice(&1_u64.to_le_bytes());
            result[16..24].copy_from_slice(&(text.len() as u64).to_le_bytes());
            result[32..32 + text.len()].copy_from_slice(text.as_bytes());
        }
        out.write_all(&result).unwrap();
    }
    out.flush().unwrap();
}
