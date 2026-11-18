use crate::CanonicalUtcTimestamp;
use crate::Precision;
use crate::UtcSuffix;

pub(crate) fn format(
    timestamp: CanonicalUtcTimestamp,
    precision: Precision,
    suffix: UtcSuffix,
) -> String {
    let value = timestamp.value;
    let year = value.year();
    let year = match year {
        ..0 => format!("-{:04}", year.unsigned_abs()),
        0..=9999 => format!("{year:04}"),
        _ => format!("+{year}"),
    };
    let month = u8::from(value.month());
    let day = value.day();
    let hour = value.hour();
    let minute = value.minute();
    let second = if timestamp.leap_second {
        60
    } else {
        value.second()
    };
    let nanos = value.nanosecond();
    let digits = match precision {
        Precision::Seconds => 0,
        Precision::Millis => 3,
        Precision::Micros => 6,
        Precision::Nanos => 9,
        Precision::AutoSi => match nanos {
            0 => 0,
            nanos if nanos.is_multiple_of(1_000_000) => 3,
            nanos if nanos.is_multiple_of(1_000) => 6,
            _ => 9,
        },
    };
    let fraction = match digits {
        0 => String::new(),
        3 => format!(".{:03}", nanos / 1_000_000),
        6 => format!(".{:06}", nanos / 1_000),
        _ => format!(".{nanos:09}"),
    };
    let suffix = match suffix {
        UtcSuffix::Z => "Z",
        UtcSuffix::Offset => "+00:00",
    };
    format!("{year}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}{fraction}{suffix}")
}
