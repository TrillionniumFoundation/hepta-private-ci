use anyhow::Context;
use anyhow::Result;
use codex_windows_sandbox::ConsoleMode;
use codex_windows_sandbox::LocalSid;
use codex_windows_sandbox::RunnerWindowStation;
use codex_windows_sandbox::StderrMode;
use codex_windows_sandbox::StdinMode;
use codex_windows_sandbox::WindowsSandboxReadScope;
use codex_windows_sandbox::create_workspace_write_token_for_read_scope;
use codex_windows_sandbox::ensure_allow_write_aces;
use codex_windows_sandbox::get_current_token_for_restriction;
use codex_windows_sandbox::spawn_process_with_pipes;
use serde_json::json;
use std::collections::HashMap;
use std::fs::File;
use std::io::Read;
use std::mem::size_of;
use std::mem::size_of_val;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::Cryptography::BCRYPT_USE_SYSTEM_PREFERRED_RNG;
use windows_sys::Win32::Security::Cryptography::BCryptGenRandom;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::TokenIntegrityLevel;
use windows_sys::Win32::Security::TokenMandatoryPolicy;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

#[path = "file_boundary.rs"]
mod file_boundary;

const OUTPUT_LIMIT: u64 = 16 * 1024;
const DIAGNOSTIC_WAIT_MS: u32 = 5_000;
const WAIT_TIMEOUT: u32 = 258;

pub(super) fn run() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let mode = args
        .next()
        .context("expected base, full, capability, or broker")?;
    let probe = args
        .next()
        .context("expected kernel32-only probe executable")?;
    anyhow::ensure!(args.next().is_none(), "unexpected diagnostic argument");
    let probe = std::fs::canonicalize(probe)?;
    let mode = mode.to_str().context("diagnostic mode must be UTF-8")?;
    if mode == "files" {
        return file_boundary::run(&probe);
    }
    anyhow::ensure!(
        matches!(mode, "base" | "full" | "capability" | "broker"),
        "unknown diagnostic mode"
    );
    // Only this diagnostic's own launcher token is queried, without mutation.
    let launcher =
        unsafe { OwnedHandle::from_raw_handle(get_current_token_for_restriction()? as _) };
    eprintln!(
        "CRYPTO_TOKEN mode={mode} role=launcher {}",
        token_metadata(launcher.as_raw_handle() as HANDLE)
    );
    drop(launcher);
    let fixture = tempfile::tempdir()?;
    let workspace = fixture.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let child = workspace.join("native-crypto-probe.exe");
    std::fs::copy(probe, &child)?;
    let environment = HashMap::from([
        ("SystemRoot".to_owned(), std::env::var("SystemRoot")?),
        ("TEMP".to_owned(), workspace.display().to_string()),
        ("TMP".to_owned(), workspace.display().to_string()),
    ]);
    // Every invocation owns its fixtures and one fresh process. No global file
    // ACL, user privilege, or system cryptography configuration is modified.
    let observation = match mode {
        "base" => {
            let output = std::process::Command::new(&child)
                .current_dir(&workspace)
                .env_clear()
                .envs(&environment)
                .output()?;
            anyhow::ensure!(
                output.stdout.len() as u64 <= OUTPUT_LIMIT
                    && output.stderr.len() as u64 <= OUTPUT_LIMIT,
                "baseline diagnostic output exceeded limit"
            );
            json!({"exit_code": output.status.code(), "stdout": String::from_utf8_lossy(&output.stdout),
                "stderr": String::from_utf8_lossy(&output.stderr)})
        }
        "full" | "capability" => match restricted(&child, &workspace, &environment, mode) {
            Ok(observation) => observation,
            Err(error) => json!({"launch_error": format!("{error:#}")}),
        },
        "broker" => {
            let home = fixture.path().join("codex-home");
            let roots =
                [codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&workspace)?];
            let result =
                codex_windows_sandbox::run_windows_sandbox_capture_with_filesystem_overrides(
                    &codex_protocol::models::PermissionProfile::workspace_write(),
                    &roots,
                    &home,
                    vec![child.display().to_string()],
                    &workspace,
                    environment,
                    Some(DIAGNOSTIC_WAIT_MS.into()),
                    /*cancellation*/ None,
                    &[],
                    &[],
                    /*use_private_desktop*/ true,
                );
            match result {
                Ok(output) => {
                    anyhow::ensure!(
                        output.stdout.len() as u64 <= OUTPUT_LIMIT
                            && output.stderr.len() as u64 <= OUTPUT_LIMIT,
                        "broker diagnostic output exceeded limit"
                    );
                    json!({"exit_code": output.exit_code, "timed_out": output.timed_out,
                        "stdout": String::from_utf8_lossy(&output.stdout), "stderr": String::from_utf8_lossy(&output.stderr)})
                }
                Err(error) => json!({"launch_error": format!("{error:#}")}),
            }
        }
        _ => unreachable!("mode validated above"),
    };
    println!(
        "{}",
        json!({"mode": mode, "observation_only": true, "result": observation})
    );
    Ok(())
}

