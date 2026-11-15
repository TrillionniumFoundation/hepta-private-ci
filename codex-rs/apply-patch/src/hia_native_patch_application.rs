//! Execute the original host calls using the HIA application continuation.

use std::io;

use codex_exec_server::ExecutorFileSystem;
use codex_exec_server::FileSystemSandboxContext;
use codex_utils_path_uri::PathUri;

use crate::AppliedPatchDelta;
use crate::ApplyPatchError;
use crate::ApplyPatchFailure;
use crate::ApplyPatchOptions;
use crate::Hunk;
use crate::IoError;
use crate::ParseError;
use crate::apply_hunks_to_files;
use crate::parse_patch;
use crate::print_summary;

unsafe extern "C" {
    fn codex_hia_patch_application(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

#[derive(Clone, Copy)]
#[repr(u64)]
enum Entry {
    Patch = 0,
    Hunks = 1,
}

#[derive(Clone, Copy)]
#[repr(u64)]
enum Event {
    Start = 0,
    ParseOk = 1,
    InvalidPatch = 2,
    InvalidHunk = 3,
    WriteOk = 4,
    WriteError = 5,
    EffectsOk = 6,
    EffectsError = 7,
    EffectsErrorIsIo = 8,
    EffectsErrorIsOther = 9,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Action {
    Parse,
    ApplyEffects,
    WriteInvalidPatch,
    WriteInvalidHunk,
    PrintSummary,
    WriteEffectsError,
    ClassifyEffectsError,
    ReturnSuccess,
    ReturnParseFailure,
    ReturnWriterFailureEmpty,
    ReturnWriterFailureCommitted,
    ReturnEffectsIoFailure,
    ReturnEffectsOtherFailure,
}

fn rejected(message: &'static str) -> ApplyPatchError {
    io::Error::other(message).into()
}

fn committed_failure(error: ApplyPatchError, delta: &AppliedPatchDelta) -> ApplyPatchFailure {
    ApplyPatchFailure::new(error, delta.clone())
}

fn take_success<T, E>(result: Result<T, E>) -> Result<T, ApplyPatchError> {
    match result {
        Ok(value) => Ok(value),
        Err(_) => Err(rejected(
            "HIA patch_application: selected success is absent",
        )),
    }
}

fn take_failure<T, E>(result: Result<T, E>) -> Result<E, ApplyPatchError> {
    match result {
        Ok(_) => Err(rejected("HIA patch_application: selected error is absent")),
        Err(error) => Ok(error),
    }
}

fn write_event(result: &io::Result<()>) -> Event {
    match result {
        Ok(()) => Event::WriteOk,
        Err(_) => Event::WriteError,
    }
}

struct Route {
    entry: Entry,
    phase: u64,
}

struct Host<'a, Out, Err> {
    cwd: &'a PathUri,
    stdout: &'a mut Out,
    stderr: &'a mut Err,
    fs: &'a dyn ExecutorFileSystem,
    sandbox: Option<&'a FileSystemSandboxContext>,
}

impl Route {
    fn new(entry: Entry) -> Self {
        Self { entry, phase: 0 }
    }

    fn step(&mut self, event: Event) -> Result<Action, ApplyPatchError> {
        let frame = [1, self.entry as u64, self.phase, event as u64, 0, 0, 0, 0];
        let mut source = [0u8; 64];
        for (index, value) in frame.into_iter().enumerate() {
            source[index * 8..index * 8 + 8].copy_from_slice(&value.to_le_bytes());
        }
        let mut output = [0u8; 64];
        // SAFETY: the fixed stack buffers are live and disjoint. The HIA
        // entry retains no pointers and the locked ABI requires no workspace.
        let status = unsafe {
            codex_hia_patch_application(
                source.as_ptr(),
                source.len() as u64,
                output.as_mut_ptr(),
                output.len() as u64,
                std::ptr::null_mut(),
                /*workspace_len*/ 0,
            )
        };
        if status != 0 {
            return Err(io::Error::other(format!(
                "HIA patch_application: native ABI rejected request ({status})"
            ))
            .into());
        }
        let mut response = [0u64; 8];
        for (index, value) in response.iter_mut().enumerate() {
            let mut word = [0u8; 8];
            word.copy_from_slice(&output[index * 8..index * 8 + 8]);
            *value = u64::from_le_bytes(word);
        }
        if response[0] != 1
            || response[1] != self.entry as u64
            || !(1..=8).contains(&response[2])
            || response[4] != self.phase
            || response[5] != event as u64
            || response[6] != 0
            || response[7] != 0
        {
            return Err(rejected("HIA patch_application: invalid result frame"));
        }
        let action = match response[3] {
            1 => Action::Parse,
            2 => Action::ApplyEffects,
            3 => Action::WriteInvalidPatch,
            4 => Action::WriteInvalidHunk,
            5 => Action::PrintSummary,
            6 => Action::WriteEffectsError,
            7 => Action::ClassifyEffectsError,
            8 => Action::ReturnSuccess,
            9 => Action::ReturnParseFailure,
            10 => Action::ReturnWriterFailureEmpty,
            11 => Action::ReturnWriterFailureCommitted,
            12 => Action::ReturnEffectsIoFailure,
            13 => Action::ReturnEffectsOtherFailure,
            _ => return Err(rejected("HIA patch_application: invalid action")),
        };
        if (response[2] == 8) != (response[3] >= 8) {
            return Err(rejected("HIA patch_application: invalid terminal state"));
        }
        self.phase = response[2];
        Ok(action)
    }
}

/// Apply patch text using the original parser, host effects and writer calls.
pub async fn apply_patch_with_options(
    patch: &str,
    options: ApplyPatchOptions,
    cwd: &PathUri,
    stdout: &mut impl io::Write,
    stderr: &mut impl io::Write,
    fs: &dyn ExecutorFileSystem,
    sandbox: Option<&FileSystemSandboxContext>,
) -> Result<AppliedPatchDelta, ApplyPatchFailure> {
    let mut route = Route::new(Entry::Patch);
    if route
        .step(Event::Start)
        .map_err(ApplyPatchFailure::without_delta)?
        != Action::Parse
    {
        return Err(ApplyPatchFailure::without_delta(rejected(
            "HIA patch_application: expected parser action",
        )));
    }
    let parsed = parse_patch(patch);
    let event = match &parsed {
        Ok(_) => Event::ParseOk,
        Err(ParseError::InvalidPatchError(_)) => Event::InvalidPatch,
        Err(ParseError::InvalidHunkError { .. }) => Event::InvalidHunk,
    };
    let action = route
        .step(event)
        .map_err(ApplyPatchFailure::without_delta)?;
    match action {
        Action::ApplyEffects => {
            let hunks = take_success(parsed)
                .map_err(ApplyPatchFailure::without_delta)?
                .hunks;
            let host = Host {
                cwd,
                stdout,
                stderr,
                fs,
                sandbox,
            };
            execute_hunks(&hunks, options, host, route).await
        }
        Action::WriteInvalidPatch | Action::WriteInvalidHunk => {
            let error = take_failure(parsed).map_err(ApplyPatchFailure::without_delta)?;
            let written = match (action, &error) {
                (Action::WriteInvalidPatch, ParseError::InvalidPatchError(message)) => {
                    writeln!(stderr, "Invalid patch: {message}")
                }
                (
                    Action::WriteInvalidHunk,
                    ParseError::InvalidHunkError {
                        message,
                        line_number,
                    },
                ) => {
                    writeln!(
                        stderr,
                        "Invalid patch hunk on line {line_number}: {message}"
                    )
                }
                _ => {
                    return Err(ApplyPatchFailure::without_delta(rejected(
                        "HIA patch_application: selected parse error is absent",
                    )));
                }
            };
            match route
                .step(write_event(&written))
                .map_err(ApplyPatchFailure::without_delta)?
            {
                Action::ReturnParseFailure => {
                    take_success(written).map_err(ApplyPatchFailure::without_delta)?;
                    Err(ApplyPatchFailure::without_delta(
                        ApplyPatchError::ParseError(error),
                    ))
                }
                Action::ReturnWriterFailureEmpty => {
                    let error = take_failure(written).map_err(ApplyPatchFailure::without_delta)?;
                    Err(ApplyPatchFailure::without_delta(ApplyPatchError::from(
                        error,
                    )))
                }
                _ => Err(ApplyPatchFailure::without_delta(rejected(
                    "HIA patch_application: invalid parse terminal",
                ))),
            }
        }
        _ => Err(ApplyPatchFailure::without_delta(rejected(
            "HIA patch_application: invalid parser continuation",
        ))),
    }
}

pub(crate) async fn apply_hunks_with_options(
    hunks: &[Hunk],
    options: ApplyPatchOptions,
    cwd: &PathUri,
    stdout: &mut impl io::Write,
    stderr: &mut impl io::Write,
    fs: &dyn ExecutorFileSystem,
    sandbox: Option<&FileSystemSandboxContext>,
) -> Result<AppliedPatchDelta, ApplyPatchFailure> {
    let mut route = Route::new(Entry::Hunks);
    if route
        .step(Event::Start)
        .map_err(ApplyPatchFailure::without_delta)?
        != Action::ApplyEffects
    {
        return Err(ApplyPatchFailure::without_delta(rejected(
            "HIA patch_application: expected effects action",
        )));
    }
    let host = Host {
        cwd,
        stdout,
        stderr,
        fs,
        sandbox,
    };
    execute_hunks(hunks, options, host, route).await
}

async fn execute_hunks(
    hunks: &[Hunk],
    options: ApplyPatchOptions,
    host: Host<'_, impl io::Write, impl io::Write>,
    mut route: Route,
) -> Result<AppliedPatchDelta, ApplyPatchFailure> {
    let Host {
        cwd,
        stdout,
        stderr,
        fs,
        sandbox,
    } = host;
    let mut delta = AppliedPatchDelta::empty();
    let applied = apply_hunks_to_files(hunks, options, cwd, fs, sandbox, &mut delta).await;
    let event = match &applied {
        Ok(_) => Event::EffectsOk,
        Err(_) => Event::EffectsError,
    };
    match route
        .step(event)
        .map_err(|error| committed_failure(error, &delta))?
    {
        Action::PrintSummary => {
            let affected_paths =
                take_success(applied).map_err(|error| committed_failure(error, &delta))?;
            let written = print_summary(&affected_paths, stdout);
            match route
                .step(write_event(&written))
                .map_err(|error| committed_failure(error, &delta))?
            {
                Action::ReturnSuccess => {
                    take_success(written).map_err(|error| committed_failure(error, &delta))?;
                    Ok(delta)
                }
                Action::ReturnWriterFailureCommitted => {
                    let error =
                        take_failure(written).map_err(|error| committed_failure(error, &delta))?;
                    Err(committed_failure(ApplyPatchError::from(error), &delta))
                }
                _ => Err(ApplyPatchFailure::new(
                    rejected("HIA patch_application: invalid summary terminal"),
                    delta,
                )),
            }
        }
        Action::WriteEffectsError => {
            let error = take_failure(applied).map_err(|error| committed_failure(error, &delta))?;
            let msg = error.to_string();
            let written = writeln!(stderr, "{msg}");
            match route
                .step(write_event(&written))
                .map_err(|error| committed_failure(error, &delta))?
            {
                Action::ReturnWriterFailureCommitted => {
                    let error =
                        take_failure(written).map_err(|error| committed_failure(error, &delta))?;
                    Err(committed_failure(ApplyPatchError::from(error), &delta))
                }
                Action::ClassifyEffectsError => {
                    take_success(written).map_err(|error| committed_failure(error, &delta))?;
                    let io = error.downcast_ref::<io::Error>();
                    let event = match io {
                        Some(_) => Event::EffectsErrorIsIo,
                        None => Event::EffectsErrorIsOther,
                    };
                    let selected = match route
                        .step(event)
                        .map_err(|error| committed_failure(error, &delta))?
                    {
                        Action::ReturnEffectsIoFailure => match io {
                            Some(io) => ApplyPatchError::from(io),
                            None => rejected("HIA patch_application: selected I/O error is absent"),
                        },
                        Action::ReturnEffectsOtherFailure if io.is_none() => {
                            ApplyPatchError::IoError(IoError {
                                context: msg,
                                source: io::Error::other(error),
                            })
                        }
                        _ => rejected("HIA patch_application: invalid effects error selection"),
                    };
                    Err(ApplyPatchFailure::new(selected, delta))
                }
                _ => Err(ApplyPatchFailure::new(
                    rejected("HIA patch_application: invalid diagnostic continuation"),
                    delta,
                )),
            }
        }
        _ => Err(ApplyPatchFailure::new(
            rejected("HIA patch_application: invalid effects continuation"),
            delta,
        )),
    }
}
