//! Serialize owned template values and materialize the HIA render result.
//!
//! HIA owns duplicate/missing/extra selection and complete output construction.
//! The generic variable loop retains the original callback and drop scopes.

use super::Segment;
use super::Template;
use super::TemplateRenderError;
use std::ops::Range;

const INPUT_HEADER_BYTES: usize = 64;
const OUTPUT_HEADER_BYTES: usize = 80;

#[derive(Clone, Copy)]
#[repr(u64)]
enum Operation {
    CheckCandidate = 0,
    Query = 1,
    Emit = 2,
}

#[derive(Clone, Copy)]
#[repr(u64)]
enum FrameKind {
    Keys = 0,
    Template = 1,
}

#[derive(Debug, PartialEq, Eq)]
enum ErrorKind {
    Duplicate,
    Missing,
    Extra,
}

#[derive(Debug, PartialEq, Eq)]
enum Origin {
    Variable,
    Placeholder,
    Segment,
}

#[derive(Debug, PartialEq, Eq)]
struct Failure {
    kind: ErrorKind,
    origin: Origin,
    index: usize,
    name: Range<usize>,
}

#[derive(Debug, PartialEq, Eq)]
struct Plan {
    required: usize,
    failure: Option<Failure>,
}

struct VariableLog {
    keys: Vec<u8>,
    values: Vec<(String, String)>,
}

struct Frame {
    bytes: Vec<u8>,
    variables: Vec<Range<usize>>,
    placeholders: Vec<Range<usize>>,
    segments: Vec<Option<Range<usize>>>,
}

