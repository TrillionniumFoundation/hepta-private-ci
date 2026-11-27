//! One cross-process credential lease per owned hosted correctness case.
//!
//! CASE_FINISHED is only a handoff request. The independent outer owner must
//! observe every original native process/stream terminal before advancing.
use crate::credential_store::HostedPrivateRoot;
use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_protocol::models::PermissionProfile;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::collections::HashMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::mem::size_of;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use windows_sys::Win32::Foundation as foundation;
use windows_sys::Win32::Security as security;
use windows_sys::Win32::Storage::FileSystem as filesystem;
use windows_sys::Win32::System::JobObjects as jobs;
use windows_sys::Win32::System::Threading as threading;

const SYNCHRONIZE: u32 = 0x0010_0000;
const MAX_OBSERVED_BYTES: u64 = 32_768;
const EXPECTED_CASES: [&str; 9] = [
    "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces",
    "unified_exec::tests::acl_setup_tests::elevated_capture_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::acl_setup_tests::elevated_session_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit",
    "unified_exec::tests::elevated_non_tty_cmd_emits_output",
    "unified_exec::tests::elevated_non_tty_cmd_enforces_deny_read_overrides",
    "unified_exec::tests::elevated_workspace_write_delete_is_limited_to_writable_roots",
    "token::tests::workspace_capability_delete_routes_require_the_capability_in_all_four_cells",
    "unified_exec::tests::delete_permission_tests::elevated_delete_routes_require_workspace_capability_in_all_four_cells",
];

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CaseManifest {
    schema: String,
    authorized: bool,
    run_id: String,
    source_head: String,
    source_tree: String,
    test_name: String,
    ordinal: usize,
    credential_home: PathBuf,
    case_directory: PathBuf,
    owner_pid: u32,
    owner_creation_filetime: u64,
    private_job_handle: u64,
    previous_closed_cases: Vec<String>,
}

#[derive(Serialize)]
struct NativeProcessObservation {
    role: &'static str,
    pid: u32,
    creation_filetime: u64,
    in_original_outer_job: bool,
    handle_signaled: bool,
    exit_code: Option<u32>,
    original_runner: Option<(u32, u64)>,
}

struct NativeProcessWitness {
    role: &'static str,
    handle: OwnedHandle,
    pid: u32,
    creation_filetime: u64,
    original_runner: Option<(u32, u64)>,
}

struct CaseShared {
    manifest: CaseManifest,
    original_job: OwnedHandle,
    owner_process: OwnedHandle,
    runners: Mutex<Vec<NativeProcessWitness>>,
}

static ACTIVE_CASE: OnceLock<Mutex<Option<Arc<CaseShared>>>> = OnceLock::new();

pub(crate) struct HostedCredentialCase {
    shared: Arc<CaseShared>,
    run_root: HostedPrivateRoot,
    case_root: HostedPrivateRoot,
    _run_lock_handle: File,
    _case_lock: File,
    data_root: PathBuf,
    credential_baseline: Vec<u8>,
    caps_baseline: Option<Value>,
    handoff_prepared: bool,
    finished: bool,
}

fn check(success: foundation::BOOL, operation: &str) -> Result<()> {
    if success == 0 {
        return Err(std::io::Error::last_os_error()).with_context(|| operation.to_owned());
    }
    Ok(())
}

fn valid_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn process_identity(handle: foundation::HANDLE) -> Result<(u32, u64)> {
    let pid = unsafe { threading::GetProcessId(handle) };
    ensure!(pid != 0, "retained process handle has no native PID");
    let mut created: foundation::FILETIME = unsafe { std::mem::zeroed() };
    let mut exited: foundation::FILETIME = unsafe { std::mem::zeroed() };
    let mut kernel: foundation::FILETIME = unsafe { std::mem::zeroed() };
    let mut user: foundation::FILETIME = unsafe { std::mem::zeroed() };
    check(
        unsafe {
            threading::GetProcessTimes(handle, &mut created, &mut exited, &mut kernel, &mut user)
        },
        "GetProcessTimes(original hosted handle)",
    )?;
    Ok((
        pid,
        (u64::from(created.dwHighDateTime) << 32) | u64::from(created.dwLowDateTime),
    ))
}

fn duplicate_from(
    source_process: foundation::HANDLE,
    handle: foundation::HANDLE,
    access: u32,
) -> Result<OwnedHandle> {
    let mut duplicate = 0;
    check(
        unsafe {
            foundation::DuplicateHandle(
                source_process,
                handle,
                threading::GetCurrentProcess(),
                &mut duplicate,
                access,
                0,
                0,
            )
        },
        "DuplicateHandle(original hosted object)",
    )?;
    ensure!(duplicate != 0, "native duplicate is null");
    Ok(unsafe { OwnedHandle::from_raw_handle(duplicate as _) })
}

