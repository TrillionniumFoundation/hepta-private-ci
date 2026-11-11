//! Ordinary delete controls run in an owned child without Backup/Restore privileges.
//! This module never changes the parent token or the elevated sandbox under test.

use crate::delete_permission_matrix::DeleteMatrix;
use crate::proc_thread_attr::ProcThreadAttributeList;
use crate::winutil::argv_to_command_line;
use crate::winutil::to_wide;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_utils_pty::JobObject;
use serde::Deserialize;
use serde::Serialize;
use std::collections::HashMap;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT;
use windows_sys::Win32::Foundation::LUID;
use windows_sys::Win32::Foundation::SetHandleInformation;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Security::AdjustTokenPrivileges;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::LookupPrivilegeValueW;
use windows_sys::Win32::Security::SE_PRIVILEGE_REMOVED;
use windows_sys::Win32::Security::TOKEN_ADJUST_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_PRIVILEGES;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_STATISTICS;
use windows_sys::Win32::Security::TokenPrivileges;
use windows_sys::Win32::Security::TokenStatistics;
use windows_sys::Win32::System::Threading::CREATE_SUSPENDED;
use windows_sys::Win32::System::Threading::CreateProcessW;
use windows_sys::Win32::System::Threading::EXTENDED_STARTUPINFO_PRESENT;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::PROCESS_INFORMATION;
use windows_sys::Win32::System::Threading::ResumeThread;
use windows_sys::Win32::System::Threading::STARTF_USESTDHANDLES;
use windows_sys::Win32::System::Threading::STARTUPINFOEXW;
use windows_sys::Win32::System::Threading::TerminateProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

const CHILD_CASE: &str = "delete_permission_control::ordinary_delete_control_child";
const RESULT_PREFIX: &str = "DELETE_CONTROL_RESULT=";
const MAX_BYTES: u64 = 64 * 1024;
type Privileges = Vec<((u32, i32), u32)>;
type NativeErrors = Vec<[Option<(std::io::ErrorKind, Option<i32>)>; 2]>;

#[derive(Serialize, Deserialize)]
enum Request {
    Native(Vec<[PathBuf; 2]>),
    Cmd {
        script: PathBuf,
        env: HashMap<String, String>,
    },
}

#[derive(Serialize, Deserialize)]
enum Reply {
    Native(Vec<[Option<(String, Option<i32>)>; 2]>),
    Cmd { code: Option<i32>, output: String },
}

fn process_token(process: HANDLE, access: u32) -> Result<OwnedHandle> {
    let mut raw = 0;
    // SAFETY: the process handle is retained, and raw receives a new owned handle.
    ensure!(
        unsafe { OpenProcessToken(process, access, &mut raw) } != 0,
        "OpenProcessToken: {}",
        std::io::Error::last_os_error()
    );
    Ok(unsafe { OwnedHandle::from_raw_handle(raw as _) })
}

fn token_id(token: &OwnedHandle) -> Result<(u32, i32)> {
    let mut statistics: TOKEN_STATISTICS = unsafe { std::mem::zeroed() };
    let mut returned = 0;
    // SAFETY: statistics is aligned and its exact writable size is supplied.
    ensure!(
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as HANDLE,
                TokenStatistics,
                (&mut statistics as *mut TOKEN_STATISTICS).cast(),
                std::mem::size_of::<TOKEN_STATISTICS>() as u32,
                &mut returned,
            )
        } != 0,
        "TokenStatistics: {}",
        std::io::Error::last_os_error()
    );
    ensure!(
        returned as usize == std::mem::size_of::<TOKEN_STATISTICS>(),
        "TokenStatistics size"
    );
    Ok((statistics.TokenId.LowPart, statistics.TokenId.HighPart))
}

