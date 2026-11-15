//! Owned storage for the HIA streaming patch state and explicit AST events.

use std::fmt;
use std::path::PathBuf;

use crate::hia_native_parser::Command;
use crate::hia_native_parser::NativeState;
use crate::hia_native_parser::Plan;
use crate::hia_native_parser::index;
use crate::hia_native_parser::span;
use crate::parser::Hunk;
use crate::parser::ParseError;
use crate::parser::UpdateFileChunk;

#[derive(Default, Clone)]
pub struct StreamingPatchParser {
    line_buffer: String,
    state: NativeState,
    hunks: Vec<Hunk>,
    environment_id: Option<String>,
}

impl StreamingPatchParser {
    pub fn environment_id(&self) -> Option<&str> {
        self.environment_id.as_deref()
    }

    pub fn push_delta(&mut self, delta: &str) -> Result<Vec<Hunk>, ParseError> {
        if self.line_buffer.is_empty() {
            // With no unfinished storage, the caller's delta can stay borrowed.
            let plan = Plan::request(Command::Push, delta, self.state, [0; 2]);
            apply_events(&plan, delta, &mut self.hunks, &mut self.environment_id);
            let error = plan.error(delta, &self.hunks);
            self.line_buffer
                .push_str(span(delta, plan.header[8], plan.header[9]));
            self.state = plan.next_state();
            self.validate_storage();
            return self.result(error);
        }
        // Append in place: a scalar-split long line never recopies its old prefix.
        self.line_buffer.push_str(delta);
        self.consume_buffer(Command::Push)
    }

    pub fn finish(&mut self) -> Result<Vec<Hunk>, ParseError> {
        self.consume_buffer(Command::Finish)
    }

    fn consume_buffer(&mut self, command: Command) -> Result<Vec<Hunk>, ParseError> {
        let plan = Plan::request(command, &self.line_buffer, self.state, [0; 2]);
        apply_events(
            &plan,
            &self.line_buffer,
            &mut self.hunks,
            &mut self.environment_id,
        );
        // Dynamic error text must be copied before the native-selected buffer cut.
        let error = plan.error(&self.line_buffer, &self.hunks);
        let keep_start = index(plan.header[8]);
        let keep_length = index(plan.header[9]);
        if keep_length == 0 {
            self.line_buffer.clear();
        } else {
            if keep_start != 0 {
                self.line_buffer.drain(..keep_start);
            }
            self.line_buffer.truncate(keep_length);
        }
        self.state = plan.next_state();
        self.validate_storage();
        self.result(error)
    }

    fn result(&self, error: Option<ParseError>) -> Result<Vec<Hunk>, ParseError> {
        match error {
            Some(error) => Err(error),
            None => Ok(self.hunks.clone()),
        }
    }

    fn validate_storage(&self) {
        assert_eq!(self.line_buffer.len(), index(self.state[2]));
        assert_eq!(self.hunks.len(), index(self.state[3]));
        assert_eq!(self.environment_id.is_some(), self.state[0] & 32 != 0);
        let (kind, moved, chunks, old, new, eof) = match self.hunks.last() {
            None => (0, false, 0, 0, 0, false),
            Some(Hunk::AddFile { .. }) => (1, false, 0, 0, 0, false),
            Some(Hunk::DeleteFile { .. }) => (2, false, 0, 0, 0, false),
            Some(Hunk::UpdateFile {
                move_path, chunks, ..
            }) => {
                let (old, new, eof) = chunks.last().map_or((0, 0, false), |chunk| {
                    (
                        chunk.old_lines.len(),
                        chunk.new_lines.len(),
                        chunk.is_end_of_file,
                    )
                });
                (3, move_path.is_some(), chunks.len(), old, new, eof)
            }
        };
        assert_eq!((self.state[0] >> 3) & 3, kind);
        assert_eq!(self.state[0] & 64 != 0, moved);
        assert_eq!(self.state[0] & 128 != 0, eof);
        assert_eq!(
            [
                index(self.state[5]),
                index(self.state[6]),
                index(self.state[7])
            ],
            [chunks, old, new]
        );
    }
}

fn chunks_mut(hunks: &mut [Hunk], hunk_index: usize) -> &mut Vec<UpdateFileChunk> {
    let Hunk::UpdateFile { chunks, .. } = hunks.get_mut(hunk_index).expect("HIA parser event hunk")
    else {
        panic!("HIA parser event selected a non-update hunk");
    };
    chunks
}