fn exact_job_member(process: foundation::HANDLE, job: foundation::HANDLE) -> Result<bool> {
    let mut member = 0;
    check(
        unsafe { jobs::IsProcessInJob(process, job, &mut member) },
        "IsProcessInJob(exact original outer job)",
    )?;
    Ok(member != 0)
}

fn open_original_owner(manifest: &CaseManifest) -> Result<OwnedHandle> {
    let handle = unsafe {
        threading::OpenProcess(
            threading::PROCESS_DUP_HANDLE
                | threading::PROCESS_QUERY_LIMITED_INFORMATION
                | SYNCHRONIZE,
            0,
            manifest.owner_pid,
        )
    };
    ensure!(
        handle != 0,
        "cannot retain the declared original outer owner process"
    );
    let owner = unsafe { OwnedHandle::from_raw_handle(handle as _) };
    ensure!(
        process_identity(handle)? == (manifest.owner_pid, manifest.owner_creation_filetime),
        "outer owner PID was reused or its original creation identity differs"
    );
    ensure!(
        unsafe { threading::WaitForSingleObject(handle, 0) } == foundation::WAIT_TIMEOUT,
        "outer owner has no current native liveness observation"
    );
    let mut token = 0;
    check(
        unsafe { threading::OpenProcessToken(handle, security::TOKEN_QUERY, &mut token) },
        "OpenProcessToken(original outer owner)",
    )?;
    let token = unsafe { OwnedHandle::from_raw_handle(token as _) };
    crate::credential_store::verify_hosted_owner_token(token.as_raw_handle() as foundation::HANDLE)?;
    Ok(owner)
}

fn assert_run_lock_is_owned(lock: &File) -> Result<()> {
    match lock.try_lock() {
        Err(std::fs::TryLockError::WouldBlock) => Ok(()),
        Err(std::fs::TryLockError::Error(error)) => Err(error).context("observe original run lock"),
        Ok(()) => {
            File::unlock(lock).context("release unexpected unowned run lock")?;
            anyhow::bail!("original credential run owner is not holding its separate native lease");
        }
    }
}

fn observed_file(path: &Path) -> Result<Value> {
    let mut file = match OpenOptions::new()
        .read(true)
        .share_mode(filesystem::FILE_SHARE_READ)
        .custom_flags(filesystem::FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)
    {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(json!({"path": path, "present": false}));
        }
        Err(error) => {
            return Err(error)
                .with_context(|| format!("observe shared fixture state {}", path.display()));
        }
    };
    let mut before: filesystem::BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    check(
        unsafe {
            filesystem::GetFileInformationByHandle(
                file.as_raw_handle() as foundation::HANDLE,
                &mut before,
            )
        },
        "GetFileInformationByHandle(shared fixture state)",
    )?;
    let bytes = (u64::from(before.nFileSizeHigh) << 32) | u64::from(before.nFileSizeLow);
    ensure!(
        before.dwFileAttributes
            & (filesystem::FILE_ATTRIBUTE_REPARSE_POINT | filesystem::FILE_ATTRIBUTE_DIRECTORY)
            == 0
            && before.nNumberOfLinks == 1
            && bytes <= MAX_OBSERVED_BYTES,
        "shared fixture state is redirected, linked or exceeds its byte bound"
    );
    let mut raw = Vec::with_capacity(bytes as usize);
    (&mut file)
        .take(MAX_OBSERVED_BYTES + 1)
        .read_to_end(&mut raw)?;
    let mut after: filesystem::BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    check(
        unsafe {
            filesystem::GetFileInformationByHandle(
                file.as_raw_handle() as foundation::HANDLE,
                &mut after,
            )
        },
        "GetFileInformationByHandle(shared fixture state after)",
    )?;
    ensure!(
        raw.len() as u64 == bytes
            && before.dwVolumeSerialNumber == after.dwVolumeSerialNumber
            && before.nFileIndexHigh == after.nFileIndexHigh
            && before.nFileIndexLow == after.nFileIndexLow
            && before.nFileSizeHigh == after.nFileSizeHigh
            && before.nFileSizeLow == after.nFileSizeLow
            && before.ftLastWriteTime.dwHighDateTime == after.ftLastWriteTime.dwHighDateTime
            && before.ftLastWriteTime.dwLowDateTime == after.ftLastWriteTime.dwLowDateTime,
        "shared fixture state changed during its retained read"
    );
    let text = String::from_utf8(raw).context("shared fixture state is not UTF8")?;
    let value: Value =
        serde_json::from_str(&text).context("shared fixture state JSON is malformed")?;
    Ok(json!({
        "path": path, "present": true, "bytes": bytes, "raw_utf8": text, "value": value,
        "volume": before.dwVolumeSerialNumber,
        "file_index": (u64::from(before.nFileIndexHigh) << 32) | u64::from(before.nFileIndexLow),
    }))
}

