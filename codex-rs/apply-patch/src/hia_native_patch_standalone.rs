//! Preserve the standalone host calls while HIA selects every continuation.

use std::io::Read;
use std::io::Write;

use crate::ApplyPatchFileUpdateMode;
use crate::CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS_ENV_VAR;

unsafe extern "C" {
    fn codex_hia_patch_standalone(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u64)]
enum Entry {
    Run = 0,
    Environment = 1,
}

#[derive(Clone, Copy)]
#[repr(u64)]
enum Event {
    Start = 0,
    ArgumentPresent = 1,
    ArgumentMissing = 2,
    ArgumentUtf8Ok = 3,
    ArgumentUtf8Error = 4,
    StdinOk = 5,
    StdinError = 6,
    NoExtraArgument = 7,
    ExtraArgument = 8,
    CwdOk = 9,
    CwdError = 10,
    RuntimeOk = 11,
    RuntimeError = 12,
    ModeReady = 13,
    ApplicationOk = 14,
    ApplicationError = 15,
    Complete = 16,
    EnvValue = 17,
    EnvUnavailable = 18,
}

#[derive(Debug, Eq, PartialEq)]
enum Action {
    ReadArguments,
    DecodeArgument,
    ReadStdin,
    CheckExtraArgument,
    OpenHandlesAndCwd,
    BuildRuntime,
    ResolvePathAndMode,
    ApplyPatch,
    Flush,
    DiagBadArgument,
    DiagUsage,
    DiagStdin,
    DiagExtraArgument,
    DiagCwd,
    DiagRuntime,
    Exit(i32),
    Mode(ApplyPatchFileUpdateMode),
}

fn native(entry: Entry, phase: u64, event: Event, source: &[u8]) -> (u64, Action) {
    let frame = [1, entry as u64, phase, event as u64, 0, 0, 0, 0];
    let mut workspace = [0u8; 64];
    for (index, value) in frame.into_iter().enumerate() {
        workspace[index * 8..index * 8 + 8].copy_from_slice(&value.to_le_bytes());
    }
    let original_workspace = workspace;
    let mut output = [0u8; 64];
    // SAFETY: these borrowed allocations remain live and disjoint. The HIA
    // entry only reads source/workspace and retains no pointers after return.
    let status = unsafe {
        codex_hia_patch_standalone(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(status, 0, "HIA patch_standalone: native request rejected");
    assert_eq!(
        workspace, original_workspace,
        "HIA patch_standalone: workspace changed"
    );
    let mut response = [0u64; 8];
    for (index, value) in response.iter_mut().enumerate() {
        let mut word = [0u8; 8];
        word.copy_from_slice(&output[index * 8..index * 8 + 8]);
        *value = u64::from_le_bytes(word);
    }
    assert!(
        response[0] == 1
            && response[1] == entry as u64
            && (1..=16).contains(&response[2])
            && response[5] == phase
            && response[6] == event as u64
            && response[7] == 0,
        "HIA patch_standalone: invalid response frame"
    );
    let action = match response[3] {
        1 => Action::ReadArguments,
        2 => Action::DecodeArgument,
        3 => Action::ReadStdin,
        4 => Action::CheckExtraArgument,
        5 => Action::OpenHandlesAndCwd,
        6 => Action::BuildRuntime,
        7 => Action::ResolvePathAndMode,
        8 => Action::ApplyPatch,
        9 => Action::Flush,
        10 => Action::DiagBadArgument,
        11 => Action::DiagUsage,
        12 => Action::DiagStdin,
        13 => Action::DiagExtraArgument,
        14 => Action::DiagCwd,
        15 => Action::DiagRuntime,
        16 => {
            assert!(
                entry == Entry::Run && response[4] <= 2,
                "HIA patch_standalone: invalid exit selection"
            );
            Action::Exit(response[4] as i32)
        }
        17 => {
            assert_eq!(entry, Entry::Environment);
            Action::Mode(match response[4] {
                0 => ApplyPatchFileUpdateMode::NormalizeToLf,
                1 => ApplyPatchFileUpdateMode::PreserveLineEndings,
                _ => panic!("HIA patch_standalone: invalid mode selection"),
            })
        }
        _ => panic!("HIA patch_standalone: invalid action"),
    };
    assert_eq!(
        response[2] == 16,
        matches!(action, Action::Exit(_) | Action::Mode(_)),
        "HIA patch_standalone: invalid terminal state"
    );
    if !matches!(action, Action::Exit(_) | Action::Mode(_)) {
        assert_eq!(entry, Entry::Run);
        assert_eq!(response[4], 0, "HIA patch_standalone: unexpected value");
    }
    (response[2], action)
}

struct Route {
    phase: u64,
}

impl Route {
    fn step(&mut self, event: Event, source: &[u8]) -> Action {
        let (phase, action) = native(Entry::Run, self.phase, event, source);
        self.phase = phase;
        action
    }

    fn finish(&mut self) -> i32 {
        match self.step(Event::Complete, &[]) {
            Action::Exit(code) => code,
            _ => panic!("HIA patch_standalone: expected completion exit"),
        }
    }
}

fn take_success<T, E>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(_) => panic!("HIA patch_standalone: selected success is absent"),
    }
}

fn take_failure<T, E>(result: Result<T, E>) -> E {
    match result {
        Ok(_) => panic!("HIA patch_standalone: selected error is absent"),
        Err(error) => error,
    }
}

