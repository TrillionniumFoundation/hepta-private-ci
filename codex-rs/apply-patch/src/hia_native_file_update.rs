//! Owned storage and framing for the HIA file-update components.
//!
//! HIA chooses every search, cursor transition, retry, context span, ordering
//! and LF output row. This adapter executes native callback requests and copies
//! native-selected values. Preserve mode composes the existing HIA SourceFile.
//! The unchanged host caller retains filesystem policy and unified-diff output.

use crate::ApplyPatchError;
use crate::ApplyPatchFileUpdateMode;
use crate::UpdateFileChunk;
use crate::hia_native;
use crate::text_file::Replacement;
use crate::text_file::SourceFile;

type Result<T> = std::result::Result<T, ApplyPatchError>;

#[derive(Clone, Copy, PartialEq)]
#[repr(u64)]
enum Operation {
    Lines = 0,
    Step = 2,
    Sort = 4,
    Render = 6,
}

#[derive(Default)]
struct Continuation {
    chunk: usize,
    cursor: usize,
    phase: u64,
    answer: Option<usize>,
}

unsafe extern "C" {
    fn codex_hia_file_update(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

fn rejected(reason: &str) -> ApplyPatchError {
    ApplyPatchError::ComputeReplacements(format!("HIA file_update: {reason}"))
}

fn number(value: u64) -> Result<usize> {
    usize::try_from(value).map_err(|_| rejected("native size does not fit usize"))
}

fn word(bytes: &[u8], offset: usize) -> Result<u64> {
    let end = offset
        .checked_add(8)
        .ok_or_else(|| rejected("native word offset overflow"))?;
    let encoded = bytes
        .get(offset..end)
        .ok_or_else(|| rejected("native word is outside the result"))?;
    let encoded =
        <[u8; 8]>::try_from(encoded).map_err(|_| rejected("native word length is invalid"))?;
    Ok(u64::from_le_bytes(encoded))
}

fn push(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_le_bytes());
}

fn frame(header: &[u64], tail_words: usize) -> Result<Vec<u8>> {
    let size = header
        .len()
        .checked_add(tail_words)
        .and_then(|count| count.checked_mul(8))
        .ok_or_else(|| rejected("request length overflow"))?;
    let mut bytes = Vec::new();
    bytes
        .try_reserve_exact(size)
        .map_err(|_| rejected("cannot allocate request"))?;
    for value in header {
        push(&mut bytes, *value);
    }
    Ok(bytes)
}

fn invoke(source: &[u8], output: &mut [u8], request: &mut [u8]) -> Result<()> {
    // SAFETY: all buffers are disjoint, remain live for this synchronous call,
    // and have the advertised lengths. HIA retains no pointers. The workspace
    // parameter carries an immutable descriptor despite its ABI mutbuf type.
    let status = unsafe {
        codex_hia_file_update(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            request.as_mut_ptr(),
            request.len() as u64,
        )
    };
    if status != 0 {
        return Err(rejected(&format!("native ABI rejected request ({status})")));
    }
    Ok(())
}

fn plan(source: &[u8], operation: Operation, mut request: Vec<u8>) -> Result<Vec<u8>> {
    let header_size = if operation == Operation::Step { 96 } else { 32 };
    let mut header = vec![0_u8; header_size];
    invoke(source, &mut header, &mut request)?;
    let needed = number(word(&header, /*offset*/ 0)?)?;
    if needed < header_size || !needed.is_multiple_of(8) {
        return Err(rejected("native plan length is invalid"));
    }
    if needed == header_size {
        return Ok(header);
    }
    let mut output = Vec::new();
    output
        .try_reserve_exact(needed)
        .map_err(|_| rejected("cannot allocate native plan"))?;
    output.resize(needed, 0);
    request[..8].copy_from_slice(&(operation as u64 + 1).to_le_bytes());
    invoke(source, &mut output, &mut request)?;
    if word(&output, /*offset*/ 0)? != needed as u64
        || (operation != Operation::Render && output[..header_size] != header)
    {
        return Err(rejected("native plan changed after query"));
    }
    Ok(output)
}

fn lf_lines(contents: &str) -> Result<Vec<String>> {
    let request = frame(&[Operation::Lines as u64], /*tail_words*/ 0)?;
    let output = plan(contents.as_bytes(), Operation::Lines, request)?;
    let count = number(word(&output, /*offset*/ 8)?)?;
    let expected = count
        .checked_mul(16)
        .and_then(|size| size.checked_add(32))
        .ok_or_else(|| rejected("native line count overflow"))?;
    if expected != output.len() || word(&output, /*offset*/ 16)? != contents.len() as u64 {
        return Err(rejected("native line framing differs"));
    }
    let mut lines = Vec::with_capacity(count);
    for row in output[32..].chunks_exact(16) {
        let start = number(word(row, /*offset*/ 0)?)?;
        let end = start
            .checked_add(number(word(row, /*offset*/ 8)?)?)
            .ok_or_else(|| rejected("native line span overflow"))?;
        let text = contents
            .get(start..end)
            .ok_or_else(|| rejected("native line is outside UTF-8 boundaries"))?;
        lines.push(text.to_owned());
    }
    if word(&output, /*offset*/ 24)? != lines.last().map_or(0, String::len) as u64 {
        return Err(rejected("native last-line length differs"));
    }
    Ok(lines)
}

fn mode_word(mode: ApplyPatchFileUpdateMode) -> u64 {
    match mode {
        ApplyPatchFileUpdateMode::NormalizeToLf => 0,
        ApplyPatchFileUpdateMode::PreserveLineEndings => 1,
    }
}

fn step_frame(
    lines: &[String],
    chunks: &[UpdateFileChunk],
    mode: ApplyPatchFileUpdateMode,
    state: &Continuation,
) -> Result<Vec<u8>> {
    let chunk = chunks.get(state.chunk);
    let old_count = chunk.map_or(0, |value| value.old_lines.len());
    let new_count = chunk.map_or(0, |value| value.new_lines.len());
    let pair_count = chunk.map_or(0, |value| value.context_line_indices.len());
    let tail_words = pair_count
        .checked_mul(2)
        .and_then(|count| count.checked_add(old_count))
        .and_then(|count| count.checked_add(new_count))
        .ok_or_else(|| rejected("chunk frame length overflow"))?;
    let mut request = frame(
        &[
            Operation::Step as u64,
            mode_word(mode),
            lines.len() as u64,
            lines.last().map_or(0, String::len) as u64,
            chunks.len() as u64,
            state.chunk as u64,
            state.cursor as u64,
            state.phase,
            u64::from(state.answer.is_some()),
            state.answer.map_or(0, |index| index as u64),
            u64::from(chunk.is_some_and(|value| value.change_context.is_some())),
            u64::from(chunk.is_some_and(|value| value.is_end_of_file)),
            old_count as u64,
            new_count as u64,
            pair_count as u64,
            0,
        ],
        tail_words,
    )?;
    if let Some(chunk) = chunk {
        for text in chunk.old_lines.iter().chain(&chunk.new_lines) {
            push(&mut request, text.len() as u64);
        }
        for (old, new) in &chunk.context_line_indices {
            push(&mut request, *old as u64);
            push(&mut request, *new as u64);
        }
    }
    Ok(request)
}

fn replacements(
    lines: &[String],
    path: &str,
    chunks: &[UpdateFileChunk],
    mode: ApplyPatchFileUpdateMode,
) -> Result<Vec<Replacement>> {
    let mut state = Continuation::default();
    let mut replacements = Vec::new();
    loop {
        let request = step_frame(lines, chunks, mode, &state)?;
        let output = plan(&[], Operation::Step, request)?;
        let action = word(&output, /*offset*/ 8)?;
        let next = number(word(&output, /*offset*/ 16)?)?;
        let cursor = number(word(&output, /*offset*/ 24)?)?;
        let phase = word(&output, /*offset*/ 32)?;
        let pattern_count = number(word(&output, /*offset*/ 40)?)?;
        let eof = word(&output, /*offset*/ 48)?;
        let count = number(word(&output, /*offset*/ 56)?)?;
        let error = word(&output, /*offset*/ 72)?;
        let expected = count
            .checked_mul(32)
            .and_then(|size| size.checked_add(96))
            .ok_or_else(|| rejected("native replacement count overflow"))?;
        if expected != output.len()
            || word(&output, /*offset*/ 64)? != mode_word(mode)
            || word(&output, /*offset*/ 80)? != 0
            || word(&output, /*offset*/ 88)? != 0
            || cursor > lines.len()
            || next > chunks.len()
            || (action != 3 && count != 0)
        {
            return Err(rejected("native continuation framing is invalid"));
        }
        match action {
            0 => {
                if next != chunks.len() || phase != 0 || error != 0 {
                    return Err(rejected("native completion is invalid"));
                }
                return sort_replacements(replacements);
            }
            1 | 2 => {
                if next != state.chunk || error != 0 || eof > 1 {
                    return Err(rejected("native search request is invalid"));
                }
                let chunk = chunks
                    .get(next)
                    .ok_or_else(|| rejected("native search chunk is missing"))?;
                let pattern = if action == 1 {
                    if phase != 1 || pattern_count != 1 || eof != 0 {
                        return Err(rejected("native context request is invalid"));
                    }
                    std::slice::from_ref(
                        chunk
                            .change_context
                            .as_ref()
                            .ok_or_else(|| rejected("native context is missing"))?,
                    )
                } else {
                    if !(2..=3).contains(&phase) {
                        return Err(rejected("native pattern phase is invalid"));
                    }
                    chunk
                        .old_lines
                        .get(..pattern_count)
                        .ok_or_else(|| rejected("native pattern range is invalid"))?
                };
                let answer =
                    hia_native::seek_sequence_checked(lines, pattern, cursor, eof == 1, mode)?;
                state = Continuation {
                    chunk: next,
                    cursor,
                    phase,
                    answer,
                };
            }
            3 => {
                if state.chunk.checked_add(1) != Some(next)
                    || phase != 0
                    || pattern_count != 0
                    || eof != 0
                    || error != 0
                {
                    return Err(rejected("native chunk completion is invalid"));
                }
                let chunk = chunks
                    .get(state.chunk)
                    .ok_or_else(|| rejected("native replacement chunk is missing"))?;
                for row in output[96..].chunks_exact(32) {
                    let start = number(word(row, /*offset*/ 0)?)?;
                    let old = number(word(row, /*offset*/ 8)?)?;
                    if !start.checked_add(old).is_some_and(|end| end <= lines.len()) {
                        return Err(rejected("native replacement is outside the source"));
                    }
                    let first = number(word(row, /*offset*/ 16)?)?;
                    let end = first
                        .checked_add(number(word(row, /*offset*/ 24)?)?)
                        .ok_or_else(|| rejected("native replacement range overflow"))?;
                    let segment = chunk
                        .new_lines
                        .get(first..end)
                        .ok_or_else(|| rejected("native replacement slice is invalid"))?;
                    replacements.push((start, old, segment.to_vec()));
                }
                state = Continuation {
                    chunk: next,
                    cursor,
                    phase,
                    answer: None,
                };
            }
            4 => {
                if next != state.chunk {
                    return Err(rejected("native error chunk differs"));
                }
                let chunk = chunks
                    .get(next)
                    .ok_or_else(|| rejected("native error chunk is missing"))?;
                return match error {
                    1 => {
                        let context = chunk
                            .change_context
                            .as_ref()
                            .ok_or_else(|| rejected("native error context is missing"))?;
                        Err(ApplyPatchError::ComputeReplacements(format!(
                            "Failed to find context '{context}' in {path}"
                        )))
                    }
                    2 => Err(ApplyPatchError::ComputeReplacements(format!(
                        "Failed to find expected lines in {path}:\n{}",
                        chunk.old_lines.join("\n"),
                    ))),
                    3 => panic!("HIA file_update: reached invalid context-line ordering"),
                    _ => Err(rejected("native semantic error is invalid")),
                };
            }
            _ => return Err(rejected("native action is invalid")),
        }
    }
}

fn sort_replacements(replacements: Vec<Replacement>) -> Result<Vec<Replacement>> {
    let count = replacements.len();
    let mut request = frame(&[Operation::Sort as u64, count as u64, 0, 0], count)?;
    for (start, _, _) in &replacements {
        push(&mut request, *start as u64);
    }
    let output = plan(&[], Operation::Sort, request)?;
    if word(&output, /*offset*/ 8)? != count as u64
        || output[32..].len() / 8 != count
        || word(&output, /*offset*/ 16)? != 0
        || word(&output, /*offset*/ 24)? != 0
    {
        return Err(rejected("native permutation length differs"));
    }
    let mut pending: Vec<_> = replacements.into_iter().map(Some).collect();
    let mut sorted = Vec::with_capacity(count);
    for row in output[32..].chunks_exact(8) {
        let index = number(word(row, /*offset*/ 0)?)?;
        let replacement = pending
            .get_mut(index)
            .and_then(Option::take)
            .ok_or_else(|| rejected("native permutation is invalid"))?;
        sorted.push(replacement);
    }
    Ok(sorted)
}

fn render_lf(lines: &[String], replacements: &[Replacement]) -> Result<String> {
    let initial_pool_count = lines
        .len()
        .checked_add(2)
        .ok_or_else(|| rejected("render pool count overflow"))?;
    let pool_count = replacements
        .iter()
        .try_fold(initial_pool_count, |count, (_, _, segment)| {
            count.checked_add(segment.len())
        })
        .ok_or_else(|| rejected("render pool count overflow"))?;
    let mut pools = Vec::with_capacity(pool_count);
    pools.extend(["\n", ""]);
    pools.extend(lines.iter().map(String::as_str));
    for (_, _, segment) in replacements {
        pools.extend(segment.iter().map(String::as_str));
    }
    let tail_words = replacements
        .len()
        .checked_mul(4)
        .and_then(|count| count.checked_add(lines.len()))
        .and_then(|count| count.checked_add(pool_count))
        .ok_or_else(|| rejected("render frame length overflow"))?;
    let mut request = frame(
        &[
            Operation::Render as u64,
            lines.len() as u64,
            replacements.len() as u64,
            pool_count as u64,
            0,
            0,
            0,
            0,
        ],
        tail_words,
    )?;
    for text in &pools {
        push(&mut request, text.len() as u64);
    }
    for index in 0..lines.len() {
        push(&mut request, index as u64 + 2);
    }
    let mut first = lines.len() + 2;
    for (start, old, segment) in replacements {
        for value in [*start, *old, first, segment.len()] {
            push(&mut request, value as u64);
        }
        first = first
            .checked_add(segment.len())
            .ok_or_else(|| rejected("render pool index overflow"))?;
    }
    let output = plan(&[], Operation::Render, request)?;
    let rows = number(word(&output, /*offset*/ 8)?)?;
    let total = number(word(&output, /*offset*/ 24)?)?;
    let logical = number(word(&output, /*offset*/ 16)?)?;
    if logical
        .checked_mul(2)
        .and_then(|count| count.checked_sub(1))
        != Some(rows)
    {
        return Err(rejected("native render logical count is invalid"));
    }
    let end = rows
        .checked_mul(8)
        .and_then(|size| size.checked_add(32))
        .ok_or_else(|| rejected("native render span count overflow"))?;
    let records = output
        .get(32..end)
        .ok_or_else(|| rejected("native render span count is invalid"))?;
    let mut contents = String::new();
    contents
        .try_reserve_exact(total)
        .map_err(|_| rejected("cannot allocate rendered contents"))?;
    for row in records.chunks_exact(8) {
        let text = pools
            .get(number(word(row, /*offset*/ 0)?)?)
            .ok_or_else(|| rejected("native render pool ID is invalid"))?;
        if !contents
            .len()
            .checked_add(text.len())
            .is_some_and(|length| length <= total)
        {
            return Err(rejected("native render byte total is invalid"));
        }
        contents.push_str(text);
    }
    if contents.len() != total {
        return Err(rejected("native render byte total differs"));
    }
    Ok(contents)
}

pub(super) fn new_contents(
    original_contents: &str,
    path: &str,
    chunks: &[UpdateFileChunk],
    mode: ApplyPatchFileUpdateMode,
) -> Result<String> {
    match mode {
        ApplyPatchFileUpdateMode::NormalizeToLf => {
            let lines = lf_lines(original_contents)?;
            let replacements = replacements(&lines, path, chunks, mode)?;
            render_lf(&lines, &replacements)
        }
        ApplyPatchFileUpdateMode::PreserveLineEndings => {
            let mut source_file = SourceFile::parse(original_contents);
            let lines = source_file.line_texts();
            let replacements = replacements(&lines, path, chunks, mode)?;
            source_file.apply_replacements(&replacements);
            Ok(source_file.into_contents())
        }
    }
}