fn apply_events(
    plan: &Plan,
    source: &str,
    hunks: &mut Vec<Hunk>,
    environment: &mut Option<String>,
) {
    for record in &plan.records {
        let hunk_index = index(record[1]);
        let chunk_index = index(record[2]);
        let text = span(source, record[3], record[4]);
        match record[0] {
            1 => {
                assert!(environment.is_none(), "HIA parser environment target");
                *environment = Some(text.to_owned());
            }
            2..=4 => {
                assert_eq!(hunk_index, hunks.len(), "HIA parser appended hunk index");
                let path = PathBuf::from(text);
                let hunk = match record[0] {
                    2 => Hunk::AddFile {
                        path,
                        contents: String::new(),
                    },
                    3 => Hunk::DeleteFile { path },
                    4 => Hunk::UpdateFile {
                        path,
                        move_path: None,
                        chunks: Vec::new(),
                    },
                    _ => unreachable!(),
                };
                hunks.push(hunk);
            }
            5 => {
                let Hunk::AddFile { contents, .. } =
                    hunks.get_mut(hunk_index).expect("HIA parser add target")
                else {
                    panic!("HIA parser append selected a non-add hunk");
                };
                contents.push_str(text);
                contents.push('\n');
            }
            6 => {
                let Hunk::UpdateFile { move_path, .. } =
                    hunks.get_mut(hunk_index).expect("HIA parser move target")
                else {
                    panic!("HIA parser move selected a non-update hunk");
                };
                assert!(move_path.is_none(), "HIA parser move target is occupied");
                *move_path = Some(PathBuf::from(text));
            }
            7 | 8 => {
                let chunks = chunks_mut(hunks, hunk_index);
                assert_eq!(chunk_index, chunks.len(), "HIA parser appended chunk index");
                let change_context = match record[0] {
                    7 => None,
                    8 => Some(text.to_owned()),
                    _ => unreachable!(),
                };
                chunks.push(UpdateFileChunk {
                    change_context,
                    ..UpdateFileChunk::default()
                });
            }
            9..=11 => {
                let chunk = chunks_mut(hunks, hunk_index)
                    .get_mut(chunk_index)
                    .expect("HIA parser line target");
                match record[0] {
                    9 => {
                        assert_eq!(index(record[5]), chunk.old_lines.len());
                        chunk.old_lines.push(text.to_owned());
                    }
                    10 => {
                        assert_eq!(index(record[6]), chunk.new_lines.len());
                        chunk.new_lines.push(text.to_owned());
                    }
                    11 => {
                        let pair = (index(record[5]), index(record[6]));
                        assert_eq!(pair, (chunk.old_lines.len(), chunk.new_lines.len()));
                        chunk.context_line_indices.push(pair);
                        chunk.old_lines.push(text.to_owned());
                        chunk.new_lines.push(text.to_owned());
                    }
                    _ => unreachable!(),
                }
            }
            12 => {
                chunks_mut(hunks, hunk_index)
                    .get_mut(chunk_index)
                    .expect("HIA parser EOF target")
                    .is_end_of_file = true;
            }
            _ => panic!("HIA parser returned a non-streaming event"),
        }
    }
}

struct ModeDebug(NativeState);

impl fmt::Debug for ModeDebug {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.0[0] & 7 {
            0 => formatter.write_str("NotStarted"),
            1 => formatter.write_str("StartedPatch"),
            2 => formatter.write_str("AddFile"),
            3 => formatter.write_str("DeleteFile"),
            4 => formatter
                .debug_struct("UpdateFile")
                .field("hunk_line_number", &index(self.0[4]))
                .finish(),
            5 => formatter.write_str("EndedPatch"),
            _ => panic!("HIA parser invalid debug state"),
        }
    }
}

struct StateDebug<'a>(&'a StreamingPatchParser);

impl fmt::Debug for StateDebug<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("StreamingParserState")
            .field("mode", &ModeDebug(self.0.state))
            .field("hunks", &self.0.hunks)
            .field("environment_id", &self.0.environment_id)
            .finish()
    }
}

impl fmt::Debug for StreamingPatchParser {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("StreamingPatchParser")
            .field("line_buffer", &self.line_buffer)
            .field("state", &StateDebug(self))
            .field("line_number", &index(self.state[1]))
            .finish()
    }
}
