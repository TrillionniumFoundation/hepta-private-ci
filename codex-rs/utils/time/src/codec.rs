use crate::OffsetTimestamp;
use crate::ParseError;
use crate::Timestamp;
use time::UtcOffset;
use time::format_description::well_known::Rfc3339;

#[derive(Clone, Copy, Debug)]
pub enum Precision {
    Seconds,
    Milliseconds,
    Microseconds,
    Nanoseconds,
    Auto,
}

pub(crate) enum UtcStyle {
    Numeric,
    Zulu,
}
pub(crate) enum ParseMode {
    Rfc3339,
    Persisted,
}

pub(crate) fn parse(input: &str, mode: ParseMode) -> Result<OffsetTimestamp, ParseError> {
    let mut text = if matches!(mode, ParseMode::Persisted) {
        normalize_persisted(input)?
    } else {
        input.to_owned()
    };
    let mut original_year = None;
    // The persisted format also admits signed expanded years. RFC 3339 itself
    // remains restricted to four unsigned digits, as the old explicit parser was.
    if matches!(mode, ParseMode::Persisted) && text.starts_with(['+', '-']) {
        let end = text[1..]
            .find('-')
            .map(|n| n + 1)
            .ok_or_else(|| ParseError("invalid expanded year".to_string()))?;
        let year = text[..end]
            .parse::<i32>()
            .map_err(|error| ParseError(error.to_string()))?;
        original_year = Some(year);
        // Gregorian dates and weekdays repeat every 400 years.
        text.replace_range(..end, &(2000 + year.rem_euclid(400)).to_string());
    }
    if !matches!(text.as_bytes().get(10), Some(b'T' | b't' | b' ')) {
        return Err(ParseError("invalid date and time separator".to_string()));
    }
    // The explicit RFC parser historically admitted U+2212 for the offset sign.
    // Only normalize its offset position, never date separators or the year.
    let suffix_start = if text.as_bytes().get(19) == Some(&b'.') {
        20 + text.as_bytes()[20..]
            .iter()
            .take_while(|byte| byte.is_ascii_digit())
            .count()
    } else {
        19
    };
    if text
        .get(suffix_start..)
        .is_some_and(|suffix| suffix.starts_with('−'))
    {
        text.replace_range(suffix_start..suffix_start + '−'.len_utf8(), "-");
    }
    let leap = text.get(17..19) == Some("60");
    if leap {
        text.replace_range(17..19, "59");
    }
    let mut parsed = time::OffsetDateTime::parse(&text, &Rfc3339)
        .map_err(|error| ParseError(error.to_string()))?;
    if let Some(year) = original_year {
        parsed = parsed
            .replace_year(year)
            .map_err(|error| ParseError(error.to_string()))?;
    }
    let nanos = parsed.nanosecond() + if leap { 1_000_000_000 } else { 0 };
    let instant = Timestamp::from_parts(parsed.unix_timestamp(), nanos)
        .ok_or_else(|| ParseError("timestamp is outside the supported range".to_string()))?;
    Ok(OffsetTimestamp {
        instant,
        offset: parsed.offset(),
        system_local: false,
    })
}

// Old persisted timestamps also admitted unpadded fields, component whitespace,
// UTC, and colon-free numeric offsets. Normalize that boundary syntax before
// passing all calendar/range validation to the maintained parser.
fn normalize_persisted(input: &str) -> Result<String, ParseError> {
    fn invalid() -> ParseError {
        ParseError("invalid persisted timestamp".to_string())
    }
    fn number(text: &mut &str, maximum: usize) -> Result<String, ParseError> {
        *text = text.trim_start();
        let length = text
            .bytes()
            .take(maximum)
            .take_while(u8::is_ascii_digit)
            .count();
        if length == 0 {
            return Err(invalid());
        }
        let result = text[..length].to_string();
        *text = &text[length..];
        Ok(result)
    }
    fn delimiter(text: &mut &str, expected: char) -> Result<(), ParseError> {
        *text = text
            .trim_start()
            .strip_prefix(expected)
            .ok_or_else(invalid)?;
        Ok(())
    }
    let mut rest = input.trim_start();
    let sign = if rest.starts_with(['+', '-']) {
        let sign = &rest[..1];
        rest = &rest[1..];
        sign
    } else {
        ""
    };
    let year = number(&mut rest, if sign.is_empty() { 4 } else { usize::MAX })?;
    delimiter(&mut rest, '-')?;
    let month = number(&mut rest, 2)?;
    delimiter(&mut rest, '-')?;
    let day = number(&mut rest, 2)?;
    if !matches!(rest.as_bytes().first(), Some(b'T' | b't' | b' ')) {
        return Err(invalid());
    }
    rest = &rest[1..];
    let hour = number(&mut rest, 2)?;
    delimiter(&mut rest, ':')?;
    let minute = number(&mut rest, 2)?;
    delimiter(&mut rest, ':')?;
    let second = number(&mut rest, 2)?;
    let fraction = if let Some(after_dot) = rest.strip_prefix('.') {
        let length = after_dot.bytes().take_while(u8::is_ascii_digit).count();
        if length == 0 {
            return Err(invalid());
        }
        rest = &after_dot[length..];
        format!(".{}", &after_dot[..length])
    } else {
        String::new()
    };
    rest = rest.trim_start();
    let offset = if rest
        .get(..3)
        .is_some_and(|text| text.eq_ignore_ascii_case("UTC"))
    {
        rest = &rest[3..];
        "Z".to_string()
    } else if rest.starts_with(['Z', 'z']) {
        rest = &rest[1..];
        "Z".to_string()
    } else {
        let sign = match rest.chars().next() {
            Some('+') => '+',
            Some('-' | '−') => '-',
            _ => return Err(invalid()),
        };
        rest = &rest[rest.chars().next().ok_or_else(invalid)?.len_utf8()..];
        let hour = rest
            .get(..2)
            .filter(|s| s.bytes().all(|b| b.is_ascii_digit()))
            .ok_or_else(invalid)?;
        rest = rest[2..].trim_start_matches(|ch: char| ch == ':' || ch.is_whitespace());
        let minute = rest
            .get(..2)
            .filter(|s| s.bytes().all(|b| b.is_ascii_digit()))
            .ok_or_else(invalid)?;
        rest = &rest[2..];
        format!("{sign}{hour}:{minute}")
    };
    if !rest.trim_start().is_empty() {
        return Err(invalid());
    }
    Ok(format!(
        "{sign}{year:0>4}-{month:0>2}-{day:0>2}T{hour:0>2}:{minute:0>2}:{second:0>2}{fraction}{offset}"
    ))
}

