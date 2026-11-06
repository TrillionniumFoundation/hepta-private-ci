//! Identity-preserving, nonprivileged ACL controls for the existing deletion tests.
//! This private test module does not qualify or alter the production sandbox token.
//! Native helpers are mechanically reused from the completed v3 observation.

use crate::proc_thread_attr::ProcThreadAttributeList;
use crate::process::make_env_block;
use crate::token::get_current_token_for_restriction;
use crate::winutil::argv_to_command_line;
use crate::winutil::to_wide;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_utils_pty::JobObject;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::ExitStatusExt;
use std::path::Path;
use std::process::ExitStatus;
use windows_sys::Win32::Foundation as win;
use windows_sys::Win32::Security as security;
use windows_sys::Win32::Storage::FileSystem as fswin;
use windows_sys::Win32::System::JobObjects as jobs;
use windows_sys::Win32::System::Pipes::CreatePipe;
use windows_sys::Win32::System::Threading as threading;
use windows_sys::Win32::Foundation::HANDLE;

fn observe(detail: std::fmt::Arguments<'_>) -> std::io::Result<()> {
    writeln!(std::io::stderr().lock(), "\nACL_CONTROL {detail}")
}

struct Handle(win::HANDLE);

impl Drop for Handle {
    fn drop(&mut self) {
        // SAFETY: this guard owns a successful native handle result.
        unsafe { win::CloseHandle(self.0) };
    }
}

#[derive(Debug, PartialEq, Eq, Serialize)]
struct TokenState { integrity_rid: u32, integrity_attributes: u32, mandatory_policy: u32 }

fn token_state(token: HANDLE) -> Result<TokenState> {
    let mut buffer = [0_u64; 128];
    let mut returned = 0;
    // SAFETY: this aligned buffer is bounded and owns the complete returned label and SID.
    ensure!(unsafe { security::GetTokenInformation(token, security::TokenIntegrityLevel,
        buffer.as_mut_ptr().cast(), std::mem::size_of_val(&buffer) as u32, &mut returned) } != 0,
        "TokenIntegrityLevel: {}", std::io::Error::last_os_error());
    ensure!(returned as usize >= std::mem::size_of::<security::TOKEN_MANDATORY_LABEL>()
        && returned as usize <= std::mem::size_of_val(&buffer), "invalid native label size");
    let label = unsafe { &*buffer.as_ptr().cast::<security::TOKEN_MANDATORY_LABEL>() };
    // SAFETY: Windows returned this SID in the live buffer; validate before reading its RID.
    ensure!(unsafe { security::IsValidSid(label.Label.Sid) } != 0
        && unsafe { *security::GetSidSubAuthorityCount(label.Label.Sid) } == 1,
        "invalid native integrity SID");
    ensure!(unsafe { (*security::GetSidIdentifierAuthority(label.Label.Sid)).Value } == [0, 0, 0, 0, 0, 16],
        "unexpected native integrity SID authority");
    let integrity_rid = unsafe { *security::GetSidSubAuthority(label.Label.Sid, /*nsubauthority*/ 0) };
    let mut policy = security::TOKEN_MANDATORY_POLICY { Policy: 0 };
    ensure!(unsafe { security::GetTokenInformation(token, security::TokenMandatoryPolicy,
        (&mut policy as *mut security::TOKEN_MANDATORY_POLICY).cast(),
        std::mem::size_of_val(&policy) as u32, &mut returned) } != 0,
        "TokenMandatoryPolicy: {}", std::io::Error::last_os_error());
    ensure!(returned as usize == std::mem::size_of_val(&policy), "invalid native policy size");
    Ok(TokenState { integrity_rid, integrity_attributes: label.Label.Attributes, mandatory_policy: policy.Policy })
}

// A bounded, aligned native result. An unexpectedly larger token is a failed
// observation precondition, never a reason to omit groups or privileges.
struct TokenBuffer {
    words: Vec<usize>,
    used: usize,
}

