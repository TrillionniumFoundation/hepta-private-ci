//! Checked host effects for the HIA command-rule dispatcher.
//!
//! Native code schedules every lookup, callback, match retention and path
//! comparison. Rust keeps the original containers, platform path service and
//! owned objects. No native error is converted into an unmatched command.

use crate::Decision;
use crate::MatchOptions;
use crate::Policy;
use crate::RuleMatch;
use crate::RuleRef;
use crate::executable_name::executable_path_lookup_key;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::path::Component;
use std::path::Path;

const MAGIC: u64 = 0x4849_4144;
const STATE_BYTES: usize = 160;
const RESPONSE_BYTES: usize = 200;

type HeuristicsFallback<'a> = Option<&'a dyn Fn(&[String]) -> Decision>;

unsafe extern "C" {
    fn codex_hia_command_dispatch(
        source: *const u8,
        source_length: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_length: u64,
    ) -> u64;
}

struct Frame {
    stack: [u8; 512],
    heap: Vec<u8>,
    length: usize,
}

impl Frame {
    fn append(&mut self, bytes: &[u8]) {
        let end = self
            .length
            .checked_add(bytes.len())
            .unwrap_or_else(|| panic!("HIA command-dispatch frame length overflow"));
        if end <= self.stack.len() {
            self.stack[self.length..end].copy_from_slice(bytes);
        } else {
            if self.heap.is_empty() {
                self.heap.try_reserve_exact(end).unwrap_or_else(|error| {
                    panic!("HIA command-dispatch frame allocation failed: {error}")
                });
                self.heap.extend_from_slice(&self.stack[..self.length]);
            } else {
                self.heap
                    .try_reserve(end - self.heap.len())
                    .unwrap_or_else(|error| {
                        panic!("HIA command-dispatch frame allocation failed: {error}")
                    });
            }
            self.heap.extend_from_slice(bytes);
        }
        self.length = end;
    }

    fn word(&mut self, value: u64) {
        self.append(&value.to_le_bytes());
    }

    fn size(&mut self, value: usize) {
        self.word(
            u64::try_from(value)
                .unwrap_or_else(|_| panic!("HIA command-dispatch size exceeds u64")),
        );
    }

    fn bytes(&self) -> &[u8] {
        if self.heap.is_empty() {
            &self.stack[..self.length]
        } else {
            &self.heap
        }
    }

    fn components(&mut self, path: &Path) {
        for component in path.components() {
            match component {
                Component::RootDir => {
                    self.word(/*value*/ 1);
                    self.word(/*value*/ 0);
                }
                Component::CurDir => {
                    self.word(/*value*/ 2);
                    self.word(/*value*/ 0);
                }
                Component::ParentDir => {
                    self.word(/*value*/ 3);
                    self.word(/*value*/ 0);
                }
                Component::Normal(value) => {
                    let bytes = value.as_encoded_bytes();
                    self.word(/*value*/ 4);
                    self.size(bytes.len());
                    self.append(bytes);
                }
                Component::Prefix(_) => {
                    panic!("HIA command dispatch requires the native Unix path profile");
                }
            }
        }
    }
}

enum Event {
    Begin {
        count: usize,
        resolve: bool,
        fallback: bool,
    },
    Bucket {
        tag: u64,
        found: bool,
        count: usize,
    },
    Rule {
        index: usize,
        origin: u64,
        kind: u64,
    },
    Path {
        usable: bool,
    },
    Candidate {
        index: usize,
    },
    Basename {
        count: usize,
    },
    Heuristic {
        decision: Decision,
    },
}

struct Objects<'p> {
    // On unwind, release partial results before the host command and program,
    // matching the original collect/iterator/local ownership nesting.
    pending: Option<RuleMatch>,
    matched: Vec<RuleMatch>,
    basename_command: Option<Vec<String>>,
    basename: Option<String>,
    program: Option<AbsolutePathBuf>,
    rules: Option<&'p Vec<RuleRef>>,
    paths: Option<&'p [AbsolutePathBuf]>,
}

struct Response {
    state: [u8; STATE_BYTES],
    append: u64,
    cleanup: u64,
    action: u64,
    operand: usize,
}

