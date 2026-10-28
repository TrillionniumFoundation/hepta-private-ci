//! Host transport compatibility for the frozen worker's YYYYMMDD slots.
//! Native requests and owner records always retain Unix seconds. This profile
//! is separate from the frozen classifier and conveys no source authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use time::Date;
use time::Month;
use time::OffsetDateTime;
use unicode_normalization::UnicodeNormalization;

use super::wire::canonical;
use super::wire::hash;

pub const MEMORY_CELL_TIME_VIEW_PROFILE_V1: &str = "hepta.memory.host-utc-midnight-time-view.v1";

/// A recognized capability boundary stays distinct from invalid profile data
/// and host failures. The caller may abstain only on this explicit variant.
#[derive(Debug, Eq, PartialEq)]
pub(super) enum TimeViewError {
    UnsupportedMultipleCutoffs,
    Invalid(String),
}

impl From<String> for TimeViewError {
    fn from(reason: String) -> Self {
        Self::Invalid(reason)
    }
}

pub(super) struct TimeView {
    pub at: u64,
    pub since: u64,
    original_digest: ContractDigestV1,
    literal: Option<Date>,
}

impl TimeView {
    pub fn build(
        request: &MemoryRequestV1,
        entities: &BTreeSet<ContractIdV1>,
        aliases: &BTreeMap<ContractIdV1, Vec<String>>,
    ) -> Result<Self, TimeViewError> {
        let original_digest = native_digest(request)?;
        let literal = literal_date(&masked_text(&request.text, entities, aliases))?;
        let (at, since) = match literal {
            Some(_) => (calendar_slot(request.at)?, calendar_slot(request.since)?),
            None => (request.at, request.since),
        };
        Ok(Self {
            at,
            since,
            original_digest,
            literal,
        })
    }

    pub fn verify_original(&self, request: &MemoryRequestV1) -> Result<(), String> {
        if native_digest(request)? != self.original_digest {
            return Err("native request changed across the private worker time view".to_string());
        }
        Ok(())
    }

    /// The selected operation must still agree with the ORIGINAL Unix cutoff.
    /// Merely landing on the same UTC day is insufficient: V1 requires midnight.
    pub fn permits(&self, request: &MemoryRequestV1, operation: MemoryOperationV1) -> bool {
        let Some(date) = self.literal else {
            return true;
        };
        let cutoff = match operation {
            MemoryOperationV1::History => request.at,
            MemoryOperationV1::Change => request.since,
            MemoryOperationV1::Current
            | MemoryOperationV1::Semantic
            | MemoryOperationV1::Procedure
            | MemoryOperationV1::Apply => return false,
        };
        u64::try_from(date.midnight().assume_utc().unix_timestamp()).ok() == Some(cutoff)
    }
}

fn native_digest(request: &MemoryRequestV1) -> Result<ContractDigestV1, String> {
    let value = serde_json::to_value(request)
        .map_err(|_| "native time-view request encoding failed".to_string())?;
    Ok(hash(&canonical(&value)?))
}

fn calendar_slot(seconds: u64) -> Result<u64, String> {
    let seconds = i64::try_from(seconds)
        .map_err(|_| "native cutoff exceeds UTC timestamp range".to_string())?;
    let date = OffsetDateTime::from_unix_timestamp(seconds)
        .map_err(|_| "native cutoff is outside the worker calendar range".to_string())?
        .date();
    if !(1..=9999).contains(&date.year()) {
        return Err("native cutoff is outside the worker date profile".to_string());
    }
    Ok(date.year() as u64 * 10_000
        + u64::from(u8::from(date.month())) * 100
        + u64::from(date.day()))
}

fn normalized(value: &str) -> String {
    value.nfkc().flat_map(char::to_lowercase).collect()
}