fn shared_snapshot(home: &Path) -> Result<Value> {
    Ok(json!({
        "capabilities": observed_file(&crate::cap::cap_sid_file(home))?,
        "deny_read_state": observed_file(&crate::setup::sandbox_dir(home).join("deny_read_acl_state.json"))?,
        "marker": observed_file(&crate::setup::setup_marker_path(home))?,
        "helper_report": observed_file(&crate::setup_error::setup_error_path(home))?,
    }))
}

fn neutral_network_marker(snapshot: &Value) -> Result<()> {
    let marker = &snapshot["marker"];
    ensure!(
        marker["present"] == true
            && marker["value"]["version"] == crate::setup::SETUP_VERSION
            && marker["value"]["offline_username"] == crate::setup::OFFLINE_USERNAME
            && marker["value"]["online_username"] == crate::setup::ONLINE_USERNAME
            && marker["value"]["proxy_ports"]
                .as_array()
                .is_some_and(Vec::is_empty)
            && marker["value"]["allow_local_binding"] == false,
        "shared fixture marker does not retain the declared fixed neutral network settings"
    );
    Ok(())
}

fn preserved_caps(before: Option<&Value>, after: &Value) -> Result<()> {
    let Some(before) = before else { return Ok(()) };
    ensure!(
        before["workspace"] == after["workspace"] && before["readonly"] == after["readonly"],
        "shared base capabilities were rotated"
    );
    for field in [
        "workspace_by_cwd",
        "writable_root_by_path",
        "readable_root_by_path",
    ] {
        let old = before[field]
            .as_object()
            .context("previous capability map is missing")?;
        let new = after[field]
            .as_object()
            .context("current capability map is missing")?;
        ensure!(
            old.iter().all(|(key, value)| new.get(key) == Some(value)),
            "an existing capability mapping changed during this owned case"
        );
    }
    Ok(())
}