fn privileges(token: &OwnedHandle) -> Result<Privileges> {
    let mut words = [0_u64; 2048];
    let capacity = std::mem::size_of_val(&words);
    let mut returned = 0;
    // SAFETY: the bounded, aligned buffer covers the full supplied capacity.
    ensure!(
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as HANDLE,
                TokenPrivileges,
                words.as_mut_ptr().cast(),
                capacity as u32,
                &mut returned,
            )
        } != 0,
        "TokenPrivileges: {}",
        std::io::Error::last_os_error()
    );
    let offset = std::mem::offset_of!(TOKEN_PRIVILEGES, Privileges);
    let stride = std::mem::size_of::<LUID_AND_ATTRIBUTES>();
    ensure!(
        (returned as usize) >= offset && returned as usize <= capacity,
        "TokenPrivileges size"
    );
    let count = unsafe { std::ptr::read_unaligned(words.as_ptr().cast::<u32>()) } as usize;
    ensure!(
        count <= (returned as usize - offset) / stride,
        "TokenPrivileges count"
    );
    let mut result = Vec::with_capacity(count);
    for index in 0..count {
        // SAFETY: each complete entry lies inside the validated returned buffer.
        let entry = unsafe {
            std::ptr::read_unaligned(
                words
                    .as_ptr()
                    .cast::<u8>()
                    .add(offset + index * stride)
                    .cast::<LUID_AND_ATTRIBUTES>(),
            )
        };
        result.push(((entry.Luid.LowPart, entry.Luid.HighPart), entry.Attributes));
    }
    result.sort_unstable();
    ensure!(
        result.windows(2).all(|pair| pair[0].0 != pair[1].0),
        "duplicate privilege LUID"
    );
    Ok(result)
}

fn removed_privileges() -> Result<[(u32, i32); 2]> {
    let mut result = [(0, 0); 2];
    for (index, name) in ["SeBackupPrivilege", "SeRestorePrivilege"]
        .iter()
        .enumerate()
    {
        let mut luid: LUID = unsafe { std::mem::zeroed() };
        // SAFETY: the fixed local name and the output LUID remain valid for the call.
        ensure!(
            unsafe { LookupPrivilegeValueW(std::ptr::null(), to_wide(name).as_ptr(), &mut luid) }
                != 0,
            "LookupPrivilegeValueW: {}",
            std::io::Error::last_os_error()
        );
        result[index] = (luid.LowPart, luid.HighPart);
    }
    Ok(result)
}

struct Child {
    process: OwnedHandle,
    thread: OwnedHandle,
    job: JobObject,
    reaped: bool,
    cleanup_attempted: bool,
}

impl Child {
    fn cleanup(&mut self) -> Result<()> {
        self.cleanup_attempted = true;
        let job_result = self.job.terminate();
        let fallback_error = if job_result.is_err() && !self.reaped {
            // SAFETY: this is the owned handle of the exact child created below.
            let killed = unsafe {
                TerminateProcess(self.process.as_raw_handle() as HANDLE, /*uexitcode*/ 1)
            };
            (killed == 0).then(std::io::Error::last_os_error)
        } else {
            None
        };
        // The failure-only cleanup uses the existing native termination grace.
        // It never extends the five-second execution or ten-second elevated budget.
        let wait_ms = if self.reaped {
            0
        } else {
            crate::RUNNER_TERMINATION_WAIT_MS
        };
        let waited =
            unsafe { WaitForSingleObject(self.process.as_raw_handle() as HANDLE, wait_ms) };
        self.reaped = waited == WAIT_OBJECT_0;
        ensure!(
            self.reaped,
            "control child cleanup remains unconfirmed: wait={waited}; job={job_result:?}; fallback={fallback_error:?}"
        );
        job_result.context("terminate the owned control process tree")
    }
}

impl Drop for Child {
    fn drop(&mut self) {
        if !self.cleanup_attempted
            && let Err(error) = self.cleanup()
        {
            eprintln!("delete control cleanup failed: {error:#}");
        }
    }
}

