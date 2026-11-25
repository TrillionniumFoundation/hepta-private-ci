//! Maintained TZif/POSIX parsing with explicit legacy compatibility boundaries.

use super::LocalTimeError;
use super::compatibility::LegacyRule;
use super::compatibility::RuleSyntax;
use super::compatibility::valid_offset_ranges;
use tz::TimeZone;
use tz::TzError;
use tz::timezone::LocalTimeType;
use tz::timezone::TimeZoneSettings;
use tz::timezone::TransitionRule;

#[derive(Debug)]
pub(super) enum ConfigurationError {
    Invalid,
    Compatibility,
}

pub(super) struct Zone {
    parsed: TimeZone,
    legacy_rule: Option<LegacyRule>,
}

impl Zone {
    pub(super) fn utc() -> Self {
        Self {
            parsed: TimeZone::utc(),
            legacy_rule: None,
        }
    }

    pub(super) fn posix(value: &str) -> Result<Self, ConfigurationError> {
        if !valid_offset_ranges(value) {
            return Err(ConfigurationError::Invalid);
        }
        // File discovery already used the untrimmed configuration. Parsing
        // the grammar must not reinterpret a padded file name as a new lookup.
        let settings = TimeZoneSettings::new(&[], |_| {
            Err(std::io::Error::from(std::io::ErrorKind::NotFound).into())
        });
        match settings.parse_posix_tz(value) {
            Ok(zone) => Self::parsed(zone),
            Err(tz::Error::Tz(TzError::TransitionRule(
                tz::error::timezone::TransitionRuleError::InconsistentRule,
            ))) => {
                let rule = LegacyRule::parse(value, RuleSyntax::Posix)
                    .ok_or(ConfigurationError::Compatibility)?;
                if !valid_name(&rule.standard) || !valid_name(&rule.daylight) {
                    return Err(ConfigurationError::Invalid);
                }
                let parsed = TimeZone::new(
                    vec![],
                    vec![rule.standard],
                    vec![],
                    /*extra_rule*/ None,
                )
                .map_err(|_| ConfigurationError::Compatibility)?;
                Ok(Self {
                    parsed,
                    legacy_rule: Some(rule),
                })
            }
            Err(_) => Err(ConfigurationError::Invalid),
        }
    }

    pub(super) fn tzif(bytes: &[u8]) -> Result<Self, ConfigurationError> {
        if let Some((start, _)) = footer_start(bytes)
            && let Some(footer) = bytes.get(start..)
            && let Ok(footer) = std::str::from_utf8(footer)
            && !valid_offset_ranges(
                footer.trim_matches(|character: char| character.is_ascii_whitespace()),
            )
        {
            return Err(ConfigurationError::Invalid);
        }
        let parsed = TimeZone::from_tz_data(bytes);
        let normalized = if matches!(
            parsed,
            Err(TzError::TzFile(
                tz::error::parse::TzFileError::InvalidStdWallUtLocal
            ))
        ) {
            Some(normalize_legacy_indicators(bytes).ok_or(ConfigurationError::Invalid)?)
        } else {
            None
        };
        let bytes = normalized.as_deref().unwrap_or(bytes);
        let parsed = if normalized.is_some() {
            TimeZone::from_tz_data(bytes)
        } else {
            parsed
        };
        match parsed {
            Ok(zone) => Self::parsed(zone),
            Err(TzError::TransitionRule(
                tz::error::timezone::TransitionRuleError::InconsistentRule,
            )) => {
                let (start, syntax) =
                    footer_start(bytes).ok_or(ConfigurationError::Compatibility)?;
                let text = std::str::from_utf8(
                    bytes
                        .get(start..)
                        .ok_or(ConfigurationError::Compatibility)?,
                )
                .map_err(|_| ConfigurationError::Compatibility)?;
                let text = text.trim_matches(|character: char| character.is_ascii_whitespace());
                let rule =
                    LegacyRule::parse(text, syntax).ok_or(ConfigurationError::Compatibility)?;
                if !valid_name(&rule.standard) || !valid_name(&rule.daylight) {
                    return Err(ConfigurationError::Invalid);
                }
                let mut without_rule = bytes[..start].to_vec();
                without_rule.extend_from_slice(b"\n\n");
                let parsed = TimeZone::from_tz_data(&without_rule)
                    .map_err(|_| ConfigurationError::Compatibility)?;
                let mut zone = Self::parsed(parsed)?;
                // Retain the former check tying the footer to the final
                // real transition; accepting a legacy rule cannot bypass it.
                let view = zone.parsed.as_ref();
                if let Some(last) = view.transitions().last() {
                    let before = last
                        .unix_leap_time()
                        .checked_sub(1)
                        .ok_or(ConfigurationError::Invalid)?;
                    let count = view
                        .leap_seconds()
                        .partition_point(|leap| leap.unix_leap_time() <= before);
                    let correction = count
                        .checked_sub(1)
                        .map(|index| view.leap_seconds()[index].correction())
                        .unwrap_or(0);
                    let seconds = last
                        .unix_leap_time()
                        .checked_sub(i64::from(correction))
                        .ok_or(ConfigurationError::Invalid)?;
                    let footer_type = rule
                        .local_type(seconds)
                        .map_err(|_| ConfigurationError::Invalid)?;
                    if &view.local_time_types()[last.local_time_type_index()] != footer_type {
                        return Err(ConfigurationError::Invalid);
                    }
                }
                zone.legacy_rule = Some(rule);
                Ok(zone)
            }
            Err(_) => Err(ConfigurationError::Invalid),
        }
    }

