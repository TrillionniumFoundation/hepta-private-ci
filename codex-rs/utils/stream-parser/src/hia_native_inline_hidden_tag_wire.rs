//! Constant-size decision transport over borrowed pending/delimiter strings.

use super::super::InlineTagSpec;

const WORDS: usize = 12;
const BYTES: usize = WORDS * 8;
type Frame = [u64; WORDS];

#[derive(Clone, Copy)]
#[repr(u64)]
enum Operation {
    Begin,
    Fold,
    Resolve,
    Close,
    Finish,
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum Decision {
    Visible {
        take: usize,
    },
    Open {
        take: usize,
        consume: usize,
        spec_index: usize,
    },
    Body {
        take: usize,
    },
    Close {
        take: usize,
        consume: usize,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum FinishChannel {
    Visible,
    Tag,
}

unsafe extern "C" {
    fn codex_hia_inline_hidden_tag(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        delimiter: *const u8,
        delimiter_len: u64,
    ) -> u64;
}

fn request(operation: Operation) -> Frame {
    let mut frame = [0; WORDS];
    frame[0] = 1;
    frame[1] = operation as u64;
    frame
}

fn invoke(source: &str, delimiter: &str, frame: Frame) -> Frame {
    let mut output = [0_u8; BYTES];
    for (bytes, word) in output.chunks_exact_mut(8).zip(frame) {
        bytes.copy_from_slice(&word.to_le_bytes());
    }
    // SAFETY: the strings and initialized output remain live and disjoint for
    // the call. HIA reads both strings, writes only these BYTES of output, and
    // retains no pointer. The third ABI buffer is never written.
    let returned = unsafe {
        codex_hia_inline_hidden_tag(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            BYTES as u64,
            delimiter.as_ptr(),
            delimiter.len() as u64,
        )
    };
    assert_eq!(returned, BYTES as u64, "HIA inline tag decision failed");
    let mut result = [0; WORDS];
    for (word, bytes) in result.iter_mut().zip(output.chunks_exact(8)) {
        let mut encoded = [0; 8];
        encoded.copy_from_slice(bytes);
        *word = u64::from_le_bytes(encoded);
    }
    assert_eq!((result[0], result[1], result[11]), (1, frame[1], 0));
    result
}

fn state(frame: &Frame, source: &str, count: usize) -> Result<(), &'static str> {
    if frame[2] != count as u64 || frame[6] > source.len() as u64 {
        return Err("fold counter or suffix extent differs");
    }
    let keep = frame[6] as usize;
    if !source.is_char_boundary(source.len() - keep) {
        return Err("suffix splits a scalar");
    }
    if frame[3] == u64::MAX {
        if frame[4] != 0 || frame[5] != 0 || (count == 0 && keep != 0) {
            return Err("absent opener carries a selection");
        }
    } else {
        let position = usize::try_from(frame[3]).map_err(|_| "position exceeds usize")?;
        let length = usize::try_from(frame[4]).map_err(|_| "length exceeds usize")?;
        let end = position
            .checked_add(length)
            .ok_or("opener extent overflows")?;
        if length == 0
            || end > source.len()
            || frame[5] >= count as u64
            || !source.is_char_boundary(position)
            || !source.is_char_boundary(end)
        {
            return Err("opener extent or index differs");
        }
    }
    Ok(())
}

pub(super) fn open<T>(source: &str, specs: &[InlineTagSpec<T>]) -> Decision {
    let mut frame = invoke(source, "", request(Operation::Begin));
    assert_eq!(frame, [1, 0, 0, u64::MAX, 0, 0, 0, 0, 0, 0, 0, 0]);
    for (index, spec) in specs.iter().enumerate() {
        frame[1] = Operation::Fold as u64;
        frame = invoke(source, spec.open, frame);
        if let Err(reason) = state(&frame, source, index + 1) {
            panic!("invalid HIA inline opener fold: {reason}");
        }
        assert_eq!(&frame[7..], &[0; 5]);
    }
    frame[1] = Operation::Resolve as u64;
    frame = invoke(source, "", frame);
    match decode_open(frame, source, specs) {
        Ok(decision) => decision,
        Err(reason) => panic!("invalid HIA inline opener decision: {reason}"),
    }
}

fn decode_open<T>(
    frame: Frame,
    source: &str,
    specs: &[InlineTagSpec<T>],
) -> Result<Decision, &'static str> {
    if (frame[0], frame[1], frame[11]) != (1, Operation::Resolve as u64, 0) {
        return Err("opener response header differs");
    }
    state(&frame, source, specs.len())?;
    let take = usize::try_from(frame[8]).map_err(|_| "take exceeds usize")?;
    let consume = usize::try_from(frame[9]).map_err(|_| "consume exceeds usize")?;
    if take > consume
        || consume > source.len()
        || !source.is_char_boundary(take)
        || !source.is_char_boundary(consume)
    {
        return Err("opener command splits or exceeds source");
    }
    match frame[7] {
        1 if frame[3] == u64::MAX
            && take == consume
            && take == source.len() - frame[6] as usize
            && frame[10] == 0 =>
        {
            Ok(Decision::Visible { take })
        }
        2 if frame[3] == frame[8] && frame[5] == frame[10] => {
            let spec_index = usize::try_from(frame[10]).map_err(|_| "spec index exceeds usize")?;
            let spec = specs.get(spec_index).ok_or("spec index exceeds list")?;
            if frame[4] != spec.open.len() as u64
                || consume - take != spec.open.len()
                || consume == 0
            {
                return Err("opener command length differs");
            }
            Ok(Decision::Open {
                take,
                consume,
                spec_index,
            })
        }
        _ => Err("unknown or inconsistent opener command"),
    }
}

pub(super) fn close(source: &str, delimiter: &str) -> Decision {
    let frame = invoke(source, delimiter, request(Operation::Close));
    match decode_close(frame, source, delimiter) {
        Ok(decision) => decision,
        Err(reason) => panic!("invalid HIA inline close decision: {reason}"),
    }
}

fn decode_close(frame: Frame, source: &str, delimiter: &str) -> Result<Decision, &'static str> {
    if (frame[0], frame[1], frame[11]) != (1, Operation::Close as u64, 0)
        || frame[2..6] != [0; 4]
        || frame[10] != 0
        || frame[6] > source.len() as u64
    {
        return Err("close response state differs");
    }
    let take = usize::try_from(frame[8]).map_err(|_| "take exceeds usize")?;
    let consume = usize::try_from(frame[9]).map_err(|_| "consume exceeds usize")?;
    if take > consume
        || consume > source.len()
        || !source.is_char_boundary(take)
        || !source.is_char_boundary(consume)
    {
        return Err("close command splits or exceeds source");
    }
    match frame[7] {
        3 if take == consume && take == source.len() - frame[6] as usize => {
            Ok(Decision::Body { take })
        }
        4 if frame[6] == 0 && consume - take == delimiter.len() && consume > 0 => {
            Ok(Decision::Close { take, consume })
        }
        _ => Err("unknown or inconsistent close command"),
    }
}

pub(super) fn finish(source: &str, channel: FinishChannel) -> FinishChannel {
    let mut frame = request(Operation::Finish);
    frame[2] = match channel {
        FinishChannel::Visible => 0,
        FinishChannel::Tag => 1,
    };
    let result = invoke(source, "", frame);
    let action = result[7];
    frame[7] = match channel {
        FinishChannel::Visible => 5,
        FinishChannel::Tag => 6,
    };
    frame[8] = source.len() as u64;
    frame[9] = source.len() as u64;
    assert_eq!(result, frame, "invalid HIA inline EOF decision");
    match action {
        5 => FinishChannel::Visible,
        6 => FinishChannel::Tag,
        _ => unreachable!("the complete EOF frame was checked"),
    }
}

#[cfg(test)]
#[path = "hia_native_inline_hidden_tag_wire_tests.rs"]
mod tests;