impl HostedCredentialCase {
    pub(crate) fn new(test_name: &str, data_root: &Path) -> Result<Self> {
        ensure!(
            std::env::var("CODEX_TEST_WINDOWS_ELEVATED_FIXTURE").as_deref()
                == Ok("github-hosted-admin-v1")
                && std::env::var("GITHUB_ACTIONS").as_deref() == Ok("true")
                && std::env::var("RUNNER_ENVIRONMENT").as_deref() == Ok("github-hosted"),
            "owned credential fixture requires the explicit hosted authorization"
        );
        let run_path = PathBuf::from(
            std::env::var_os("HEPTA_CREDENTIAL_RUN_ROOT")
                .context("no owned credential run root")?,
        );
        let case_path = PathBuf::from(
            std::env::var_os("HEPTA_CREDENTIAL_CASE_DIRECTORY")
                .context("no owned credential case directory")?,
        );
        let nonce = std::env::var("HEPTA_CREDENTIAL_RUN_NONCE").context("no owned run nonce")?;
        let run_root = HostedPrivateRoot::open(&run_path)?;
        let case_root = HostedPrivateRoot::open(&case_path)?;
        ensure!(
            case_root.path().starts_with(run_root.path()) && case_root.path() != run_root.path(),
            "case evidence is outside the original protected run"
        );
        let mut manifest: CaseManifest = serde_json::from_slice(&case_root.read("case.json")?)?;
        manifest.case_directory = std::fs::canonicalize(&manifest.case_directory)?;
        manifest.credential_home = std::fs::canonicalize(&manifest.credential_home)?;
        ensure!(
            manifest.schema == "hepta-owned-credential-case-v1"
                && manifest.authorized
                && valid_hex(&manifest.run_id, 32)
                && manifest.run_id == nonce
                && valid_hex(&manifest.source_head, 40)
                && valid_hex(&manifest.source_tree, 40)
                && (1..=EXPECTED_CASES.len()).contains(&manifest.ordinal)
                && EXPECTED_CASES[manifest.ordinal - 1] == test_name
                && manifest.test_name == test_name
                && manifest
                    .previous_closed_cases
                    .iter()
                    .map(String::as_str)
                    .eq(EXPECTED_CASES[..manifest.ordinal - 1].iter().copied())
                && manifest.case_directory == case_root.path()
                && manifest.credential_home == run_root.path().join("credential-home")
                && manifest.private_job_handle > 0
                && manifest.private_job_handle <= isize::MAX as u64,
            "owned credential manifest or exact case ordering differs"
        );
        ensure!(
            !run_root.path().join("POISONED.json").try_exists()?,
            "the original credential run is poisoned by a prior failure"
        );
        for ordinal in 1..manifest.ordinal {
            let previous = HostedPrivateRoot::open(
                &run_root.path().join("cases").join(format!("{ordinal:02}")),
            )?;
            let closed: Value =
                serde_json::from_slice(&previous.read("NATIVE_HANDOFF_CLOSED.json")?)?;
            ensure!(
                closed["native_complete"] == true
                    && closed["successful"] == true
                    && closed["run_id"] == manifest.run_id
                    && closed["source_head"] == manifest.source_head
                    && closed["source_tree"] == manifest.source_tree
                    && closed["ordinal"] == ordinal
                    && closed["test_name"] == EXPECTED_CASES[ordinal - 1],
                "a prior case has no original full native handoff"
            );
        }
        let run_lock = run_root.open_file("run.lock", true, true)?;
        assert_run_lock_is_owned(&run_lock)?;
        let case_lock = run_root.open_file("case.lock", true, true)?;
        case_lock
            .try_lock()
            .map_err(std::io::Error::from)
            .context("acquire the separate cross-process case lease without waiting or retrying")?;
        let owner_process = open_original_owner(&manifest)?;
        let original_job = duplicate_from(
            owner_process.as_raw_handle() as foundation::HANDLE,
            manifest.private_job_handle as foundation::HANDLE,
            jobs::JOB_OBJECT_QUERY,
        )?;
        ensure!(
            exact_job_member(
                unsafe { threading::GetCurrentProcess() },
                original_job.as_raw_handle() as foundation::HANDLE
            )?,
            "test process is not in the exact original outer owner job"
        );
        let data_root = std::fs::canonicalize(data_root)?;
        ensure!(
            !data_root.starts_with(run_root.path()) && !run_root.path().starts_with(&data_root),
            "case data root must remain separate from credential and owner state"
        );
        let shared = Arc::new(CaseShared {
            manifest,
            original_job,
            owner_process,
            runners: Mutex::new(Vec::new()),
        });
        let mut current = ACTIVE_CASE
            .get_or_init(|| Mutex::new(None))
            .lock()
            .map_err(|_| anyhow::anyhow!("in-process hosted registration is poisoned"))?;
        ensure!(
            current.is_none(),
            "a second hosted case attempted to join one test process"
        );
        let manifest_raw = serde_json::to_vec_pretty(&shared.manifest)?;
        case_root.create_file("IN_FLIGHT.json", &manifest_raw)?;
        *current = Some(Arc::clone(&shared));
        drop(current);
        let mut case = Self {
            shared,
            run_root,
            case_root,
            _run_lock_handle: run_lock,
            _case_lock: case_lock,
            data_root,
            credential_baseline: Vec::new(),
            caps_baseline: None,
            handoff_prepared: false,
            finished: false,
        };
        let before = shared_snapshot(case.path())?;
        case.record("SHARED_STATE_BEFORE.json", &before)?;
        ensure!(
            before["helper_report"]["present"] == false,
            "a case must not reuse an old helper failure report"
        );
        case.caps_baseline = before["capabilities"]["value"]
            .as_object()
            .map(|_| before["capabilities"]["value"].clone());
        case.prepare_neutral_policy(true)?;
        case.credential_baseline = crate::credential_store::hosted_credential_bytes(case.path())?;
        let prepared = shared_snapshot(case.path())?;
        neutral_network_marker(&prepared)?;
        ensure!(
            prepared["helper_report"]["present"] == false,
            "native provisioning returned with an unresolved helper report"
        );
        preserved_caps(
            case.caps_baseline.as_ref(),
            &prepared["capabilities"]["value"],
        )?;
        case.record("SHARED_STATE_PREPARED.json", &prepared)?;
        Ok(case)
    }

    pub(crate) fn path(&self) -> &Path {
        &self.shared.manifest.credential_home
    }

    fn record(&self, name: &str, value: &Value) -> Result<()> {
        self.case_root
            .create_file(name, &serde_json::to_vec_pretty(value)?)?;
        Ok(())
    }

