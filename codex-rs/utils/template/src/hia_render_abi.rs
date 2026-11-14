//! Framing for HIA's render policy and its shared native byte-range index.
//!
//! Source contains five little-endian words: command, two command operands,
//! and two zero reserved words. The eight-word workspace contains variable,
//! placeholder and segment counts/positions, phase, and two reserved words.
//! Successful replies contain four words. Errors modify neither mutable buffer;
//! their name index is the already submitted index or the pending phase index.

use super::hia_native_index::Insert;

pub(super) enum Control {
    Variable(Insert),
    Finish {
        placeholders: usize,
        segments: usize,
    },
    Placeholder(Option<usize>),
    Extra(Option<usize>),
    Literal,
    Value(Option<usize>),
}

pub(super) enum Following {
    Segment { index: usize },
    Done,
}

impl Following {
    pub(super) fn action(self) -> Action {
        match self {
            Self::Segment { index } => Action::Segment { index },
            Self::Done => Action::Done,
        }
    }
}

pub(super) enum Action {
    Accepted {
        index: usize,
    },
    Placeholder {
        index: usize,
    },
    Unused,
    Segment {
        index: usize,
    },
    AppendLiteral {
        segment: usize,
        following: Following,
    },
    AppendValue {
        segment: usize,
        variable: usize,
        following: Following,
    },
    Done,
}

pub(super) enum ErrorKind {
    Duplicate,
    Missing,
    Extra,
    MissingSegment,
}

pub(super) struct NativeError {
    pub(super) kind: ErrorKind,
    pub(super) index: usize,
}

pub(super) struct Machine {
    workspace: [u8; 64],
    output: [u8; 32],
}

unsafe extern "C" {
    fn codex_hia_template_render(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

impl Machine {
    pub(super) fn new() -> Self {
        Self {
            workspace: [0; 64],
            output: [0; 32],
        }
    }

    pub(super) fn control(&mut self, control: Control) -> Result<Action, NativeError> {
        let [command, a, b] = match control {
            Control::Variable(Insert::New { id }) => [0, 0, id as u64],
            Control::Variable(Insert::Existing { id }) => [0, 1, id as u64],
            Control::Finish {
                placeholders,
                segments,
            } => [1, placeholders as u64, segments as u64],
            Control::Placeholder(result) => found(/*command*/ 2, result),
            Control::Extra(result) => found(/*command*/ 3, result),
            Control::Literal => [4, 0, 0],
            Control::Value(result) => found(/*command*/ 5, result),
        };
        let mut source = [0_u8; 40];
        for (index, value) in [command, a, b, 0, 0].into_iter().enumerate() {
            source[index * 8..index * 8 + 8].copy_from_slice(&value.to_le_bytes());
        }
        // SAFETY: the three disjoint buffers live throughout this synchronous
        // call. The HIA program checks frame sizes and phase before access,
        // commits only successful results, and retains no Rust pointers.
        let status = unsafe {
            codex_hia_template_render(
                source.as_ptr(),
                source.len() as u64,
                self.output.as_mut_ptr(),
                self.output.len() as u64,
                self.workspace.as_mut_ptr(),
                self.workspace.len() as u64,
            )
        };
        let error = match (status, command) {
            (32, _) => None,
            (0xffff_fffc, 0) => Some((ErrorKind::Duplicate, size(b))),
            (0xffff_fffb, 2) => Some((
                ErrorKind::Missing,
                size(word(&self.workspace, /*offset*/ 16)),
            )),
            (0xffff_fffa, 3) => Some((ErrorKind::Extra, size(b))),
            (0xffff_fff9, 5) => Some((
                ErrorKind::MissingSegment,
                size(word(&self.workspace, /*offset*/ 32)),
            )),
            _ => panic!("invalid HIA template renderer status: {status}"),
        };
        if let Some((kind, index)) = error {
            return Err(NativeError { kind, index });
        }
        let [event, a, b, c] = std::array::from_fn(|index| word(&self.output, 8 * index));
        let action = match event {
            0 | 1 | 3 => {
                assert_eq!((b, c), (0, 0), "invalid HIA render index result");
                let index = size(a);
                match event {
                    0 => Action::Accepted { index },
                    1 => Action::Placeholder { index },
                    3 => Action::Segment { index },
                    _ => unreachable!("the enclosing match fixes the event"),
                }
            }
            2 | 6 => {
                assert_eq!((a, b, c), (0, 0, 0), "invalid HIA render state result");
                if event == 2 {
                    Action::Unused
                } else {
                    Action::Done
                }
            }
            4 => {
                assert_eq!(c, 0, "invalid HIA literal result");
                Action::AppendLiteral {
                    segment: size(a),
                    following: next(a, b),
                }
            }
            5 => Action::AppendValue {
                segment: size(a),
                variable: size(b),
                following: next(a, c),
            },
            7 => {
                assert_eq!((b, c), (0, 0), "invalid HIA final literal result");
                Action::AppendLiteral {
                    segment: size(a),
                    following: Following::Done,
                }
            }
            8 => {
                assert_eq!(c, 0, "invalid HIA final value result");
                Action::AppendValue {
                    segment: size(a),
                    variable: size(b),
                    following: Following::Done,
                }
            }
            _ => panic!("invalid HIA renderer event: {event}"),
        };
        Ok(action)
    }
}

fn found(command: u64, result: Option<usize>) -> [u64; 3] {
    match result {
        Some(id) => [command, 1, id as u64],
        None => [command, 0, 0],
    }
}

fn next(current: u64, next: u64) -> Following {
    assert_eq!(
        current.checked_add(1),
        Some(next),
        "invalid HIA segment progress"
    );
    Following::Segment { index: size(next) }
}

fn size(value: u64) -> usize {
    usize::try_from(value).unwrap_or_else(|_| panic!("invalid HIA render index: {value}"))
}

fn word(bytes: &[u8], offset: usize) -> u64 {
    let Some(encoded) = bytes.get(offset..offset + 8) else {
        panic!("invalid HIA render word offset");
    };
    let Ok(encoded) = encoded.try_into() else {
        unreachable!("render words contain eight bytes");
    };
    u64::from_le_bytes(encoded)
}
