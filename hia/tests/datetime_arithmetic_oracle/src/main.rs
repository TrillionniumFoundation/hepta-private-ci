use chrono::DateTime;
use chrono::TimeDelta;
use chrono::TimeZone;
use chrono::Utc;
use std::io::Read;
use std::io::Write;

fn datetime(seconds: u64, nanos: u64) -> Option<DateTime<Utc>> {
    u32::try_from(nanos)
        .ok()
        .and_then(|nanos| DateTime::from_timestamp(seconds as i64, nanos))
}

fn date_result(inputs_valid: bool, value: Option<DateTime<Utc>>) -> [u64; 8] {
    match value {
        Some(value) => [
            1,
            u64::from(inputs_valid),
            1,
            value.timestamp() as u64,
            u64::from(value.timestamp_subsec_nanos()),
            0,
            0,
            0,
        ],
        None => [1, u64::from(inputs_valid), 0, 0, 0, 0, 0, 0],
    }
}

fn observe(words: [u64; 7]) -> [u64; 8] {
    let [operation, a, b, c, d, e, f] = words;
    if operation == 3 {
        let value = i32::try_from(a as i64)
            .ok()
            .zip(u32::try_from(b).ok())
            .zip(u32::try_from(c).ok())
            .zip(u32::try_from(d).ok())
            .zip(u32::try_from(e).ok())
            .zip(u32::try_from(f).ok())
            .and_then(|(((((year, month), day), hour), minute), second)| {
                Utc.with_ymd_and_hms(year, month, day, hour, minute, second)
                    .single()
            });
        return date_result(value.is_some(), value);
    }
    assert_eq!((e, f), (0, 0));
    let Some(left) = datetime(a, b) else {
        return date_result(false, None);
    };
    if operation == 2 {
        let Some(right) = datetime(c, d) else {
            return date_result(false, None);
        };
        let difference = left.signed_duration_since(right);
        let whole = difference.num_seconds();
        let fraction = difference.subsec_nanos();
        let (seconds, nanos) = if fraction < 0 {
            (whole - 1, fraction + 1_000_000_000)
        } else {
            (whole, fraction)
        };
        assert_eq!(
            TimeDelta::new(seconds, u32::try_from(nanos).unwrap()),
            Some(difference)
        );
        return [
            1,
            1,
            1,
            seconds as u64,
            u64::try_from(nanos).unwrap(),
            whole as u64,
            i64::from(fraction) as u64,
            0,
        ];
    }
    let Some(delta) = u32::try_from(d)
        .ok()
        .and_then(|nanos| TimeDelta::new(c as i64, nanos))
    else {
        return date_result(false, None);
    };
    let result = match operation {
        0 => left.checked_add_signed(delta),
        1 => left.checked_sub_signed(delta),
        _ => panic!("unknown operation"),
    };
    date_result(true, result)
}

fn main() {
    let mut raw = Vec::new();
    std::io::stdin().read_to_end(&mut raw).unwrap();
    assert_eq!(raw.len() % 56, 0);
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    for row in raw.chunks_exact(56) {
        let words = std::array::from_fn(|index| {
            u64::from_le_bytes(row[index * 8..(index + 1) * 8].try_into().unwrap())
        });
        for word in observe(words) {
            out.write_all(&word.to_le_bytes()).unwrap();
        }
    }
    out.flush().unwrap();
}