    fn prepare_neutral_policy(&self, full: bool) -> Result<()> {
        let profile = PermissionProfile::read_only();
        let permissions =
            ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
                &profile,
                &[],
            )?;
        let environment = HashMap::new();
        let request = crate::setup::SandboxSetupRequest {
            permissions: &permissions,
            command_cwd: &self.data_root,
            env_map: &environment,
            codex_home: self.path(),
            proxy_enforced: false,
        };
        let overrides = crate::setup::SetupRootOverrides {
            read_roots: Some(if full {
                vec![self.data_root.clone()]
            } else {
                Vec::new()
            }),
            read_roots_include_platform_defaults: false,
            write_roots: Some(Vec::new()),
            deny_read_paths: Some(Vec::new()),
            deny_write_paths: Some(Vec::new()),
        };
        let network = crate::setup::OfflineProxySettings {
            proxy_ports: Vec::new(),
            allow_local_binding: false,
        };
        if full {
            // Reuses the protected credentials after the first case. The real
            // native firewall/identity setup remains part of this case's cost.
            crate::setup::run_elevated_setup_with_proxy_settings(request, overrides, &network)?;
        } else {
            crate::setup::run_setup_refresh_with_overrides_and_proxy_settings(
                request, overrides, &network,
            )?;
        }
        Ok(())
    }

    fn runner_terminals(&self, evidence_name: &str) -> Result<Vec<NativeProcessObservation>> {
        let witnesses = self
            .shared
            .runners
            .lock()
            .map_err(|_| anyhow::anyhow!("original runner custody is poisoned"))?;
        let mut observations = Vec::new();
        ensure!(
            witnesses.len() <= 32,
            "original runner witness count exceeds the declared case bound"
        );
        for witness in witnesses.iter() {
            let handle = witness.handle.as_raw_handle() as foundation::HANDLE;
            ensure!(
                process_identity(handle)? == (witness.pid, witness.creation_filetime),
                "retained runner handle identity changed"
            );
            let in_job = exact_job_member(
                handle,
                self.shared.original_job.as_raw_handle() as foundation::HANDLE,
            )?;
            let signaled =
                unsafe { threading::WaitForSingleObject(handle, 0) } == foundation::WAIT_OBJECT_0;
            let mut code = 0;
            check(
                unsafe { threading::GetExitCodeProcess(handle, &mut code) },
                "GetExitCodeProcess(original runner)",
            )?;
            observations.push(NativeProcessObservation {
                role: witness.role,
                pid: witness.pid,
                creation_filetime: witness.creation_filetime,
                in_original_outer_job: in_job,
                handle_signaled: signaled,
                exit_code: if signaled { Some(code) } else { None },
                original_runner: witness.original_runner,
            });
        }
        self.record(evidence_name, &serde_json::to_value(&observations)?)?;
        ensure!(
            observations
                .iter()
                .all(|row| row.in_original_outer_job && row.handle_signaled),
            "original runner is outside the outer job or lacks a same-handle terminal"
        );
        let token_only = self.shared.manifest.test_name.starts_with("token::tests::");
        ensure!(
            observations.iter().any(|row| row.role == "setup"),
            "owned case has no original direct setup helper witness"
        );
        ensure!(
            token_only || observations.iter().any(|row| row.role == "runner"),
            "elevated route has no original runner witness"
        );
        for runner in observations.iter().filter(|row| row.role == "runner") {
            ensure!(
                observations
                    .iter()
                    .filter(|row| row.role == "child"
                        && row.original_runner == Some((runner.pid, runner.creation_filetime)))
                    .count()
                    == 1,
                "original runner has no unique original child-object witness"
            );
        }
        Ok(observations)
    }

    pub(crate) fn prepare_handoff(&mut self) -> Result<()> {
        ensure!(
            !self.handoff_prepared && !self.finished,
            "case handoff is not repeatable"
        );
        self.runner_terminals("ORIGINAL_RUNNER_TERMINALS_BEFORE_HANDOFF.json")?;
        // Retain the original negative report before the real refresh clears it.
        let before_reset = shared_snapshot(self.path())?;
        self.record("SHARED_STATE_BEFORE_HANDOFF.json", &before_reset)?;
        self.prepare_neutral_policy(false)?;
        let after = shared_snapshot(self.path())?;
        neutral_network_marker(&after)?;
        ensure!(
            after["helper_report"]["present"] == false
                && after["deny_read_state"]["present"] == true
                && after["deny_read_state"]["value"]["principals"]
                    .as_object()
                    .is_some_and(serde_json::Map::is_empty),
            "shared policy/report state was not reset before case handoff"
        );
        preserved_caps(self.caps_baseline.as_ref(), &after["capabilities"]["value"])?;
        ensure!(
            crate::credential_store::hosted_credential_bytes(self.path())?
                == self.credential_baseline,
            "protected credential ciphertext changed during the owned case"
        );
        self.record("SHARED_STATE_AFTER_HANDOFF_PREPARATION.json", &after)?;
        self.handoff_prepared = true;
        Ok(())
    }

    pub(crate) fn finish(mut self) -> Result<()> {
        ensure!(
            self.handoff_prepared && !self.finished,
            "case handoff was not prepared exactly once"
        );
        ensure!(
            !self.data_root.try_exists()?,
            "owned test data root has not been removed"
        );
        let observations = self.runner_terminals("ORIGINAL_RUNNER_TERMINALS_AT_FINISH.json")?;
        ensure!(
            unsafe {
                threading::WaitForSingleObject(
                    self.shared.owner_process.as_raw_handle() as foundation::HANDLE,
                    0,
                )
            } == foundation::WAIT_TIMEOUT,
            "original outer owner exited before final case evidence"
        );
        assert_run_lock_is_owned(&self._run_lock_handle)?;
        let offline_sid = crate::winutil::string_from_sid_bytes(
            &crate::credential_store::local_private_sandbox_account_sid(
                crate::setup::OFFLINE_USERNAME,
            )?,
        )
        .map_err(anyhow::Error::msg)?;
        let online_sid = crate::winutil::string_from_sid_bytes(
            &crate::credential_store::local_private_sandbox_account_sid(
                crate::setup::ONLINE_USERNAME,
            )?,
        )
        .map_err(anyhow::Error::msg)?;
        self.record("CASE_FINISHED.json", &json!({
            "schema": "hepta-owned-credential-case-finished-v1",
            "run_id": self.shared.manifest.run_id, "test_name": self.shared.manifest.test_name,
            "source_head": self.shared.manifest.source_head, "source_tree": self.shared.manifest.source_tree,
            "ordinal": self.shared.manifest.ordinal, "credential_ciphertext_unchanged": true,
            "private_offline_sid": offline_sid, "private_online_sid": online_sid,
            "data_root": self.data_root, "data_root_absent": true,
            "original_runner_observations": observations,
            "handoff_prepared": true, "whole_case_native_terminal": false,
            "outer_owner_must_still_verify_all_members_and_both_eofs": true,
        }))?;
        let mut slot = ACTIVE_CASE
            .get()
            .context("owned case registration is absent at finish")?
            .lock()
            .map_err(|_| anyhow::anyhow!("owned case registration is poisoned at finish"))?;
        ensure!(
            slot.as_ref()
                .is_some_and(|current| Arc::ptr_eq(current, &self.shared)),
            "owned case registration changed before explicit finish"
        );
        *slot = None;
        drop(slot);
        self.finished = true;
        Ok(())
    }
}

