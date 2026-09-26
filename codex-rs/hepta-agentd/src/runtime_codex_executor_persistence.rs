use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use tokio::time::Instant;

use super::JOB_SCHEMA_VERSION;
use super::MAX_EXECUTABLE_BYTES;
use super::MAX_EXECUTION_TIMEOUT;
use super::MAX_MODEL_BYTES;
use super::MAX_PROCESS_OUTPUT_BYTES;
use super::MAX_RECONCILE_OPERATIONS;
use super::ProcessRuntimeCodexExecutorV1;
use super::RuntimeCodexExecutionInputV1;
use super::RuntimeCodexExecutionReceiptV1;
use super::RuntimeCodexOwnerV1;
use crate::AgentdError;

pub(super) const MANIFEST_FILE: &str = "manifest.json";
pub(super) const DISPATCH_FENCE_FILE: &str = "dispatch-fenced.json";
pub(super) const RECEIPT_FILE: &str = "receipt.json";
pub(super) const NATIVE_JOURNAL_FILE: &str = "native-control.journal";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RuntimeCodexJobManifestV1 {
    pub(super) schema_version: u32,
    pub(super) owner_agent_id: String,
    pub(super) owner_generation: u64,
    pub(super) run_id: String,
    pub(super) expected_revision: u64,
    pub(super) context_digest: String,
    pub(super) envelope_digest: String,
    pub(super) model: String,
    pub(super) deadline_ms: u64,
    pub(super) timeout_ms: u64,
    pub(super) input_digest: String,
    pub(super) worker_artifact_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RuntimeCodexDispatchFenceV1 {
    schema_version: u32,
    run_id: String,
    input_digest: String,
    worker_artifact_digest: String,
}

pub(super) struct OperationPaths {
    pub(super) directory: PathBuf,
    pub(super) manifest: PathBuf,
    pub(super) dispatch_fence: PathBuf,
    pub(super) receipt: PathBuf,
    pub(super) native_journal: PathBuf,
}

impl OperationPaths {
    pub(super) fn for_directory(directory: &Path) -> Self {
        Self {
            directory: directory.to_path_buf(),
            manifest: directory.join(MANIFEST_FILE),
            dispatch_fence: directory.join(DISPATCH_FENCE_FILE),
            receipt: directory.join(RECEIPT_FILE),
            native_journal: directory.join(NATIVE_JOURNAL_FILE),
        }
    }
}

pub(super) struct PreparedOperation {
    pub(super) paths: OperationPaths,
    pub(super) manifest: RuntimeCodexJobManifestV1,
}

pub(super) fn prepare_operation(
    executor: &ProcessRuntimeCodexExecutorV1,
    owner: &RuntimeCodexOwnerV1,
    input: &RuntimeCodexExecutionInputV1,
    input_digest: Digest32,
) -> Result<PreparedOperation, AgentdError> {
    let operation_key = Digest32::of_bytes(input.run_id().as_str().as_bytes()).to_string();
    let directory = executor.journal_root.join(operation_key);
    let paths = OperationPaths::for_directory(&directory);
    match std::fs::create_dir(&directory) {
        Ok(()) => {
            set_private_directory(&directory)?;
            let manifest = RuntimeCodexJobManifestV1 {
                schema_version: JOB_SCHEMA_VERSION,
                owner_agent_id: owner.agent_id().to_string(),
                owner_generation: owner.generation(),
                run_id: input.run_id().to_string(),
                expected_revision: input.expected_revision(),
                context_digest: input.context_digest().to_string(),
                envelope_digest: input.envelope_digest().to_string(),
                model: input.model().to_string(),
                deadline_ms: input.deadline_ms(),
                timeout_ms: remaining_timeout_ms(input.deadline_ms())?,
                input_digest: input_digest.to_string(),
                worker_artifact_digest: executor.worker_artifact_digest.to_string(),
            };
            write_new_json(&paths.manifest, &manifest)?;
            sync_directory(&directory)?;
            Ok(PreparedOperation { paths, manifest })
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            require_canonical_directory(&directory, "runtime.codex operation directory")?;
            let manifest = read_manifest(&paths.manifest)?;
            validate_manifest_owner(&manifest, owner, executor.worker_artifact_digest)?;
            if manifest.run_id != input.run_id().as_str()
                || manifest.expected_revision != input.expected_revision()
                || manifest.context_digest != input.context_digest().to_string()
                || manifest.envelope_digest != input.envelope_digest().to_string()
                || manifest.model != input.model()
                || manifest.deadline_ms != input.deadline_ms()
                || manifest.input_digest != input_digest.to_string()
            {
                return Err(AgentdError::Protocol(
                    "runtime.codex operation identity already exists with semantic drift"
                        .to_string(),
                ));
            }
            Ok(PreparedOperation { paths, manifest })
        }
        Err(error) => Err(error.into()),
    }
}

pub(super) fn dispatch_is_fenced(
    paths: &OperationPaths,
    manifest: &RuntimeCodexJobManifestV1,
) -> Result<bool, AgentdError> {
    let fence: RuntimeCodexDispatchFenceV1 = match read_bounded_json(&paths.dispatch_fence, 16 * 1024)
    {
        Ok(value) => value,
        Err(AgentdError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
            // A native worker journal means a prior process crossed the process
            // boundary even if the outer fence was lost. Never infer Fresh in
            // that state; require reconcile-only behavior.
            return match std::fs::symlink_metadata(&paths.native_journal) {
                Ok(metadata) if metadata.is_file() && !metadata.file_type().is_symlink() => Ok(true),
                Ok(_) => Err(AgentdError::Protocol(
                    "runtime.codex native journal is not a regular file".to_string(),
                )),
                Err(native_error) if native_error.kind() == std::io::ErrorKind::NotFound => {
                    Ok(false)
                }
                Err(native_error) => Err(native_error.into()),
            };
        }
        Err(error) => return Err(error),
    };
    validate_dispatch_fence(&fence, manifest)?;
    Ok(true)
}

pub(super) fn mark_dispatch_fenced(
    paths: &OperationPaths,
    manifest: &RuntimeCodexJobManifestV1,
) -> Result<(), AgentdError> {
    let expected = RuntimeCodexDispatchFenceV1 {
        schema_version: JOB_SCHEMA_VERSION,
        run_id: manifest.run_id.clone(),
        input_digest: manifest.input_digest.clone(),
        worker_artifact_digest: manifest.worker_artifact_digest.clone(),
    };
    match write_new_json(&paths.dispatch_fence, &expected) {
        Ok(()) => {
            sync_directory(&paths.directory)?;
            Ok(())
        }
        Err(AgentdError::Io(error)) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            let observed: RuntimeCodexDispatchFenceV1 =
                read_bounded_json(&paths.dispatch_fence, 16 * 1024)?;
            validate_dispatch_fence(&observed, manifest)
        }
        Err(error) => Err(error),
    }
}