unsafe extern "C" {
    fn codex_hia_template_render(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

fn word(value: usize) -> u64 {
    let Ok(value) = u64::try_from(value) else {
        panic!("HIA template render length does not fit u64");
    };
    value
}

fn index(value: u64) -> usize {
    let Ok(value) = usize::try_from(value) else {
        panic!("HIA template render length does not fit usize");
    };
    value
}

fn append(bytes: &mut Vec<u8>, value: &[u8]) -> Range<usize> {
    let start = bytes.len();
    let Some(end) = start.checked_add(value.len()) else {
        panic!("HIA template render input extent overflowed");
    };
    if let Err(error) = bytes.try_reserve(value.len()) {
        panic!("HIA template render allocation failed: {error}");
    }
    bytes.extend_from_slice(value);
    start..end
}

fn seal(bytes: &mut [u8], kind: FrameKind, counts: [usize; 3]) {
    let words = [
        1,
        kind as u64,
        word(bytes.len()),
        word(counts[0]),
        word(counts[1]),
        word(counts[2]),
        0,
        0,
    ];
    for (target, value) in bytes[..INPUT_HEADER_BYTES]
        .chunks_exact_mut(/*chunk_size*/ 8)
        .zip(words)
    {
        target.copy_from_slice(&value.to_le_bytes());
    }
}

fn invoke(source: &[u8], output: &mut [u8], operation: Operation) -> Plan {
    let mut workspace = [0_u8; 32];
    workspace[..8].copy_from_slice(&1_u64.to_le_bytes());
    workspace[8..16].copy_from_slice(&(operation as u64).to_le_bytes());
    // SAFETY: all three buffers are live and disjoint for this synchronous
    // invocation. Their exact extents are passed, and HIA retains no pointers.
    let status = unsafe {
        codex_hia_template_render(
            source.as_ptr(),
            word(source.len()),
            output.as_mut_ptr(),
            word(output.len()),
            workspace.as_mut_ptr(),
            word(workspace.len()),
        )
    };
    assert_eq!(status, 0, "HIA template render transport failed");
    assert!(
        output.len() >= OUTPUT_HEADER_BYTES,
        "HIA template render header is short"
    );
    let mut words = [0_u64; 10];
    for (target, bytes) in words
        .iter_mut()
        .zip(output[..OUTPUT_HEADER_BYTES].chunks_exact(/*chunk_size*/ 8))
    {
        let mut value = [0_u8; 8];
        value.copy_from_slice(bytes);
        *target = u64::from_le_bytes(value);
    }
    assert_eq!(words[0], 1, "HIA template render revision differs");
    assert_eq!(
        words[1], operation as u64,
        "HIA template render operation differs"
    );
    assert_eq!(
        words[2],
        word(source.len()),
        "HIA template render source extent differs"
    );
    let required = index(words[3]);
    assert!(
        required >= OUTPUT_HEADER_BYTES,
        "HIA template render response extent is invalid"
    );
    let failure = if words[5] == 0 {
        assert_eq!(
            words[6..],
            [0; 4],
            "HIA template render success has error details"
        );
        None
    } else {
        assert_eq!(
            required, OUTPUT_HEADER_BYTES,
            "HIA template render error has a payload"
        );
        let kind = match words[5] {
            1 => ErrorKind::Duplicate,
            2 => ErrorKind::Missing,
            3 => ErrorKind::Extra,
            _ => panic!("HIA template render error kind is invalid"),
        };
        let origin = match words[6] {
            1 => Origin::Variable,
            2 => Origin::Placeholder,
            3 => Origin::Segment,
            _ => panic!("HIA template render error origin is invalid"),
        };
        let start = index(words[8]);
        let Some(end) = start.checked_add(index(words[9])) else {
            panic!("HIA template render name extent overflowed");
        };
        assert!(
            source.get(start..end).is_some(),
            "HIA template render name escapes its input"
        );
        Some(Failure {
            kind,
            origin,
            index: index(words[7]),
            name: start..end,
        })
    };
    let written = match operation {
        Operation::CheckCandidate => {
            assert_eq!(
                required, OUTPUT_HEADER_BYTES,
                "HIA template key check has a payload"
            );
            OUTPUT_HEADER_BYTES
        }
        Operation::Query => OUTPUT_HEADER_BYTES,
        Operation::Emit => required,
    };
    assert_eq!(
        words[4],
        word(written),
        "HIA template render written extent differs"
    );
    assert!(
        written <= output.len(),
        "HIA template render output exceeds capacity"
    );
    Plan { required, failure }
}

impl VariableLog {
    fn new() -> Self {
        Self {
            keys: vec![0; INPUT_HEADER_BYTES],
            values: Vec::new(),
        }
    }

    fn insert(&mut self, name: String, value: String) -> Option<()> {
        let Some(count) = self.values.len().checked_add(/*rhs*/ 1) else {
            panic!("HIA template variable count overflowed");
        };
        append(&mut self.keys, &word(name.len()).to_le_bytes());
        let range = append(&mut self.keys, name.as_bytes());
        seal(&mut self.keys, FrameKind::Keys, [count, 0, 0]);
        let mut header = [0_u8; OUTPUT_HEADER_BYTES];
        let plan = invoke(&self.keys, &mut header, Operation::CheckCandidate);
        if let Some(failure) = plan.failure {
            assert_eq!(
                failure,
                Failure {
                    kind: ErrorKind::Duplicate,
                    origin: Origin::Variable,
                    index: self.values.len(),
                    name: range,
                },
                "HIA template duplicate does not identify the current candidate"
            );
            return Some(());
        }
        self.values.push((name, value));
        None
    }
}

fn build_variable_map<I, K, V>(variables: I) -> Result<VariableLog, TemplateRenderError>
where
    I: IntoIterator<Item = (K, V)>,
    K: AsRef<str>,
    V: AsRef<str>,
{
    let mut map = VariableLog::new();
    for (name, value) in variables {
        let name = name.as_ref().to_string();
        if map
            .insert(name.clone(), value.as_ref().to_string())
            .is_some()
        {
            return Err(TemplateRenderError::DuplicateValue { name });
        }
    }
    Ok(map)
}

impl Frame {
    fn serialize(template: &Template, variables: &[(String, String)]) -> Self {
        let mut frame = Self {
            bytes: vec![0; INPUT_HEADER_BYTES],
            variables: Vec::new(),
            placeholders: Vec::new(),
            segments: Vec::new(),
        };
        for (name, value) in variables {
            append(&mut frame.bytes, &word(name.len()).to_le_bytes());
            append(&mut frame.bytes, &word(value.len()).to_le_bytes());
            let range = append(&mut frame.bytes, name.as_bytes());
            append(&mut frame.bytes, value.as_bytes());
            frame.variables.push(range);
        }
        let placeholders = template.placeholders();
        let placeholder_count = placeholders.len();
        for name in placeholders {
            append(&mut frame.bytes, &word(name.len()).to_le_bytes());
            let range = append(&mut frame.bytes, name.as_bytes());
            frame.placeholders.push(range);
        }
        for segment in &template.segments {
            let (kind, text) = match segment {
                Segment::Literal(text) => (1_u64, text),
                Segment::Placeholder(text) => (3_u64, text),
            };
            append(&mut frame.bytes, &kind.to_le_bytes());
            append(&mut frame.bytes, &word(text.len()).to_le_bytes());
            let range = append(&mut frame.bytes, text.as_bytes());
            frame.segments.push(match segment {
                Segment::Literal(_) => None,
                Segment::Placeholder(_) => Some(range),
            });
        }
        seal(
            &mut frame.bytes,
            FrameKind::Template,
            [variables.len(), placeholder_count, template.segments.len()],
        );
        frame
    }

    fn error_name(&self, failure: &Failure) -> String {
        let expected = match failure.origin {
            Origin::Variable => self.variables.get(failure.index),
            Origin::Placeholder => self.placeholders.get(failure.index),
            Origin::Segment => self.segments.get(failure.index).and_then(Option::as_ref),
        };
        assert_eq!(
            expected,
            Some(&failure.name),
            "HIA template error does not identify a name field"
        );
        let Some(bytes) = self.bytes.get(failure.name.clone()) else {
            panic!("HIA template error name escaped its source");
        };
        let Ok(name) = std::str::from_utf8(bytes) else {
            panic!("HIA template error name is not UTF-8");
        };
        name.to_owned()
    }
}

pub(super) fn render<I, K, V>(
    template: &Template,
    variables: I,
) -> Result<String, TemplateRenderError>
where
    I: IntoIterator<Item = (K, V)>,
    K: AsRef<str>,
    V: AsRef<str>,
{
    let variables = build_variable_map(variables)?;
    let frame = Frame::serialize(template, &variables.values);
    let mut header = [0_u8; OUTPUT_HEADER_BYTES];
    let plan = invoke(&frame.bytes, &mut header, Operation::Query);
    if let Some(failure) = &plan.failure {
        return Err(match failure.kind {
            ErrorKind::Duplicate => panic!("HIA template accepted a duplicate during iteration"),
            ErrorKind::Missing => {
                assert!(
                    matches!(failure.origin, Origin::Placeholder | Origin::Segment),
                    "HIA template missing error has the wrong origin"
                );
                TemplateRenderError::MissingValue {
                    name: frame.error_name(failure),
                }
            }
            ErrorKind::Extra => {
                assert_eq!(
                    failure.origin,
                    Origin::Variable,
                    "HIA template extra error has the wrong origin"
                );
                TemplateRenderError::ExtraValue {
                    name: frame.error_name(failure),
                }
            }
        });
    }
    let mut output = Vec::new();
    if let Err(error) = output.try_reserve_exact(plan.required) {
        panic!("HIA template render output allocation failed: {error}");
    }
    output.resize(plan.required, /*value*/ 0);
    assert_eq!(
        invoke(&frame.bytes, &mut output, Operation::Emit),
        plan,
        "HIA template render query and emit disagree"
    );
    drop(output.drain(..OUTPUT_HEADER_BYTES));
    let Ok(rendered) = String::from_utf8(output) else {
        panic!("HIA template rendered output is not UTF-8");
    };
    Ok(rendered)
}
