use chrono::TimeDelta;
use std::io::Read;
use std::io::Write;
use std::time::Duration;

fn observe(operation: u64, argument: u64, nanos: u64) -> [u64; 21] {
    assert!(operation == 0 || operation == 9 || nanos == 0);
    let signed = argument as i64;
    let value = match operation {
        0 => u32::try_from(nanos)
            .ok()
            .and_then(|nanos| TimeDelta::new(signed, nanos)),
        1 => TimeDelta::try_weeks(signed),
        2 => TimeDelta::try_days(signed),
        3 => TimeDelta::try_hours(signed),
        4 => TimeDelta::try_minutes(signed),
        5 => TimeDelta::try_seconds(signed),
        6 => TimeDelta::try_milliseconds(signed),
        7 => Some(TimeDelta::microseconds(signed)),
        8 => Some(TimeDelta::nanoseconds(signed)),
        9 => u32::try_from(nanos)
            .ok()
            .filter(|nanos| *nanos < 1_000_000_000)
            .and_then(|nanos| TimeDelta::from_std(Duration::new(argument, nanos)).ok()),
        10 => {
            assert_eq!(argument, 0);
            Some(TimeDelta::zero())
        }
        _ => panic!("unknown operation"),
    };
    let Some(value) = value else {
        let mut absent = [0; 21];
        absent[0] = 1;
        return absent;
    };
    let whole = value.num_seconds();
    let fraction = value.subsec_nanos();
    let (seconds, nanos) = if fraction < 0 {
        (whole - 1, fraction + 1_000_000_000)
    } else {
        (whole, fraction)
    };
    assert_eq!(
        TimeDelta::new(seconds, u32::try_from(nanos).unwrap()),
        Some(value)
    );
    let micros = value.num_microseconds();
    let total_nanos = value.num_nanoseconds();
    let standard = value.to_std().ok();
    [
        1,
        1,
        seconds as u64,
        u64::try_from(nanos).unwrap(),
        value.num_weeks() as u64,
        value.num_days() as u64,
        value.num_hours() as u64,
        value.num_minutes() as u64,
        whole as u64,
        value.num_milliseconds() as u64,
        u64::from(micros.is_some()),
        micros.unwrap_or(0) as u64,
        u64::from(total_nanos.is_some()),
        total_nanos.unwrap_or(0) as u64,
        i64::from(value.subsec_millis()) as u64,
        i64::from(value.subsec_micros()) as u64,
        i64::from(fraction) as u64,
        u64::from(standard.is_some()),
        standard.map_or(0, |duration| duration.as_secs()),
        standard.map_or(0, |duration| u64::from(duration.subsec_nanos())),
        u64::from(value.is_zero()),
    ]
}

fn main() {
    let mut raw = Vec::new();
    std::io::stdin().read_to_end(&mut raw).unwrap();
    assert_eq!(raw.len() % 24, 0);
    let mut out = std::io::BufWriter::new(std::io::stdout().lock());
    for row in raw.chunks_exact(24) {
        let operation = u64::from_le_bytes(row[..8].try_into().unwrap());
        let argument = u64::from_le_bytes(row[8..16].try_into().unwrap());
        let nanos = u64::from_le_bytes(row[16..].try_into().unwrap());
        for word in observe(operation, argument, nanos) {
            out.write_all(&word.to_le_bytes()).unwrap();
        }
    }
    out.flush().unwrap();
}