fn validate_dispatch_fence(
    fence: &RuntimeCodexDispatchFenceV1,
    manifest: &RuntimeCodexJobManifestV1,
) -> Result<(), AgentdError> {
    if fence.schema_version != JOB_SCHEMA_VERSION
        || fence.run_id != manifest.run_id
        || fence.input_digest != manifest.input_digest
        || fence.worker_artifact_digest != manifest.worker_artifact_digest
    {
        return Err(AgentdError::Protocol(
            "runtime.codex dispatch fence does not match its immutable manifest".to_string(),
        ));
    }
    Ok(())
}

pub(super) fn list_operation_directories(root: &Path) -> Result<Vec<PathBuf>, AgentdError> {
    let mut entries = std::fs::read_dir(root)?.collect::<Result<Vec<_>, _>>()?;
    entries.sort_by_key(std::fs::DirEntry::file_name);
    if entries.len() > MAX_RECONCILE_OPERATIONS {
        return Err(AgentdError::Protocol(format!(
            "runtime.codex recovery found {} operations, exceeding the bounded scan of {MAX_RECONCILE_OPERATIONS}",
            entries.len()
        )));
    }
    let mut directories = Vec::with_capacity(entries.len());
    for entry in entries {
        let metadata = entry.metadata()?;
        if !metadata.is_dir() || entry.file_type()?.is_symlink() {
            return Err(AgentdError::Protocol(format!(
                "unexpected non-directory entry in runtime.codex journal root: {}",
                entry.path().display()
            )));
        }
        directories.push(entry.path());
    }
    Ok(directories)
}

