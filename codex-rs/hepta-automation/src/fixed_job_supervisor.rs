//! Private transport for the fixed job supervisor. No public script/argv API.
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;

use crate::hcsn_job::HCSN_MAX_TRAINING_PAYLOAD_BYTES;

const MAX_COMMAND_BYTES: usize = 2 * HCSN_MAX_TRAINING_PAYLOAD_BYTES + 64 * 1024;
pub(crate) const MAX_RESPONSE_BYTES: u64 = 64 * 1024;
static NEXT_EXCHANGE: AtomicU64 = AtomicU64::new(1);

#[cfg(target_os = "linux")]
use crate::joint_text_job::JointTextRootIdentityV1;
use serde::Serialize;

#[cfg(target_os = "linux")]
#[path = "joint_text_supervisor_root.rs"]
mod joint_root;

#[derive(Clone, Debug)]
pub(crate) struct FixedProcessConfig {
    /// Absolute path; a venv symlink is retained when launching its interpreter.
    pub(crate) python_executable: PathBuf,
    pub(crate) python_sha256: Sha256Digest,
    /// Canonical repository directory containing the fixed supervisor module.
    pub(crate) repository_root: PathBuf,
    pub(crate) supervisor_sha256: Sha256Digest,
    /// Existing, initialized, canonical store owned by the supervisor.
    pub(crate) durable_root: PathBuf,
    /// Only the short supervision RPC, not the lifetime of the training job.
    pub(crate) deadline: Duration,
}

#[derive(Clone, Copy, Debug)]
pub(crate) enum FixedProcessError {
    BeforeContact,
    Unknown,
}

enum FixedProfile {
    Hcsn,
    #[cfg(target_os = "linux")]
    JointText(JointTextRootIdentityV1),
}

impl FixedProfile {
    fn maximum_command_bytes(&self) -> usize {
        match self {
            Self::Hcsn => MAX_COMMAND_BYTES,
            #[cfg(target_os = "linux")]
            Self::JointText(_) => crate::joint_text_job::JOINT_TEXT_MAX_COMMAND_BYTES,
        }
    }
    fn rpc_prefix(&self) -> &'static str {
        match self {
            Self::Hcsn => ".hcsn-rpc",
            #[cfg(target_os = "linux")]
            Self::JointText(_) => ".joint-text-rpc",
        }
    }
}

pub(crate) struct FixedProcessSupervisor {
    profile: FixedProfile,
    config: FixedProcessConfig,
    supervisor_script: PathBuf,
    contact_guard: Box<dyn Fn() -> Result<(), FixedProcessError> + Send + Sync>,
}