fn run(request: Request) -> Result<Reply> {
    let deadline = Instant::now() + Duration::from_millis(/*millis*/ 5_000);
    let encoded = serde_json::to_vec(&request)?;
    ensure!(
        encoded.len() as u64 <= MAX_BYTES,
        "control request exceeds bound"
    );
    let mut input = tempfile::tempfile()?;
    input.write_all(&encoded)?;
    input.rewind()?;
    let mut output = tempfile::tempfile()?;
    // Only these new test-owned handles become inheritable; never parent stdio.
    let handles = [
        input.as_raw_handle() as HANDLE,
        output.as_raw_handle() as HANDLE,
    ];
    for handle in handles {
        ensure!(
            unsafe { SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT) } != 0,
            "control handle inheritance: {}",
            std::io::Error::last_os_error()
        );
    }
    let parent = process_token(unsafe { GetCurrentProcess() }, TOKEN_QUERY)?;
    let parent_id = token_id(&parent)?;
    let parent_before = privileges(&parent)?;
    let removed = removed_privileges()?;
    let job = JobObject::create_without_breakaway()?;
    let mut attributes = ProcThreadAttributeList::new(/*attr_count*/ 2)?;
    attributes.set_job(job.as_raw_handle() as HANDLE)?;
    attributes.set_handle_list(handles.to_vec())?;
    let executable = std::env::current_exe()?;
    let argv = [
        executable
            .to_str()
            .context("control executable is not Unicode")?
            .to_owned(),
        "--exact".into(),
        CHILD_CASE.into(),
        "--ignored".into(),
        "--nocapture".into(),
        "--test-threads=1".into(),
    ];
    let mut command = to_wide(argv_to_command_line(&argv));
    let mut startup: STARTUPINFOEXW = unsafe { std::mem::zeroed() };
    startup.StartupInfo.cb = std::mem::size_of::<STARTUPINFOEXW>() as u32;
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = handles[0];
    startup.StartupInfo.hStdOutput = handles[1];
    startup.StartupInfo.hStdError = handles[1];
    startup.lpAttributeList = attributes.as_mut_ptr();
    let mut information: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: all buffers/attributes are owned through creation. The child is
    // atomically in our job and suspended before any test or cmd code can run.
    ensure!(
        unsafe {
            CreateProcessW(
                to_wide(&executable).as_ptr(),
                command.as_mut_ptr(),
                std::ptr::null(),
                std::ptr::null(),
                /*binherithandles*/ 1,
                CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT,
                std::ptr::null(),
                std::ptr::null(),
                &startup.StartupInfo,
                &mut information,
            )
        } != 0,
        "CreateProcessW control: {}",
        std::io::Error::last_os_error()
    );
    let mut child = Child {
        process: unsafe { OwnedHandle::from_raw_handle(information.hProcess as _) },
        thread: unsafe { OwnedHandle::from_raw_handle(information.hThread as _) },
        job,
        reaped: false,
        cleanup_attempted: false,
    };
    let execution = (|| -> Result<()> {
        let token = process_token(
            child.process.as_raw_handle() as HANDLE,
            TOKEN_QUERY | TOKEN_ADJUST_PRIVILEGES,
        )?;
        ensure!(
            token_id(&token)? != parent_id,
            "control must own a distinct primary token"
        );
        let before = privileges(&token)?;
        for (low, high) in removed {
            if !before.iter().any(|(id, _)| *id == (low, high)) {
                continue;
            }
            let change = TOKEN_PRIVILEGES {
                PrivilegeCount: 1,
                Privileges: [LUID_AND_ATTRIBUTES {
                    Luid: LUID {
                        LowPart: low,
                        HighPart: high,
                    },
                    Attributes: SE_PRIVILEGE_REMOVED,
                }],
            };
            // SAFETY: only this distinct, suspended child's token can be adjusted.
            let changed = unsafe {
                AdjustTokenPrivileges(
                    token.as_raw_handle() as HANDLE,
                    /*disableallprivileges*/ 0,
                    &change,
                    /*bufferlength*/ 0,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                )
            };
            let error = unsafe { GetLastError() };
            // ERROR_NOT_ALL_ASSIGNED is a failure, even when the API returns true.
            ensure!(
                changed != 0 && error == ERROR_SUCCESS,
                "remove control privilege: errno={error}"
            );
        }
        let expected: Privileges = before
            .into_iter()
            .filter(|(id, _)| !removed.contains(id))
            .collect();
        ensure!(
            privileges(&token)? == expected,
            "child privilege removal changed another privilege or left Backup/Restore"
        );
        ensure!(
            privileges(&parent)? == parent_before,
            "parent privileges changed before control resume"
        );
        eprintln!(
            "delete_control verified_before_resume distinct_token=true backup_present=false restore_present=false other_privileges_unchanged=true"
        );
        ensure!(
            Instant::now() < deadline,
            "control setup exhausted the original 5s budget"
        );
        let previous = unsafe { ResumeThread(child.thread.as_raw_handle() as HANDLE) };
        ensure!(previous == 1, "control ResumeThread returned {previous}");
        let wait_ms = deadline
            .saturating_duration_since(Instant::now())
            .as_millis() as u32;
        let waited =
            unsafe { WaitForSingleObject(child.process.as_raw_handle() as HANDLE, wait_ms) };
        ensure!(
            waited == WAIT_OBJECT_0,
            "ordinary control did not finish within original 5s: wait={waited}"
        );
        child.reaped = true;
        let mut code = 0;
        ensure!(
            unsafe { GetExitCodeProcess(child.process.as_raw_handle() as HANDLE, &mut code) } != 0,
            "control exit query: {}",
            std::io::Error::last_os_error()
        );
        ensure!(code == 0, "ordinary control libtest exited {code}");
        Ok(())
    })();
    let cleanup = child.cleanup();
    let parent_after = privileges(&parent);
    ensure!(
        cleanup.is_ok(),
        "ordinary control cleanup failed: {cleanup:?}; execution={execution:?}; parent_snapshot_available={}",
        parent_after.is_ok()
    );
    ensure!(
        parent_after? == parent_before,
        "parent privileges changed after control"
    );
    output.rewind()?;
    let mut bytes = Vec::new();
    output.take(MAX_BYTES + 1).read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() as u64 <= MAX_BYTES,
        "control output exceeds bound"
    );
    let output = String::from_utf8(bytes)?;
    execution.with_context(|| format!("ordinary control output: {output}"))?;
    let results: Vec<_> = output
        .lines()
        .filter_map(|line| line.strip_prefix(RESULT_PREFIX))
        .collect();
    ensure!(
        results.len() == 1,
        "expected exactly one completed control result: {output}"
    );
    serde_json::from_str(results[0]).context("decode the completed control result")
}

