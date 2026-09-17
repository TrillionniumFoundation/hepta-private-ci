use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Mutex;
use std::sync::PoisonError;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;

use super::platform_adapter::NativePlatform;
use super::security::DetachedSignatureVerifier;

const UPDATE_SCHEMA: &str = "native-update-v1";
const MAX_UPDATE_JOURNAL_BYTES: u64 = 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct UpdateCandidate {
    pub(crate) package_path: PathBuf,
    pub(crate) package_digest: String,
    pub(crate) predecessor_digest: String,
    pub(crate) evidence_digest: String,
    pub(crate) producer_id: String,
    pub(crate) selector_id: String,
    pub(crate) platform: NativePlatform,
    pub(crate) architecture: String,
    pub(crate) backend_protocol_version: u64,
    pub(crate) release_signature: Vec<u8>,
    pub(crate) selection_signature: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct VerifiedUpdateCandidate {
    pub(crate) candidate: UpdateCandidate,
}

/// Computes a trustworthy digest for an on-disk update artifact. Implementors
/// must inspect the exact file path supplied and must not trust caller metadata.
pub(crate) trait ArtifactDigest: Send + Sync {
    fn sha256(&self, path: &Path) -> Result<String>;
}

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct SystemArtifactDigest;

impl ArtifactDigest for SystemArtifactDigest {
    fn sha256(&self, path: &Path) -> Result<String> {
        if !path.is_absolute() || !path.is_file() {
            bail!("native update artifact must be an existing absolute file");
        }
        match NativePlatform::current() {
            NativePlatform::Windows => windows_digest(path),
            NativePlatform::Macos => unix_digest("shasum", &["-a", "256"], path),
            NativePlatform::Linux => unix_digest("sha256sum", &[], path),
            NativePlatform::Unsupported => bail!("native update digest is unsupported on this OS"),
        }
    }
}

pub(crate) struct UpdateVerifier<R, S, D> {
    release_signatures: R,
    selection_signatures: S,
    digests: D,
    expected_platform: NativePlatform,
    expected_architecture: String,
    expected_backend_protocol: u64,
}

impl<R, S, D> UpdateVerifier<R, S, D>
where
    R: DetachedSignatureVerifier,
    S: DetachedSignatureVerifier,
    D: ArtifactDigest,
{
    pub(crate) fn new(
        release_signatures: R,
        selection_signatures: S,
        digests: D,
        expected_platform: NativePlatform,
        expected_architecture: String,
        expected_backend_protocol: u64,
    ) -> Result<Self> {
        validate_id(&expected_architecture, "architecture")?;
        if expected_backend_protocol == 0 {
            bail!("backend protocol version must be positive");
        }
        Ok(Self {
            release_signatures,
            selection_signatures,
            digests,
            expected_platform,
            expected_architecture,
            expected_backend_protocol,
        })
    }

    pub(crate) fn verify(&self, candidate: UpdateCandidate) -> Result<VerifiedUpdateCandidate> {
        validate_digest(&candidate.package_digest, "package digest")?;
        validate_digest(&candidate.predecessor_digest, "predecessor digest")?;
        validate_digest(&candidate.evidence_digest, "evidence digest")?;
        validate_id(&candidate.producer_id, "producer id")?;
        validate_id(&candidate.selector_id, "selector id")?;
        validate_id(&candidate.architecture, "architecture")?;
        if candidate.producer_id == candidate.selector_id {
            bail!("native update selector must be independent from the producer");
        }
        if candidate.platform != self.expected_platform
            || candidate.architecture != self.expected_architecture
            || candidate.backend_protocol_version != self.expected_backend_protocol
        {
            bail!("native update platform, architecture or backend protocol is incompatible");
        }
        let observed_digest = self.digests.sha256(&candidate.package_path)?;
        if observed_digest != candidate.package_digest {
            bail!("native update package digest does not match the selected artifact");
        }

        let release_message = release_message(&candidate);
        if !self
            .release_signatures
            .verify(release_message.as_bytes(), &candidate.release_signature)?
        {
            bail!("native update release signature is invalid");
        }
        let selection_message = selection_message(&candidate);
        if !self
            .selection_signatures
            .verify(selection_message.as_bytes(), &candidate.selection_signature)?
        {
            bail!("native update independent selection signature is invalid");
        }
        Ok(VerifiedUpdateCandidate { candidate })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum UpdateDisposition {
    RestartRequired,
    Confirmed,
    RolledBack,
    Quarantined,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum UpdateState {
    Clean,
    Applied {
        package_digest: String,
        predecessor_digest: String,
    },
    Confirmed {
        package_digest: String,
    },
    RolledBack {
        package_digest: String,
        predecessor_digest: String,
    },
}

pub(crate) struct TransactionalUpdater<D> {
    digests: D,
    active_path: PathBuf,
    rollback_path: PathBuf,
    stage_path: PathBuf,
    journal_path: PathBuf,
    state: Mutex<UpdateState>,
}

impl<D> TransactionalUpdater<D>
where
    D: ArtifactDigest,
{
    pub(crate) fn open(
        digests: D,
        active_path: PathBuf,
        rollback_path: PathBuf,
        stage_path: PathBuf,
        journal_path: PathBuf,
    ) -> Result<Self> {
        for (name, path) in [
            ("active path", &active_path),
            ("rollback path", &rollback_path),
            ("stage path", &stage_path),
            ("journal path", &journal_path),
        ] {
            if !path.is_absolute() {
                bail!("native updater {name} must be absolute");
            }
        }
        let state = read_update_state(&journal_path)?;
        Ok(Self {
            digests,
            active_path,
            rollback_path,
            stage_path,
            journal_path,
            state: Mutex::new(state),
        })
    }

    pub(crate) fn apply(
        &self,
        verified: &VerifiedUpdateCandidate,
    ) -> Result<UpdateDisposition> {
        let candidate = &verified.candidate;
        let current_digest = self.digests.sha256(&self.active_path)?;
        if current_digest != candidate.predecessor_digest {
            bail!("native update predecessor digest does not match the active artifact");
        }
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        if matches!(*state, UpdateState::Applied { .. }) {
            bail!("native update already awaits restart confirmation");
        }

        copy_synced(&self.active_path, &self.rollback_path)?;
        copy_synced(&candidate.package_path, &self.stage_path)?;
        if let Err(error) = install_stage(&self.stage_path, &self.active_path) {
            let _ = restore_file(&self.rollback_path, &self.active_path);
            return Err(error).context("install native update stage");
        }
        if self.digests.sha256(&self.active_path)? != candidate.package_digest {
            restore_file(&self.rollback_path, &self.active_path)?;
            append_state(
                &self.journal_path,
                &format!(
                    "R|{}|{}",
                    candidate.package_digest, candidate.predecessor_digest
                ),
            )?;
            *state = UpdateState::RolledBack {
                package_digest: candidate.package_digest.clone(),
                predecessor_digest: candidate.predecessor_digest.clone(),
            };
            return Ok(UpdateDisposition::Quarantined);
        }
        append_state(
            &self.journal_path,
            &format!(
                "A|{}|{}",
                candidate.package_digest, candidate.predecessor_digest
            ),
        )?;
        *state = UpdateState::Applied {
            package_digest: candidate.package_digest.clone(),
            predecessor_digest: candidate.predecessor_digest.clone(),
        };
        Ok(UpdateDisposition::RestartRequired)
    }

    pub(crate) fn recover_or_confirm(
        &self,
        running_digest: &str,
    ) -> Result<UpdateDisposition> {
        validate_digest(running_digest, "running digest")?;
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        let UpdateState::Applied {
            package_digest,
            predecessor_digest,
        } = &*state
        else {
            return Ok(UpdateDisposition::Confirmed);
        };
        if running_digest == package_digest
            && self.digests.sha256(&self.active_path)? == *package_digest
        {
            append_state(&self.journal_path, &format!("C|{package_digest}"))?;
            *state = UpdateState::Confirmed {
                package_digest: package_digest.clone(),
            };
            let _ = std::fs::remove_file(&self.rollback_path);
            return Ok(UpdateDisposition::Confirmed);
        }

        let package_digest = package_digest.clone();
        let predecessor_digest = predecessor_digest.clone();
        restore_file(&self.rollback_path, &self.active_path)?;
        if self.digests.sha256(&self.active_path)? != predecessor_digest {
            bail!("native update rollback did not restore the predecessor digest");
        }
        append_state(
            &self.journal_path,
            &format!("R|{package_digest}|{predecessor_digest}"),
        )?;
        *state = UpdateState::RolledBack {
            package_digest,
            predecessor_digest,
        };
        Ok(UpdateDisposition::RolledBack)
    }
}

fn release_message(candidate: &UpdateCandidate) -> String {
    format!(
        "{UPDATE_SCHEMA}|{}|{}|{}|{}|{}|{}|{}",
        candidate.package_digest,
        candidate.predecessor_digest,
        candidate.evidence_digest,
        platform_name(candidate.platform),
        candidate.architecture,
        candidate.backend_protocol_version,
        candidate.producer_id
    )
}

fn selection_message(candidate: &UpdateCandidate) -> String {
    format!(
        "{}|{}",
        release_message(candidate), candidate.selector_id
    )
}

fn platform_name(platform: NativePlatform) -> &'static str {
    match platform {
        NativePlatform::Windows => "windows",
        NativePlatform::Macos => "macos",
        NativePlatform::Linux => "linux",
        NativePlatform::Unsupported => "unsupported",
    }
}

fn unix_digest(command: &str, args: &[&str], path: &Path) -> Result<String> {
    let output = Command::new(command)
        .args(args)
        .arg(path)
        .stdin(Stdio::null())
        .output()
        .with_context(|| format!("execute {command} for native update digest"))?;
    if !output.status.success() {
        bail!("{command} failed for native update digest");
    }
    parse_digest_output(&output.stdout)
}

fn windows_digest(path: &Path) -> Result<String> {
    const SCRIPT: &str = "(Get-FileHash -Algorithm SHA256 -LiteralPath $args[0]).Hash.ToLowerInvariant()";
    let output = Command::new("powershell.exe")
        .args(["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", SCRIPT, "--"])
        .arg(path)
        .stdin(Stdio::null())
        .output()
        .context("execute PowerShell native update digest")?;
    if !output.status.success() {
        bail!("PowerShell failed for native update digest");
    }
    parse_digest_output(&output.stdout)
}

fn parse_digest_output(bytes: &[u8]) -> Result<String> {
    let text = std::str::from_utf8(bytes).context("native update digest output is not UTF-8")?;
    let digest = text
        .split_whitespace()
        .next()
        .context("native update digest output is empty")?
        .to_ascii_lowercase();
    validate_digest(&digest, "observed artifact digest")?;
    Ok(digest)
}

fn copy_synced(source: &Path, destination: &Path) -> Result<()> {
    if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent).context("create native updater directory")?;
    }
    std::fs::copy(source, destination).with_context(|| {
        format!(
            "copy native update artifact from {} to {}",
            source.display(),
            destination.display()
        )
    })?;
    OpenOptions::new()
        .read(true)
        .open(destination)?
        .sync_all()
        .context("sync native updater artifact")
}

fn install_stage(stage: &Path, active: &Path) -> Result<()> {
    if active.exists() {
        std::fs::remove_file(active).context("remove predecessor before native update rename")?;
    }
    std::fs::rename(stage, active).context("rename native update stage into active path")
}

fn restore_file(rollback: &Path, active: &Path) -> Result<()> {
    if !rollback.is_file() {
        bail!("native update predecessor rollback artifact is missing");
    }
    if active.exists() {
        std::fs::remove_file(active).context("remove failed native update artifact")?;
    }
    copy_synced(rollback, active)
}

fn append_state(path: &Path, line: &str) -> Result<()> {
    if path.metadata().map(|metadata| metadata.len()).unwrap_or(0) > MAX_UPDATE_JOURNAL_BYTES {
        bail!("native update journal exceeds its byte budget");
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).context("create native update journal parent")?;
    }
    let mut options = OpenOptions::new();
    options.create(true).append(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).context("open native update journal")?;
    writeln!(file, "{line}").context("append native update journal")?;
    file.flush().context("flush native update journal")?;
    file.sync_all().context("sync native update journal")
}