impl FixedProcessSupervisor {
    pub(crate) fn hcsn(
        config: FixedProcessConfig,
        guard: impl Fn() -> Result<(), FixedProcessError> + Send + Sync + 'static,
    ) -> Result<Self, FixedProcessError> {
        let supervisor = Self {
            profile: FixedProfile::Hcsn,
            supervisor_script: config
                .repository_root
                .join("qualification/hcsn_training/supervisor.py"),
            config,
            contact_guard: Box::new(guard),
        };
        supervisor.validate_config()?;
        Ok(supervisor)
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn joint_text(
        config: FixedProcessConfig,
        root_identity: JointTextRootIdentityV1,
        guard: impl Fn() -> Result<(), FixedProcessError> + Send + Sync + 'static,
    ) -> Result<Self, FixedProcessError> {
        let supervisor = Self {
            supervisor_script: config
                .repository_root
                .join("qualification/hcsn_training/joint_supervisor.py"),
            profile: FixedProfile::JointText(root_identity),
            config,
            contact_guard: Box::new(guard),
        };
        supervisor.validate_config()?;
        Ok(supervisor)
    }

    fn validate_config(&self) -> Result<(), FixedProcessError> {
        let config = &self.config;
        if !config.python_executable.is_absolute()
            || config.deadline.is_zero()
            || config.deadline > Duration::from_secs(30)
        {
            return Err(FixedProcessError::BeforeContact);
        }
        for directory in [&config.repository_root, &config.durable_root] {
            if !directory.is_dir()
                || std::fs::canonicalize(directory).map_err(|_| FixedProcessError::BeforeContact)?
                    != *directory
            {
                return Err(FixedProcessError::BeforeContact);
            }
        }
        if std::fs::canonicalize(&self.supervisor_script)
            .map_err(|_| FixedProcessError::BeforeContact)?
            != self.supervisor_script
            || file_digest(&config.python_executable)? != config.python_sha256
            || file_digest(&self.supervisor_script)? != config.supervisor_sha256
        {
            return Err(FixedProcessError::BeforeContact);
        }
        #[cfg(target_os = "linux")]
        if let FixedProfile::JointText(expected) = &self.profile {
            joint_root::RootGuard::open(&config.durable_root, expected)?;
        }
        Ok(())
    }
}

impl FixedProcessSupervisor {
    pub(crate) fn exchange<T: Serialize>(
        &mut self,
        command: &T,
    ) -> Result<Vec<u8>, FixedProcessError> {
        self.validate_config()?;
        let bytes = serde_json::to_vec(command).map_err(|_| FixedProcessError::BeforeContact)?;
        if bytes.len() > self.profile.maximum_command_bytes() {
            return Err(FixedProcessError::BeforeContact);
        }
        #[cfg(target_os = "linux")]
        let root_guard = match &self.profile {
            FixedProfile::Hcsn => None,
            FixedProfile::JointText(expected) => Some(joint_root::RootGuard::open(
                &self.config.durable_root,
                expected,
            )?),
        };
        #[cfg(target_os = "linux")]
        let storage_root = root_guard.as_ref().map_or_else(
            || self.config.durable_root.clone(),
            joint_root::RootGuard::storage_path,
        );
        #[cfg(not(target_os = "linux"))]
        let storage_root = self.config.durable_root.clone();
        // Declared after root_guard: temporary files are removed through the
        // still-held directory fd before it closes, even if the root is renamed.
        let mut io = ExchangeFiles::create(&storage_root, self.profile.rpc_prefix())
            .map_err(|_| FixedProcessError::BeforeContact)?;
        let input = io.input.as_mut().ok_or(FixedProcessError::BeforeContact)?;
        input
            .write_all(&bytes)
            .map_err(|_| FixedProcessError::BeforeContact)?;
        input
            .rewind()
            .map_err(|_| FixedProcessError::BeforeContact)?;
        let output = io.output.as_mut().ok_or(FixedProcessError::BeforeContact)?;
        let mut process = Command::new(&self.config.python_executable);
        process
            .args(["-I", "-B"])
            .arg(&self.supervisor_script)
            .arg("--root")
            .arg(&self.config.durable_root)
            .current_dir(&self.config.repository_root)
            .stdin(Stdio::from(
                input
                    .try_clone()
                    .map_err(|_| FixedProcessError::BeforeContact)?,
            ))
            .stdout(Stdio::from(
                output
                    .try_clone()
                    .map_err(|_| FixedProcessError::BeforeContact)?,
            ))
            .stderr(Stdio::null());
        #[cfg(target_os = "linux")]
        if let FixedProfile::JointText(expected) = &self.profile {
            process
                .arg("--root-device")
                .arg(expected.device.to_string())
                .arg("--root-inode")
                .arg(expected.inode.to_string())
                .arg("--root-uid")
                .arg(expected.uid.to_string());
        }
        (self.contact_guard)().map_err(|_| FixedProcessError::BeforeContact)?;
        #[cfg(target_os = "linux")]
        if let Some(root) = &root_guard {
            root.validate()?;
        }
        let mut child = process
            .spawn()
            .map_err(|_| FixedProcessError::BeforeContact)?;
        // Every error below is ambiguous provider contact. Kill only the RPC
        // child we own; the durable runner/worker is reconciled by its owner.
        let deadline = Instant::now() + self.config.deadline;
        let exit = loop {
            if output
                .metadata()
                .map_or(true, |metadata| metadata.len() > MAX_RESPONSE_BYTES)
            {
                break None;
            }
            match child.try_wait() {
                Ok(Some(status)) => break Some(status),
                Ok(None) => {}
                Err(_) => break None,
            }
            if Instant::now() >= deadline {
                break None;
            }
            std::thread::sleep(
                Duration::from_millis(5).min(deadline.saturating_duration_since(Instant::now())),
            );
        };
        let Some(exit) = exit else {
            let _ = child.kill();
            let _ = child.wait();
            return Err(FixedProcessError::Unknown);
        };
        if !exit.success() {
            return Err(FixedProcessError::Unknown);
        }
        output.rewind().map_err(|_| FixedProcessError::Unknown)?;
        let mut bytes = Vec::new();
        output
            .take(MAX_RESPONSE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| FixedProcessError::Unknown)?;
        if bytes.len() as u64 > MAX_RESPONSE_BYTES {
            return Err(FixedProcessError::Unknown);
        }
        #[cfg(target_os = "linux")]
        if let Some(root) = &root_guard {
            root.validate().map_err(|_| FixedProcessError::Unknown)?;
        }
        Ok(bytes)
    }
}

pub(crate) fn file_digest(path: &Path) -> Result<Sha256Digest, FixedProcessError> {
    const MAX_PINNED_FILE_BYTES: u64 = 256 * 1024 * 1024;
    let metadata = std::fs::metadata(path).map_err(|_| FixedProcessError::BeforeContact)?;
    if !metadata.is_file() || metadata.len() > MAX_PINNED_FILE_BYTES {
        return Err(FixedProcessError::BeforeContact);
    }
    let mut file = File::open(path).map_err(|_| FixedProcessError::BeforeContact)?;
    if !file
        .metadata()
        .map_err(|_| FixedProcessError::BeforeContact)?
        .is_file()
    {
        return Err(FixedProcessError::BeforeContact);
    }
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut bytes_read = 0_u64;
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| FixedProcessError::BeforeContact)?;
        if count == 0 {
            break;
        }
        bytes_read += count as u64;
        if bytes_read > MAX_PINNED_FILE_BYTES {
            return Err(FixedProcessError::BeforeContact);
        }
        hasher.update(&buffer[..count]);
    }
    Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
}