impl TokenBuffer {
    fn query(token: win::HANDLE, class: security::TOKEN_INFORMATION_CLASS) -> Result<Self> {
        let mut words = vec![0_usize; 65_536 / std::mem::size_of::<usize>()];
        let mut returned = 0;
        // SAFETY: the aligned allocation is live and its exact extent is supplied.
        ensure!(unsafe { security::GetTokenInformation(token, class, words.as_mut_ptr().cast(),
            /*tokeninformationlength*/ 65_536, &mut returned) } != 0, "token information {class}: {}", std::io::Error::last_os_error());
        ensure!(returned > 0 && returned <= 65_536, "invalid token result extent");
        Ok(Self { words, used: returned as usize })
    }

    fn read<T: Copy>(&self, offset: usize) -> Result<T> {
        ensure!(offset.checked_add(std::mem::size_of::<T>()).is_some_and(|end| end <= self.used),
            "native token member outside result");
        // SAFETY: the full member lies within the initialized native result.
        Ok(unsafe { self.words.as_ptr().cast::<u8>().add(offset).cast::<T>().read_unaligned() })
    }

    fn sid(&self, sid: win::PSID) -> Result<Vec<u8>> {
        let start = self.words.as_ptr() as usize;
        let offset = (sid as usize).checked_sub(start).ok_or_else(|| anyhow::anyhow!("SID before result"))?;
        let header: [u8; 8] = self.read(offset)?;
        let length = 8 + usize::from(header[1]) * 4;
        ensure!(offset.checked_add(length).is_some_and(|end| end <= self.used), "SID outside result");
        // SAFETY: both the complete SID header and its stated subauthorities are bounded.
        ensure!(unsafe { security::IsValidSid(sid) } != 0, "invalid native SID");
        Ok(unsafe { std::slice::from_raw_parts(sid.cast::<u8>(), length) }.to_vec())
    }

    fn groups(&self) -> Result<Vec<(Vec<u8>, u32)>> {
        let count: u32 = self.read(/*offset*/ 0)?;
        if count == 0 {
            return Ok(Vec::new());
        }
        let offset = std::mem::offset_of!(security::TOKEN_GROUPS, Groups);
        let width = std::mem::size_of::<security::SID_AND_ATTRIBUTES>();
        ensure!((count as usize).checked_mul(width).and_then(|n| offset.checked_add(n))
            .is_some_and(|end| end <= self.used), "native group array outside result");
        let mut groups = Vec::new();
        for index in 0..count as usize {
            let entry: security::SID_AND_ATTRIBUTES = self.read(offset + index * width)?;
            groups.push((self.sid(entry.Sid)?, entry.Attributes));
        }
        groups.sort();
        Ok(groups)
    }
}