    fn parsed(parsed: TimeZone) -> Result<Self, ConfigurationError> {
        let view = parsed.as_ref();
        let valid = view.local_time_types().iter().all(valid_name)
            && match view.extra_rule() {
                None => true,
                Some(TransitionRule::Fixed(local)) => valid_name(local),
                Some(TransitionRule::Alternate(rule)) => {
                    valid_name(rule.std()) && valid_name(rule.dst())
                }
            };
        if !valid {
            return Err(ConfigurationError::Invalid);
        }
        Ok(Self {
            parsed,
            legacy_rule: None,
        })
    }

    pub(super) fn offset(&self, seconds: i64) -> Result<i32, LocalTimeError> {
        let view = self.parsed.as_ref();
        let local = if view.transitions().is_empty()
            && let Some(rule) = &self.legacy_rule
        {
            rule.local_type(seconds)?
        } else {
            match self.parsed.find_local_time_type(seconds) {
                Ok(local) => local,
                // Old Local deliberately kept the final offset when a TZif
                // file omitted its extrapolation footer (notably on macOS).
                Err(TzError::NoAvailableLocalTimeType) if view.extra_rule().is_none() => {
                    match &self.legacy_rule {
                        Some(rule) => rule.local_type(seconds)?,
                        None => {
                            let last = view
                                .transitions()
                                .last()
                                .ok_or(LocalTimeError::Unavailable)?;
                            &view.local_time_types()[last.local_time_type_index()]
                        }
                    }
                }
                Err(_) => return Err(LocalTimeError::Unavailable),
            }
        };
        let offset = local.ut_offset();
        if !(-86_399..=86_399).contains(&offset) {
            return Err(LocalTimeError::InvalidOffset);
        }
        Ok(offset)
    }
}

fn valid_name(local: &LocalTimeType) -> bool {
    let name = local.time_zone_designation();
    name.is_empty() || name.len() >= 3
}

// The former reader rejected only the (wall, UT) pair (0, 1). Other indicator
// bytes never entered its UTC lookup. Retain that exact acceptance boundary
// while handing a canonical, otherwise byte-identical block to the maintained
// parser. DST flags, transition data and leap records are never rewritten.
fn normalize_legacy_indicators(bytes: &[u8]) -> Option<Vec<u8>> {
    let block = |start: usize, width: usize| {
        let header = bytes.get(start..start.checked_add(44)?)?;
        if header.get(..4)? != b"TZif" {
            return None;
        }
        let count = |offset: usize| -> Option<usize> {
            usize::try_from(u32::from_be_bytes(
                header.get(offset..offset + 4)?.try_into().ok()?,
            ))
            .ok()
        };
        let ut = count(20)?;
        let wall = count(24)?;
        let types = count(36)?;
        if types == 0 || count(40)? == 0 || (ut != 0 && ut != types) || (wall != 0 && wall != types)
        {
            return None;
        }
        let indicators = start
            .checked_add(44)?
            .checked_add(count(32)?.checked_mul(width + 1)?)?
            .checked_add(types.checked_mul(6)?)?
            .checked_add(count(40)?)?
            .checked_add(count(28)?.checked_mul(width + 4)?)?;
        let end = indicators.checked_add(wall)?.checked_add(ut)?;
        bytes.get(start..end)?;
        Some((indicators, wall, ut, types, end))
    };
    let first = block(0, 4)?;
    let (start, wall, ut, types, end) = match bytes.get(4)? {
        0 => first,
        b'2' | b'3' => block(first.4, 8)?,
        _ => return None,
    };
    for index in 0..types {
        let std_wall = if wall == 0 { 0 } else { bytes[start + index] };
        let ut_local = if ut == 0 {
            0
        } else {
            bytes[start + wall + index]
        };
        if (std_wall, ut_local) == (0, 1) {
            return None;
        }
    }
    let mut normalized = bytes.to_vec();
    normalized.get_mut(start..end)?.fill(0);
    Some(normalized)
}

fn footer_start(bytes: &[u8]) -> Option<(usize, RuleSyntax)> {
    let block_end = |start: usize, width: usize| {
        let header = bytes.get(start..start.checked_add(44)?)?;
        let count = |offset: usize| -> Option<usize> {
            usize::try_from(u32::from_be_bytes(
                header.get(offset..offset + 4)?.try_into().ok()?,
            ))
            .ok()
        };
        let size = count(32usize)?
            .checked_mul(width + 1)?
            .checked_add(count(36)?.checked_mul(6)?)?
            .checked_add(count(40)?)?
            .checked_add(count(28)?.checked_mul(width + 4)?)?
            .checked_add(count(24)?)?
            .checked_add(count(20)?)?;
        start.checked_add(44)?.checked_add(size)
    };
    let second_header = block_end(0usize, 4usize)?;
    let syntax = match bytes.get(second_header.checked_add(4)?)? {
        b'2' => RuleSyntax::Posix,
        b'3' => RuleSyntax::TzifV3,
        _ => return None,
    };
    Some((block_end(second_header, 8usize)?, syntax))
}

#[cfg(test)]
#[path = "local_zone_tests.rs"]
mod tests;
