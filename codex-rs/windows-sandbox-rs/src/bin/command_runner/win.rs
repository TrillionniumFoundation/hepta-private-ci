//! Windows command runner used by the **elevated** sandbox path.
//!
//! The CLI launches this binary under the sandbox user when Windows sandbox level is
//! Elevated. It connects to the IPC pipes, reads the framed `SpawnRequest`, derives a
//! restricted token from the sandbox user, and spawns the child process via ConPTY
//! (`tty=true`) or pipes (`tty=false`). It then streams output frames back to the parent,
//! accepts stdin/terminate frames, and emits a final exit frame. The legacy restricted‑token
//! path spawns the child directly and does not use this runner.

#![allow(unsafe_op_in_unsafe_fn)]

mod child_exit;
mod cwd_junction;

use anyhow::Context;
use anyhow::Result;
use codex_utils_pty::JobObject;
use codex_windows_sandbox::ConsoleMode;
use codex_windows_sandbox::ErrorPayload;
use codex_windows_sandbox::ErrorStage;
use codex_windows_sandbox::ExitPayload;
use codex_windows_sandbox::FramedMessage;
use codex_windows_sandbox::IPC_PROTOCOL_VERSION;
use codex_windows_sandbox::LocalSid;
use codex_windows_sandbox::Message;
use codex_windows_sandbox::OutputPayload;
use codex_windows_sandbox::OutputStream;
use codex_windows_sandbox::PipeSpawnHandles;
use codex_windows_sandbox::ResizePayload;
use codex_windows_sandbox::SpawnReady;
use codex_windows_sandbox::SpawnRequest;
use codex_windows_sandbox::StderrMode;
use codex_windows_sandbox::StdinMode;
use codex_windows_sandbox::WindowsSandboxTokenMode;
use codex_windows_sandbox::allow_null_device;
use codex_windows_sandbox::create_readonly_token_with_caps_and_user_from;
use codex_windows_sandbox::create_workspace_write_token_with_caps_and_user_from;
use codex_windows_sandbox::decode_bytes;
use codex_windows_sandbox::encode_bytes;
use codex_windows_sandbox::get_current_token_for_restriction;
use codex_windows_sandbox::hide_current_user_profile_dir;
use codex_windows_sandbox::log_note;
use codex_windows_sandbox::read_frame;
use codex_windows_sandbox::read_handle_loop;
use codex_windows_sandbox::spawn_process_with_pipes;
use codex_windows_sandbox::to_wide;
use codex_windows_sandbox::token_mode_for_permission_profile;
use codex_windows_sandbox::write_frame;
use std::ffi::OsStr;
use std::fs::File;
use std::os::windows::io::FromRawHandle;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;
use std::sync::Arc;
use std::sync::Mutex as StdMutex;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_FILE_NOT_FOUND;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::System::Console::COORD;
use windows_sys::Win32::System::Console::ResizePseudoConsole;
use windows_sys::Win32::System::Threading::GetProcessId;
use windows_sys::Win32::System::Threading::INFINITE;
use windows_sys::Win32::System::Threading::MUTEX_ALL_ACCESS;
use windows_sys::Win32::System::Threading::OpenMutexW;
use windows_sys::Win32::System::Threading::PROCESS_INFORMATION;
use windows_sys::Win32::System::Threading::TerminateProcess;

// Kept in sync with codex_exec_server::CODEX_FS_HELPER_ARG1 without introducing
// a dependency cycle.
const FS_HELPER_ARG: &str = "--codex-run-as-fs-helper";
const READ_ACL_MUTEX_NAME: &str = "Local\\CodexSandboxReadAcl";

struct IpcSpawnedProcess {
    log_dir: PathBuf,
    pi: PROCESS_INFORMATION,
    job: Arc<JobObject>,
    stdout_handle: HANDLE,
    stderr_handle: HANDLE,
    stdin_handle: Option<HANDLE>,
    conpty_owner: Option<codex_windows_sandbox::ConptyInstance>,
    hpc_handle: Option<HANDLE>,
    _pipe_handles: Option<PipeSpawnHandles>,
    // On returning/error paths, desktop owners drop before the station guard.
    // The existing normal std::process::exit path ends this runner directly.
    _private_station: PrivateWindowStation,
}

