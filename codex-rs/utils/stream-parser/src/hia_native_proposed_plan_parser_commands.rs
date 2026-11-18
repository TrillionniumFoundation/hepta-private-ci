//! Validate a complete command stream before applying its mechanical effects.

use super::super::PlanTag;
use super::wire::COMMAND_BYTES;
use super::wire::FINAL;
use super::wire::FIRST;
use super::wire::Operation;
use super::wire::Request;
use super::wire::Response;
use super::wire::WireError;
use super::wire::read_words;
use crate::tagged_line_parser::TaggedLineSegment;
use std::borrow::Cow;
use std::ops::Range;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum TextKind {
    Normal,
    Delta,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum Command {
    Append(Range<usize>),
    Flush {
        kind: TextKind,
        continue_text: bool,
    },
    Drop,
    Input {
        kind: TextKind,
        range: Range<usize>,
        continue_text: bool,
    },
    Start,
    End,
}

fn text_word(kind: Option<TextKind>) -> u64 {
    match kind {
        None => 0,
        Some(TextKind::Normal) => 1,
        Some(TextKind::Delta) => 2,
    }
}

fn continuation(
    kind: TextKind,
    value: u64,
    last: &mut Option<TextKind>,
) -> Result<bool, WireError> {
    if value > 1 || (value == 1 && *last != Some(kind)) {
        return Err(WireError::Command);
    }
    *last = Some(kind);
    Ok(value == 1)
}

pub(super) fn decode(
    request: &Request<'_>,
    response: &Response<'_>,
    pending_len: usize,
    segments: &[TaggedLineSegment<PlanTag>],
) -> Result<Vec<Command>, WireError> {
    request.validate(pending_len)?;
    let mut last = match segments.last() {
        Some(TaggedLineSegment::Normal(_)) => Some(TextKind::Normal),
        Some(TaggedLineSegment::TagDelta(PlanTag::ProposedPlan, _)) => Some(TextKind::Delta),
        Some(TaggedLineSegment::TagStart(_) | TaggedLineSegment::TagEnd(_)) | None => None,
    };
    if request.operation != Operation::Push || request.flags & FIRST != 0 {
        if !segments.is_empty() {
            return Err(WireError::Command);
        }
    } else if text_word(last) != request.state.last_text_kind {
        return Err(WireError::Command);
    }
    if !response.records.len().is_multiple_of(COMMAND_BYTES) {
        return Err(WireError::Command);
    }
    let mut commands = Vec::with_capacity(response.records.len() / COMMAND_BYTES);
    let mut cursor = 0;
    let mut pending = pending_len;
    for record in response.records.chunks_exact(COMMAND_BYTES) {
        let [kind, offset, length, continue_text] = read_words::<4>(record)?;
        let command = match kind {
            0 | 4 | 5 => {
                if request.operation != Operation::Push || length == 0 {
                    return Err(WireError::Command);
                }
                let start = usize::try_from(offset).map_err(|_| WireError::Command)?;
                let length = usize::try_from(length).map_err(|_| WireError::Command)?;
                let end = start.checked_add(length).ok_or(WireError::Command)?;
                if start != cursor || request.payload.get(start..end).is_none() {
                    return Err(WireError::Command);
                }
                cursor = end;
                if kind == 0 {
                    if continue_text != 0 {
                        return Err(WireError::Command);
                    }
                    pending = pending.checked_add(length).ok_or(WireError::Command)?;
                    Command::Append(start..end)
                } else {
                    let kind = if kind == 4 {
                        TextKind::Normal
                    } else {
                        TextKind::Delta
                    };
                    Command::Input {
                        kind,
                        range: start..end,
                        continue_text: continuation(kind, continue_text, &mut last)?,
                    }
                }
            }
            1..=3 => {
                if offset != 0
                    || length == 0
                    || u64::try_from(pending).map_err(|_| WireError::Command)? != length
                {
                    return Err(WireError::Command);
                }
                pending = 0;
                if kind == 3 {
                    if continue_text != 0 {
                        return Err(WireError::Command);
                    }
                    Command::Drop
                } else {
                    let kind = if kind == 1 {
                        TextKind::Normal
                    } else {
                        TextKind::Delta
                    };
                    Command::Flush {
                        kind,
                        continue_text: continuation(kind, continue_text, &mut last)?,
                    }
                }
            }
            6 | 7 => {
                if offset != 0 || length != 0 || continue_text != 0 {
                    return Err(WireError::Command);
                }
                last = None;
                if kind == 6 {
                    Command::Start
                } else {
                    Command::End
                }
            }
            _ => return Err(WireError::Command),
        };
        commands.push(command);
    }
    if cursor != request.payload.len()
        || u64::try_from(pending).map_err(|_| WireError::Command)? != response.state.pending_bytes
    {
        return Err(WireError::Command);
    }
    if request.operation == Operation::Push
        && request.flags & FINAL == 0
        && text_word(last) != response.state.last_text_kind
    {
        return Err(WireError::Command);
    }
    Ok(commands)
}

fn append_text(
    segments: &mut Vec<TaggedLineSegment<PlanTag>>,
    kind: TextKind,
    continue_text: bool,
    text: Cow<'_, str>,
) {
    if continue_text {
        match (kind, segments.last_mut()) {
            (TextKind::Normal, Some(TaggedLineSegment::Normal(existing)))
            | (
                TextKind::Delta,
                Some(TaggedLineSegment::TagDelta(PlanTag::ProposedPlan, existing)),
            ) => existing.push_str(&text),
            _ => panic!("HIA proposed plan parser: invalid validated continuation"),
        }
    } else {
        segments.push(match kind {
            TextKind::Normal => TaggedLineSegment::Normal(text.into_owned()),
            TextKind::Delta => {
                TaggedLineSegment::TagDelta(PlanTag::ProposedPlan, text.into_owned())
            }
        });
    }
}

pub(super) fn apply(
    commands: Vec<Command>,
    payload: &str,
    pending: &mut String,
    segments: &mut Vec<TaggedLineSegment<PlanTag>>,
) {
    for command in commands {
        match command {
            Command::Append(range) => pending.push_str(&payload[range]),
            Command::Flush {
                kind,
                continue_text,
            } => append_text(
                segments,
                kind,
                continue_text,
                Cow::Owned(std::mem::take(pending)),
            ),
            Command::Drop => pending.clear(),
            Command::Input {
                kind,
                range,
                continue_text,
            } => append_text(
                segments,
                kind,
                continue_text,
                Cow::Borrowed(&payload[range]),
            ),
            Command::Start => segments.push(TaggedLineSegment::TagStart(PlanTag::ProposedPlan)),
            Command::End => segments.push(TaggedLineSegment::TagEnd(PlanTag::ProposedPlan)),
        }
    }
}
