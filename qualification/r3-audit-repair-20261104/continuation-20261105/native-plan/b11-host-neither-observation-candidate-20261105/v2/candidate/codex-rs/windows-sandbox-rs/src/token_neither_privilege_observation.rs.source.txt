//! Owned-object observations only; no expected denial or sandbox qualification.

use super::Impersonation;
use super::support::Handle;
use super::support::observe;
use super::token_state;
use crate::delete_permission_matrix::DeleteMatrix;
use crate::delete_permission_matrix::DeleteOutcome;
use crate::delete_permission_matrix::DeleteRoute;
use crate::process::ConsoleMode;
use crate::process::CreatedProcess;
use crate::process::create_process_as_user;
use crate::token::get_current_token_for_restriction;
use anyhow::Result;
use anyhow::ensure;
use serde_json::Value;
use serde_json::json;
use std::collections::HashMap;
use std::fs;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use windows_sys::Win32::Foundation as win;
use windows_sys::Win32::Security as security;
use windows_sys::Win32::Storage::FileSystem as fswin;
use windows_sys::Win32::System::JobObjects as jobs;
use windows_sys::Win32::System::Pipes::CreatePipe;
use windows_sys::Win32::System::Threading as threading;

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

fn physical(outcomes: &[DeleteOutcome]) -> Vec<Value> {
    outcomes.iter().map(|outcome| json!({"route": format!("{:?}", outcome.route),
        "file_deleted": outcome.file_deleted, "directory_deleted": outcome.directory_deleted})).collect()
}

struct OwnedChild {
    created: CreatedProcess,
    process: Handle,
    _thread: Handle,
    cleaned: bool,
}

impl Drop for OwnedChild {
    fn drop(&mut self) {
        if !self.cleaned {
            let terminated = self.created.job.terminate();
            // SAFETY: this is the original owned process handle, never a PID lookup.
            let wait = unsafe { threading::WaitForSingleObject(self.process.0, /*dwmilliseconds*/ 5_000) };
            let _ = observe(format_args!("neither_privileges unwind_cleanup terminate={terminated:?} wait={wait}"));
        }
    }
}

