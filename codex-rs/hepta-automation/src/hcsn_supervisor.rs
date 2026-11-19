//! Bounded transport to the fixed HCSN Python supervisor. Executable, source,
//! and durable-store configuration belong to the host, never the task payload.

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
use crate::hcsn_job::HcsnJobObservationV1;
use crate::hcsn_job::HcsnSupervisor;
use crate::hcsn_job::HcsnSupervisorCommandV1;
use crate::hcsn_job::HcsnSupervisorError;

const MAX_COMMAND_BYTES: usize = 2 * HCSN_MAX_TRAINING_PAYLOAD_BYTES + 64 * 1024;
const MAX_RESPONSE_BYTES: u64 = 64 * 1024;
static NEXT_EXCHANGE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug)]
pub struct HcsnProcessSupervisorConfig {
    /// Absolute path; a venv symlink is retained when launching its interpreter.
    pub python_executable: PathBuf,
    pub python_sha256: Sha256Digest,
    /// Canonical repository directory containing the fixed supervisor module.
    pub repository_root: PathBuf,
    pub supervisor_sha256: Sha256Digest,
    /// Existing, initialized, canonical store owned by the supervisor.
    pub durable_root: PathBuf,
    /// Only the short supervision RPC, not the lifetime of the training job.
    pub deadline: Duration,
}

pub struct HcsnProcessSupervisor {
    config: HcsnProcessSupervisorConfig,
    supervisor_script: PathBuf,
    contact_guard: Box<dyn Fn() -> Result<(), HcsnSupervisorError> + Send + Sync>,
}

impl HcsnProcessSupervisor {
    pub fn new(config: HcsnProcessSupervisorConfig) -> Result<Self, HcsnSupervisorError> {
        Self::new_with_contact_guard(config, || Ok(()))
    }

    /// Adds a denial-only check after transport preparation, immediately before
    /// spawning the supervisor. Passing this check does not grant dispatch
    /// authority; the owner must already have admitted the exchange.
    pub fn new_with_contact_guard(
        config: HcsnProcessSupervisorConfig,
        guard: impl Fn() -> Result<(), HcsnSupervisorError> + Send + Sync + 'static,
    ) -> Result<Self, HcsnSupervisorError> {
        let supervisor = Self {
            supervisor_script: config
                .repository_root
                .join("qualification/hcsn_training/supervisor.py"),
            config,
            contact_guard: Box::new(guard),
        };
        supervisor.validate_config()?;
        Ok(supervisor)
    }

    fn validate_config(&self) -> Result<(), HcsnSupervisorError> {
        let config = &self.config;
        if !config.python_executable.is_absolute()
            || config.deadline.is_zero()
            || config.deadline > Duration::from_secs(30)
        {
            return Err(HcsnSupervisorError::BeforeContact);
        }
        for directory in [&config.repository_root, &config.durable_root] {
            if !directory.is_dir()
                || std::fs::canonicalize(directory)
                    .map_err(|_| HcsnSupervisorError::BeforeContact)?
                    != *directory
            {
                return Err(HcsnSupervisorError::BeforeContact);
            }
        }
        if std::fs::canonicalize(&self.supervisor_script)
            .map_err(|_| HcsnSupervisorError::BeforeContact)?
            != self.supervisor_script
            || file_digest(&config.python_executable)? != config.python_sha256
            || file_digest(&self.supervisor_script)? != config.supervisor_sha256
        {
            return Err(HcsnSupervisorError::BeforeContact);
        }
        Ok(())
    }
}

impl HcsnSupervisor for HcsnProcessSupervisor {
    fn exchange(
        &mut self,
        command: &HcsnSupervisorCommandV1,
    ) -> Result<HcsnJobObservationV1, HcsnSupervisorError> {
        command.validate()?;
        self.validate_config()?;
        let bytes = serde_json::to_vec(command).map_err(|_| HcsnSupervisorError::BeforeContact)?;
        if bytes.len() > MAX_COMMAND_BYTES {
            return Err(HcsnSupervisorError::BeforeContact);
        }
        let mut io = ExchangeFiles::create(&self.config.durable_root)
            .map_err(|_| HcsnSupervisorError::BeforeContact)?;
        let input = io
            .input
            .as_mut()
            .ok_or(HcsnSupervisorError::BeforeContact)?;
        input
            .write_all(&bytes)
            .map_err(|_| HcsnSupervisorError::BeforeContact)?;
        input
            .rewind()
            .map_err(|_| HcsnSupervisorError::BeforeContact)?;
        let output = io
            .output
            .as_mut()
            .ok_or(HcsnSupervisorError::BeforeContact)?;
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
                    .map_err(|_| HcsnSupervisorError::BeforeContact)?,
            ))
            .stdout(Stdio::from(
                output
                    .try_clone()
                    .map_err(|_| HcsnSupervisorError::BeforeContact)?,
            ))
            .stderr(Stdio::null());
        (self.contact_guard)().map_err(|_| HcsnSupervisorError::BeforeContact)?;
        let mut child = process
            .spawn()
            .map_err(|_| HcsnSupervisorError::BeforeContact)?;
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
            return Err(HcsnSupervisorError::Unknown);
        };
        if !exit.success() {
            return Err(HcsnSupervisorError::Unknown);
        }
        output.rewind().map_err(|_| HcsnSupervisorError::Unknown)?;
        let mut bytes = Vec::new();
        output
            .take(MAX_RESPONSE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| HcsnSupervisorError::Unknown)?;
        if bytes.len() as u64 > MAX_RESPONSE_BYTES {
            return Err(HcsnSupervisorError::Unknown);
        }
        let observation: HcsnJobObservationV1 =
            serde_json::from_slice(&bytes).map_err(|_| HcsnSupervisorError::Unknown)?;
        observation
            .validate_for(command)
            .map_err(|_| HcsnSupervisorError::Unknown)?;
        Ok(observation)
    }
}

fn file_digest(path: &Path) -> Result<Sha256Digest, HcsnSupervisorError> {
    const MAX_PINNED_FILE_BYTES: u64 = 256 * 1024 * 1024;
    let metadata = std::fs::metadata(path).map_err(|_| HcsnSupervisorError::BeforeContact)?;
    if !metadata.is_file() || metadata.len() > MAX_PINNED_FILE_BYTES {
        return Err(HcsnSupervisorError::BeforeContact);
    }
    let mut file = File::open(path).map_err(|_| HcsnSupervisorError::BeforeContact)?;
    if !file
        .metadata()
        .map_err(|_| HcsnSupervisorError::BeforeContact)?
        .is_file()
    {
        return Err(HcsnSupervisorError::BeforeContact);
    }
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut bytes_read = 0_u64;
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| HcsnSupervisorError::BeforeContact)?;
        if count == 0 {
            break;
        }
        bytes_read += count as u64;
        if bytes_read > MAX_PINNED_FILE_BYTES {
            return Err(HcsnSupervisorError::BeforeContact);
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
    fn create(root: &Path) -> std::io::Result<Self> {
        let mut options = OpenOptions::new();
        options.read(true).write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        for _ in 0..16 {
            let serial = NEXT_EXCHANGE.fetch_add(1, Ordering::Relaxed);
            let name = format!(".hcsn-rpc-{}-{serial}", std::process::id());
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

#[cfg(test)]
#[path = "hcsn_supervisor_tests.rs"]
mod tests;