fn token_record(token: win::HANDLE) -> Result<Value> {
    let user = TokenBuffer::query(token, security::TokenUser)?;
    let entry: security::SID_AND_ATTRIBUTES = user.read(/*offset*/ 0)?;
    let groups = TokenBuffer::query(token, security::TokenGroups)?.groups()?;
    let restricted = TokenBuffer::query(token, security::TokenRestrictedSids)?.groups()?;
    let privileges = TokenBuffer::query(token, security::TokenPrivileges)?;
    let count: u32 = privileges.read(/*offset*/ 0)?;
    let offset = std::mem::offset_of!(security::TOKEN_PRIVILEGES, Privileges);
    let width = std::mem::size_of::<security::LUID_AND_ATTRIBUTES>();
    ensure!((count as usize).checked_mul(width).and_then(|n| offset.checked_add(n))
        .is_some_and(|end| end <= privileges.used), "native privilege array outside result");
    let mut records = Vec::new();
    for index in 0..count as usize {
        let privilege: security::LUID_AND_ATTRIBUTES = privileges.read(offset + index * width)?;
        let mut name = [0_u16; 256];
        let mut length = name.len() as u32;
        // SAFETY: the copied LUID and bounded writable name buffer are live.
        ensure!(unsafe { security::LookupPrivilegeNameW(std::ptr::null(), &privilege.Luid,
            name.as_mut_ptr(), &mut length) } != 0, "LookupPrivilegeNameW: {}", std::io::Error::last_os_error());
        ensure!(length as usize <= name.len(), "native privilege name outside result");
        records.push((privilege.Luid.HighPart, privilege.Luid.LowPart, privilege.Attributes,
            String::from_utf16(&name[..length as usize])?));
    }
    records.sort();
    let token_type = TokenBuffer::query(token, security::TokenType)?.read::<i32>(/*offset*/ 0)?;
    ensure!(matches!(token_type, security::TokenPrimary | security::TokenImpersonation),
        "unexpected native token type");
    let impersonation_level = if token_type == security::TokenImpersonation {
        Some(TokenBuffer::query(token, security::TokenImpersonationLevel)?.read::<i32>(/*offset*/ 0)?)
    } else {
        None
    };
    Ok(json!({"identity": {"user": (user.sid(entry.Sid)?, entry.Attributes),
        "groups": groups, "restricted_sids": restricted, "integrity_and_policy": token_state(token)?,
        "session": TokenBuffer::query(token, security::TokenSessionId)?.read::<u32>(/*offset*/ 0)?,
        "app_container": TokenBuffer::query(token, security::TokenIsAppContainer)?.read::<u32>(/*offset*/ 0)?},
        "token_type": token_type, "impersonation_level": impersonation_level,
        "privileges": records.iter().map(|(high, low, attributes, name)| json!({
            "luid_high": high, "luid_low": low, "attributes": attributes, "name": name,
            "enabled": attributes & security::SE_PRIVILEGE_ENABLED != 0})).collect::<Vec<_>>()}))
}

fn effective_record() -> Result<(Value, bool)> {
    let mut token = 0;
    // SAFETY: this queries only this synchronous test thread, without changing it.
    let is_thread = unsafe { threading::OpenThreadToken(threading::GetCurrentThread(),
        security::TOKEN_QUERY, /*openasself*/ 1, &mut token) } != 0;
    if !is_thread {
        ensure!(unsafe { win::GetLastError() } == win::ERROR_NO_TOKEN,
            "OpenThreadToken: {}", std::io::Error::last_os_error());
        ensure!(unsafe { threading::OpenProcessToken(threading::GetCurrentProcess(),
            security::TOKEN_QUERY, &mut token) } != 0, "OpenProcessToken: {}", std::io::Error::last_os_error());
    }
    let token = Handle(token);
    Ok((token_record(token.0)?, is_thread))
}

struct OwnedChild {
    job: JobObject,
    process: Handle,
    _thread: Handle,
    cleaned: bool,
}

impl Drop for OwnedChild {
    fn drop(&mut self) {
        if !self.cleaned {
            let terminated = self.job.terminate();
            // SAFETY: this is the original owned process handle, never a PID lookup.
            let wait = unsafe { threading::WaitForSingleObject(self.process.0, /*dwmilliseconds*/ 5_000) };
            let _ = observe(format_args!("neither_privileges unwind_cleanup terminate={terminated:?} wait={wait}"));
        }
    }
}

