use super::MAX_YEAR;
use super::MIN_YEAR;
use super::Timestamp;
use time::Date;
use time::Month;
use time::Time;

pub(super) fn filename_timestamp(mut input: &str) -> Option<Timestamp> {
    input = input.trim_start();
    let (sign, width) = if let Some(rest) = input.strip_prefix('-') {
        input = rest;
        (-1, usize::MAX)
    } else if let Some(rest) = input.strip_prefix('+') {
        input = rest;
        (1, usize::MAX)
    } else {
        (1, 4)
    };
    if width == usize::MAX && input.starts_with(char::is_whitespace) {
        return None;
    }
    let year = i32::try_from(number(&mut input, width)?.checked_mul(sign)?).ok()?;
    input = input.strip_prefix('-')?;
    let month = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    input = input.strip_prefix('-')?;
    let day = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    input = input.strip_prefix('T')?;
    let hour = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    input = input.strip_prefix('-')?;
    let minute = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    input = input.strip_prefix('-')?;
    let second = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    if !input.is_empty() || second > 60 {
        return None;
    }
    let base = Timestamp::from_ymd_hms(
        year,
        u32::from(month),
        u32::from(day),
        u32::from(hour),
        u32::from(minute),
        u32::from(second.min(59)),
    )?;
    if second == 60 {
        base.with_nanosecond(/*nanoseconds*/ 1_000_000_000)
    } else {
        Some(base)
    }
}

pub(super) fn strict_timestamp(input: &str) -> Option<Timestamp> {
    let bytes = input.as_bytes();
    let fixed = bytes.get(..19)?;
    for (index, byte) in fixed.iter().enumerate() {
        let valid = match index {
            4 | 7 => *byte == b'-',
            10 => matches!(byte, b'T' | b't' | b' '),
            13 | 16 => *byte == b':',
            _ => byte.is_ascii_digit(),
        };
        if !valid {
            return None;
        }
    }
    let mut suffix = input.get(19..)?;
    if let Some(fraction) = suffix.strip_prefix('.') {
        let count = fraction.bytes().take_while(u8::is_ascii_digit).count();
        if count == 0 {
            return None;
        }
        suffix = &fraction[count..];
    }
    if suffix != "Z" && suffix != "z" {
        let offset = suffix
            .strip_prefix(['+', '-'])
            .or_else(|| suffix.strip_prefix('−'))?;
        if offset.len() != 5 || offset.as_bytes()[2] != b':' {
            return None;
        }
        if !offset
            .as_bytes()
            .iter()
            .enumerate()
            .all(|(index, byte)| index == 2 || byte.is_ascii_digit())
        {
            return None;
        }
    }
    timestamp(input)
}

pub(super) fn timestamp(mut input: &str) -> Option<Timestamp> {
    input = input.trim_start();
    let (sign, width) = if let Some(rest) = input.strip_prefix('-') {
        input = rest;
        (-1, usize::MAX)
    } else if let Some(rest) = input.strip_prefix('+') {
        input = rest;
        (1, usize::MAX)
    } else {
        (1, 4)
    };
    if width == usize::MAX && input.starts_with(char::is_whitespace) {
        return None;
    }
    let year = i32::try_from(number(&mut input, width)?.checked_mul(sign)?).ok()?;
    if !(MIN_YEAR..=MAX_YEAR).contains(&year) {
        return None;
    }
    input = input.trim_start().strip_prefix('-')?;
    let month = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    input = input.trim_start().strip_prefix('-')?;
    let day = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    input = input.strip_prefix(['T', 't', ' '])?;
    let hour = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    input = input.trim_start().strip_prefix(':')?;
    let minute = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    input = input.trim_start().strip_prefix(':')?;
    let second = u8::try_from(number(&mut input, /*width*/ 2)?).ok()?;
    if second > 60 {
        return None;
    }

    let mut nanos = 0_u32;
    if let Some(fraction) = input.strip_prefix('.') {
        let count = fraction.bytes().take_while(u8::is_ascii_digit).count();
        if count == 0 {
            return None;
        }
        // The persisted parser truncates extra decimal places; it does not round.
        let significant = count.min(9);
        nanos = fraction[..significant].parse::<u32>().ok()?
            * 10_u32.pow(u32::try_from(9 - significant).ok()?);
        input = &fraction[count..];
    }
    input = input.trim_start();
    let offset = if input
        .get(..3)
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case("UTC"))
    {
        input = &input[3..];
        0
    } else if let Some(rest) = input.strip_prefix(['Z', 'z']) {
        input = rest;
        0
    } else {
        let sign = match input.chars().next()? {
            '+' => {
                input = &input[1..];
                1
            }
            '-' => {
                input = &input[1..];
                -1
            }
            '−' => {
                input = &input['−'.len_utf8()..];
                -1
            }
            _ => return None,
        };
        // Offset fields always have two digits, even in the relaxed legacy format.
        let hours = offset_number(&mut input)?;
        input = input.trim_start_matches(|c: char| c == ':' || c.is_whitespace());
        let minutes = offset_number(&mut input)?;
        if hours > 23 || minutes > 59 {
            return None;
        }
        sign * (i64::from(hours) * 3600 + i64::from(minutes) * 60)
    };
    if !input.trim_start().is_empty() {
        return None;
    }

    let date = Date::from_calendar_date(year, Month::try_from(month).ok()?, day).ok()?;
    let time = Time::from_hms(hour, minute, second.min(59)).ok()?;
    let seconds = date
        .with_time(time)
        .assume_utc()
        .unix_timestamp()
        .checked_sub(offset)?;
    let utc = time::OffsetDateTime::from_unix_timestamp(seconds).ok()?;
    if !(MIN_YEAR..=MAX_YEAR).contains(&utc.year()) {
        return None;
    }
    if second == 60 {
        nanos += 1_000_000_000;
    }
    Some(Timestamp {
        seconds,
        nanoseconds: nanos,
    })
}

fn number(input: &mut &str, width: usize) -> Option<i64> {
    *input = input.trim_start();
    let count = input
        .bytes()
        .take(width)
        .take_while(u8::is_ascii_digit)
        .count();
    if count == 0 {
        return None;
    }
    let value = input[..count].parse().ok()?;
    *input = &input[count..];
    Some(value)
}

fn offset_number(input: &mut &str) -> Option<u8> {
    let digits = input.as_bytes().get(..2)?;
    if !digits.iter().all(u8::is_ascii_digit) {
        return None;
    }
    let value = (digits[0] - b'0') * 10 + digits[1] - b'0';
    *input = &input[2..];
    Some(value)
}