fn cmd_observation(root: &Path, subject: &str, token: win::HANDLE,
    expected: &Value, matrix: DeleteMatrix) -> Result<()> {
    let script_path = root.join(format!("{subject}.cmd"));
    let output_path = root.join(format!("{subject}.output"));
    // The private pipe stays open until the actual child primary token is read.
    // No deletion can pass this gate on EOF or an unexpected input value.
    let mut script = concat!("@echo off\r\n", "set \"B11_RELEASE=\"\r\n", "set /p B11_RELEASE=\r\n",
        "if not \"%B11_RELEASE%\"==\"release-owned-fixture\" exit /b 87\r\n",
        "echo NEITHER_INPUT_RELEASED\r\n").to_owned();
    let mut env: HashMap<String, String> = std::env::vars().collect();
    env.retain(|name, _| {
        !name.eq_ignore_ascii_case("ERRORLEVEL")
            && !name.eq_ignore_ascii_case("B11_RELEASE")
            && !(0..4).any(|index| {
                name.eq_ignore_ascii_case(&format!("MATRIX_FILE_{index}"))
                    || name.eq_ignore_ascii_case(&format!("MATRIX_DIR_{index}"))
            })
    });
    for (index, (file, directory)) in matrix.paths().enumerate() {
        env.insert(format!("MATRIX_FILE_{index}"), file.to_string_lossy().into_owned());
        env.insert(format!("MATRIX_DIR_{index}"), directory.to_string_lossy().into_owned());
        script.push_str(&format!("echo MATRIX_ATTEMPT_{index}\r\ndel /f /q \"%MATRIX_FILE_{index}%\"\r\n\
            echo FILE_RC_{index}=%ERRORLEVEL%\r\nrmdir \"%MATRIX_DIR_{index}%\"\r\necho DIR_RC_{index}=%ERRORLEVEL%\r\n"));
    }
    script.push_str("echo MATRIX_DONE\r\nexit /b 0\r\n");
    fs::write(&script_path, script)?;
    let output = fs::OpenOptions::new().create_new(true).read(true).write(true).open(&output_path)?;
    let (mut input, mut release) = (0, 0);
    // SAFETY: both outputs become owned guards immediately after successful creation.
    ensure!(unsafe { CreatePipe(&mut input, &mut release, std::ptr::null(), /*nsize*/ 0) } != 0,
        "CreatePipe: {}", std::io::Error::last_os_error());
    let input = Handle(input);
    let release = Handle(release);
    let mut release_flags = 0;
    ensure!(unsafe { win::GetHandleInformation(release.0, &mut release_flags) } != 0
        && release_flags & win::HANDLE_FLAG_INHERIT == 0, "release writer must not be inherited");
    let command = vec![r"C:\Windows\System32\cmd.exe".to_owned(), "/d".to_owned(),
        "/e:on".to_owned(), "/v:off".to_owned(), "/c".to_owned(), script_path.to_string_lossy().into_owned()];
    // The existing backend assigns its real Job at creation and inherits only
    // the declared stdio handles. The parent's release writer is not inherited.
    let created = unsafe { create_process_as_user(token, &command, root, &env, /*logs_base_dir*/ None,
        Some((input.0, output.as_raw_handle() as win::HANDLE, output.as_raw_handle() as win::HANDLE)),
        ConsoleMode::NoWindow, /*use_private_desktop*/ false) }?;
    let mut child = OwnedChild { process: Handle(created.process_info.hProcess),
        _thread: Handle(created.process_info.hThread), created, cleaned: false };
    drop(input);
    let work = (|| -> Result<(Value, u32)> {
        let mut actual_token = 0;
        // SAFETY: query the actual process handle while its input gate is closed.
        ensure!(unsafe { threading::OpenProcessToken(child.process.0, security::TOKEN_QUERY,
            &mut actual_token) } != 0, "child OpenProcessToken: {}", std::io::Error::last_os_error());
        let actual_token = Handle(actual_token);
        let actual = token_record(actual_token.0)?;
        observe(format_args!("neither_privileges child_before_release {}", json!({"subject": subject, "token": actual})))?;
        ensure!(actual["identity"] == expected["identity"] && actual["privileges"] == expected["privileges"]
            && actual["token_type"] == security::TokenPrimary, "child token differs before release");
        let bytes = b"release-owned-fixture\r\n";
        let mut written = 0;
        ensure!(unsafe { fswin::WriteFile(release.0, bytes.as_ptr(), bytes.len() as u32,
            &mut written, std::ptr::null_mut()) } != 0 && written as usize == bytes.len(),
            "release owned cmd input: {}", std::io::Error::last_os_error());
        let wait = unsafe { threading::WaitForSingleObject(child.process.0, /*dwmilliseconds*/ 5_000) };
        let wait_error = (wait == win::WAIT_FAILED).then(std::io::Error::last_os_error);
        let mut exit = 0;
        ensure!(wait == win::WAIT_OBJECT_0, "owned cmd did not finish: wait={wait}, error={wait_error:?}");
        ensure!(unsafe { threading::GetExitCodeProcess(child.process.0, &mut exit) } != 0,
            "owned cmd exit code: {}", std::io::Error::last_os_error());
        Ok((actual, exit))
    })();
    drop(release);
    // Always finish the owned Job before reading physical outcomes or removing fixtures.
    let terminated = child.created.job.terminate();
    let cleanup_wait = unsafe { threading::WaitForSingleObject(child.process.0, /*dwmilliseconds*/ 5_000) };
    let mut accounting: jobs::JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { std::mem::zeroed() };
    let accounted = unsafe { jobs::QueryInformationJobObject(child.created.job.as_raw_handle() as win::HANDLE,
        jobs::JobObjectBasicAccountingInformation, (&mut accounting as *mut jobs::JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
        std::mem::size_of_val(&accounting) as u32, std::ptr::null_mut()) };
    drop(output);
    let raw = fs::read(&output_path)?;
    observe(format_args!("neither_privileges child_finished {}", json!({"subject": subject,
        "work_error": work.as_ref().err().map(|error| format!("{error:#}")),
        "exit": work.as_ref().ok().map(|(_, exit)| exit), "cleanup_wait": cleanup_wait,
        "terminate_error": terminated.as_ref().err().map(ToString::to_string),
        "accounted": accounted, "active_processes": accounting.ActiveProcesses,
        "stdout_stderr_bytes": raw, "stdout_stderr": String::from_utf8_lossy(&raw)})))?;
    terminated?;
    ensure!(cleanup_wait == win::WAIT_OBJECT_0 && accounted != 0 && accounting.ActiveProcesses == 0,
        "owned cmd Job did not finish");
    child.cleaned = true;
    let (_, exit) = work?;
    let text = String::from_utf8_lossy(&raw);
    ensure!(exit == 0 && text.lines().filter(|line| line.starts_with("MATRIX_")).collect::<Vec<_>>()
        == ["MATRIX_ATTEMPT_0", "MATRIX_ATTEMPT_1", "MATRIX_ATTEMPT_2", "MATRIX_ATTEMPT_3", "MATRIX_DONE"]
        && text.lines().filter(|line| *line == "NEITHER_INPUT_RELEASED").count() == 1,
        "owned cmd did not execute its complete original delete operations");
    let mut codes = Vec::new();
    for index in 0..4 {
        let mut pair = Vec::new();
        for operation in ["FILE", "DIR"] {
            let prefix = format!("{operation}_RC_{index}=");
            let values = text.lines().filter_map(|line| line.strip_prefix(&prefix))
                .map(str::parse::<i32>).collect::<std::result::Result<Vec<_>, _>>()?;
            ensure!(values.len() == 1, "missing or repeated cmd result {prefix}");
            pair.push(values[0]);
        }
        codes.push(pair);
    }
    let outcomes = matrix.finish(&format!("privilege-observation-cmd-{subject}"))?;
    observe(format_args!("neither_privileges cmd_physical {}", json!({"subject": subject,
        "command_exit_codes": codes, "outcomes": physical(&outcomes)})))?;
    ensure!(outcomes.len() == 4 && outcomes[3].route == DeleteRoute::Both
        && outcomes[3].file_deleted && outcomes[3].directory_deleted && codes[3] == [0, 0], "cmd Both positive control failed");
    Ok(())
}

pub(super) fn run() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let volume = fs::OpenOptions::new().read(true).share_mode(fswin::FILE_SHARE_READ | fswin::FILE_SHARE_WRITE | fswin::FILE_SHARE_DELETE)
        .custom_flags(fswin::FILE_FLAG_BACKUP_SEMANTICS | fswin::FILE_FLAG_OPEN_REPARSE_POINT).open(fixture.path())?;
    let (mut name, mut filesystem) = ([0_u16; 261], [0_u16; 261]);
    let (mut serial, mut maximum_component, mut flags) = (0, 0, 0);
    let mut identity: fswin::FILE_ID_INFO = unsafe { std::mem::zeroed() };
    // SAFETY: both queries use the same live owned root handle and exact output extents.
    ensure!(unsafe { fswin::GetVolumeInformationByHandleW(volume.as_raw_handle() as win::HANDLE,
        name.as_mut_ptr(), name.len() as u32, &mut serial, &mut maximum_component, &mut flags,
        filesystem.as_mut_ptr(), filesystem.len() as u32) } != 0, "volume information: {}", std::io::Error::last_os_error());
    ensure!(unsafe { fswin::GetFileInformationByHandleEx(volume.as_raw_handle() as win::HANDLE, fswin::FileIdInfo,
        (&mut identity as *mut fswin::FILE_ID_INFO).cast(), std::mem::size_of_val(&identity) as u32) } != 0,
        "volume root identity: {}", std::io::Error::last_os_error());
    observe(format_args!("neither_privileges filesystem {}", json!({"root": fixture.path(), "serial": serial,
        "volume_serial_64": identity.VolumeSerialNumber, "file_id_128": identity.FileId.Identifier,
        "flags": flags, "maximum_component": maximum_component,
        "filesystem": String::from_utf16(&filesystem[..filesystem.iter().position(|c| *c == 0).ok_or_else(|| anyhow::anyhow!("unterminated filesystem name"))?])?,
        "volume_name": String::from_utf16(&name[..name.iter().position(|c| *c == 0).ok_or_else(|| anyhow::anyhow!("unterminated volume name"))?])?})))?;
    let base = Handle(unsafe { get_current_token_for_restriction()? });
    let original = token_record(base.0)?;
    let (effective, is_thread) = effective_record()?;
    ensure!(!is_thread && effective == original && original["token_type"] == security::TokenPrimary,
        "ordinary observation started with a different effective token");
    let mut stripped = 0;
    // SAFETY: only an owned derived token changes. No SID filtering, LUA_TOKEN,
    // WRITE_RESTRICTED, host token adjustment, capability or label policy is added.
    ensure!(unsafe { security::CreateRestrictedToken(base.0, security::DISABLE_MAX_PRIVILEGE,
        /*disablesidcount*/ 0, std::ptr::null(), /*deleteprivilegecount*/ 0, std::ptr::null(),
        /*restrictedsidcount*/ 0, std::ptr::null(), &mut stripped) } != 0,
        "derive privilege-only token: {}", std::io::Error::last_os_error());
    let stripped = Handle(stripped);
    let disabled = token_record(stripped.0)?;
    observe(format_args!("neither_privileges subjects {}", json!({"ordinary": original, "disable_max_privilege": disabled})))?;
    ensure!(original["identity"] == disabled["identity"] && original["identity"]["restricted_sids"] == json!([])
        && disabled["token_type"] == security::TokenPrimary, "derived token changed the compared identity or restricting SIDs");
    ensure!(disabled["privileges"].as_array().is_some_and(|records| records.iter().all(|record|
        record["enabled"] == false || record["name"] == "SeChangeNotifyPrivilege")), "derived token kept another enabled privilege");
    let matrices = ["rust-ordinary-direct", "rust-ordinary-impersonated", "rust-disabled-impersonated",
        "cmd-ordinary", "cmd-disabled"]
        .map(|name| DeleteMatrix::new(&fixture.path().join(name))).into_iter().collect::<Result<Vec<_>>>()?;
    for matrix in &matrices[1..] { matrices[0].assert_same_acls(matrix); }
    let mut matrices = matrices.into_iter();
    // Preserve the direct ordinary-host observation. The paired comparison then
    // impersonates both subjects identically and queries each effective thread
    // token inside that scope, so privilege and impersonation changes are separate.
    for (subject, token, expected, impersonate) in [("ordinary-direct", base.0, &original, false),
        ("ordinary-impersonated", base.0, &original, true),
        ("disabled-impersonated", stripped.0, &disabled, true)] {
        let matrix = matrices.next().ok_or_else(|| anyhow::anyhow!("missing Rust matrix"))?;
        let results = {
            let _impersonation = if impersonate { Some(Impersonation::enter(token)?) } else { None };
            let (actual, is_thread) = effective_record()?;
            observe(format_args!("neither_privileges rust_before {}", json!({"subject": subject, "token": actual, "is_thread": is_thread})))?;
            ensure!(is_thread == impersonate && actual["identity"] == expected["identity"]
                && actual["privileges"] == expected["privileges"], "effective Rust token differs");
            ensure!(if impersonate { actual["token_type"] == security::TokenImpersonation
                && actual["impersonation_level"] == security::SecurityImpersonation }
                else { actual["token_type"] == security::TokenPrimary && actual["impersonation_level"].is_null() },
                "effective Rust token type or impersonation level differs");
            matrix.paths().map(|(file, directory)| {
                let read = fs::read_to_string(file);
                let file_result = fs::remove_file(file);
                let directory_result = fs::remove_dir(directory);
                json!({"read": read.as_ref().ok(), "read_error": read.err().map(|error| error.to_string()),
                    "file_error": file_result.err().map(|error| json!({"code": error.raw_os_error(), "error": error.to_string()})),
                    "directory_error": directory_result.err().map(|error| json!({"code": error.raw_os_error(), "error": error.to_string()}))})
            }).collect::<Vec<_>>()
        }; // RevertToSelf precedes every fixture SD readback/restore.
        let outcomes = matrix.finish(&format!("privilege-observation-rust-{subject}"))?;
        observe(format_args!("neither_privileges rust_physical {}", json!({"subject": subject,
            "operations": results, "outcomes": physical(&outcomes)})))?;
        ensure!(results.iter().all(|result| result["read"] == "matrix-original")
            && outcomes.len() == 4 && outcomes[3].route == DeleteRoute::Both
            && outcomes[3].file_deleted && outcomes[3].directory_deleted
            && results[3]["file_error"].is_null() && results[3]["directory_error"].is_null(), "Rust read/Both positive control failed");
    }
    for (subject, token, expected) in [("ordinary", base.0, &original), ("disabled", stripped.0, &disabled)] {
        cmd_observation(fixture.path(), subject, token, expected,
            matrices.next().ok_or_else(|| anyhow::anyhow!("missing cmd matrix"))?)?;
    }
    ensure!(effective_record()? == (original, false), "ordinary token changed after observations");
    drop(volume);
    fixture.close()?;
    observe(format_args!("neither_privileges complete subjects=2 matrices=5 routes=4 rust_contexts=3 cmd_contexts=2 owned_child_processes=2 observation_only=true isolation_qualified=false"))?;
    Ok(())
}