pub(crate) fn matches_for_command(
    policy: &Policy,
    command: &[String],
    fallback: HeuristicsFallback<'_>,
    options: &MatchOptions,
) -> Vec<RuleMatch> {
    let mut state = [0; STATE_BYTES];
    let mut objects = Objects {
        rules: None,
        paths: None,
        program: None,
        basename: None,
        basename_command: None,
        pending: None,
        matched: Vec::new(),
    };
    let mut event = Event::Begin {
        count: command.len(),
        resolve: options.resolve_host_executables,
        fallback: fallback.is_some(),
    };
    loop {
        // The temporary transport frame is dropped before any following host
        // callback, including heuristic fallback.
        let response = step(&state, &event, &objects);
        state = response.state;
        match response.append {
            0 => assert!(
                objects.pending.is_none(),
                "HIA discarded a pending rule result"
            ),
            1 => objects.matched.push(
                objects
                    .pending
                    .take()
                    .unwrap_or_else(|| panic!("HIA retained a missing rule result")),
            ),
            2 => {
                let annotated = {
                    let pending = objects
                        .pending
                        .take()
                        .unwrap_or_else(|| panic!("HIA annotated a missing rule result"));
                    let RuleMatch::PrefixRuleMatch {
                        matched_prefix,
                        decision,
                        justification,
                        ..
                    } = pending
                    else {
                        panic!("HIA annotated a non-prefix rule result");
                    };
                    let program = objects
                        .program
                        .as_ref()
                        .unwrap_or_else(|| panic!("HIA annotation has no resolved program"));
                    RuleMatch::PrefixRuleMatch {
                        matched_prefix,
                        decision,
                        resolved_program: Some(program.clone()),
                        justification,
                    }
                };
                objects.matched.push(annotated);
            }
            _ => panic!("HIA command-dispatch append tag is invalid"),
        }
        if response.cleanup & 1 != 0 {
            drop(
                objects
                    .basename_command
                    .take()
                    .unwrap_or_else(|| panic!("HIA released a missing basename command")),
            );
        }
        if response.cleanup & 2 != 0 {
            drop(
                objects
                    .basename
                    .take()
                    .unwrap_or_else(|| panic!("HIA released a missing basename")),
            );
        }
        if response.cleanup & 4 != 0 {
            drop(
                objects
                    .program
                    .take()
                    .unwrap_or_else(|| panic!("HIA released a missing program")),
            );
        }
        event = match response.action {
            0 => {
                assert!(objects.pending.is_none(), "HIA left a pending result");
                assert!(
                    objects.basename_command.is_none()
                        && objects.basename.is_none()
                        && objects.program.is_none(),
                    "HIA left host temporaries alive"
                );
                assert!(
                    fallback.is_none() || !objects.matched.is_empty(),
                    "HIA violated the nonempty heuristic-result contract"
                );
                return objects.matched;
            }
            1 => {
                let first = command.first().unwrap_or_else(|| {
                    panic!("HIA requested an exact lookup for an empty command")
                });
                objects.rules = policy.rules().get_vec(first);
                Event::Bucket {
                    tag: 1,
                    found: objects.rules.is_some(),
                    count: objects.rules.map_or(0, Vec::len),
                }
            }
            2 | 8 => {
                let rule = objects
                    .rules
                    .and_then(|rules| rules.get(response.operand))
                    .unwrap_or_else(|| panic!("HIA rule index is out of range"));
                let (input, origin) = if response.action == 2 {
                    (command, 0)
                } else {
                    (
                        objects
                            .basename_command
                            .as_deref()
                            .unwrap_or_else(|| panic!("HIA requested a missing basename command")),
                        1,
                    )
                };
                objects.pending = rule.matches(input);
                let kind = match objects.pending.as_ref() {
                    None => 0,
                    Some(RuleMatch::PrefixRuleMatch { .. }) => 1,
                    Some(RuleMatch::HeuristicsRuleMatch { .. }) => 2,
                };
                Event::Rule {
                    index: response.operand,
                    origin,
                    kind,
                }
            }
            3 => {
                assert!(
                    objects.program.is_none()
                        && objects.basename.is_none()
                        && objects.basename_command.is_none(),
                    "HIA repeated path acquisition"
                );
                let resolved = resolve_original_path(command);
                let usable = resolved.is_some();
                if let Some((program, basename)) = resolved {
                    objects.program = Some(program);
                    objects.basename = Some(basename);
                }
                Event::Path { usable }
            }
            4 => {
                let basename = objects
                    .basename
                    .as_ref()
                    .unwrap_or_else(|| panic!("HIA host lookup has no basename"));
                objects.rules = policy.rules().get_vec(basename);
                Event::Bucket {
                    tag: 4,
                    found: objects.rules.is_some(),
                    count: objects.rules.map_or(0, Vec::len),
                }
            }
            5 => {
                let basename = objects
                    .basename
                    .as_ref()
                    .unwrap_or_else(|| panic!("HIA allowlist lookup has no basename"));
                objects.paths = policy.host_executables().get(basename).map(AsRef::as_ref);
                Event::Bucket {
                    tag: 5,
                    found: objects.paths.is_some(),
                    count: objects.paths.map_or(0, <[AbsolutePathBuf]>::len),
                }
            }
            6 => Event::Candidate {
                index: response.operand,
            },
            7 => {
                assert!(
                    objects.basename_command.is_none(),
                    "HIA repeated basename construction"
                );
                let basename = objects
                    .basename
                    .take()
                    .unwrap_or_else(|| panic!("HIA basename construction has no basename"));
                // Keep the original iterator and clone order, including an
                // explicitly present but empty host rule bucket.
                objects.basename_command = Some(
                    std::iter::once(basename)
                        .chain(command.iter().skip(1).cloned())
                        .collect(),
                );
                Event::Basename {
                    count: command.len(),
                }
            }
            9 => {
                assert!(
                    objects.basename_command.is_none()
                        && objects.basename.is_none()
                        && objects.program.is_none(),
                    "HIA requested fallback before host cleanup"
                );
                assert!(
                    objects.matched.is_empty(),
                    "HIA requested fallback after retaining a match"
                );
                let callback = fallback
                    .unwrap_or_else(|| panic!("HIA requested an absent heuristic callback"));
                let owned_command = command.to_vec();
                let decision = callback(command);
                objects.pending = Some(RuleMatch::HeuristicsRuleMatch {
                    command: owned_command,
                    decision,
                });
                Event::Heuristic { decision }
            }
            _ => panic!("HIA command-dispatch action is invalid"),
        };
    }
}

