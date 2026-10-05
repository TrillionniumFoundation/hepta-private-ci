//! Gregorian calendar validation for the registered, bounded UTC expiry syntax.
//! This checks representation only; it does not compare expiry to a host clock.

pub(super) fn valid_utc_timestamp(value: &str) -> bool {
    let bytes = value.as_bytes();
    if !(20..=64).contains(&bytes.len())
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || bytes[10] != b'T'
        || bytes[13] != b':'
        || bytes[16] != b':'
        || bytes[bytes.len() - 1] != b'Z'
    {
        return false;
    }
    let fields = (
        decimal(&bytes[0..4]),
        decimal(&bytes[5..7]),
        decimal(&bytes[8..10]),
        decimal(&bytes[11..13]),
        decimal(&bytes[14..16]),
        decimal(&bytes[17..19]),
    );
    let (Some(year), Some(month), Some(day), Some(hour), Some(minute), Some(second)) = fields
    else {
        return false;
    };
    let days_in_month = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        2 => 28,
        _ => return false,
    };
    if day == 0 || day > days_in_month || hour > 23 || minute > 59 || second > 59 {
        return false;
    }
    let fractional = &bytes[19..bytes.len() - 1];
    fractional.is_empty()
        || (fractional[0] == b'.'
            && fractional.len() > 1
            && fractional[1..].iter().all(u8::is_ascii_digit))
}

fn decimal(bytes: &[u8]) -> Option<u32> {
    bytes.iter().try_fold(0_u32, |value, byte| {
        if !byte.is_ascii_digit() {
            return None;
        }
        value.checked_mul(10)?.checked_add(u32::from(byte - b'0'))
    })
}
