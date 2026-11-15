//! Borrowed-window framing for the native template parser.
//!
//! HIA owns delimiter recognition, UTF-8 decoding, Unicode whitespace trimming,
//! and parse-error precedence. Each successful call commits one span or parser
//! progress, returning 24 bytes: three little-endian u64 words (event, begin,
//! end). Workspace words hold total length, position, opening anchor, and the
//! trimmed name's begin/end; bytes 40/41 hold phase and the EOF-window flag.
//! Errors write neither buffer. Literal/placeholder spans borrow the original
//! input, so neither input size nor placeholder length is capped by the window.

use super::Segment;
use super::Template;
use super::TemplateParseError;
use super::hia_native_placeholders::Builder;
use super::push_literal;

unsafe extern "C" {
    fn codex_hia_template_parser(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(super) fn parse(source: &str) -> Result<Template, TemplateParseError> {
    let mut workspace = [0_u8; 48];
    workspace[..8].copy_from_slice(&(source.len() as u64).to_le_bytes());
    let mut output = [0_u8; 24];
    let mut position = 0;
    let mut placeholders = Builder::new(source);
    let mut segments = Vec::new();
    loop {
        let remaining = &source.as_bytes()[position..];
        let frame = &remaining[..remaining.len().min(4096)];
        workspace[41] = u8::from(frame.len() == remaining.len());
        let anchor = word(&workspace[16..24]);
        // SAFETY: distinct borrowed buffers remain live for this synchronous
        // call; HIA retains no pointers. The complete source is valid UTF-8,
        // though a window may end within a scalar or delimiter. HIA commits
        // only complete scalar prefixes and validates before writing.
        let status = unsafe {
            codex_hia_template_parser(
                frame.as_ptr(),
                frame.len() as u64,
                output.as_mut_ptr(),
                output.len() as u64,
                workspace.as_mut_ptr(),
                workspace.len() as u64,
            )
        };
        match status {
            24 => {}
            0xffff_fffc => return Err(TemplateParseError::EmptyPlaceholder { start: anchor }),
            0xffff_fffb => return Err(TemplateParseError::NestedPlaceholder { start: anchor }),
            0xffff_fffa => {
                return Err(TemplateParseError::UnmatchedClosingDelimiter { start: position });
            }
            0xffff_fff9 => {
                return Err(TemplateParseError::UnterminatedPlaceholder { start: anchor });
            }
            _ => panic!("invalid HIA template parser status: {status}"),
        }
        let next = word(&workspace[8..16]);
        let event = word(&output[..8]);
        let begin = word(&output[8..16]);
        let end = word(&output[16..24]);
        assert!(
            (position..=position + frame.len()).contains(&next)
                && source.is_char_boundary(next)
                && (next > position || event == 3),
            "invalid HIA template parser progress"
        );
        match event {
            0 => assert!(
                begin == 0 && end == 0 && workspace[40] == 1,
                "invalid HIA template parser state"
            ),
            1 | 2 => {
                assert!(begin < end && end <= next && workspace[40] == 0);
                let Some(span) = source.get(begin..end) else {
                    panic!("invalid HIA template parser span");
                };
                if event == 1 {
                    assert_eq!(begin, position);
                    push_literal(&mut segments, span);
                } else {
                    assert!(begin >= anchor + 2);
                    let name = span.to_owned();
                    placeholders.insert(begin..end, &name);
                    segments.push(Segment::Placeholder(name));
                }
            }
            3 => {
                assert!(next == source.len() && workspace[40] == 2 && begin == 0 && end == 0);
                return Ok(Template {
                    placeholders: placeholders.finish(),
                    segments,
                });
            }
            _ => panic!("invalid HIA template parser event: {event}"),
        }
        position = next;
    }
}

fn word(bytes: &[u8]) -> usize {
    let Ok(encoded) = bytes.try_into() else {
        unreachable!("template parser words contain eight bytes");
    };
    let Ok(value) = usize::try_from(u64::from_le_bytes(encoded)) else {
        panic!("invalid HIA template parser word");
    };
    value
}
