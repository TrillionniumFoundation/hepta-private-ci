use time::Date;
use time::Month;
use time::PrimitiveDateTime;
use time::Time;
use time::UtcOffset;

use crate::CanonicalUtcTimestamp;
use crate::TimestampError;
use crate::check_seconds;

#[derive(Clone, Copy, Eq, PartialEq)]
pub(crate) enum Grammar {
    Rfc3339,
    LegacySerde,
}

struct Input<'a> {
    rest: &'a str,
    grammar: Grammar,
}

pub(crate) fn parse(
    value: &str,
    grammar: Grammar,
) -> Result<CanonicalUtcTimestamp, TimestampError> {
    let mut input = Input {
        rest: value,
        grammar,
    };
    let year = input.year()?;
    input.separator('-')?;
    let month = input.component()?;
    input.separator('-')?;
    let day = input.component()?;
    if !(input.consume('T') || input.consume('t') || input.consume(' ')) {
        return Err(TimestampError::InvalidSyntax);
    }
    let hour = input.component()?;
    input.separator(':')?;
    let minute = input.component()?;
    input.separator(':')?;
    let second = input.component()?;
    let nanos = input.fraction()?;
    let offset = input.offset()?;
    input.whitespace();
    if !input.rest.is_empty() {
        return Err(TimestampError::InvalidSyntax);
    }
    if !(-262_143..=262_142).contains(&year) || second > 60 {
        return Err(TimestampError::OutOfRange);
    }
    let month = Month::try_from(month).map_err(|_| TimestampError::OutOfRange)?;
    let date =
        Date::from_calendar_date(year, month, day).map_err(|_| TimestampError::OutOfRange)?;
    let leap_second = second == 60;
    let second = if leap_second { 59 } else { second };
    let time =
        Time::from_hms_nano(hour, minute, second, nanos).map_err(|_| TimestampError::OutOfRange)?;
    let value = PrimitiveDateTime::new(date, time)
        .assume_offset(offset)
        .to_offset(UtcOffset::UTC);
    check_seconds(value.unix_timestamp())?;
    Ok(CanonicalUtcTimestamp { value, leap_second })
}

impl Input<'_> {
    fn consume(&mut self, character: char) -> bool {
        if let Some(rest) = self.rest.strip_prefix(character) {
            self.rest = rest;
            return true;
        }
        false
    }

    fn whitespace(&mut self) {
        if self.grammar == Grammar::LegacySerde {
            self.rest = self.rest.trim_start();
        }
    }

    fn separator(&mut self, character: char) -> Result<(), TimestampError> {
        self.whitespace();
        if !self.consume(character) {
            return Err(TimestampError::InvalidSyntax);
        }
        Ok(())
    }

    fn number(&mut self, minimum: usize, maximum: usize) -> Result<i64, TimestampError> {
        let mut number = 0i64;
        let mut count = 0;
        for digit in self.rest.bytes().take(maximum) {
            if !digit.is_ascii_digit() {
                break;
            }
            number = number
                .checked_mul(10)
                .and_then(|value| value.checked_add(i64::from(digit - b'0')))
                .ok_or(TimestampError::OutOfRange)?;
            count += 1;
        }
        if count < minimum {
            return Err(TimestampError::InvalidSyntax);
        }
        // The consumed prefix contains only single-byte ASCII digits.
        self.rest = &self.rest[count..];
        Ok(number)
    }

    fn year(&mut self) -> Result<i32, TimestampError> {
        self.whitespace();
        let year = match self.grammar {
            Grammar::Rfc3339 => self.number(4, 4)?,
            Grammar::LegacySerde => {
                if self.consume('-') {
                    -self.number(1, usize::MAX)?
                } else if self.consume('+') {
                    self.number(1, usize::MAX)?
                } else {
                    self.number(1, 4)?
                }
            }
        };
        i32::try_from(year).map_err(|_| TimestampError::OutOfRange)
    }

    fn component(&mut self) -> Result<u8, TimestampError> {
        self.whitespace();
        let minimum = match self.grammar {
            Grammar::Rfc3339 => 2,
            Grammar::LegacySerde => 1,
        };
        u8::try_from(self.number(minimum, 2)?).map_err(|_| TimestampError::OutOfRange)
    }

    fn fraction(&mut self) -> Result<u32, TimestampError> {
        if !self.consume('.') {
            return Ok(0);
        }
        let count = self.rest.bytes().take_while(u8::is_ascii_digit).count();
        if count == 0 {
            return Err(TimestampError::InvalidSyntax);
        }
        let significant = count.min(9);
        let nanos = self.rest.as_bytes()[..significant]
            .iter()
            .fold(0u32, |value, digit| value * 10 + u32::from(digit - b'0'))
            * 10u32.pow(9 - significant as u32);
        self.rest = &self.rest[count..];
        Ok(nanos)
    }

    fn offset(&mut self) -> Result<UtcOffset, TimestampError> {
        self.whitespace();
        if self.grammar == Grammar::LegacySerde
            && self
                .rest
                .get(..3)
                .is_some_and(|prefix| prefix.eq_ignore_ascii_case("UTC"))
        {
            self.rest = &self.rest[3..];
            return Ok(UtcOffset::UTC);
        }
        if self.consume('Z') || self.consume('z') {
            return Ok(UtcOffset::UTC);
        }
        let sign = if self.consume('+') {
            1
        } else if self.consume('-') || self.consume('−') {
            -1
        } else {
            return Err(TimestampError::InvalidSyntax);
        };
        let hours = self.number(2, 2)?;
        match self.grammar {
            Grammar::Rfc3339 => self.separator(':')?,
            Grammar::LegacySerde => {
                self.rest = self.rest.trim_start_matches(|character: char| {
                    character == ':' || character.is_whitespace()
                });
            }
        }
        let minutes = self.number(2, 2)?;
        if hours > 23 || minutes > 59 {
            return Err(TimestampError::OutOfRange);
        }
        let seconds = sign * (hours * 3_600 + minutes * 60);
        UtcOffset::from_whole_seconds(seconds as i32).map_err(|_| TimestampError::OutOfRange)
    }
}