fn spawn_observation_child(
    token: win::HANDLE,
    argv: &[String],
    cwd: &Path,
    env: &HashMap<String, String>,
    input: &Handle,
    output: &fs::File,
) -> Result<OwnedChild> {
    // These ordinary and privilege-only subjects deliberately have no restricting
    // SIDs. The production LaunchDesktop contract remains sandbox-only. Reuse its
    // process assembly helpers here without changing that production precondition.
    let job = JobObject::create().context("create observation process job")?;
    let mut attrs = ProcThreadAttributeList::new(2)?;
    attrs.set_job(job.as_raw_handle() as win::HANDLE)?;
    let inherited_handles = vec![input.0, output.as_raw_handle() as win::HANDLE];
    for &handle in &inherited_handles {
        // SAFETY: both handles are borrowed from live owned guards; only this
        // private input reader and output file become inheritable, never the writer.
        ensure!(unsafe {
            win::SetHandleInformation(handle, win::HANDLE_FLAG_INHERIT, win::HANDLE_FLAG_INHERIT)
        } != 0, "observation stdio inheritance: {}", std::io::Error::last_os_error());
    }
    attrs.set_handle_list(inherited_handles)?;

    let mut command_line = to_wide(argv_to_command_line(argv));
    let environment = make_env_block(env);
    let directory = to_wide(cwd);
    let mut desktop = to_wide(r"Winsta0\Default");
    // SAFETY: these Windows records permit zero initialization before fields are set.
    let mut startup: threading::STARTUPINFOEXW = unsafe { std::mem::zeroed() };
    startup.StartupInfo.cb = std::mem::size_of::<threading::STARTUPINFOEXW>() as u32;
    startup.StartupInfo.lpDesktop = desktop.as_mut_ptr();
    startup.StartupInfo.dwFlags = threading::STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = input.0;
    startup.StartupInfo.hStdOutput = output.as_raw_handle() as win::HANDLE;
    startup.StartupInfo.hStdError = output.as_raw_handle() as win::HANDLE;
    startup.lpAttributeList = attrs.as_mut_ptr();
    let creation_flags = threading::CREATE_UNICODE_ENVIRONMENT
        | threading::EXTENDED_STARTUPINFO_PRESENT
        | threading::CREATE_NO_WINDOW;
    let mut process_info: threading::PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: the owned primary token, both stdio guards, job, attribute buffers,
    // mutable command line, desktop, environment and cwd all outlive this call.
    // Job assignment and the handle whitelist are part of creation, with no fallback.
    let created = unsafe {
        threading::CreateProcessAsUserW(
            token,
            std::ptr::null(),
            command_line.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            /*binherithandles*/ 1,
            creation_flags,
            environment.as_ptr().cast(),
            directory.as_ptr(),
            &startup.StartupInfo,
            &mut process_info,
        )
    };
    if created == 0 {
        // Capture the initial native failure before any cleanup can change it.
        let error = std::io::Error::last_os_error();
        return Err(error).context("owned observation CreateProcessAsUserW");
    }
    // No fallible work separates successful creation from owning both returned
    // handles and the Job. Every later error therefore reaches OwnedChild::drop.
    Ok(OwnedChild {
        job,
        process: Handle(process_info.hProcess),
        _thread: Handle(process_info.hThread),
        cleaned: false,
    })
}

/// Only the enabled privilege set differs from the original ordinary identity.
pub(crate) struct AclControl {
    token: Handle,
    original: Value,
    expected: Value,
}

impl AclControl {
    pub(crate) fn new() -> Result<Self> {
        let base = Handle(unsafe { get_current_token_for_restriction()? });
        let original = token_record(base.0)?;
        ensure!(effective_record()? == (original.clone(), false)
            && original["token_type"] == security::TokenPrimary,
            "ACL control must begin with the ordinary process token");
        let mut stripped = 0;
        // SAFETY: derive an owned token only. Do not filter SIDs, change integrity,
        // add capabilities, LUA_TOKEN/WRITE_RESTRICTED, or adjust the host token.
        ensure!(unsafe { security::CreateRestrictedToken(base.0, security::DISABLE_MAX_PRIVILEGE,
            /*disablesidcount*/ 0, std::ptr::null(), /*deleteprivilegecount*/ 0, std::ptr::null(),
            /*restrictedsidcount*/ 0, std::ptr::null(), &mut stripped) } != 0,
            "derive nonprivileged ACL control: {}", std::io::Error::last_os_error());
        let token = Handle(stripped);
        let expected = token_record(token.0)?;
        observe(format_args!("subjects {}", json!({"ordinary": original, "nonprivileged_acl": expected})))?;
        ensure!(original["identity"] == expected["identity"]
            && expected["identity"]["restricted_sids"] == json!([])
            && expected["token_type"] == security::TokenPrimary,
            "ACL control changed identity or has restricting SIDs");
        ensure!(expected["privileges"].as_array().is_some_and(|records| records.iter().all(|record|
            record["enabled"] == false || record["name"] == "SeChangeNotifyPrivilege")),
            "ACL control retained another enabled privilege");
        Ok(Self { token, original, expected })
    }