pub(super) fn read_manifest(path: &Path) -> Result<RuntimeCodexJobManifestV1, AgentdError> {
    read_bounded_json(path, 64 * 1024)
}

pub(super) fn read_receipt_if_present(
    path: &Path,
    manifest: &RuntimeCodexJobManifestV1,
) -> Result<Option<RuntimeCodexExecutionReceiptV1>, AgentdError> {
    let receipt: RuntimeCodexExecutionReceiptV1 =
        match read_bounded_json(path, MAX_PROCESS_OUTPUT_BYTES + 64 * 1024) {
            Ok(value) => value,
            Err(AgentdError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(None);
            }
            Err(error) => return Err(error),
        };
    validate_receipt(&receipt, manifest)?;
    Ok(Some(receipt))
}

pub(super) fn write_receipt(
    path: &Path,
    manifest: &RuntimeCodexJobManifestV1,
    receipt: &RuntimeCodexExecutionReceiptV1,
) -> Result<(), AgentdError> {
    validate_receipt(receipt, manifest)?;
    if let Some(observed) = read_receipt_if_present(path, manifest)? {
        if observed == *receipt {
            return Ok(());
        }
        return Err(AgentdError::Protocol(
            "runtime.codex terminal receipt is immutable and conflicts with an existing receipt"
                .to_string(),
        ));
    }
    match write_json_atomic(path, receipt) {
        Ok(()) => Ok(()),
        Err(AgentdError::Io(error)) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            let observed = read_receipt_if_present(path, manifest)?.ok_or_else(|| {
                AgentdError::Protocol(
                    "runtime.codex receipt appeared without readable terminal evidence".to_string(),
                )
            })?;
            if observed == *receipt {
                Ok(())
            } else {
                Err(AgentdError::Protocol(
                    "runtime.codex terminal receipt conflicts with a concurrent writer".to_string(),
                ))
            }
        }
        Err(error) => Err(error),
    }
}

fn validate_receipt(
    receipt: &RuntimeCodexExecutionReceiptV1,
    manifest: &RuntimeCodexJobManifestV1,
) -> Result<(), AgentdError> {
    if receipt.schema_version != JOB_SCHEMA_VERSION
        || receipt.run_id != manifest.run_id
        || receipt.input_digest != manifest.input_digest
        || receipt.worker_artifact_digest != manifest.worker_artifact_digest
        || !receipt.output.terminal_observed
    {
        return Err(AgentdError::Protocol(
            "runtime.codex durable receipt does not match its operation manifest".to_string(),
        ));
    }
    Ok(())
}

pub(super) fn validate_manifest_owner(
    manifest: &RuntimeCodexJobManifestV1,
    owner: &RuntimeCodexOwnerV1,
    worker_digest: Digest32,
) -> Result<(), AgentdError> {
    if manifest.schema_version != JOB_SCHEMA_VERSION
        || manifest.owner_agent_id != owner.agent_id().to_string()
        || manifest.owner_generation != owner.generation()
        || manifest.worker_artifact_digest != worker_digest.to_string()
        || manifest.expected_revision == 0
        || StableId::new(manifest.run_id.clone()).is_err()
        || Digest32::from_str(&manifest.context_digest).is_err()
        || Digest32::from_str(&manifest.envelope_digest).is_err()
        || Digest32::from_str(&manifest.input_digest).is_err()
        || manifest.model.is_empty()
        || manifest.model.len() > MAX_MODEL_BYTES
        || manifest.timeout_ms == 0
        || manifest.timeout_ms
            > u64::try_from(MAX_EXECUTION_TIMEOUT.as_millis()).unwrap_or(u64::MAX)
    {
        return Err(AgentdError::Protocol(
            "runtime.codex durable manifest failed owner or semantic validation".to_string(),
        ));
    }
    Ok(())
}