fn resolve_original_path(command: &[String]) -> Option<(AbsolutePathBuf, String)> {
    let first = command.first()?;
    let program = AbsolutePathBuf::try_from(first.clone()).ok()?;
    let basename = executable_path_lookup_key(program.as_path())?;
    Some((program, basename))
}

fn step(state: &[u8; STATE_BYTES], event: &Event, objects: &Objects<'_>) -> Response {
    let mut frame = Frame {
        stack: [0; 512],
        heap: Vec::new(),
        length: 0,
    };
    frame.word(/*value*/ 1);
    let tag = match event {
        Event::Begin { .. } => 0,
        Event::Bucket { tag, .. } => *tag,
        Event::Rule { .. } => 2,
        Event::Path { .. } => 3,
        Event::Candidate { .. } => 6,
        Event::Basename { .. } => 7,
        Event::Heuristic { .. } => 8,
    };
    frame.word(tag);
    frame.append(state);
    match event {
        Event::Begin {
            count,
            resolve,
            fallback,
        } => {
            frame.size(*count);
            frame.word(u64::from(*resolve));
            frame.word(u64::from(*fallback));
        }
        Event::Bucket { found, count, .. } => {
            frame.word(u64::from(*found));
            frame.size(*count);
        }
        Event::Rule {
            index,
            origin,
            kind,
        } => {
            frame.size(*index);
            frame.word(*origin);
            frame.word(*kind);
        }
        Event::Path { usable } => frame.word(u64::from(*usable)),
        Event::Candidate { index } => {
            let program = objects
                .program
                .as_ref()
                .unwrap_or_else(|| panic!("HIA path comparison has no program"));
            let candidate = objects
                .paths
                .and_then(|paths| paths.get(*index))
                .unwrap_or_else(|| panic!("HIA allowlist index is out of range"));
            frame.size(*index);
            frame.size(program.as_path().components().count());
            frame.size(candidate.as_path().components().count());
            frame.components(program.as_path());
            frame.components(candidate.as_path());
        }
        Event::Basename { count } => frame.size(*count),
        Event::Heuristic { decision } => frame.word(match decision {
            Decision::Allow => 0,
            Decision::Prompt => 1,
            Decision::Forbidden => 2,
        }),
    }
    let source = frame.bytes();
    let mut output = [0xff_u8; RESPONSE_BYTES];
    let mut workspace = [];
    // SAFETY: these disjoint buffers remain live for this synchronous call.
    // Native code retains no pointers; each response is decoded before host
    // effects resume. Source and workspace are read-only by the ABI contract.
    let status = unsafe {
        codex_hia_command_dispatch(
            source.as_ptr(),
            u64::try_from(source.len()).unwrap_or_else(|_| panic!("HIA source size exceeds u64")),
            output.as_mut_ptr(),
            RESPONSE_BYTES as u64,
            workspace.as_mut_ptr(),
            /*workspace_length*/ 0,
        )
    };
    assert_eq!(status, 0, "HIA command-dispatch operation failed");
    assert_eq!(
        word(&output, 0),
        MAGIC,
        "HIA command-dispatch state marker is invalid"
    );
    let action = word(&output, 176);
    assert!(action <= 9, "HIA command-dispatch action is invalid");
    assert_eq!(
        word(&output, 8),
        if action == 0 { 10 } else { action },
        "HIA command-dispatch phase is invalid"
    );
    assert_eq!(
        word(&output, 80),
        word(state, 80)
            .checked_add(1)
            .unwrap_or_else(|| panic!("HIA command-dispatch sequence overflow")),
        "HIA command-dispatch sequence is invalid"
    );
    let (flags, count) = match event {
        Event::Begin {
            count,
            resolve,
            fallback,
        } => (
            u64::from(*resolve) + 2 * u64::from(*fallback),
            u64::try_from(*count).unwrap_or_else(|_| panic!("HIA command count exceeds u64")),
        ),
        _ => (word(state, 16), word(state, 24)),
    };
    assert_eq!(
        word(&output, 16),
        flags,
        "HIA changed immutable dispatch flags"
    );
    assert_eq!(word(&output, 24), count, "HIA changed the command count");
    for offset in (88..160).step_by(8) {
        assert_eq!(
            word(&output, offset),
            0,
            "HIA state reserved word is nonzero"
        );
    }
    assert_eq!(
        word(&output, 192),
        0,
        "HIA response reserved word is nonzero"
    );
    let append = word(&output, 160);
    let cleanup = word(&output, 168);
    assert!(append <= 2, "HIA command-dispatch append tag is invalid");
    assert!(matches!(cleanup, 0 | 5 | 6), "HIA cleanup mask is invalid");
    let operand = usize::try_from(word(&output, 184))
        .unwrap_or_else(|_| panic!("HIA command-dispatch operand exceeds usize"));
    if !matches!(action, 2 | 6 | 8) {
        assert_eq!(operand, 0, "HIA action has an unexpected operand");
    }
    let rule_count = word(&output, 32);
    let rule_index = word(&output, 40);
    let rule_matches = word(&output, 48);
    let path_count = word(&output, 56);
    let path_index = word(&output, 64);
    assert!(
        rule_matches <= rule_index && rule_index <= rule_count,
        "HIA rule progress is out of range"
    );
    assert!(
        path_index <= path_count,
        "HIA path progress is out of range"
    );
    let resources = match action {
        4..=7 => 6,
        8 => 5,
        _ => 0,
    };
    assert_eq!(
        word(&output, 72),
        resources,
        "HIA resource state is invalid"
    );
    if (1..=8).contains(&action) {
        assert!(count > 0, "HIA scheduled command work for an empty command");
    }
    if (3..=8).contains(&action) {
        assert!(flags & 1 != 0, "HIA scheduled disabled host resolution");
    }
    if matches!(action, 3..=7 | 9) {
        assert_eq!(
            rule_matches, 0,
            "HIA continuation has inconsistent match progress"
        );
    }
    if matches!(action, 3..=4) {
        assert_eq!(
            rule_index, rule_count,
            "HIA continuation has unfinished exact progress"
        );
    }
    if matches!(action, 5..=7) {
        assert_eq!(
            rule_index, 0,
            "HIA continuation has premature host progress"
        );
    }
    if action == 1 {
        assert_eq!(
            [rule_count, rule_index, rule_matches, path_count, path_index],
            [0; 5],
            "HIA initial continuation has nonzero progress"
        );
        assert_eq!(word(&output, 80), 1, "HIA repeated initial lookup");
    }
    if action == 9 {
        assert!(flags & 2 != 0, "HIA scheduled an absent heuristic callback");
    }
    match action {
        2 | 8 => {
            assert_eq!(
                word(&output, 184),
                rule_index,
                "HIA rule operand is inconsistent"
            );
            assert!(rule_index < rule_count, "HIA rule operand is out of range");
        }
        6 => {
            assert_eq!(
                word(&output, 184),
                path_index,
                "HIA path operand is inconsistent"
            );
            assert!(path_index < path_count, "HIA path operand is out of range");
        }
        _ => {}
    }
    let mut next = [0; STATE_BYTES];
    next.copy_from_slice(&output[..STATE_BYTES]);
    Response {
        state: next,
        append,
        cleanup,
        action,
        operand,
    }
}

fn word(bytes: &[u8], at: usize) -> u64 {
    let value: [u8; 8] = at
        .checked_add(8)
        .and_then(|end| bytes.get(at..end))
        .and_then(|slice| slice.try_into().ok())
        .unwrap_or_else(|| panic!("HIA command-dispatch output word is out of range"));
    u64::from_le_bytes(value)
}