fn restricted(
    child: &Path,
    workspace: &Path,
    environment: &HashMap<String, String>,
    mode: &str,
) -> Result<serde_json::Value> {
    let capability = LocalSid::from_string("S-1-5-21-127-239-349-461")?;
    // SAFETY: the validated SID and freshly owned fixture remain live throughout.
    unsafe { ensure_allow_write_aces(workspace, &[capability.as_ptr()])? };
    // SAFETY: the API returns a new owned process token on success.
    let base = unsafe { OwnedHandle::from_raw_handle(get_current_token_for_restriction()? as _) };
    let scope = if mode == "full" {
        WindowsSandboxReadScope::FullDisk
    } else {
        WindowsSandboxReadScope::CapabilityRoots
    };
    // SAFETY: token and capability are owned here; this controlled diagnostic
    // compares the real factories without changing user permission configuration.
    let token = unsafe {
        OwnedHandle::from_raw_handle(create_workspace_write_token_for_read_scope(
            base.as_raw_handle() as HANDLE,
            &[capability.as_ptr()],
            &[],
            scope,
        )? as _)
    };
    eprintln!(
        "CRYPTO_TOKEN mode={mode} role=restricted_child {}",
        token_metadata(token.as_raw_handle() as HANDLE)
    );
    // Compare an already initialized provider with the fresh kernel32-only
    // child. This is only an observation, never a child launch workaround.
    anyhow::ensure!(
        unsafe { ImpersonateLoggedOnUser(token.as_raw_handle() as HANDLE) } != 0,
        "impersonate diagnostic token: {}",
        std::io::Error::last_os_error()
    );
    let mut random = [0_u8; 16];
    let random_status = unsafe {
        BCryptGenRandom(
            std::ptr::null_mut(),
            random.as_mut_ptr(),
            random.len() as u32,
            BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    };
    for byte in &mut random {
        unsafe {
            std::ptr::write_volatile(byte, /*src*/ 0)
        };
    }
    if unsafe { RevertToSelf() } == 0 {
        // The observer must never continue preparing a child under this token.
        std::process::abort();
    }
    eprintln!(
        "CRYPTO_PRELOADED_RNG mode={mode} ntstatus={:#010x}",
        random_status as u32
    );
    // SAFETY: this standalone diagnostic has not started workers or children.
    let station = unsafe { RunnerWindowStation::prepare(token.as_raw_handle() as HANDLE)? };
    let pipes = spawn_process_with_pipes(
        token.as_raw_handle() as HANDLE,
        &[child.display().to_string()],
        workspace,
        environment,
        StdinMode::Closed,
        StderrMode::MergeStdout,
        ConsoleMode::NoWindow,
        /*use_private_desktop*/ true,
        /*logs_base_dir*/ None,
    )?;
    // SAFETY: the pipe-spawn result transfers each returned handle to its caller.
    let (process, thread, stdout) = unsafe {
        (
            OwnedHandle::from_raw_handle(pipes.process.hProcess as _),
            OwnedHandle::from_raw_handle(pipes.process.hThread as _),
            File::from_raw_handle(pipes.stdout_read as _),
        )
    };
    let reader = std::thread::spawn(move || -> std::io::Result<Vec<u8>> {
        let mut output = Vec::new();
        stdout.take(OUTPUT_LIMIT + 1).read_to_end(&mut output)?;
        Ok(output)
    });
    let wait =
        unsafe { WaitForSingleObject(process.as_raw_handle() as HANDLE, DIAGNOSTIC_WAIT_MS) };
    if wait != 0 {
        pipes.job().terminate()?;
        anyhow::ensure!(
            unsafe { WaitForSingleObject(process.as_raw_handle() as HANDLE, DIAGNOSTIC_WAIT_MS) }
                == 0,
            "diagnostic child did not terminate after unsuccessful wait"
        );
    }
    let mut code = 0;
    anyhow::ensure!(
        unsafe { GetExitCodeProcess(process.as_raw_handle() as HANDLE, &mut code) } != 0,
        "read diagnostic child exit: {}",
        std::io::Error::last_os_error()
    );
    let output = reader
        .join()
        .map_err(|_| anyhow::anyhow!("diagnostic output reader panicked"))??;
    anyhow::ensure!(
        output.len() as u64 <= OUTPUT_LIMIT,
        "diagnostic output exceeded limit"
    );
    drop(thread);
    drop(process);
    drop(pipes);
    drop(station);
    Ok(
        json!({"exit_code": code, "wait_status": wait, "timed_out": wait == WAIT_TIMEOUT,
        "stdout": String::from_utf8_lossy(&output)}),
    )
}

fn token_metadata(token: HANDLE) -> serde_json::Value {
    let mut label = [0_usize; 32];
    let mut returned = 0;
    let label_ok = unsafe {
        GetTokenInformation(
            token,
            TokenIntegrityLevel,
            label.as_mut_ptr().cast(),
            size_of_val(&label) as u32,
            &mut returned,
        )
    } != 0;
    let label_error = (!label_ok).then(std::io::Error::last_os_error);
    let rid = if label_ok && returned as usize <= size_of_val(&label) {
        let offset = label[0].checked_sub(label.as_ptr() as usize);
        offset
            .filter(|offset| *offset >= 2 * size_of::<usize>())
            .filter(|offset| {
                offset
                    .checked_add(12)
                    .is_some_and(|end| end <= returned as usize)
            })
            .and_then(|offset| {
                // The returned SID_AND_ATTRIBUTES must point into this buffer
                // and encode S-1-16 with one integrity RID, not an account SID.
                let bytes = unsafe {
                    std::slice::from_raw_parts(label.as_ptr().cast::<u8>().add(offset), 12)
                };
                (bytes[..8] == [1, 1, 0, 0, 0, 0, 0, 16])
                    .then(|| u32::from_le_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]))
            })
    } else {
        None
    };
    let mut policy = 0_u32;
    let policy_ok = unsafe {
        GetTokenInformation(
            token,
            TokenMandatoryPolicy,
            (&mut policy as *mut u32).cast(),
            size_of_val(&policy) as u32,
            &mut returned,
        )
    } != 0;
    let policy_error = (!policy_ok).then(std::io::Error::last_os_error);
    json!({
        "integrity_query_ok": label_ok,
        "integrity_win32_error": label_error.and_then(|error| error.raw_os_error()),
        "integrity_rid": rid,
        "mandatory_query_ok": policy_ok,
        "mandatory_win32_error": policy_error.and_then(|error| error.raw_os_error()),
        "mandatory_policy": (policy_ok && returned == size_of_val(&policy) as u32).then_some(policy),
    })
}
