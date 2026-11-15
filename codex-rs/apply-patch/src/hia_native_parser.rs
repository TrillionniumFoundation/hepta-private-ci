//! Checked transport and storage projection for the HIA patch grammar.

use std::path::Path;

use crate::ApplyPatchArgs;
use crate::parser::Hunk;
use crate::parser::ParseError;
use crate::streaming_parser::StreamingPatchParser;

pub(crate) const HEADER_BYTES: usize = 160;
const RECORD_BYTES: usize = 64;
pub(crate) type NativeState = [u64; 8];

unsafe extern "C" {
    fn codex_hia_parser(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

#[derive(Clone, Copy)]
pub(crate) enum Command {
    Push,
    Finish,
    NormalizeStrict,
    NormalizeLenient,
    AffectedPath,
    SourcePath,
}

impl Command {
    fn code(self) -> u64 {
        match self {
            Self::Push => 4,
            Self::Finish => 6,
            Self::NormalizeStrict => 12,
            Self::NormalizeLenient => 14,
            Self::AffectedPath => 16,
            Self::SourcePath => 17,
        }
    }

    fn result_kind(self) -> u64 {
        match self {
            Self::Push | Self::Finish => 0,
            Self::NormalizeStrict | Self::NormalizeLenient => 1,
            Self::AffectedPath | Self::SourcePath => 2,
        }
    }
}

pub(crate) struct Plan {
    pub(crate) header: [u64; 20],
    pub(crate) records: Vec<[u64; 8]>,
}

fn put_word(buffer: &mut [u8], offset: usize, value: u64) {
    buffer[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}

fn words<const N: usize>(buffer: &[u8]) -> [u64; N] {
    assert_eq!(buffer.len(), N * 8, "HIA parser word extent");
    std::array::from_fn(|index| {
        u64::from_le_bytes(buffer[index * 8..index * 8 + 8].try_into().unwrap())
    })
}

pub(crate) fn index(value: u64) -> usize {
    usize::try_from(value).expect("HIA parser integer fits the host")
}

pub(crate) fn span(source: &str, start: u64, length: u64) -> &str {
    let begin = index(start);
    let end = begin.checked_add(index(length)).expect("HIA parser span");
    source.get(begin..end).expect("HIA parser UTF-8 span")
}

fn invoke(source: &str, output: &mut [u8], workspace: &mut [u8; 128]) {
    // These disjoint borrowed allocations remain live for this synchronous call.
    // Trusted operations receive valid Rust strings and native-origin state.
    let status = unsafe {
        codex_hia_parser(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(status, 0, "HIA parser rejected its native transport");
}

impl Plan {
    pub(crate) fn request(
        command: Command,
        source: &str,
        state: NativeState,
        arguments: [u64; 2],
    ) -> Self {
        let mut workspace = [0_u8; 128];
        put_word(&mut workspace, 0, 1);
        put_word(&mut workspace, 8, command.code());
        put_word(&mut workspace, 16, arguments[0]);
        put_word(&mut workspace, 24, arguments[1]);
        for (position, value) in state.into_iter().enumerate() {
            put_word(&mut workspace, 32 + position * 8, value);
        }
        let mut query = [0_u8; HEADER_BYTES];
        invoke(source, &mut query, &mut workspace);
        let header = words::<20>(&query);
        assert_eq!(header[19], 1, "HIA parser result version");
        assert_eq!(header[17], command.result_kind(), "HIA parser result kind");
        assert!(header[2] <= 9, "HIA parser semantic error");
        let count = index(header[1]);
        let required = count
            .checked_mul(RECORD_BYTES)
            .and_then(|bytes| bytes.checked_add(HEADER_BYTES))
            .expect("HIA parser result extent");
        assert_eq!(index(header[0]), required, "HIA parser required size");
        let records = if count == 0 {
            Vec::new()
        } else {
            let mut output = vec![0_u8; required];
            put_word(&mut workspace, 8, command.code() + 1);
            invoke(source, &mut output, &mut workspace);
            assert_eq!(&output[..HEADER_BYTES], query, "HIA parser query/emit plan");
            output[HEADER_BYTES..]
                .chunks_exact(RECORD_BYTES)
                .map(words::<8>)
                .collect()
        };
        for record in &records {
            assert_eq!(record[7], 0, "HIA parser reserved event operand");
            assert!((1..=14).contains(&record[0]), "HIA parser event kind");
            if record[0] == 14 {
                assert_eq!(&record[1..], &[0, 0, 0, 1, 0, 0, 0]);
            } else {
                span(source, record[3], record[4]);
            }
        }
        if header[4] == 1 {
            span(source, header[5], header[6]);
        } else {
            assert!(header[4] <= 2, "HIA parser error argument kind");
        }
        if command.result_kind() == 0 {
            assert!(index(header[7]) <= source.len(), "HIA parser progress");
            span(source, header[8], header[9]);
        }
        Self { header, records }
    }

    pub(crate) fn next_state(&self) -> NativeState {
        let h = &self.header;
        [h[10], h[11], h[9], h[12], h[13], h[14], h[15], h[16]]
    }

    pub(crate) fn error(&self, source: &str, hunks: &[Hunk]) -> Option<ParseError> {
        let h = &self.header;
        let line_number = index(h[3]);
        let text = || {
            assert_eq!(h[4], 1, "HIA parser source error argument");
            span(source, h[5], h[6])
        };
        let message = match h[2] {
            0 => return None,
            1 => {
                return Some(ParseError::InvalidPatchError(
                    "The first line of the patch must be '*** Begin Patch'".to_string(),
                ));
            }
            2 => {
                return Some(ParseError::InvalidPatchError(
                    "The last line of the patch must be '*** End Patch'".to_string(),
                ));
            }
            3 => {
                return Some(ParseError::InvalidPatchError(
                    "apply_patch environment_id cannot be specified more than once".to_string(),
                ));
            }
            4 => {
                return Some(ParseError::InvalidPatchError(
                    "apply_patch environment_id cannot be empty".to_string(),
                ));
            }
            5 => {
                let argument = text();
                format!(
                    "'{argument}' is not a valid hunk header. Valid hunk headers: '*** Add File: {{path}}', '*** Delete File: {{path}}', '*** Update File: {{path}}'"
                )
            }
            6 => {
                assert_eq!(h[4], 2, "HIA parser path error argument");
                let Hunk::UpdateFile { path, .. } =
                    hunks.get(index(h[5])).expect("HIA parser error hunk")
                else {
                    panic!("HIA parser selected a non-update error hunk");
                };
                format!("Update file hunk for path '{}' is empty", path.display())
            }
            7 => "Update hunk does not contain any lines".to_string(),
            8 => {
                let argument = text();
                format!(
                    "Unexpected line found in update hunk: '{argument}'. Every line should start with ' ' (context line), '+' (added line), or '-' (removed line)"
                )
            }
            9 => {
                let argument = text();
                format!("Expected update hunk to start with a @@ context marker, got: '{argument}'")
            }
            _ => panic!("HIA parser unknown semantic error"),
        };
        Some(ParseError::InvalidHunkError {
            message,
            line_number,
        })
    }
}

pub(crate) enum Normalization {
    Strict,
    Lenient,
}

pub(crate) fn parse_patch_text(
    source: &str,
    normalization: Normalization,
) -> Result<ApplyPatchArgs, ParseError> {
    let command = match normalization {
        Normalization::Strict => Command::NormalizeStrict,
        Normalization::Lenient => Command::NormalizeLenient,
    };
    let plan = Plan::request(command, source, [0; 8], [0; 2]);
    if let Some(error) = plan.error(source, &[]) {
        return Err(error);
    }
    let mut patch = String::with_capacity(index(plan.header[18]));
    for record in &plan.records {
        match record[0] {
            13 => patch.push_str(span(source, record[3], record[4])),
            14 => patch.push('\n'),
            _ => panic!("HIA parser returned a non-normalization record"),
        }
    }
    assert_eq!(patch.len(), index(plan.header[18]), "HIA normalized length");
    let mut parser = StreamingPatchParser::default();
    parser.push_delta(&patch)?;
    let hunks = parser.finish()?;
    let environment_id = parser.environment_id().map(str::to_owned);
    Ok(ApplyPatchArgs {
        patch,
        hunks,
        workdir: None,
        environment_id,
    })
}

pub(crate) enum PathRole {
    Affected,
    Source,
}

pub(crate) fn select_hunk_path(hunk: &Hunk, role: PathRole) -> &Path {
    let (kind, source, moved) = match hunk {
        Hunk::AddFile { path, .. } => (1, path, None),
        Hunk::DeleteFile { path } => (2, path, None),
        Hunk::UpdateFile {
            path, move_path, ..
        } => (3, path, move_path.as_ref()),
    };
    let command = match role {
        PathRole::Affected => Command::AffectedPath,
        PathRole::Source => Command::SourcePath,
    };
    let plan = Plan::request(command, "", [0; 8], [kind, u64::from(moved.is_some())]);
    assert_eq!(plan.header[2], 0, "HIA path selection semantic status");
    match plan.header[18] {
        0 => source.as_path(),
        1 => moved
            .expect("HIA parser selected an absent move path")
            .as_path(),
        _ => panic!("HIA parser unknown path selection"),
    }
}
