//! Test-only transport for the actual Rust implementation in this checkout.
//! Build with rustc directly; no Cargo dependencies or copied search algorithm.
use std::io::Read;
use std::io::Write;
use std::io::{self};

#[derive(Clone, Copy)]
pub enum ApplyPatchFileUpdateMode {
    NormalizeToLf,
    PreserveLineEndings,
}

// The included module also contains the production dispatcher. This oracle
// compiles without hia-native and calls only the unchanged Rust matcher below.
#[derive(Debug)]
pub enum ApplyPatchError {
    ComputeReplacements(String),
}

#[path = "../../codex-rs/apply-patch/src/seek_sequence.rs"]
mod reference;

const MAGIC: &[u8; 8] = b"HIASEEK1";
const INVALID: u64 = 0xffff_ffff;
const MAX_STREAM: u64 = 128 * 1024 * 1024;

fn take_u64(bytes: &[u8], at: &mut usize) -> Option<u64> {
    let end = at.checked_add(8)?;
    let value = u64::from_le_bytes(bytes.get(*at..end)?.try_into().ok()?);
    *at = end;
    Some(value)
}

fn evaluate(wire: &[u8]) -> Option<(u64, u64)> {
    let mut at = 0;
    let line_count = usize::try_from(take_u64(wire, &mut at)?).ok()?;
    let pattern_count = usize::try_from(take_u64(wire, &mut at)?).ok()?;
    let start = usize::try_from(take_u64(wire, &mut at)?).ok()?;
    let flags = take_u64(wire, &mut at)?;
    if flags > 3 {
        return None;
    }
    let count = line_count.checked_add(pattern_count)?;
    let table_bytes = count.checked_add(1)?.checked_mul(8)?;
    let payload = wire.get(at.checked_add(table_bytes)?..)?;
    let mut previous = usize::try_from(take_u64(wire, &mut at)?).ok()?;
    if previous != 0 {
        return None;
    }
    let mut strings = Vec::with_capacity(count);
    for _ in 0..count {
        let next = usize::try_from(take_u64(wire, &mut at)?).ok()?;
        strings.push(
            std::str::from_utf8(payload.get(previous..next)?)
                .ok()?
                .to_owned(),
        );
        previous = next;
    }
    if previous != payload.len() {
        return None;
    }
    let mode = if flags & 2 == 0 {
        ApplyPatchFileUpdateMode::NormalizeToLf
    } else {
        ApplyPatchFileUpdateMode::PreserveLineEndings
    };
    let result = reference::seek_sequence(
        &strings[..line_count],
        &strings[line_count..],
        start,
        flags & 1 != 0,
        mode,
    );
    Some(match result {
        Some(index) => (1, index as u64),
        None => (0, 0),
    })
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = Vec::new();
    io::stdin().take(MAX_STREAM + 1).read_to_end(&mut input)?;
    if input.len() as u64 > MAX_STREAM || input.get(..8) != Some(MAGIC) {
        return Err("invalid oracle stream header or size".into());
    }
    let mut at = 8;
    let count = take_u64(&input, &mut at).ok_or("missing case count")?;
    let mut output = Vec::new();
    output.extend_from_slice(MAGIC);
    output.extend_from_slice(&count.to_le_bytes());
    for _ in 0..count {
        let size = usize::try_from(take_u64(&input, &mut at).ok_or("missing frame size")?)?;
        let end = at.checked_add(size).ok_or("frame size overflow")?;
        let wire = input.get(at..end).ok_or("truncated frame")?;
        at = end;
        let (code, found, index) = match evaluate(wire) {
            Some((found, index)) => (16, found, index),
            None => (INVALID, 0, 0),
        };
        // Echo exact input bytes so an offline result cannot be paired with
        // a different seed/corpus just because its case count is the same.
        output.extend_from_slice(&(size as u64).to_le_bytes());
        output.extend_from_slice(wire);
        for value in [code, found, index] {
            output.extend_from_slice(&value.to_le_bytes());
        }
    }
    if at != input.len() {
        return Err("unexpected trailing stream bytes".into());
    }
    io::stdout().lock().write_all(&output)?;
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("seek_sequence oracle: {error}");
        std::process::exit(1);
    }
}