    pub(crate) fn ensure_restored(&self) -> Result<()> {
        ensure!(effective_record()? == (self.original.clone(), false),
            "ordinary effective token changed after ACL control");
        Ok(())
    }

    pub(crate) fn impersonate(&self) -> Result<ImpersonatedAclControl<'_>> {
        self.ensure_restored()?;
        // SAFETY: the returned guard borrows this live owned token until revert.
        ensure!(unsafe { security::ImpersonateLoggedOnUser(self.token.0) } != 0,
            "ACL control impersonation: {}", std::io::Error::last_os_error());
        let guard = ImpersonatedAclControl { _control: self };
        let (actual, is_thread) = effective_record()?;
        observe(format_args!("rust_before {}", json!({"token": actual, "is_thread": is_thread})))?;
        ensure!(is_thread && actual["identity"] == self.expected["identity"]
            && actual["privileges"] == self.expected["privileges"]
            && actual["token_type"] == security::TokenImpersonation
            && actual["impersonation_level"] == security::SecurityImpersonation,
            "effective ACL control token differs");
        Ok(guard)
    }

    pub(crate) fn run_cmd(&self, script_path: &Path,
        overrides: &HashMap<String, String>, output_path: &Path) -> Result<ExitStatus> {
        self.ensure_restored()?;
        // Execute all original matrix bytes after a fail-closed private input gate.
        // Keep the original file intact and preserve Command's inherited cwd/env.
        let gated_path = script_path.with_extension("acl-control.cmd");
        let mut script = concat!("@echo off\r\n",
            "setlocal EnableExtensions DisableDelayedExpansion\r\n",
            "set \"B11_RELEASE=\"\r\n", "set /p B11_RELEASE=\r\n",
            "if not \"%B11_RELEASE%\"==\"release-owned-fixture\" exit /b 87\r\n",
            "echo ACL_CONTROL_INPUT_RELEASED\r\n", "endlocal\r\n").as_bytes().to_vec();
        script.extend(fs::read(script_path)?);
        fs::OpenOptions::new().create_new(true).write(true).open(&gated_path)?.write_all(&script)?;
        let cwd = std::env::current_dir()?;
        let mut env: HashMap<String, String> = std::env::vars().collect();
        for (name, value) in overrides {
            // std::process::Command treats Windows environment keys without case.
            env.retain(|existing, _| !existing.eq_ignore_ascii_case(name));
            env.insert(name.clone(), value.clone());
        }
        env.retain(|name, _| !name.eq_ignore_ascii_case("B11_RELEASE"));
        let output = fs::OpenOptions::new().create_new(true).read(true).write(true).open(output_path)?;
        let (mut input, mut release) = (0, 0);
        // SAFETY: own both pipe handles immediately after successful creation.
        ensure!(unsafe { CreatePipe(&mut input, &mut release, std::ptr::null(), /*nsize*/ 0) } != 0,
            "ACL control pipe: {}", std::io::Error::last_os_error());
        let input = Handle(input);
        let release = Handle(release);
        let mut release_flags = 0;
        ensure!(unsafe { win::GetHandleInformation(release.0, &mut release_flags) } != 0
            && release_flags & win::HANDLE_FLAG_INHERIT == 0, "release writer must not be inherited");
        let command = vec![r"C:\Windows\System32\cmd.exe".to_owned(), "/d".to_owned(),
            "/c".to_owned(), gated_path.to_string_lossy().into_owned()];
        let mut child = spawn_observation_child(self.token.0, &command, &cwd, &env, &input, &output)?;
        drop(input);
        let work = (|| -> Result<u32> {
            let mut actual_token = 0;
            // SAFETY: query the actual child while its stdin release is withheld.
            ensure!(unsafe { threading::OpenProcessToken(child.process.0, security::TOKEN_QUERY,
                &mut actual_token) } != 0, "ACL child token: {}", std::io::Error::last_os_error());
            let actual_token = Handle(actual_token);
            let actual = token_record(actual_token.0)?;
            observe(format_args!("child_before_release {}", json!({"token": actual})))?;
            ensure!(actual["identity"] == self.expected["identity"]
                && actual["privileges"] == self.expected["privileges"]
                && actual["token_type"] == security::TokenPrimary,
                "actual ACL child token differs before release");
            let bytes = b"release-owned-fixture\r\n";
            let mut written = 0;
            ensure!(unsafe { fswin::WriteFile(release.0, bytes.as_ptr(), bytes.len() as u32,
                &mut written, std::ptr::null_mut()) } != 0 && written as usize == bytes.len(),
                "release ACL child: {}", std::io::Error::last_os_error());
            // Preserve the actual d851 preimage's existing five-second work budget.
            let wait = unsafe { threading::WaitForSingleObject(child.process.0, /*dwmilliseconds*/ 5_000) };
            let wait_error = (wait == win::WAIT_FAILED).then(std::io::Error::last_os_error);
            ensure!(wait == win::WAIT_OBJECT_0, "ACL child did not finish: wait={wait}, error={wait_error:?}");
            let mut exit = 0;
            ensure!(unsafe { threading::GetExitCodeProcess(child.process.0, &mut exit) } != 0,
                "ACL child exit: {}", std::io::Error::last_os_error());
            Ok(exit)
        })();
        drop(release);
        // As in v3, finish this owned Job on every work Result before physical checks.
        let terminated = child.job.terminate();
        let cleanup_wait = unsafe { threading::WaitForSingleObject(child.process.0, /*dwmilliseconds*/ 5_000) };
        let mut accounting: jobs::JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { std::mem::zeroed() };
        let accounted = unsafe { jobs::QueryInformationJobObject(child.job.as_raw_handle() as win::HANDLE,
            jobs::JobObjectBasicAccountingInformation, (&mut accounting as *mut jobs::JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
            std::mem::size_of_val(&accounting) as u32, std::ptr::null_mut()) };
        drop(output);
        let raw = fs::read(output_path)?;
        observe(format_args!("child_finished {}", json!({"work_error": work.as_ref().err().map(|error| format!("{error:#}")),
            "exit": work.as_ref().ok(), "cleanup_wait": cleanup_wait,
            "terminate_error": terminated.as_ref().err().map(ToString::to_string),
            "accounted": accounted, "active_processes": accounting.ActiveProcesses,
            "stdout_stderr_bytes": raw, "stdout_stderr": String::from_utf8_lossy(&raw)})))?;
        terminated?;
        ensure!(cleanup_wait == win::WAIT_OBJECT_0 && accounted != 0 && accounting.ActiveProcesses == 0,
            "ACL child Job did not finish");
        child.cleaned = true;
        self.ensure_restored()?;
        let exit = work?;
        ensure!(String::from_utf8_lossy(&raw).lines().filter(|line| *line == "ACL_CONTROL_INPUT_RELEASED").count() == 1,
            "ACL child input gate was not released exactly once");
        Ok(ExitStatus::from_raw(exit))
    }
}

pub(crate) struct ImpersonatedAclControl<'a> {
    _control: &'a AclControl,
}

impl Drop for ImpersonatedAclControl<'_> {
    fn drop(&mut self) {
        // SAFETY: this synchronous guard never outlives or yields beyond its scope.
        if unsafe { security::RevertToSelf() } == 0 {
            std::process::abort();
        }
    }
}
