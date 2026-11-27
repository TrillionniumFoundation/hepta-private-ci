//! Match-response structure and fixed anchor links; no Host match search.

use super::overflow;
use super::wire;
use super::wire::Error;
use super::wire::HayRecord;
use super::wire::Request;
use super::wire::Response;
use super::wire::State;
use super::wire::field as f;
use super::wire::require;
use super::wire::to_u64;
use super::wire::to_usize;

#[derive(Debug, Eq, PartialEq)]
pub(super) struct Frame {
    pub(super) indices: Vec<usize>,
    pub(super) terminal: Option<(i32, overflow::Witness)>,
}

pub(super) fn decode(
    request: &Request<'_>,
    response: &Response,
    hay: &[HayRecord],
    needle: &[u32],
    indices: &[usize],
) -> Result<Frame, Error> {
    let old = request.state;
    let next = response.state;
    require(
        to_u64(hay.len())? == old[f::HAY_LOWER]
            && to_u64(needle.len())? == old[f::NEEDLE_LOWER]
            && to_u64(indices.len())? == old[f::UNIQUE],
        "stored match counts",
    )?;
    if old[f::NEEDLE_CURSOR] != 0 {
        require(
            indices.first().copied() == Some(to_usize(old[f::FIRST_ORIGINAL])?)
                && indices.last().copied() == Some(to_usize(old[f::LAST_ORIGINAL])?),
            "stored match endpoints",
        )?;
    }
    bind_anchors(next, hay, needle)?;
    let added = next[f::UNIQUE]
        .checked_sub(old[f::UNIQUE])
        .ok_or("unique index regression")?;
    require(added <= response.advance_b, "unique index advance")?;
    if added == 0 {
        require(
            next[f::LAST_ORIGINAL] == old[f::LAST_ORIGINAL]
                && next[f::LAST_START] == old[f::LAST_START],
            "unchanged unique endpoint",
        )?;
    }
    require(
        response.records.len() == response.record_count,
        "index record width",
    )?;
    if next[f::OUTCOME] == wire::NONE {
        require(response.record_count == 0, "none index records")?;
        return Ok(Frame {
            indices: Vec::new(),
            terminal: None,
        });
    }
    require(
        to_u64(response.record_count)? == added,
        "index record count",
    )?;
    let mut selected = Vec::with_capacity(response.record_count);
    let mut previous = if old[f::NEEDLE_CURSOR] == 0 {
        None
    } else {
        Some(old[f::LAST_ORIGINAL])
    };
    for &index in &response.records {
        require(index < old[f::HAY_ORIGINAL], "original index range")?;
        if let Some(prior) = previous {
            require(index > prior, "original index order")?;
        }
        selected.push(to_usize(index)?);
        previous = Some(index);
    }
    if let Some(last) = selected.last() {
        require(
            to_u64(*last)? == next[f::LAST_ORIGINAL],
            "last emitted index",
        )?;
        if old[f::NEEDLE_CURSOR] == 0 {
            require(
                selected.first().copied() == Some(to_usize(next[f::FIRST_ORIGINAL])?),
                "first emitted index",
            )?;
        }
    }
    let count = indices
        .len()
        .checked_add(selected.len())
        .ok_or("host index count")?;
    require(to_u64(count)? == next[f::UNIQUE], "accumulated index count")?;
    let terminal = if next[f::OUTCOME] == wire::SOME {
        Some(overflow::validate(next, needle.len())?)
    } else {
        None
    };
    Ok(Frame {
        indices: selected,
        terminal,
    })
}

fn bind_anchors(state: State, hay: &[HayRecord], needle: &[u32]) -> Result<(), Error> {
    if state[f::HAY_CURSOR] != 0 {
        let record = hay
            .get(to_usize(state[f::HAY_CURSOR] - 1)?)
            .ok_or("scanned anchor range")?;
        require(
            record.original == state[f::SCANNED_ORIGINAL]
                && record.start == state[f::SCANNED_START],
            "scanned anchor identity",
        )?;
    }
    if state[f::NEEDLE_CURSOR] == 0 {
        return Ok(());
    }
    let first = hay
        .get(to_usize(state[f::FIRST_HIT])?)
        .ok_or("first anchor range")?;
    let last = hay
        .get(to_usize(state[f::LAST_HIT])?)
        .ok_or("last anchor range")?;
    require(
        first.original == state[f::FIRST_ORIGINAL]
            && first.start == state[f::FIRST_START]
            && needle.first() == Some(&first.scalar),
        "first anchor identity",
    )?;
    require(
        last.original == state[f::LAST_ORIGINAL]
            && last.start == state[f::LAST_START]
            && needle.get(to_usize(state[f::NEEDLE_CURSOR] - 1)?) == Some(&last.scalar),
        "last anchor identity",
    )?;
    for (index, original) in [
        (state[f::FIRST_START], state[f::FIRST_ORIGINAL]),
        (state[f::LAST_START], state[f::LAST_ORIGINAL]),
    ] {
        let record = hay.get(to_usize(index)?).ok_or("original start range")?;
        require(
            record.start == index && record.original == original,
            "original start identity",
        )?;
    }
    Ok(())
}