impl Drop for HostedCredentialCase {
    fn drop(&mut self) {
        if !self.finished {
            let unfinished = match shared_snapshot(self.path()) {
                Ok(value) => value,
                Err(error) => json!({"snapshot_failed": true, "error": format!("{error:#}")}),
            };
            if let Err(error) = self.record("SHARED_STATE_AT_UNFINISHED_DROP.json", &unfinished) {
                eprintln!("owned original shared-state failure retention failed: {error:#}");
            }
            let failure = json!({
                "schema": "hepta-owned-credential-poison-v1", "run_id": self.shared.manifest.run_id,
                "test_name": self.shared.manifest.test_name,
                "reason": "case did not complete its explicit evidence and owned data handoff",
                "old_failure_retained": true, "safe_to_start_another_case": false,
            });
            if let Err(error) = self.run_root.create_file(
                "POISONED.json",
                &serde_json::to_vec_pretty(&failure)
                    .unwrap_or_else(|_| b"{\"poisoned\":true}".to_vec()),
            ) {
                eprintln!(
                    "owned credential poison retention failed; original run remains failed/unknown: {error:#}"
                );
            }
        }
        if !self.finished {
            match ACTIVE_CASE.get().and_then(|slot| slot.lock().ok()) {
                Some(mut slot)
                    if slot
                        .as_ref()
                        .is_some_and(|current| Arc::ptr_eq(current, &self.shared)) =>
                {
                    *slot = None;
                }
                _ => {
                    eprintln!("owned credential case registration could not be released cleanly");
                }
            }
        }
        // Dropping the case lock is not a terminal proof. The outer owner keeps
        // the run lease and cannot advance until its original native run closes.
    }
}

/// Record the actual hProcess returned by CreateProcessWithLogonW. This is a
/// test-only addition to existing production custody; it never substitutes a PID
/// lookup, assigns a live process to a job, or performs a second termination.
pub(crate) fn record_original_runner_process(process: foundation::HANDLE) -> Result<()> {
    record_original_process(process, "runner")
}

/// The hosted scope must already have its real elevated token. A ShellExecute
/// elevation broker is not silently treated as a descendant of the original Job.
pub(crate) fn require_owned_setup_route(needs_elevation: bool) -> Result<()> {
    if std::env::var_os("HEPTA_CREDENTIAL_RUN_ROOT").is_some() {
        ensure!(
            !needs_elevation,
            "owned hosted setup refuses an unobserved elevation-broker route"
        );
        let current = ACTIVE_CASE
            .get()
            .context("owned setup lacks case registration")?
            .lock()
            .map_err(|_| anyhow::anyhow!("owned case registration is poisoned"))?;
        ensure!(
            current.is_some(),
            "owned setup is outside the current case lease"
        );
    }
    Ok(())
}

/// Retain the original std::process::Child handle before its existing wait.
pub(crate) fn record_original_setup_process(process: foundation::HANDLE) -> Result<()> {
    record_original_process(process, "setup")
}