pub(super) fn validate_owner(
    executor: &ProcessRuntimeCodexExecutorV1,
    owner: &RuntimeCodexOwnerV1,
) -> Result<(), AgentdError> {
    require_canonical_directory(owner.home_root(), "runtime.codex owner home")?;
    if !owner.agentd_socket().is_absolute()
        || !executor.journal_root.starts_with(owner.home_root())
        || executor.journal_root == owner.home_root()
    {
        return Err(AgentdError::Invalid(
            "runtime.codex journal root must be a private descendant of Agent home".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let home = std::fs::metadata(owner.home_root())?;
        let worker = std::fs::metadata(&executor.worker_executable)?;
        let authority = std::fs::metadata(&executor.final_use_authority_config)?;
        if worker.uid() != home.uid() || authority.uid() != home.uid() {
            return Err(AgentdError::Invalid(
                "runtime.codex executable and authority config must share the Agent owner uid"
                    .to_string(),
            ));
        }
    }
    Ok(())
}

pub(super) fn revalidate_external_files(
    executor: &ProcessRuntimeCodexExecutorV1,
) -> Result<(), AgentdError> {
    validate_protected_file(
        &executor.worker_executable,
        /*executable*/ true,
        executor.worker_artifact_digest,
    )?;
    validate_protected_file(
        &executor.final_use_authority_config,
        /*executable*/ false,
        executor.final_use_authority_digest,
    )
}

pub(super) fn prepare_private_directory(path: &Path) -> Result<(), AgentdError> {
    if !path.is_absolute() {
        return Err(AgentdError::Invalid(
            "runtime.codex journal root must be absolute".to_string(),
        ));
    }
    std::fs::create_dir_all(path)?;
    set_private_directory(path)?;
    require_canonical_directory(path, "runtime.codex journal root")
}

pub(super) fn validate_protected_file(
    path: &Path,
    executable: bool,
    expected_digest: Digest32,
) -> Result<(), AgentdError> {
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err(AgentdError::Invalid(format!(
            "runtime.codex protected path must be absolute, canonical and symlink-free: {}",
            path.display()
        )));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_EXECUTABLE_BYTES
    {
        return Err(AgentdError::Invalid(format!(
            "invalid runtime.codex protected file: {}",
            path.display()
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = metadata.permissions().mode();
        if mode & 0o022 != 0 || (executable && mode & 0o100 == 0) {
            return Err(AgentdError::Invalid(format!(
                "runtime.codex protected file permissions are unsafe: {}",
                path.display()
            )));
        }
    }
    let observed = digest_file(path, metadata.len())?;
    if observed != expected_digest {
        return Err(AgentdError::GenerationFenced(format!(
            "runtime.codex protected file digest drifted: {}",
            path.display()
        )));
    }
    Ok(())
}

pub(super) fn deadline_instant(
    deadline_ms: u64,
    reconciled: bool,
) -> Result<Instant, AgentdError> {
    let now_ms = unix_time_ms()?;
    let duration = if deadline_ms > now_ms {
        Duration::from_millis(deadline_ms - now_ms)
    } else if reconciled {
        Duration::from_secs(30)
    } else {
        return Err(AgentdError::Invalid(
            "runtime.codex execution deadline has elapsed".to_string(),
        ));
    };
    Ok(Instant::now() + duration.min(MAX_EXECUTION_TIMEOUT))
}

pub(super) fn unix_time_ms() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdError::Protocol("system clock predates the Unix epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| AgentdError::Protocol("system clock exceeds u64 milliseconds".to_string()))
}

fn remaining_timeout_ms(deadline_ms: u64) -> Result<u64, AgentdError> {
    let remaining = deadline_ms.checked_sub(unix_time_ms()?).ok_or_else(|| {
        AgentdError::Invalid("runtime.codex execution deadline has elapsed".to_string())
    })?;
    let maximum = u64::try_from(MAX_EXECUTION_TIMEOUT.as_millis())
        .map_err(|_| AgentdError::Protocol("runtime.codex timeout bound overflow".to_string()))?;
    Ok(remaining.clamp(1, maximum))
}

fn digest_file(path: &Path, expected_len: u64) -> Result<Digest32, AgentdError> {
    let mut file = File::open(path)?;
    let before = file.metadata()?;
    if before.len() != expected_len {
        return Err(AgentdError::GenerationFenced(
            "runtime.codex protected file changed before observation".to_string(),
        ));
    }
    let digest = Digest32::of_reader(&mut file, expected_len)?;
    let after = file.metadata()?;
    if before.len() != after.len() || before.modified()? != after.modified()? {
        return Err(AgentdError::GenerationFenced(
            "runtime.codex protected file changed during observation".to_string(),
        ));
    }
    Ok(digest)
}

fn read_bounded_json<T>(path: &Path, maximum: usize) -> Result<T, AgentdError>
where
    T: for<'de> Deserialize<'de>,
{
    validate_read_path(path)?;
    let mut file = File::open(path)?;
    let metadata = file.metadata()?;
    let maximum_u64 = u64::try_from(maximum)
        .map_err(|_| AgentdError::Protocol("JSON read bound overflow".to_string()))?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > maximum_u64 {
        return Err(AgentdError::Protocol(format!(
            "invalid bounded runtime.codex file: {}",
            path.display()
        )));
    }
    let capacity = usize::try_from(metadata.len()).unwrap_or(maximum);
    let mut bytes = Vec::with_capacity(capacity.min(maximum));
    file.take(maximum_u64.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err(AgentdError::Protocol(
            "runtime.codex JSON exceeded its read bound".to_string(),
        ));
    }
    Ok(serde_json::from_slice(&bytes)?)
}

fn validate_read_path(path: &Path) -> Result<(), AgentdError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(AgentdError::Protocol(format!(
            "runtime.codex path is not a regular non-symlink file: {}",
            path.display()
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o022 != 0 {
            return Err(AgentdError::Protocol(format!(
                "runtime.codex file is group/other writable: {}",
                path.display()
            )));
        }
    }
    Ok(())
}

fn require_canonical_directory(path: &Path, label: &str) -> Result<(), AgentdError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || path.canonicalize()? != path
    {
        return Err(AgentdError::Invalid(format!(
            "{label} must be an absolute canonical non-symlink directory: {}",
            path.display()
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(AgentdError::Invalid(format!(
                "{label} must be owner-only: {}",
                path.display()
            )));
        }
    }
    Ok(())
}

fn set_private_directory(path: &Path) -> Result<(), AgentdError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

fn write_new_json<T>(path: &Path, value: &T) -> Result<(), AgentdError>
where
    T: Serialize,
{
    let bytes = serde_json::to_vec(value)?;
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(())
}

fn write_json_atomic<T>(path: &Path, value: &T) -> Result<(), AgentdError>
where
    T: Serialize,
{
    let parent = path.parent().ok_or_else(|| {
        AgentdError::Protocol("runtime.codex receipt has no parent directory".to_string())
    })?;
    let bytes = serde_json::to_vec(value)?;
    let mut staging = None;
    for suffix in 0_u8..16 {
        let candidate = parent.join(format!(
            ".{}.{}.{}.tmp",
            path.file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("receipt"),
            std::process::id(),
            suffix
        ));
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(&candidate) {
            Ok(mut file) => {
                file.write_all(&bytes)?;
                file.sync_all()?;
                staging = Some(candidate);
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    }
    let staging = staging.ok_or_else(|| {
        AgentdError::Io(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "unable to allocate runtime.codex receipt staging path",
        ))
    })?;
    // `hard_link` provides create-if-absent semantics for the immutable receipt;
    // unlike rename, it never replaces a concurrent writer's terminal evidence.
    match std::fs::hard_link(&staging, path) {
        Ok(()) => {
            sync_directory(parent)?;
            let _ = std::fs::remove_file(&staging);
            Ok(())
        }
        Err(error) => {
            let _ = std::fs::remove_file(&staging);
            Err(error.into())
        }
    }
}

fn sync_directory(path: &Path) -> Result<(), AgentdError> {
    File::open(path)?.sync_all()?;
    Ok(())
}