fn year_text(year: i32) -> String {
    if year < 0 {
        format!("-{:04}", year.unsigned_abs())
    } else if year > 9999 {
        format!("+{year}")
    } else {
        format!("{year:04}")
    }
}

fn fraction(nanoseconds: u32, precision: Precision) -> String {
    let nanos = nanoseconds % 1_000_000_000;
    let digits = match precision {
        Precision::Seconds => 0,
        Precision::Milliseconds => 3,
        Precision::Microseconds => 6,
        Precision::Nanoseconds => 9,
        Precision::Auto if nanos == 0 => 0,
        Precision::Auto if nanos.is_multiple_of(1_000_000) => 3,
        Precision::Auto if nanos.is_multiple_of(1_000) => 6,
        Precision::Auto => 9,
    };
    if digits == 0 {
        String::new()
    } else {
        format!(
            ".{:0width$}",
            nanos / 10_u32.pow(9 - digits),
            width = digits as usize
        )
    }
}

pub(crate) fn format_offset(offset: UtcOffset) -> String {
    let seconds = offset.whole_seconds();
    let sign = if seconds < 0 { '-' } else { '+' };
    let seconds = seconds.unsigned_abs();
    format!("{sign}{:02}:{:02}", seconds / 3600, seconds % 3600 / 60)
}

pub(crate) fn rfc3339(
    instant: Timestamp,
    offset: UtcOffset,
    precision: Precision,
    style: UtcStyle,
) -> String {
    let local = instant.calendar().to_offset(offset);
    let suffix = if matches!(style, UtcStyle::Zulu) && offset.is_utc() {
        "Z".to_string()
    } else {
        format_offset(offset)
    };
    let second = u32::from(local.second()) + instant.nanoseconds / 1_000_000_000;
    format!(
        "{}-{:02}-{:02}T{:02}:{:02}:{second:02}{}{suffix}",
        year_text(local.year()),
        local.month() as u8,
        local.day(),
        local.hour(),
        local.minute(),
        fraction(instant.nanoseconds, precision)
    )
}

pub(crate) fn format(
    instant: Timestamp,
    offset: UtcOffset,
    pattern: &str,
    zone_name: &str,
) -> String {
    let local = instant.calendar().to_offset(offset);
    let year = year_text(local.year());
    let seconds = (u32::from(local.second()) + instant.nanoseconds / 1_000_000_000).to_string();
    let nanos = instant.nanoseconds % 1_000_000_000;
    let mut adapted = String::new();
    let mut chars = pattern.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch != '%' {
            adapted.push(ch);
            continue;
        }
        match chars.next() {
            Some('Y') => adapted.push_str(&year),
            Some('S') => adapted.push_str(&format!("{seconds:0>2}")),
            Some('s') => adapted.push_str(&instant.seconds.to_string()),
            Some('Z') => adapted.push_str(zone_name),
            Some('f') => adapted.push_str(&format!("{nanos:09}")),
            Some('.') => {
                let precision = match chars.next() {
                    Some('f') => Precision::Auto,
                    Some('3') if chars.next() == Some('f') => Precision::Milliseconds,
                    Some('6') if chars.next() == Some('f') => Precision::Microseconds,
                    Some('9') if chars.next() == Some('f') => Precision::Nanoseconds,
                    _ => panic!("unsupported time fraction format"),
                };
                adapted.push_str(&fraction(nanos, precision));
            }
            Some('%') => adapted.push_str("%%"),
            Some(ch) => {
                adapted.push('%');
                adapted.push(ch);
            }
            None => panic!("incomplete time format"),
        }
    }
    // Mapping into a Gregorian 400-year cycle lets Jiff format even the
    // expanded years supported by our persisted format. %Y and %s above retain
    // the original year/instant; month, weekday and leap-day layout are identical.
    let civil = jiff::civil::DateTime::new(
        (2000 + local.year().rem_euclid(400)) as i16,
        local.month() as i8,
        local.day() as i8,
        local.hour() as i8,
        local.minute() as i8,
        local.second() as i8,
        nanos as i32,
    )
    .expect("validated calendar fields");
    let zone_offset =
        jiff::tz::Offset::from_seconds(offset.whole_seconds()).expect("validated offset");
    let zoned = zone_offset
        .to_timestamp(civil)
        .expect("cycle date in range")
        .to_zoned_datetime(jiff::tz::TimeZone::fixed(zone_offset));
    zoned.strftime(&adapted).to_string()
}