// Only owner-listed metadata is masked, longest match first, with the frozen
// worker's ASCII-edge word/hyphen boundaries. The actual request text is never
// rewritten. Lowercasing is not full Unicode casefold: a missed date-bearing
// alias may conservatively fail the final operation/cutoff check, but unrelated
// registry aliases must never veto an otherwise valid literal cutoff.
fn masked_text(
    text: &str,
    entities: &BTreeSet<ContractIdV1>,
    aliases: &BTreeMap<ContractIdV1, Vec<String>>,
) -> String {
    let text = normalized(text);
    let names: BTreeSet<_> = entities
        .iter()
        .flat_map(|entity| {
            std::iter::once(entity.as_str()).chain(
                aliases
                    .get(entity)
                    .into_iter()
                    .flatten()
                    .map(String::as_str),
            )
        })
        .map(normalized)
        .collect();
    let word = |c: char| c.is_alphanumeric() || c == '_' || c == '-';
    let mut spans = Vec::new();
    for name in &names {
        if name.is_empty() {
            continue;
        }
        for (start, _) in text.match_indices(name.as_str()) {
            let end = start + name.len();
            if name.as_bytes()[0].is_ascii_alphanumeric()
                && text[..start].chars().next_back().is_some_and(word)
                || name.as_bytes()[name.len() - 1].is_ascii_alphanumeric()
                    && text[end..].chars().next().is_some_and(word)
            {
                continue;
            }
            spans.push((start, end));
        }
    }
    spans.sort_by_key(|(start, end)| (std::cmp::Reverse(end - start), *start));
    let mut selected = Vec::new();
    for span in spans {
        if !selected
            .iter()
            .any(|old: &(usize, usize)| span.0 < old.1 && old.0 < span.1)
        {
            selected.push(span);
        }
    }
    selected.sort_unstable();
    let mut masked = text;
    for (start, end) in selected.into_iter().rev() {
        masked.replace_range(start..end, " entity ");
    }
    masked
}

fn literal_date(text: &str) -> Result<Option<Date>, TimeViewError> {
    let chars: Vec<_> = text.chars().collect();
    let mut found = None;
    let mut offset = 0;
    while offset < chars.len() {
        if !chars[offset].is_numeric() || offset > 0 && chars[offset - 1].is_numeric() {
            offset += 1;
            continue;
        }
        let mut parsed = None;
        for width in [10, 8] {
            let Some(candidate) = chars.get(offset..offset + width) else {
                continue;
            };
            if chars.get(offset + width).is_some_and(|c| c.is_numeric()) {
                continue;
            }
            if !candidate.iter().enumerate().all(|(index, c)| {
                if width == 10 && (index == 4 || index == 7) {
                    *c == '-'
                } else {
                    c.is_numeric()
                }
            }) {
                continue;
            }
            if !candidate.iter().all(char::is_ascii) {
                return Err(TimeViewError::Invalid(
                    "non-ASCII decimal date is outside the host time profile".to_string(),
                ));
            }
            let digits: String = candidate.iter().copied().filter(|c| *c != '-').collect();
            let year: i32 = digits[..4]
                .parse()
                .map_err(|_| "invalid date year".to_string())?;
            let month: u8 = digits[4..6]
                .parse()
                .map_err(|_| "invalid date month".to_string())?;
            let day: u8 = digits[6..]
                .parse()
                .map_err(|_| "invalid date day".to_string())?;
            let month = Month::try_from(month).map_err(|_| "invalid date month".to_string())?;
            if year == 0 {
                return Err(TimeViewError::Invalid("invalid date year".to_string()));
            }
            parsed = Some((
                Date::from_calendar_date(year, month, day)
                    .map_err(|_| "invalid literal calendar date".to_string())?,
                width,
            ));
            break;
        }
        if let Some((date, width)) = parsed {
            if found.is_some_and(|old| old != date) {
                return Err(TimeViewError::UnsupportedMultipleCutoffs);
            }
            found = Some(date);
            offset += width;
        } else {
            offset += 1;
        }
    }
    Ok(found)
}

#[cfg(test)]
#[path = "memory_cell_time_view_tests.rs"]
mod tests;