/// Regular files avoid an inherited pipe keeping a reader thread blocked after
/// the RPC deadline. Input/output are private, exclusive, and removed on exit.
struct ExchangeFiles {
    input_path: PathBuf,
    output_path: PathBuf,
    input: Option<File>,
    output: Option<File>,
}

impl ExchangeFiles {
    fn create(root: &Path, prefix: &str) -> std::io::Result<Self> {
        let mut options = OpenOptions::new();
        options.read(true).write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        for _ in 0..16 {
            let serial = NEXT_EXCHANGE.fetch_add(1, Ordering::Relaxed);
            let name = format!("{prefix}-{}-{serial}", std::process::id());
            let input_path = root.join(format!("{name}.in"));
            let output_path = root.join(format!("{name}.out"));
            let input = match options.open(&input_path) {
                Ok(file) => file,
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error),
            };
            match options.open(&output_path) {
                Ok(output) => {
                    return Ok(Self {
                        input_path,
                        output_path,
                        input: Some(input),
                        output: Some(output),
                    });
                }
                Err(error) => {
                    drop(input);
                    let _ = std::fs::remove_file(&input_path);
                    if error.kind() != std::io::ErrorKind::AlreadyExists {
                        return Err(error);
                    }
                }
            }
        }
        Err(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "HCSN transport files already exist",
        ))
    }
}

impl Drop for ExchangeFiles {
    fn drop(&mut self) {
        drop(self.input.take());
        drop(self.output.take());
        let _ = std::fs::remove_file(&self.input_path);
        let _ = std::fs::remove_file(&self.output_path);
    }
}