fn read_update_state(path: &Path) -> Result<UpdateState> {
    if !path.exists() {
        return Ok(UpdateState::Clean);
    }
    let mut file = File::open(path).context("open native update journal")?;
    if file.metadata()?.len() > MAX_UPDATE_JOURNAL_BYTES {
        bail!("native update journal exceeds its byte budget");
    }
    let mut text = String::new();
    file.read_to_string(&mut text)
        .context("read native update journal")?;
    let mut state = UpdateState::Clean;
    for line in text.lines() {
        let fields = line.split('|').collect::<Vec<_>>();
        state = match fields.as_slice() {
            ["A", package, predecessor] => {
                validate_digest(package, "journal package digest")?;
                validate_digest(predecessor, "journal predecessor digest")?;
                UpdateState::Applied {
                    package_digest: (*package).to_string(),
                    predecessor_digest: (*predecessor).to_string(),
                }
            }
            ["C", package] => {
                validate_digest(package, "journal package digest")?;
                UpdateState::Confirmed {
                    package_digest: (*package).to_string(),
                }
            }
            ["R", package, predecessor] => {
                validate_digest(package, "journal package digest")?;
                validate_digest(predecessor, "journal predecessor digest")?;
                UpdateState::RolledBack {
                    package_digest: (*package).to_string(),
                    predecessor_digest: (*predecessor).to_string(),
                }
            }
            _ => bail!("native update journal contains a malformed record"),
        };
    }
    Ok(state)
}

fn validate_digest(value: &str, name: &str) -> Result<()> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value.bytes().all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        bail!("{name} must be a non-zero lowercase SHA-256 digest");
    }
    Ok(())
}

fn validate_id(value: &str, name: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        bail!("native update {name} is not a bounded stable identifier");
    }
    Ok(())
}
