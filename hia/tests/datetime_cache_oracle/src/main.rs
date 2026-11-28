use chrono::DateTime;
use chrono::TimeDelta;
use chrono::Utc;
use std::io::Read;
use std::io::Write;
use std::time::Duration;

fn timestamp(seconds: u64, nanos: u64) -> Option<DateTime<Utc>> {
    u32::try_from(nanos)
        .ok()
        .and_then(|fraction| DateTime::from_timestamp(seconds as i64, fraction))
}

fn observe(row: [u64; 7]) -> [u64; 4] {
    let [
        operation,
        fetched_seconds,
        fetched_nanos,
        now_seconds,
        now_nanos,
        seconds,
        nanos,
    ] = row;
    assert!(operation <= 2);
    if operation == 0 {
        assert_eq!(
            [fetched_seconds, fetched_nanos, now_seconds, now_nanos],
            [0; 4]
        );
    }
    let (Some(fetched_at), Some(now)) = (
        timestamp(fetched_seconds, fetched_nanos),
        timestamp(now_seconds, now_nanos),
    ) else {
        return [1, 0, 0, 0];
    };
    let Some(standard) = u32::try_from(nanos)
        .ok()
        .filter(|fraction| *fraction < 1_000_000_000)
        .map(|fraction| Duration::new(seconds, fraction))
    else {
        return [1, 1, 0, 0];
    };
    let Ok(ttl_duration) = TimeDelta::from_std(standard) else {
        return [1, 1, 0, 0];
    };
    let fresh = match operation {
        0 => false,
        1 => {
            if standard.is_zero() {
                false
            } else {
                let age = now.signed_duration_since(fetched_at);
                age <= ttl_duration
            }
        }
        2 => {
            let age = now.signed_duration_since(fetched_at);
            age >= TimeDelta::zero() && age <= ttl_duration
        }
        _ => unreachable!(),
    };
    [1, 1, 1, u64::from(fresh)]
}

fn main() {
    let mut raw = Vec::new();
    std::io::stdin().read_to_end(&mut raw).unwrap();
    assert_eq!(raw.len() % 56, 0);
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    for bytes in raw.chunks_exact(56) {
        let row = std::array::from_fn(|index| {
            u64::from_le_bytes(bytes[index * 8..(index + 1) * 8].try_into().unwrap())
        });
        for word in observe(row) {
            out.write_all(&word.to_le_bytes()).unwrap();
        }
    }
    out.flush().unwrap();
}