fn record_original_process(process: foundation::HANDLE, role: &'static str) -> Result<()> {
    ensure!(
        matches!(role, "setup" | "runner"),
        "unexpected hosted process role"
    );
    if std::env::var_os("HEPTA_CREDENTIAL_RUN_ROOT").is_none() {
        return Ok(());
    }
    let shared = ACTIVE_CASE
        .get()
        .context("owned hosted runner launched without case registration")?
        .lock()
        .map_err(|_| anyhow::anyhow!("owned case registry is poisoned"))?
        .as_ref()
        .cloned()
        .context("owned hosted runner launched outside its active case lease")?;
    let (pid, creation_filetime) = process_identity(process)?;
    let duplicate = duplicate_from(
        unsafe { threading::GetCurrentProcess() },
        process,
        threading::PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
    )?;
    let in_job = exact_job_member(
        process,
        shared.original_job.as_raw_handle() as foundation::HANDLE,
    )?;
    let mut witnesses = shared
        .runners
        .lock()
        .map_err(|_| anyhow::anyhow!("original runner witnesses poisoned"))?;
    ensure!(
        !witnesses
            .iter()
            .any(|row| row.pid == pid && row.creation_filetime == creation_filetime),
        "the same original runner launch was registered twice"
    );
    witnesses.push(NativeProcessWitness {
        role,
        handle: duplicate,
        pid,
        creation_filetime,
        original_runner: None,
    });
    ensure!(
        in_job,
        "actual {role} original process handle is outside the exact original outer job"
    );
    Ok(())
}

const OWNED_JOB_ENV: &str = "__HEPTA_NATIVE_JOB_HANDLE";
const OWNED_WITNESS_ENV: &str = "__HEPTA_NATIVE_WITNESS_WRITE";
const OWNED_ACK_ENV: &str = "__HEPTA_NATIVE_ACK_READ";
const OWNED_BRIDGE_VERSION_ENV: &str = "__HEPTA_NATIVE_BRIDGE_VERSION";
const CHILD_WITNESS_MAGIC: u64 = 0x4850_5441_434c_4431;
const CHILD_WITNESS_WORDS: usize = 8;

/// Only this test process can request the narrow native observation protocol.
/// It transfers a query-only Job and pipe endpoints, never a handle that permits
/// the private account to duplicate handles out of the host/test process.
pub(crate) struct OriginalChildWitness {
    runner: OwnedHandle,
    runner_pid: u32,
    runner_creation: u64,
    remote_job: foundation::HANDLE,
    read: File,
    acknowledge: File,
    shared: Arc<CaseShared>,
}

fn native_pipe() -> Result<(OwnedHandle, OwnedHandle)> {
    let mut read = 0;
    let mut write = 0;
    check(
        unsafe {
            windows_sys::Win32::System::Pipes::CreatePipe(
                &mut read,
                &mut write,
                std::ptr::null(),
                4096,
            )
        },
        "create original private witness pipe",
    )?;
    ensure!(
        read != 0 && write != 0,
        "native witness pipe returned a null endpoint"
    );
    Ok(unsafe {
        (
            OwnedHandle::from_raw_handle(read as _),
            OwnedHandle::from_raw_handle(write as _),
        )
    })
}

fn duplicate_into_runner(
    source: foundation::HANDLE,
    runner: foundation::HANDLE,
    access: u32,
    same_access: bool,
) -> Result<foundation::HANDLE> {
    let mut remote = 0;
    check(
        unsafe {
            foundation::DuplicateHandle(
                threading::GetCurrentProcess(),
                source,
                runner,
                &mut remote,
                access,
                0,
                if same_access {
                    foundation::DUPLICATE_SAME_ACCESS
                } else {
                    0
                },
            )
        },
        "duplicate only a query Job or private pipe endpoint into original runner",
    )?;
    ensure!(remote != 0, "original remote witness handle is null");
    // A construction failure goes through the caller's existing original
    // RunnerProcessOwner reconciliation. No remote PID or new terminator is used.
    Ok(remote)
}

pub(crate) fn prepare_original_child_witness(
    runner: foundation::HANDLE,
    request: &mut crate::ipc_framed::SpawnRequest,
) -> Result<Option<OriginalChildWitness>> {
    if std::env::var_os("HEPTA_CREDENTIAL_RUN_ROOT").is_none() {
        return Ok(None);
    }
    let shared = ACTIVE_CASE
        .get()
        .context("owned child bridge has no active case")?
        .lock()
        .map_err(|_| anyhow::anyhow!("owned case registry is poisoned"))?
        .as_ref()
        .cloned()
        .context("owned child bridge is outside the case lease")?;
    let (runner_pid, runner_creation) = process_identity(runner)?;
    ensure!(
        exact_job_member(
            runner,
            shared.original_job.as_raw_handle() as foundation::HANDLE
        )?,
        "original broker is not in the exact outer Job"
    );
    let runner_owner = duplicate_from(
        unsafe { threading::GetCurrentProcess() },
        runner,
        threading::PROCESS_DUP_HANDLE | threading::PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
    )?;
    let (read, witness_write) = native_pipe()?;
    let (ack_read, acknowledge) = native_pipe()?;
    let remote_job = duplicate_into_runner(
        shared.original_job.as_raw_handle() as foundation::HANDLE,
        runner,
        jobs::JOB_OBJECT_QUERY,
        false,
    )?;
    let remote_write = duplicate_into_runner(witness_write.as_raw_handle() as _, runner, 0, true)?;
    let remote_ack = duplicate_into_runner(ack_read.as_raw_handle() as _, runner, 0, true)?;
    for (key, value) in [
        (OWNED_JOB_ENV, remote_job.to_string()),
        (OWNED_WITNESS_ENV, remote_write.to_string()),
        (OWNED_ACK_ENV, remote_ack.to_string()),
        (OWNED_BRIDGE_VERSION_ENV, "1".to_owned()),
    ] {
        ensure!(
            request.env.insert(key.to_owned(), value).is_none(),
            "reserved native observation key already exists"
        );
    }
    drop(witness_write);
    drop(ack_read);
    Ok(Some(OriginalChildWitness {
        runner: runner_owner,
        runner_pid,
        runner_creation,
        remote_job,
        read: File::from(read),
        acknowledge: File::from(acknowledge),
        shared,
    }))
}