pub(crate) fn native(matrix: &DeleteMatrix) -> Result<NativeErrors> {
    let request = matrix
        .paths()
        .map(|(file, directory)| [file.to_path_buf(), directory.to_path_buf()])
        .collect();
    let Reply::Native(errors) = run(Request::Native(request))? else {
        anyhow::bail!("wrong native control result");
    };
    errors
        .into_iter()
        .map(|pair| {
            let mut decoded = [None; 2];
            for (index, error) in pair.into_iter().enumerate() {
                if let Some((kind, raw)) = error {
                    let code = raw.context("native control error has no Win32 code")?;
                    let actual = std::io::Error::from_raw_os_error(code).kind();
                    ensure!(
                        format!("{actual:?}") == kind,
                        "native control error kind/code mismatch"
                    );
                    decoded[index] = Some((actual, raw));
                }
            }
            Ok(decoded)
        })
        .collect()
}

pub(crate) fn cmd(script: &Path, env: HashMap<String, String>) -> Result<(Option<i32>, String)> {
    let Reply::Cmd { code, output } = run(Request::Cmd {
        script: script.to_path_buf(),
        env,
    })?
    else {
        anyhow::bail!("wrong cmd control result");
    };
    Ok((code, output))
}

#[test]
#[ignore = "private subprocess entry; the two parent matrix cases supply its owned input"]
fn ordinary_delete_control_child() -> Result<()> {
    let token = process_token(unsafe { GetCurrentProcess() }, TOKEN_QUERY)?;
    let removed = removed_privileges()?;
    ensure!(
        privileges(&token)?
            .iter()
            .all(|(id, _)| !removed.contains(id)),
        "control child still has Backup/Restore"
    );
    let mut bytes = Vec::new();
    std::io::stdin()
        .lock()
        .take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() as u64 <= MAX_BYTES,
        "control request exceeds bound"
    );
    let reply = match serde_json::from_slice::<Request>(&bytes)? {
        Request::Native(paths) => {
            ensure!(paths.len() == 4, "native control requires all four cells");
            let errors = paths
                .into_iter()
                .map(|[file, directory]| {
                    [std::fs::remove_file(file), std::fs::remove_dir(directory)].map(|result| {
                        result
                            .err()
                            .map(|error| (format!("{:?}", error.kind()), error.raw_os_error()))
                    })
                })
                .collect();
            Reply::Native(errors)
        }
        Request::Cmd { script, env } => {
            let mut log = tempfile::tempfile()?;
            let status = std::process::Command::new("C:\\Windows\\System32\\cmd.exe")
                .args(["/d", "/c"])
                .arg(script)
                .envs(env)
                .stdout(log.try_clone()?)
                .stderr(log.try_clone()?)
                .status()?;
            log.rewind()?;
            let mut output = String::new();
            log.take(MAX_BYTES + 1).read_to_string(&mut output)?;
            ensure!(output.len() as u64 <= MAX_BYTES, "cmd output exceeds bound");
            Reply::Cmd {
                code: status.code(),
                output,
            }
        }
    };
    println!("\n{RESULT_PREFIX}{}", serde_json::to_string(&reply)?);
    Ok(())
}