// This runner owns one command. Switch only its process, before starting any
// child/transport worker, to a create-only station for this new logon session.
// No DACL on the inherited interactive station or desktop is changed.
struct PrivateWindowStation {
    owned: isize,
    previous: isize,
}

impl PrivateWindowStation {
    fn create_for_token(token: HANDLE) -> Result<Self> {
        use windows_sys::Win32::Security::GetTokenInformation;
        use windows_sys::Win32::Security::InitializeSecurityDescriptor;
        use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
        use windows_sys::Win32::Security::SECURITY_DESCRIPTOR;
        use windows_sys::Win32::Security::SetSecurityDescriptorDacl;
        use windows_sys::Win32::Security::TOKEN_DEFAULT_DACL;
        use windows_sys::Win32::Security::TokenDefaultDacl;
        use windows_sys::Win32::System::StationsAndDesktops::CloseWindowStation;
        use windows_sys::Win32::System::StationsAndDesktops::CreateWindowStationW;
        use windows_sys::Win32::System::StationsAndDesktops::GetProcessWindowStation;
        use windows_sys::Win32::System::StationsAndDesktops::SetProcessWindowStation;
        use windows_sys::Win32::UI::WindowsAndMessaging::CWF_CREATE_ONLY;

        let previous = unsafe { GetProcessWindowStation() };
        if previous == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let mut needed = 0;
        unsafe { GetTokenInformation(token, TokenDefaultDacl, ptr::null_mut(), 0, &mut needed) };
        if needed < std::mem::size_of::<TOKEN_DEFAULT_DACL>() as u32 || needed > 65_536 {
            anyhow::bail!("invalid native default-DACL length: {needed}");
        }
        // TOKEN_DEFAULT_DACL contains a pointer and needs aligned backing storage.
        let mut buffer = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
        if unsafe {
            GetTokenInformation(
                token,
                TokenDefaultDacl,
                buffer.as_mut_ptr().cast(),
                needed,
                &mut needed,
            )
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        let dacl = unsafe { &*buffer.as_ptr().cast::<TOKEN_DEFAULT_DACL>() };
        if dacl.DefaultDacl.is_null() {
            anyhow::bail!("private station requires an explicit token default DACL");
        }
        let mut descriptor: SECURITY_DESCRIPTOR = unsafe { std::mem::zeroed() };
        if unsafe {
            InitializeSecurityDescriptor((&mut descriptor as *mut SECURITY_DESCRIPTOR).cast(), 1)
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        if unsafe {
            SetSecurityDescriptorDacl(
                (&mut descriptor as *mut SECURITY_DESCRIPTOR).cast(),
                1,
                dacl.DefaultDacl,
                0,
            )
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        let attributes = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: (&mut descriptor as *mut SECURITY_DESCRIPTOR).cast(),
            bInheritHandle: 0,
        };
        // NULL requests the OS name for this logon session. Non-admin private
        // accounts cannot choose a station name. CREATE_ONLY rejects reuse.
        let owned =
            unsafe { CreateWindowStationW(ptr::null(), CWF_CREATE_ONLY, 0x1000_0000, &attributes) };
        if owned == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        if unsafe { SetProcessWindowStation(owned) } == 0 {
            let error = std::io::Error::last_os_error();
            unsafe { CloseWindowStation(owned) };
            return Err(error.into());
        }
        Ok(Self { owned, previous })
    }
}

impl Drop for PrivateWindowStation {
    fn drop(&mut self) {
        use windows_sys::Win32::System::StationsAndDesktops::CloseWindowStation;
        use windows_sys::Win32::System::StationsAndDesktops::SetProcessWindowStation;
        // A failed restoration is not recoverable by running another command
        // under the wrong process station. The runner owns only this command.
        if unsafe { SetProcessWindowStation(self.previous) } == 0 {
            eprintln!(
                "failed to restore runner window station: {}",
                std::io::Error::last_os_error()
            );
            std::process::abort();
        }
        if unsafe { CloseWindowStation(self.owned) } == 0 {
            eprintln!(
                "failed to close owned runner window station: {}",
                std::io::Error::last_os_error()
            );
            std::process::abort();
        }
    }
}

/// Small RAII wrapper for raw Win32 handles.
///
/// The elevated runner has a few early-return paths where we acquire a token, job, or pipe
/// handle and then may fail while preparing the child. Keeping those handles in a guard makes
/// the error paths read more directly and closes the gaps that were previously leaking them.
struct OwnedWinHandle(HANDLE);

impl OwnedWinHandle {
    fn new(handle: HANDLE) -> Self {
        Self(handle)
    }

    fn raw(&self) -> HANDLE {
        self.0
    }

    fn into_raw(mut self) -> HANDLE {
        // Transfer ownership to the caller. After this point the caller is responsible for
        // eventually closing the returned HANDLE.
        let handle = self.0;
        self.0 = 0;
        handle
    }
}

impl Drop for OwnedWinHandle {
    fn drop(&mut self) {
        if self.0 != 0 && self.0 != INVALID_HANDLE_VALUE {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

/// Open a named pipe created by the parent process.
fn open_pipe(name: &str, access: u32) -> Result<HANDLE> {
    let path = to_wide(name);
    let handle = unsafe {
        CreateFileW(
            path.as_ptr(),
            access,
            0,
            std::ptr::null_mut(),
            OPEN_EXISTING,
            0,
            0,
        )
    };
    if handle == windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE {
        let err = unsafe { GetLastError() };
        return Err(anyhow::anyhow!("CreateFileW failed for pipe {name}: {err}"));
    }
    Ok(handle)
}

/// Send an error frame back to the parent process.
fn send_error(
    writer: &Arc<StdMutex<File>>,
    stage: ErrorStage,
    windows_error_code: Option<u32>,
    message: String,
) -> Result<()> {
    let msg = FramedMessage {
        version: IPC_PROTOCOL_VERSION,
        message: Message::Error {
            payload: ErrorPayload {
                message,
                stage,
                windows_error_code,
            },
        },
    };
    if let Ok(mut guard) = writer.lock() {
        write_frame(&mut *guard, &msg)?;
    }
    Ok(())
}

fn windows_error_code(err: &anyhow::Error) -> Option<u32> {
    err.chain().find_map(|cause| {
        cause
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error)
            .and_then(|code| u32::try_from(code).ok())
    })
}

/// Read and validate the initial spawn request frame.
fn read_spawn_request(reader: &mut File) -> Result<SpawnRequest> {
    let Some(msg) = read_frame(reader)? else {
        anyhow::bail!("runner: pipe closed before spawn_request");
    };
    if msg.version != IPC_PROTOCOL_VERSION {
        anyhow::bail!("runner: unsupported protocol version {}", msg.version);
    }
    match msg.message {
        Message::SpawnRequest { payload } => Ok(*payload),
        other => anyhow::bail!("runner: expected spawn_request, got {other:?}"),
    }
}

fn read_acl_mutex_exists() -> Result<bool> {
    let name = to_wide(OsStr::new(READ_ACL_MUTEX_NAME));
    let handle = unsafe { OpenMutexW(MUTEX_ALL_ACCESS, 0, name.as_ptr()) };
    if handle == 0 {
        let err = unsafe { GetLastError() };
        if err == ERROR_FILE_NOT_FOUND {
            return Ok(false);
        }
        return Err(anyhow::anyhow!("OpenMutexW failed: {err}"));
    }
    unsafe {
        CloseHandle(handle);
    }
    Ok(true)
}

/// Pick an effective CWD, using a junction if the ACL helper is active.
fn effective_cwd(req_cwd: &Path, log_dir: Option<&Path>) -> PathBuf {
    let use_junction = match read_acl_mutex_exists() {
        Ok(exists) => exists,
        Err(err) => {
            log_note(
                &format!(
                    "junction: failed to probe ACL mutex state: {err}; defaulting to junction cwd"
                ),
                log_dir,
            );
            true
        }
    };
    if use_junction {
        cwd_junction::create_cwd_junction(req_cwd, log_dir).unwrap_or_else(|| req_cwd.to_path_buf())
    } else {
        req_cwd.to_path_buf()
    }
}

fn spawn_ipc_process(req: &SpawnRequest) -> Result<IpcSpawnedProcess> {
    let log_dir = req.codex_home.clone();
    hide_current_user_profile_dir(req.codex_home.as_path());
    let token_mode = token_mode_for_permission_profile(
        &req.permission_profile,
        &req.workspace_roots,
        &req.cwd,
        &req.env,
    )
    .context("resolve permission profile token mode")?;
    let mut cap_psids: Vec<LocalSid> = Vec::new();
    for sid in &req.cap_sids {
        cap_psids.push(
            LocalSid::from_string(sid)
                .context("ConvertStringSidToSidW failed for capability SID")?,
        );
    }
    if cap_psids.is_empty() {
        anyhow::bail!("runner: empty capability SID list");
    }
    let network_proxy_restricting_sid = req
        .network_proxy_restricting_sid
        .as_deref()
        .map(LocalSid::from_string)
        .transpose()
        .context("ConvertStringSidToSidW failed for network proxy restricting SID")?;

    // The token helpers still take raw SID pointers, but we keep ownership in `LocalSid`
    // wrappers for as long as possible. That way any failure after SID parsing but before the
    // child is fully spawned still releases the backing LocalAlloc memory automatically.
    let cap_psid_ptrs: Vec<*mut _> = cap_psids.iter().map(LocalSid::as_ptr).collect();
    let additional_restricting_sid_ptrs: Vec<*mut _> = network_proxy_restricting_sid
        .iter()
        .map(LocalSid::as_ptr)
        .collect();
    let base = OwnedWinHandle::new(unsafe { get_current_token_for_restriction()? });
    let h_token = OwnedWinHandle::new(unsafe {
        match token_mode {
            WindowsSandboxTokenMode::ReadOnlyCapability => {
                create_readonly_token_with_caps_and_user_from(
                    base.raw(),
                    &cap_psid_ptrs,
                    &additional_restricting_sid_ptrs,
                )
            }
            WindowsSandboxTokenMode::WritableRootsCapability => {
                create_workspace_write_token_with_caps_and_user_from(
                    base.raw(),
                    &cap_psid_ptrs,
                    &additional_restricting_sid_ptrs,
                )
            }
        }
    }?);
    let private_station = PrivateWindowStation::create_for_token(h_token.raw())
        .context("prepare private capability window station")?;
    // Full capability tokens never use the interactive desktop, including when
    // a caller did not request the optional old desktop mode.
    let use_private_desktop = true;
    unsafe {
        // These ACL adjustments need the raw SID values, but ownership stays with `cap_psids`.
        // We do not manually `LocalFree` anything here; the wrappers handle every return path.
        allow_null_device(cap_psid_ptrs[0]);
        for psid in &cap_psid_ptrs {
            allow_null_device(*psid);
        }
    }

    let effective_cwd = effective_cwd(&req.cwd, Some(log_dir.as_path()));

    let mut conpty_owner = None;
    let mut hpc_handle: Option<HANDLE> = None;
    let mut pipe_handles = None;
    let (pi, job, stdout_handle, stderr_handle, stdin_handle) = if req.tty {
        let (pi, mut conpty) = codex_windows_sandbox::spawn_conpty_process_as_user(
            h_token.raw(),
            &req.command,
            &effective_cwd,
            &req.env,
            use_private_desktop,
            Some(log_dir.as_path()),
        )?;
        let job = conpty
            .job()
            .context("spawned ConPTY is missing its process job")?;
        hpc_handle = conpty.raw_handle();
        let input_write = conpty.take_input_write();
        let output_read = conpty.take_output_read();
        conpty_owner = Some(conpty);
        let stdin_handle = if req.stdin_open {
            Some(input_write)
        } else {
            unsafe {
                CloseHandle(input_write);
            }
            None
        };
        (
            pi,
            job,
            output_read,
            windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE,
            stdin_handle,
        )
    } else {
        let stdin_mode = if req.stdin_open {
            StdinMode::Open
        } else {
            StdinMode::Closed
        };
        let spawned_pipes: PipeSpawnHandles = spawn_process_with_pipes(
            h_token.raw(),
            &req.command,
            &effective_cwd,
            &req.env,
            stdin_mode,
            StderrMode::Separate,
            if req.command.get(1).is_some_and(|arg| arg == FS_HELPER_ARG) {
                ConsoleMode::NoWindow
            } else {
                ConsoleMode::Inherit
            },
            use_private_desktop,
            Some(log_dir.as_path()),
        )?;
        let pi = spawned_pipes.process;
        let stdout_handle = spawned_pipes.stdout_read;
        let stderr_handle = spawned_pipes
            .stderr_read
            .unwrap_or(windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE);
        let stdin_handle = spawned_pipes.stdin_write;
        let job = spawned_pipes.job();
        pipe_handles = Some(spawned_pipes);
        (pi, job, stdout_handle, stderr_handle, stdin_handle)
    };
    Ok(IpcSpawnedProcess {
        log_dir,
        pi,
        job,
        stdout_handle,
        stderr_handle,
        stdin_handle,
        conpty_owner,
        hpc_handle,
        _pipe_handles: pipe_handles,
        _private_station: private_station,
    })
}

/// Stream stdout/stderr from the child into Output frames.
fn spawn_output_reader(
    writer: Arc<StdMutex<File>>,
    handle: HANDLE,
    stream: OutputStream,
    log_dir: Option<PathBuf>,
) -> std::thread::JoinHandle<()> {
    read_handle_loop(handle, move |chunk| {
        let msg = FramedMessage {
            version: IPC_PROTOCOL_VERSION,
            message: Message::Output {
                payload: OutputPayload {
                    data_b64: encode_bytes(chunk),
                    stream,
                },
            },
        };
        if let Ok(mut guard) = writer.lock()
            && let Err(err) = write_frame(&mut *guard, &msg)
        {
            log_note(
                &format!("runner output write failed: {err}"),
                log_dir.as_deref(),
            );
        }
    })
}

fn terminate_job_or_process(job: &JobObject, process: HANDLE, log_dir: Option<&Path>) {
    if let Err(job_err) = job.terminate() {
        log_note(
            &format!("runner failed to terminate process tree: {job_err}"),
            log_dir,
        );
        if unsafe { TerminateProcess(process, 1) } == 0 {
            log_note(
                &format!("runner failed to terminate root process: {}", unsafe {
                    GetLastError()
                }),
                log_dir,
            );
        }
    }
}

/// Read stdin/terminate frames and forward to the child process.
fn spawn_input_loop(
    mut reader: File,
    stdin_handle: Option<HANDLE>,
    hpc_handle: Arc<StdMutex<Option<HANDLE>>>,
    job: Arc<JobObject>,
    process: HANDLE,
    log_dir: Option<PathBuf>,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        let mut stdin_handle = stdin_handle;
        loop {
            let msg = match read_frame(&mut reader) {
                Ok(Some(v)) => v,
                Ok(None) => break,
                Err(_) => break,
            };
            match msg.message {
                Message::Stdin { payload } => {
                    let Ok(bytes) = decode_bytes(&payload.data_b64) else {
                        continue;
                    };
                    if let Some(handle) = stdin_handle {
                        let mut offset = 0usize;
                        // `WriteFile` can report success after consuming only part of the buffer
                        // when the target is a pipe. Treat this like a normal partial write and
                        // keep advancing until every decoded stdin byte has been forwarded.
                        //
                        // If the child closes stdin or the pipe enters an error state, we log
                        // that fact, close our local HANDLE, and stop trying to forward later
                        // `Stdin` frames. That prevents silent truncation while also avoiding an
                        // endless stream of failing writes after the child is already gone.
                        while offset < bytes.len() {
                            let chunk = &bytes[offset..];
                            let chunk_len = chunk.len().min(u32::MAX as usize);
                            let mut written = 0u32;
                            let ok = unsafe {
                                windows_sys::Win32::Storage::FileSystem::WriteFile(
                                    handle,
                                    chunk.as_ptr(),
                                    chunk_len as u32,
                                    &mut written,
                                    ptr::null_mut(),
                                )
                            };
                            if ok == 0 {
                                log_note(
                                    &format!(
                                        "runner stdin write failed after {offset} bytes: {}",
                                        unsafe { GetLastError() }
                                    ),
                                    log_dir.as_deref(),
                                );
                                unsafe {
                                    CloseHandle(handle);
                                }
                                stdin_handle = None;
                                break;
                            }
                            if written == 0 {
                                log_note(
                                    "runner stdin write made no progress; closing child stdin",
                                    log_dir.as_deref(),
                                );
                                unsafe {
                                    CloseHandle(handle);
                                }
                                stdin_handle = None;
                                break;
                            }
                            offset += written as usize;
                        }
                    }
                }
                Message::CloseStdin { .. } => {
                    if let Some(handle) = stdin_handle.take() {
                        unsafe {
                            CloseHandle(handle);
                        }
                    }
                }
                Message::Resize {
                    payload: ResizePayload { rows, cols },
                } => {
                    if let Ok(guard) = hpc_handle.lock()
                        && let Some(hpc) = guard.as_ref()
                    {
                        unsafe {
                            let _ = ResizePseudoConsole(
                                *hpc,
                                COORD {
                                    X: cols as i16,
                                    Y: rows as i16,
                                },
                            );
                        }
                    }
                }
                Message::Terminate { .. } => {
                    terminate_job_or_process(&job, process, log_dir.as_deref());
                }
                Message::SpawnRequest { .. } => {}
                Message::SpawnReady { .. } => {}
                Message::Output { .. } => {}
                Message::Exit { .. } => {}
                Message::Error { .. } => {}
            }
        }
        // Losing the owner's control transport is not CloseStdin. End only
        // this runner's job; the existing normal-exit descendant policy still
        // makes this a no-op after preserve_descendants has committed.
        if let Err(error) = job.terminate() {
            log_note(
                &format!("runner control transport closed; owned job termination failed: {error}"),
                log_dir.as_deref(),
            );
        }
        if let Some(handle) = stdin_handle {
            unsafe {
                CloseHandle(handle);
            }
        }
    })
}

// Only the host test fixture can add these keys after the public transport has
// rejected every caller-supplied reserved key. They are removed before policy
// selection and before either CPAS/ConPTY child environment is constructed.
struct OriginalChildObservation {
    job: OwnedWinHandle,
    witness: File,
    acknowledge: File,
}

impl OriginalChildObservation {
    fn take_from_env(env: &mut std::collections::HashMap<String, String>) -> Result<Option<Self>> {
        const KEYS: [&str; 4] = [
            "__HEPTA_NATIVE_JOB_HANDLE",
            "__HEPTA_NATIVE_WITNESS_WRITE",
            "__HEPTA_NATIVE_ACK_READ",
            "__HEPTA_NATIVE_BRIDGE_VERSION",
        ];
        let found = KEYS.iter().filter(|key| env.contains_key(**key)).count();
        if found == 0 {
            anyhow::ensure!(
                !env.keys()
                    .any(|key| key.to_ascii_uppercase().starts_with("__HEPTA_NATIVE_")),
                "unrecognized reserved native observation key"
            );
            return Ok(None);
        }
        anyhow::ensure!(
            found == KEYS.len(),
            "incomplete original native observation bridge"
        );
        let version = env
            .remove(KEYS[3])
            .context("native bridge version disappeared")?;
        anyhow::ensure!(
            version == "1",
            "unsupported original native observation bridge"
        );
        let mut handles = Vec::with_capacity(3);
        for key in &KEYS[..3] {
            let text = env
                .remove(*key)
                .context("native bridge handle disappeared")?;
            let value: isize = text
                .parse()
                .context("native bridge handle is not a decimal native value")?;
            anyhow::ensure!(
                value > 0 && value.to_string() == text && !handles.contains(&value),
                "original native bridge handle is null, duplicated or malformed"
            );
            handles.push(value);
        }
        anyhow::ensure!(
            !env.keys()
                .any(|key| key.to_ascii_uppercase().starts_with("__HEPTA_NATIVE_")),
            "unexpected additional original native bridge key"
        );
        let job = OwnedWinHandle::new(handles[0]);
        let witness = unsafe { File::from_raw_handle(handles[1] as _) };
        let acknowledge = unsafe { File::from_raw_handle(handles[2] as _) };
        let mut member = 0;
        let ok = unsafe {
            windows_sys::Win32::System::JobObjects::IsProcessInJob(
                windows_sys::Win32::System::Threading::GetCurrentProcess(),
                job.raw(),
                &mut member,
            )
        };
        anyhow::ensure!(
            ok != 0 && member != 0,
            "original private runner does not belong to the supplied query-only outer Job"
        );
        Ok(Some(Self {
            job,
            witness,
            acknowledge,
        }))
    }

    fn retain_original_child_until_ack(mut self, process: HANDLE) -> Result<()> {
        use std::io::Read;
        use std::io::Write;
        let pid = unsafe { GetProcessId(process) };
        let mut created: windows_sys::Win32::Foundation::FILETIME = unsafe { std::mem::zeroed() };
        let mut exited = created;
        let mut kernel = created;
        let mut user = created;
        let times = unsafe {
            windows_sys::Win32::System::Threading::GetProcessTimes(
                process,
                &mut created,
                &mut exited,
                &mut kernel,
                &mut user,
            )
        };
        if pid == 0 || times == 0 {
            return Err(std::io::Error::last_os_error())
                .context("original child hProcess identity for native witness");
        }
        let mut in_job = 0;
        let membership = unsafe {
            windows_sys::Win32::System::JobObjects::IsProcessInJob(
                process,
                self.job.raw(),
                &mut in_job,
            )
        };
        if membership == 0 {
            return Err(std::io::Error::last_os_error())
                .context("original CPAS/ConPTY hProcess outer Job membership");
        }
        let words = [
            0x4850_5441_434c_4431u64,
            1,
            u64::from(pid),
            process as u64,
            (u64::from(created.dwHighDateTime) << 32) | u64::from(created.dwLowDateTime),
            u64::from(in_job != 0),
            self.job.raw() as u64,
            0,
        ];
        let mut raw = [0u8; 64];
        for (chunk, word) in raw.chunks_exact_mut(8).zip(words) {
            chunk.copy_from_slice(&word.to_le_bytes());
        }
        self.witness
            .write_all(&raw)
            .context("write bounded original child-object witness")?;
        // pi.hProcess remains owned by IpcSpawnedProcess throughout this wait.
        // The host's existing 15-second SpawnReady deadline is shared with this
        // acknowledgment. Losing that original host endpoint yields pipe EOF.
        let mut acknowledgment = [0u8; 1];
        self.acknowledge
            .read_exact(&mut acknowledgment)
            .context("read original host child-object acknowledgment")?;
        anyhow::ensure!(
            in_job != 0 && acknowledgment == [1],
            "original host refused child identity or exact outer Job custody"
        );
        Ok(())
    }
}

/// Entry point for the Windows command runner process.
pub fn main() -> Result<()> {
    let mut pipe_in = None;
    let mut pipe_out = None;
    for arg in std::env::args().skip(1) {
        if let Some(rest) = arg.strip_prefix("--pipe-in=") {
            pipe_in = Some(rest.to_string());
        } else if let Some(rest) = arg.strip_prefix("--pipe-out=") {
            pipe_out = Some(rest.to_string());
        }
    }

    let Some(pipe_in) = pipe_in else {
        anyhow::bail!("runner: no pipe-in provided");
    };
    let Some(pipe_out) = pipe_out else {
        anyhow::bail!("runner: no pipe-out provided");
    };

    // Open both pipe ends under guards first so a failure on the second open cannot leak the
    // first HANDLE. Only after both opens succeed do we transfer ownership into `File`, which
    // then becomes responsible for closing them.
    let h_pipe_in = OwnedWinHandle::new(open_pipe(&pipe_in, FILE_GENERIC_READ)?);
    let h_pipe_out = OwnedWinHandle::new(open_pipe(&pipe_out, FILE_GENERIC_WRITE)?);
    let mut pipe_read = unsafe { File::from_raw_handle(h_pipe_in.into_raw() as _) };
    let pipe_write = Arc::new(StdMutex::new(unsafe {
        File::from_raw_handle(h_pipe_out.into_raw() as _)
    }));

    let mut req = match read_spawn_request(&mut pipe_read) {
        Ok(v) => v,
        Err(err) => {
            let _ = send_error(
                &pipe_write,
                ErrorStage::ReadSpawnRequest,
                /*windows_error_code*/ None,
                err.to_string(),
            );
            return Err(err);
        }
    };

    let original_child_observation = match OriginalChildObservation::take_from_env(&mut req.env) {
        Ok(value) => value,
        Err(error) => {
            let _ = send_error(
                &pipe_write,
                ErrorStage::ReadSpawnRequest,
                windows_error_code(&error),
                error.to_string(),
            );
            return Err(error);
        }
    };

    let ipc_spawn = match spawn_ipc_process(&req) {
        Ok(value) => value,
        Err(err) => {
            let _ = send_error(
                &pipe_write,
                ErrorStage::SpawnChild,
                windows_error_code(&err),
                err.to_string(),
            );
            return Err(err);
        }
    };
    if let Some(observation) = original_child_observation {
        if let Err(error) = observation.retain_original_child_until_ack(ipc_spawn.pi.hProcess) {
            let _ = send_error(
                &pipe_write,
                ErrorStage::SpawnChild,
                windows_error_code(&error),
                error.to_string(),
            );
            return Err(error);
        }
    }
    let log_dir = Some(ipc_spawn.log_dir.as_path());
    let pi = ipc_spawn.pi;
    let stdout_handle = ipc_spawn.stdout_handle;
    let stderr_handle = ipc_spawn.stderr_handle;
    let job = Arc::clone(&ipc_spawn.job);
    let mut conpty_owner = ipc_spawn.conpty_owner;
    let stdin_handle = ipc_spawn.stdin_handle;
    let hpc_handle = Arc::new(StdMutex::new(ipc_spawn.hpc_handle));

    let msg = FramedMessage {
        version: IPC_PROTOCOL_VERSION,
        message: Message::SpawnReady {
            payload: SpawnReady {
                process_id: unsafe { GetProcessId(pi.hProcess) },
            },
        },
    };
    if let Err(err) = if let Ok(mut guard) = pipe_write.lock() {
        write_frame(&mut *guard, &msg)
    } else {
        anyhow::bail!("runner spawn_ready write failed: pipe_write lock poisoned");
    } {
        let _ = send_error(
            &pipe_write,
            ErrorStage::WriteSpawnReady,
            /*windows_error_code*/ None,
            err.to_string(),
        );
        return Err(err);
    }
    let log_dir_owned = log_dir.map(Path::to_path_buf);
    let out_thread = spawn_output_reader(
        Arc::clone(&pipe_write),
        stdout_handle,
        OutputStream::Stdout,
        log_dir_owned.clone(),
    );
    let err_thread = if stderr_handle != windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE {
        Some(spawn_output_reader(
            Arc::clone(&pipe_write),
            stderr_handle,
            OutputStream::Stderr,
            log_dir_owned.clone(),
        ))
    } else {
        None
    };

    let _input_thread = spawn_input_loop(
        pipe_read,
        stdin_handle,
        Arc::clone(&hpc_handle),
        Arc::clone(&job),
        pi.hProcess,
        log_dir_owned,
    );

    let timeout = req.timeout_ms.map(|ms| ms as u32).unwrap_or(INFINITE);
    let observed_exit = child_exit::observe_command_exit(
        timeout,
        |wait_ms| child_exit::wait_for_native_child(pi.hProcess, wait_ms),
        || terminate_job_or_process(&job, pi.hProcess, log_dir),
    )?;
    let (exit_code, timed_out) = match observed_exit {
        child_exit::CommandExit::Normal(exit_code) => {
            if let Err(err) = job.preserve_descendants() {
                log_note(
                    &format!("runner failed to preserve descendants after root exit: {err}"),
                    log_dir,
                );
            }
            (exit_code, false)
        }
        child_exit::CommandExit::TimedOut => (128 + 64, true),
    };

    unsafe {
        if pi.hThread != 0 {
            CloseHandle(pi.hThread);
        }
        if pi.hProcess != 0 {
            CloseHandle(pi.hProcess);
        }
    }

    if let Ok(mut guard) = hpc_handle.lock() {
        let _ = guard.take();
    }
    drop(conpty_owner.take());

    if out_thread.join().is_err() {
        log_note("runner stdout reader thread panicked", log_dir);
    }
    if let Some(thread) = err_thread
        && thread.join().is_err()
    {
        log_note("runner stderr reader thread panicked", log_dir);
    }

    let exit_msg = FramedMessage {
        version: IPC_PROTOCOL_VERSION,
        message: Message::Exit {
            payload: ExitPayload {
                exit_code,
                timed_out,
            },
        },
    };
    if let Ok(mut guard) = pipe_write.lock()
        && let Err(err) = write_frame(&mut *guard, &exit_msg)
    {
        log_note(&format!("runner exit write failed: {err}"), log_dir);
    }

    std::process::exit(exit_code);
}