impl OriginalChildWitness {
    /// Shares the original SpawnReady deadline. A successful acknowledgment is
    /// sent only after duplicating the real child object out of the retained
    /// original runner, not by reopening a PID.
    pub(crate) fn receive(mut self, deadline: std::time::Instant) -> Result<()> {
        let observed = (|| -> Result<()> {
            let mut available = 0u32;
            loop {
                ensure!(
                    std::time::Instant::now() < deadline,
                    "original SpawnReady deadline exhausted before child witness"
                );
                check(
                    unsafe {
                        windows_sys::Win32::System::Pipes::PeekNamedPipe(
                            self.read.as_raw_handle() as _,
                            std::ptr::null_mut(),
                            0,
                            std::ptr::null_mut(),
                            &mut available,
                            std::ptr::null_mut(),
                        )
                    },
                    "observe original fixed child witness pipe",
                )?;
                ensure!(
                    available as usize <= CHILD_WITNESS_WORDS * size_of::<u64>(),
                    "original child witness has an unexpected trailing payload"
                );
                if available as usize == CHILD_WITNESS_WORDS * size_of::<u64>() {
                    break;
                }
                ensure!(
                    unsafe { threading::WaitForSingleObject(self.runner.as_raw_handle() as _, 0) }
                        == foundation::WAIT_TIMEOUT,
                    "original runner exited before its child witness"
                );
                std::thread::sleep(std::cmp::min(
                    std::time::Duration::from_millis(5),
                    deadline.saturating_duration_since(std::time::Instant::now()),
                ));
            }
            let mut raw = [0u8; CHILD_WITNESS_WORDS * size_of::<u64>()];
            self.read.read_exact(&mut raw)?;
            let words: Vec<u64> = raw
                .chunks_exact(8)
                .map(|word| u64::from_le_bytes(word.try_into().expect("fixed eight-byte word")))
                .collect();
            ensure!(
                words[0] == CHILD_WITNESS_MAGIC
                    && words[1] == 1
                    && words[2] > 0
                    && words[2] <= u64::from(u32::MAX)
                    && words[3] > 0
                    && words[3] <= isize::MAX as u64
                    && words[4] > 0
                    && words[5] == 1
                    && words[6] == self.remote_job as u64
                    && words[7] == 0,
                "original child native witness is malformed or lacks exact Job membership"
            );
            ensure!(
                process_identity(self.runner.as_raw_handle() as _)?
                    == (self.runner_pid, self.runner_creation),
                "original runner identity changed"
            );
            let child = duplicate_from(
                self.runner.as_raw_handle() as _,
                words[3] as _,
                threading::PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
            )?;
            let (pid, creation_filetime) = process_identity(child.as_raw_handle() as _)?;
            ensure!(
                (pid, creation_filetime) == (words[2] as u32, words[4])
                    && exact_job_member(
                        child.as_raw_handle() as _,
                        self.shared.original_job.as_raw_handle() as _
                    )?,
                "duplicated original child object differs from native creation/outer Job"
            );
            let mut witnesses = self
                .shared
                .runners
                .lock()
                .map_err(|_| anyhow::anyhow!("original child custody is poisoned"))?;
            ensure!(
                !witnesses
                    .iter()
                    .any(|row| row.pid == pid && row.creation_filetime == creation_filetime),
                "original child object was registered twice"
            );
            witnesses.push(NativeProcessWitness {
                role: "child",
                handle: child,
                pid,
                creation_filetime,
                original_runner: Some((self.runner_pid, self.runner_creation)),
            });
            Ok(())
        })();
        // A single fresh ACK byte cannot fill the private 4096-byte pipe. The
        // original runner's own Job remains its existing child cleanup owner.
        let acknowledged = self.acknowledge.write_all(&[u8::from(observed.is_ok())]);
        match (observed, acknowledged) {
            (Ok(()), Ok(())) => Ok(()),
            (Err(original), Ok(())) => Err(original),
            (Ok(()), Err(error)) => Err(error).context("acknowledge retained original child"),
            (Err(original), Err(error)) => Err(anyhow::anyhow!(
                "original child witness failed: {original:#}; acknowledgment failed: {error}"
            )),
        }
    }
}