/// Reads the update mode selected for an arg0-dispatched `apply_patch` process.
#[doc(hidden)]
pub fn apply_patch_file_update_mode_from_env() -> ApplyPatchFileUpdateMode {
    let value = std::env::var(CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS_ENV_VAR);
    let (event, source) = match &value {
        Ok(value) => (Event::EnvValue, value.as_bytes()),
        Err(_) => (Event::EnvUnavailable, &[][..]),
    };
    match native(Entry::Environment, /*phase*/ 0, event, source).1 {
        Action::Mode(mode) => mode,
        _ => panic!("HIA patch_standalone: expected environment mode"),
    }
}

pub fn main() -> ! {
    let exit_code = run_main();
    std::process::exit(exit_code);
}

/// We would prefer to return `std::process::ExitCode`, but its `exit_process()`
/// method is still a nightly API and we want main() to return !.
pub fn run_main() -> i32 {
    let mut route = Route { phase: 0 };
    assert_eq!(route.step(Event::Start, &[]), Action::ReadArguments);
    let mut args = std::env::args_os();
    let _argv0 = args.next();
    let argument = args.next();
    let event = match &argument {
        Some(_) => Event::ArgumentPresent,
        None => Event::ArgumentMissing,
    };
    let patch_arg = match route.step(event, &[]) {
        Action::DecodeArgument => {
            let arg = match argument {
                Some(arg) => arg,
                None => panic!("HIA patch_standalone: selected argument is absent"),
            };
            let decoded = arg.into_string();
            let event = match &decoded {
                Ok(_) => Event::ArgumentUtf8Ok,
                Err(_) => Event::ArgumentUtf8Error,
            };
            match route.step(event, &[]) {
                Action::CheckExtraArgument => take_success(decoded),
                Action::DiagBadArgument => {
                    assert!(decoded.is_err());
                    eprintln!("Error: apply_patch requires a UTF-8 PATCH argument.");
                    return route.finish();
                }
                _ => panic!("HIA patch_standalone: invalid argument continuation"),
            }
        }
        Action::ReadStdin => {
            assert!(argument.is_none());
            let mut buf = String::new();
            let read = std::io::stdin().read_to_string(&mut buf);
            let (event, source) = match &read {
                Ok(_) => (Event::StdinOk, buf.as_bytes()),
                Err(_) => (Event::StdinError, &[][..]),
            };
            match route.step(event, source) {
                Action::CheckExtraArgument => {
                    take_success(read);
                    buf
                }
                Action::DiagUsage => {
                    take_success(read);
                    eprintln!("Usage: apply_patch 'PATCH'\n       echo 'PATCH' | apply_patch");
                    return route.finish();
                }
                Action::DiagStdin => {
                    let err = take_failure(read);
                    eprintln!("Error: Failed to read PATCH from stdin.\n{err}");
                    return route.finish();
                }
                _ => panic!("HIA patch_standalone: invalid stdin continuation"),
            }
        }
        _ => panic!("HIA patch_standalone: invalid input continuation"),
    };

    let event = match args.next() {
        Some(_) => Event::ExtraArgument,
        None => Event::NoExtraArgument,
    };
    match route.step(event, &[]) {
        Action::OpenHandlesAndCwd => {}
        Action::DiagExtraArgument => {
            eprintln!("Error: apply_patch accepts exactly one argument.");
            return route.finish();
        }
        _ => panic!("HIA patch_standalone: invalid extra-argument continuation"),
    }

    let mut stdout = std::io::stdout();
    let mut stderr = std::io::stderr();
    let directory = codex_utils_absolute_path::AbsolutePathBuf::current_dir();
    let event = match &directory {
        Ok(_) => Event::CwdOk,
        Err(_) => Event::CwdError,
    };
    let cwd = match route.step(event, &[]) {
        Action::BuildRuntime => take_success(directory),
        Action::DiagCwd => {
            let err = take_failure(directory);
            eprintln!("Error: Failed to determine current directory.\n{err}");
            return route.finish();
        }
        _ => panic!("HIA patch_standalone: invalid cwd continuation"),
    };
    let built = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build();
    let event = match &built {
        Ok(_) => Event::RuntimeOk,
        Err(_) => Event::RuntimeError,
    };
    let runtime = match route.step(event, &[]) {
        Action::ResolvePathAndMode => take_success(built),
        Action::DiagRuntime => {
            let err = take_failure(built);
            eprintln!("Error: Failed to initialize runtime.\n{err}");
            return route.finish();
        }
        _ => panic!("HIA patch_standalone: invalid runtime continuation"),
    };
    let cwd = codex_utils_path_uri::PathUri::from_abs_path(&cwd);
    let update_file_mode = crate::apply_patch_file_update_mode_from_env();
    assert_eq!(route.step(Event::ModeReady, &[]), Action::ApplyPatch);
    let applied = runtime.block_on(crate::apply_patch_with_options(
        &patch_arg,
        crate::ApplyPatchOptions {
            update_file_mode,
            ..Default::default()
        },
        &cwd,
        &mut stdout,
        &mut stderr,
        codex_exec_server::LOCAL_FS.as_ref(),
        /*sandbox*/ None,
    ));
    let event = match &applied {
        Ok(_) => Event::ApplicationOk,
        Err(_) => Event::ApplicationError,
    };
    match route.step(event, &[]) {
        Action::Flush => {
            assert!(applied.is_ok());
            let _ = stdout.flush();
            route.finish()
        }
        Action::Exit(code) => {
            assert!(applied.is_err());
            code
        }
        _ => panic!("HIA patch_standalone: invalid application continuation"),
    }
}
