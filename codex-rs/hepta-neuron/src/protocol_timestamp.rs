//! Calendar validation for the registered UTC timestamp profile.
//!
//! This validates syntax and representability only. Runtime admission owns the
//! comparison with an authenticated current clock.

pub(crate) fn is_valid_expiry_utc(value: &str) -> bool {
    let bytes = value.as_bytes();
    if !(20..=64).contains(&bytes.len())
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || bytes[10] != b'T'
        || bytes[13] != b':'
        || bytes[16] != b':'
        || bytes.last() != Some(&b'Z')
    {
        return false;
    }
    let components = [
        &bytes[0..4],
        &bytes[5..7],
        &bytes[8..10],
        &bytes[11..13],
        &bytes[14..16],
        &bytes[17..19],
    ];
    let mut numbers = [0_u32; 6];
    for (number, component) in numbers.iter_mut().zip(components) {
        for digit in component {
            if !digit.is_ascii_digit() {
                return false;
            }
            *number = *number * 10 + u32::from(digit - b'0');
        }
    }
    let [year, month, day, hour, minute, second] = numbers;
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
        || (fractional.len() > 1
            && fractional[0] == b'.'
            && fractional[1..].iter().all(u8::is_ascii_digit))
}
