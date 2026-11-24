//! Numeric calendar formats used by persisted rollout names and date windows.

use crate::CivilDate;
use crate::ParseError;
use crate::Timestamp;

// This deliberately supports the repository's numeric directives rather than a
// general strptime language. Calendar validity remains the `time` crate's job.
fn fields(input: &str, pattern: &str) -> Result<[Option<i32>; 6], ParseError> {
    let invalid = || ParseError("invalid numeric calendar value".to_string());
    let mut result = [None; 6];
    let mut rest = input;
    let mut pattern = pattern.chars();
    while let Some(character) = pattern.next() {
        if character != '%' {
            rest = rest.strip_prefix(character).ok_or_else(invalid)?;
            continue;
        }
        let directive = pattern.next().ok_or_else(invalid)?;
        let index = match directive {
            'Y' => 0,
            'm' => 1,
            'd' => 2,
            'H' => 3,
            'M' => 4,
            'S' => 5,
            _ => {
                return Err(ParseError(
                    "unsupported numeric calendar directive".to_string(),
                ));
            }
        };
        rest = rest.trim_start();
        let signed = index == 0 && rest.starts_with(['+', '-']);
        let prefix = usize::from(signed);
        let maximum = if signed {
            usize::MAX
        } else if index == 0 {
            4
        } else {
            2
        };
        let digits = rest[prefix..]
            .bytes()
            .take(maximum)
            .take_while(u8::is_ascii_digit)
            .count();
        if digits == 0 {
            return Err(invalid());
        }
        let length = prefix + digits;
        let value = rest[..length].parse::<i32>().map_err(|_| invalid())?;
        if result[index].is_some_and(|previous| previous != value) {
            return Err(invalid());
        }
        result[index] = Some(value);
        rest = &rest[length..];
    }
    if !rest.is_empty() {
        return Err(invalid());
    }
    Ok(result)
}

pub(crate) fn parse_date(input: &str, pattern: &str) -> Result<CivilDate, ParseError> {
    let parts = fields(input, pattern)?;
    let invalid = || ParseError("invalid calendar date".to_string());
    crate::civil_date(
        parts[0].ok_or_else(invalid)?,
        parts[1]
            .ok_or_else(invalid)?
            .try_into()
            .map_err(|_| invalid())?,
        parts[2]
            .ok_or_else(invalid)?
            .try_into()
            .map_err(|_| invalid())?,
    )
    .ok_or_else(invalid)
}

pub(crate) fn parse_utc(input: &str, pattern: &str) -> Result<Timestamp, ParseError> {
    let parts = fields(input, pattern)?;
    let invalid = || ParseError("invalid UTC calendar timestamp".to_string());
    let second: u32 = parts[5]
        .ok_or_else(invalid)?
        .try_into()
        .map_err(|_| invalid())?;
    let timestamp = Timestamp::from_ymd_hms(
        parts[0].ok_or_else(invalid)?,
        parts[1]
            .ok_or_else(invalid)?
            .try_into()
            .map_err(|_| invalid())?,
        parts[2]
            .ok_or_else(invalid)?
            .try_into()
            .map_err(|_| invalid())?,
        parts[3]
            .ok_or_else(invalid)?
            .try_into()
            .map_err(|_| invalid())?,
        parts[4]
            .ok_or_else(invalid)?
            .try_into()
            .map_err(|_| invalid())?,
        if second == 60 { 59 } else { second },
    )
    .ok_or_else(invalid)?;
    timestamp
        .with_nanoseconds(if second == 60 { 1_000_000_000 } else { 0 })
        .ok_or_else(invalid)
}
