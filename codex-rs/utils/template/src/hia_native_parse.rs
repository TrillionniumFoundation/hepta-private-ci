//! Materialize the complete HIA template parse plan in the original Rust types.
//!
//! Delimiters, Unicode trim, error selection and literal coalescing belong to
//! HIA. This module validates the returned frame and copies its source ranges.
//! This parse bridge leaves public error formatting unchanged.

use super::Segment;
use super::Template;
use super::TemplateParseError;
use super::hia_native_placeholders::Builder;

const HEADER_BYTES: usize = 64;
const RECORD_BYTES: usize = 24;

#[derive(Clone, Copy)]
#[repr(u64)]
enum Operation {
    Query = 0,
    Emit = 1,
}

#[derive(Debug, PartialEq, Eq)]
struct Plan {
    count: usize,
    required: usize,
    error: u64,
    error_start: usize,
}

unsafe extern "C" {
    fn codex_hia_template_parse(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

fn invoke(source: &str, output: &mut [u8], operation: Operation) {
    let mut workspace = [0_u8; 32];
    workspace[..8].copy_from_slice(&1_u64.to_le_bytes());
    workspace[8..16].copy_from_slice(&(operation as u64).to_le_bytes());
    // SAFETY: the three disjoint buffers remain live for this synchronous call.
    // Their exact capacities are passed; HIA validates the frame, full UTF-8
    // source and final output extent before writing, and retains no pointers.
    let status = unsafe {
        codex_hia_template_parse(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(status, 0, "HIA template parse transport failed");
}

fn decode_word(bytes: &[u8]) -> u64 {
    let mut word = [0_u8; 8];
    word.copy_from_slice(bytes);
    u64::from_le_bytes(word)
}

fn index(value: u64) -> usize {
    let Ok(value) = usize::try_from(value) else {
        panic!("HIA template parse index does not fit usize");
    };
    value
}

fn read_plan(source: &str, output: &[u8], operation: Operation) -> Plan {
    assert!(output.len() >= HEADER_BYTES, "HIA template header is short");
    let mut words = [0_u64; 8];
    for (word, bytes) in words.iter_mut().zip(output[..HEADER_BYTES].chunks_exact(8)) {
        *word = decode_word(bytes);
    }
    assert_eq!(words[0], 1, "HIA template revision is invalid");
    assert_eq!(
        words[1], operation as u64,
        "HIA template operation is invalid"
    );
    assert_eq!(
        words[2],
        source.len() as u64,
        "HIA template source length differs"
    );
    let plan = Plan {
        count: index(words[3]),
        required: index(words[4]),
        error: words[6],
        error_start: index(words[7]),
    };
    assert!(
        plan.count <= source.len(),
        "HIA template record count is invalid"
    );
    assert_eq!(
        plan.count
            .checked_mul(RECORD_BYTES)
            .and_then(|bytes| bytes.checked_add(HEADER_BYTES)),
        Some(plan.required),
        "HIA template table size is invalid"
    );
    let written = match operation {
        Operation::Query => HEADER_BYTES,
        Operation::Emit => plan.required,
    };
    assert_eq!(
        words[5], written as u64,
        "HIA template write extent is invalid"
    );
    assert!(
        written <= output.len(),
        "HIA template output exceeds capacity"
    );
    assert!(plan.error <= 4, "HIA template semantic error is invalid");
    if plan.error == 0 {
        assert_eq!(
            plan.error_start, 0,
            "HIA template success has an error offset"
        );
        assert_eq!(
            plan.count == 0,
            source.is_empty(),
            "HIA template empty plan differs"
        );
    } else {
        assert_eq!(plan.count, 0, "HIA template error returned partial records");
        let Some(end) = plan.error_start.checked_add(2) else {
            panic!("HIA template error span overflowed");
        };
        assert!(
            end <= source.len()
                && source.is_char_boundary(plan.error_start)
                && source.is_char_boundary(end),
            "HIA template error offset is invalid"
        );
    }
    plan
}

pub(super) fn parse(source: &str) -> Result<Template, TemplateParseError> {
    let mut header = [0_u8; HEADER_BYTES];
    invoke(source, &mut header, Operation::Query);
    let plan = read_plan(source, &header, Operation::Query);
    let start = plan.error_start;
    let error = match plan.error {
        0 => None,
        1 => Some(TemplateParseError::EmptyPlaceholder { start }),
        2 => Some(TemplateParseError::NestedPlaceholder { start }),
        3 => Some(TemplateParseError::UnmatchedClosingDelimiter { start }),
        4 => Some(TemplateParseError::UnterminatedPlaceholder { start }),
        _ => panic!("HIA template semantic error is invalid"),
    };
    if let Some(error) = error {
        return Err(error);
    }
    let mut placeholders = Builder::new(source);
    let mut segments = Vec::new();
    if plan.count == 0 {
        return Ok(Template {
            placeholders: placeholders.finish(),
            segments,
        });
    }
    let mut table = vec![0_u8; plan.required];
    invoke(source, &mut table, Operation::Emit);
    assert_eq!(
        read_plan(source, &table, Operation::Emit),
        plan,
        "HIA template query and emit disagree"
    );
    let mut previous_end = 0;
    for record in table[HEADER_BYTES..].chunks_exact(RECORD_BYTES) {
        let kind = decode_word(&record[..8]);
        let start = index(decode_word(&record[8..16]));
        let end = index(decode_word(&record[16..]));
        assert!(
            start >= previous_end && end > start,
            "HIA template ranges overlap, regress or are empty"
        );
        let Some(value) = source.get(start..end) else {
            panic!("HIA template range is not a valid string slice");
        };
        match kind {
            1 => {
                assert!(
                    !matches!(segments.last(), Some(Segment::Literal(_))),
                    "HIA template new literal follows a literal"
                );
                segments.push(Segment::Literal(value.to_owned()));
            }
            2 => {
                let Some(Segment::Literal(previous)) = segments.last_mut() else {
                    panic!("HIA template append has no preceding literal");
                };
                previous.push_str(value);
            }
            3 => {
                let name = value.to_owned();
                placeholders.insert(start..end, &name);
                segments.push(Segment::Placeholder(name));
            }
            _ => panic!("HIA template record kind is invalid"),
        }
        previous_end = end;
    }
    Ok(Template {
        placeholders: placeholders.finish(),
        segments,
    })
}
