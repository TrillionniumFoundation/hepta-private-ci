//! Complete bounded normalization-record checks before container changes.

use super::wire;
use super::wire::Error;
use super::wire::HayRecord;
use super::wire::Request;
use super::wire::Response;
use super::wire::field as f;
use super::wire::require;
use super::wire::scalar;
use super::wire::to_u64;
use super::wire::to_usize;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) enum NeedleCommand {
    Append(u32),
    Replace(usize),
}

pub(super) fn decode_hay(
    request: &Request<'_>,
    response: &Response,
    hay: &[HayRecord],
) -> Result<Vec<HayRecord>, Error> {
    let old = request.state;
    let next = response.state;
    require(to_u64(hay.len())? == old[f::HAY_LOWER], "stored hay length")?;
    let original_count = std::str::from_utf8(request.payload)
        .map_err(|_| "input UTF8")?
        .chars()
        .count();
    require(
        next[f::HAY_ORIGINAL]
            == old[f::HAY_ORIGINAL]
                .checked_add(to_u64(original_count)?)
                .ok_or("original hay count overflow")?,
        "original hay count",
    )?;
    require(
        next[f::HAY_LOWER].checked_sub(old[f::HAY_LOWER]) == Some(to_u64(response.record_count)?)
            && response.record_count.checked_mul(wire::RECORD_WORDS)
                == Some(response.records.len()),
        "hay output count",
    )?;
    let length = hay
        .len()
        .checked_add(response.record_count)
        .ok_or("host hay count")?;
    require(to_usize(next[f::HAY_LOWER])? == length, "host hay count")?;
    if let Some(last) = hay.last() {
        require(
            last.original.checked_add(/*rhs*/ 1) == Some(old[f::HAY_ORIGINAL]),
            "stored hay original frontier",
        )?;
    }
    let mut records: Vec<HayRecord> = Vec::with_capacity(response.record_count);
    for (offset, words) in response
        .records
        .chunks_exact(wire::RECORD_WORDS)
        .enumerate()
    {
        let position = old[f::HAY_LOWER]
            .checked_add(to_u64(offset)?)
            .ok_or("hay position overflow")?;
        let record = HayRecord {
            scalar: scalar(words[0])?,
            original: words[1],
            start: words[2],
        };
        require(
            record.original < next[f::HAY_ORIGINAL]
                && record.start <= position
                && position - record.start < wire::MAPPING_SLOTS,
            "hay record bounds",
        )?;
        if let Some(previous) = records.last() {
            if record.original == previous.original {
                require(record.start == previous.start, "expansion start")?;
            } else {
                require(
                    previous.original.checked_add(/*rhs*/ 1) == Some(record.original)
                        && record.start == position,
                    "original hay order",
                )?;
            }
        } else {
            require(
                record.original == old[f::HAY_ORIGINAL] && record.start == old[f::HAY_LOWER],
                "first hay record",
            )?;
        }
        records.push(record);
    }
    if let Some(last) = records.last() {
        require(
            last.original.checked_add(/*rhs*/ 1) == Some(next[f::HAY_ORIGINAL]),
            "last hay record",
        )?;
    } else {
        require(original_count == 0, "missing hay records")?;
    }
    Ok(records)
}

pub(super) fn decode_needle(
    request: &Request<'_>,
    response: &Response,
    needle: &[u32],
) -> Result<Vec<NeedleCommand>, Error> {
    let old = request.state;
    let next = response.state;
    require(
        to_u64(needle.len())? == old[f::NEEDLE_LOWER],
        "stored needle length",
    )?;
    if old[f::SIGMA_PENDING] != 0 {
        require(
            needle.get(to_usize(old[f::SIGMA_SLOT])?) == Some(&wire::NORMAL_SIGMA),
            "stored pending sigma",
        )?;
    }
    let original_count = std::str::from_utf8(request.payload)
        .map_err(|_| "input UTF8")?
        .chars()
        .count();
    require(
        next[f::NEEDLE_ORIGINAL]
            == old[f::NEEDLE_ORIGINAL]
                .checked_add(to_u64(original_count)?)
                .ok_or("original needle count overflow")?
            && response.record_count.checked_mul(wire::RECORD_WORDS)
                == Some(response.records.len()),
        "needle original count",
    )?;
    let mut commands = Vec::with_capacity(response.record_count);
    let mut appended = Vec::new();
    let mut last_replacement = None;
    let mut old_replaced = false;
    for words in response.records.chunks_exact(wire::RECORD_WORDS) {
        let index = words[1];
        let value = scalar(words[2])?;
        match words[0] {
            0 => {
                require(
                    index
                        == old[f::NEEDLE_LOWER]
                            .checked_add(to_u64(appended.len())?)
                            .ok_or("needle append overflow")?,
                    "needle append frontier",
                )?;
                appended.push(value);
                commands.push(NeedleCommand::Append(value));
            }
            1 => {
                require(value == wire::FINAL_SIGMA, "replacement scalar")?;
                if let Some(previous) = last_replacement {
                    require(index > previous, "replacement order")?;
                }
                let target = to_usize(index)?;
                if index < old[f::NEEDLE_LOWER] {
                    require(
                        old[f::SIGMA_PENDING] == 1
                            && index == old[f::SIGMA_SLOT]
                            && needle.get(target) == Some(&wire::NORMAL_SIGMA),
                        "old sigma replacement",
                    )?;
                    old_replaced = true;
                } else {
                    let local = to_usize(index - old[f::NEEDLE_LOWER])?;
                    let prior = appended.get_mut(local).ok_or("future sigma replacement")?;
                    require(*prior == wire::NORMAL_SIGMA, "appended sigma replacement")?;
                    *prior = wire::FINAL_SIGMA;
                }
                last_replacement = Some(index);
                commands.push(NeedleCommand::Replace(target));
            }
            _ => return Err("needle command"),
        }
    }
    require(
        next[f::NEEDLE_LOWER].checked_sub(old[f::NEEDLE_LOWER]) == Some(to_u64(appended.len())?)
            && appended.len() >= original_count
            && appended.len() <= original_count * wire::RECORD_WORDS,
        "needle lower count",
    )?;
    let length = needle
        .len()
        .checked_add(appended.len())
        .ok_or("host needle count")?;
    require(
        to_usize(next[f::NEEDLE_LOWER])? == length,
        "host needle count",
    )?;
    if next[f::SIGMA_PENDING] != 0 {
        let index = next[f::SIGMA_SLOT];
        if index < old[f::NEEDLE_LOWER] {
            require(
                old[f::SIGMA_PENDING] == 1
                    && index == old[f::SIGMA_SLOT]
                    && !old_replaced
                    && needle.get(to_usize(index)?) == Some(&wire::NORMAL_SIGMA),
                "retained pending sigma",
            )?;
        } else {
            require(
                appended.get(to_usize(index - old[f::NEEDLE_LOWER])?) == Some(&wire::NORMAL_SIGMA),
                "new pending sigma",
            )?;
        }
    }
    Ok(commands)
}

pub(super) fn apply_needle(commands: Vec<NeedleCommand>, needle: &mut Vec<u32>) {
    let additional = commands
        .iter()
        .filter(|command| matches!(command, NeedleCommand::Append(_)))
        .count();
    // Reserve before any old-slot patch. All indices and scalar commands were validated.
    needle.reserve(additional);
    for command in commands {
        match command {
            NeedleCommand::Append(scalar) => needle.push(scalar),
            NeedleCommand::Replace(index) => needle[index] = wire::FINAL_SIGMA,
        }
    }
}
