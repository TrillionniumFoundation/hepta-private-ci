use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::runtime::NativeError;

const SCHEMA: u32 = 1;
const MAX_MANIFEST: u64 = 256 * 1024;
const MAX_BINARY: u64 = 1024 * 1024 * 1024;
const MAX_ARGS: usize = 64;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UpdateManifest {
    pub schema_version: u32,
    pub version: String,
    pub package_path: PathBuf,
    pub package_sha256: Sha256Digest,
    pub predecessor_sha256: Sha256Digest,
    pub target_os: String,
    pub target_arch: String,
    pub backend_protocol_version: u32,
    pub selected_by: String,
    pub generator_principal: String,
    pub restart_args: Vec<String>,
}

impl UpdateManifest {
    fn validate(&self) -> Result<(), NativeError> {
        if self.schema_version != SCHEMA
            || self.version.is_empty()
            || self.version.len() > 128
            || !self.package_path.is_absolute()
            || self.backend_protocol_version == 0
            || !stable_id(&self.selected_by)
            || !stable_id(&self.generator_principal)
            || self.selected_by == self.generator_principal
            || self.restart_args.len() > MAX_ARGS
            || self
                .restart_args
                .iter()
                .any(|arg| arg.len() > 4096 || arg.as_bytes().contains(&0))
        {
            return Err(NativeError::Update(
                "signed update manifest failed validation".to_string(),
            ));
        }
        if self.target_os != std::env::consts::OS || self.target_arch != std::env::consts::ARCH {
            return Err(NativeError::Update(format!(
                "update targets {}/{}, host is {}/{}",
                self.target_os,
                self.target_arch,
                std::env::consts::OS,
                std::env::consts::ARCH
            )));
        }
        Ok(())
    }

    fn signing_bytes(&self) -> Result<Vec<u8>, NativeError> {
        self.validate()?;
        let mut bytes = b"hepta.ui.native.update.v1\0".to_vec();
        bytes.extend(
            serde_json::to_vec(self)
                .map_err(|error| NativeError::Update(format!("encode update manifest: {error}")))?,
        );
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedUpdateManifest {
    pub manifest: UpdateManifest,
    pub signature_hex: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UpdateDisposition {
    RestartScheduled { version: String },
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct UpdateJob {
    schema_version: u32,
    signed: SignedUpdateManifest,
    staged_path: PathBuf,
    current_path: PathBuf,
    backup_path: PathBuf,
    verifying_key_hex: String,
}

pub struct SignedUpdater {
    key: [u8; 32],
    state_dir: PathBuf,
    backend_protocol_version: u32,
}

impl SignedUpdater {
    pub fn new(
        key: [u8; 32],
        state_dir: PathBuf,
        backend_protocol_version: u32,
    ) -> Result<Self, NativeError> {
        if !state_dir.is_absolute() || backend_protocol_version == 0 {
            return Err(NativeError::Update(
                "updater requires absolute state directory and protocol".to_string(),
            ));
        }
        let verifying_key = VerifyingKey::from_bytes(&key)
            .map_err(|_| NativeError::Update("invalid update Ed25519 key".to_string()))?;
        if verifying_key.is_weak() {
            return Err(NativeError::Update("weak update key is forbidden".to_string()));
        }
        Ok(Self {
            key,
            state_dir,
            backend_protocol_version,
        })
    }

    pub fn verify_path(&self, path: &Path) -> Result<SignedUpdateManifest, NativeError> {
        let signed: SignedUpdateManifest = read_json(path)?;
        signed.manifest.validate()?;
        if signed.manifest.backend_protocol_version != self.backend_protocol_version {
            return Err(NativeError::Update(
                "backend protocol is incompatible with update".to_string(),
            ));
        }
        verify_signature(self.key, &signed)?;
        let current = std::env::current_exe()
            .map_err(|error| NativeError::Update(format!("resolve current executable: {error}")))?;
        if file_digest(&current)? != signed.manifest.predecessor_sha256 {
            return Err(NativeError::Update(
                "running executable is not signed predecessor".to_string(),
            ));
        }
        if file_digest(&signed.manifest.package_path)? != signed.manifest.package_sha256 {
            return Err(NativeError::Update(
                "candidate package digest mismatch".to_string(),
            ));
        }
        if equivalent(&current, &signed.manifest.package_path) {
            return Err(NativeError::Update(
                "candidate package aliases the running executable".to_string(),
            ));
        }
        Ok(signed)
    }

    pub fn stage_and_schedule(&self, path: &Path) -> Result<UpdateDisposition, NativeError> {
        let signed = self.verify_path(path)?;

        #[cfg(windows)]
        {
            let _ = signed;
            return Err(NativeError::Update(
                "Windows update apply is fail-closed until kernel authority state has a hardened Windows store"
                    .to_string(),
            ));
        }

        #[cfg(unix)]
        {
            private_dir(&self.state_dir)?;
            let staged = self
                .state_dir
                .join(format!("staged-{}", signed.manifest.package_sha256.as_str()));
            let backup = self.state_dir.join(format!(
                "predecessor-{}",
                signed.manifest.predecessor_sha256.as_str()
            ));
            if backup.exists() {
                return Err(NativeError::Update(
                    "recoverable predecessor already exists".to_string(),
                ));
            }
            private_copy(&signed.manifest.package_path, &staged)?;
            if file_digest(&staged)? != signed.manifest.package_sha256 {
                return Err(NativeError::Update("staged candidate changed".to_string()));
            }
            let current = std::env::current_exe().map_err(|error| {
                NativeError::Update(format!("resolve current executable: {error}"))
            })?;
            let job = UpdateJob {
                schema_version: SCHEMA,
                signed: signed.clone(),
                staged_path: staged,
                current_path: current.clone(),
                backup_path: backup,
                verifying_key_hex: encode_hex(&self.key),
            };
            let job_path = self
                .state_dir
                .join(format!("job-{}.json", signed.manifest.package_sha256.as_str()));
            private_json(&job_path, &job)?;
            let helper = current
                .parent()
                .ok_or_else(|| NativeError::Update("current executable has no parent".to_string()))?
                .join("hepta-native-updater");
            if !helper.is_file() {
                return Err(NativeError::Update(format!(
                    "update helper is missing at {}",
                    helper.display()
                )));
            }
            Command::new(helper)
                .arg("--job")
                .arg(job_path)
                .spawn()
                .map_err(|error| NativeError::Update(format!("spawn update helper: {error}")))?;
            Ok(UpdateDisposition::RestartScheduled {
                version: signed.manifest.version,
            })
        }

        #[cfg(not(any(unix, windows)))]
        {
            let _ = signed;
            Err(NativeError::Update("unsupported updater platform".to_string()))
        }
    }
}

pub fn run_update_helper(path: &Path) -> Result<(), NativeError> {
    #[cfg(windows)]
    {
        let _ = path;
        return Err(NativeError::Update(
            "Windows helper is fail-closed pending hardened authority/update state".to_string(),
        ));
    }

    #[cfg(unix)]
    {
        let job: UpdateJob = read_json(path)?;
        if job.schema_version != SCHEMA {
            return Err(NativeError::Update("unsupported update job schema".to_string()));
        }
        let key = parse_hex_32(&job.verifying_key_hex)?;
        verify_signature(key, &job.signed)?;
        if file_digest(&job.staged_path)? != job.signed.manifest.package_sha256
            || file_digest(&job.current_path)? != job.signed.manifest.predecessor_sha256
        {
            return Err(NativeError::Update(
                "helper digest check failed before replacement".to_string(),
            ));
        }

        std::thread::sleep(Duration::from_millis(1200));
        replace_with_probe(
            &job.staged_path,
            &job.current_path,
            &job.backup_path,
            |current| {
                let status = Command::new(current)
                    .args(&job.signed.manifest.restart_args)
                    .arg("--post-update-probe")
                    .status()
                    .map_err(|error| {
                        NativeError::Update(format!("run post-update probe: {error}"))
                    })?;
                Ok(status.success())
            },
        )?;
        Command::new(&job.current_path)
            .args(&job.signed.manifest.restart_args)
            .spawn()
            .map_err(|error| NativeError::Update(format!("restart updated shell: {error}")))?;
        Ok(())
    }

    #[cfg(not(any(unix, windows)))]
    {
        let _ = path;
        Err(NativeError::Update("unsupported updater platform".to_string()))
    }
}

pub fn parse_hex_32(value: &str) -> Result<[u8; 32], NativeError> {
    parse_hex::<32>(value)
}

fn verify_signature(key: [u8; 32], signed: &SignedUpdateManifest) -> Result<(), NativeError> {
    let key = VerifyingKey::from_bytes(&key)
        .map_err(|_| NativeError::Update("invalid update Ed25519 key".to_string()))?;
    let signature = Signature::from_bytes(&parse_hex::<64>(&signed.signature_hex)?);
    key.verify_strict(&signed.manifest.signing_bytes()?, &signature)
        .map_err(|_| NativeError::Update("update signature verification failed".to_string()))
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, NativeError> {
    let mut file = File::open(path)
        .map_err(|error| NativeError::Update(format!("open {}: {error}", path.display())))?;
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_MANIFEST + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| NativeError::Update(format!("read {}: {error}", path.display())))?;
    if bytes.len() as u64 > MAX_MANIFEST {
        return Err(NativeError::Update("update document exceeds bound".to_string()));
    }
    serde_json::from_slice(&bytes)
        .map_err(|error| NativeError::Update(format!("decode {}: {error}", path.display())))
}

fn file_digest(path: &Path) -> Result<Sha256Digest, NativeError> {
    let mut file = File::open(path)
        .map_err(|error| NativeError::Update(format!("open {}: {error}", path.display())))?;
    let metadata = file
        .metadata()
        .map_err(|error| NativeError::Update(format!("stat {}: {error}", path.display())))?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_BINARY {
        return Err(NativeError::Update(
            "candidate must be a bounded non-empty regular file".to_string(),
        ));
    }
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| NativeError::Update(format!("hash {}: {error}", path.display())))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
}

#[cfg(unix)]
fn private_dir(path: &Path) -> Result<(), NativeError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    if path.exists()
        && std::fs::symlink_metadata(path)
            .map_err(|error| NativeError::Update(format!("inspect state directory: {error}")))?
            .file_type()
            .is_symlink()
    {
        return Err(NativeError::Update(
            "update state directory cannot be a symlink".to_string(),
        ));
    }
    std::fs::create_dir_all(path)
        .map_err(|error| NativeError::Update(format!("create update state: {error}")))?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
        .map_err(|error| NativeError::Update(format!("secure update state: {error}")))?;
    let metadata = std::fs::metadata(path)
        .map_err(|error| NativeError::Update(format!("stat update state: {error}")))?;
    if metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
        || !metadata.is_dir()
    {
        return Err(NativeError::Update(
            "update state is not private to current user".to_string(),
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn private_copy(source: &Path, destination: &Path) -> Result<(), NativeError> {
    use std::os::unix::fs::OpenOptionsExt;
    let mut input = File::open(source)
        .map_err(|error| NativeError::Update(format!("open staged source: {error}")))?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o700)
        .open(destination)
        .map_err(|error| NativeError::Update(format!("create staged candidate: {error}")))?;
    std::io::copy(&mut input, &mut output)
        .map_err(|error| NativeError::Update(format!("copy staged candidate: {error}")))?;
    output
        .sync_all()
        .map_err(|error| NativeError::Update(format!("sync staged candidate: {error}")))
}

#[cfg(unix)]
fn private_json<T: Serialize>(path: &Path, value: &T) -> Result<(), NativeError> {
    use std::os::unix::fs::OpenOptionsExt;
    let bytes = serde_json::to_vec(value)
        .map_err(|error| NativeError::Update(format!("encode update job: {error}")))?;
    if bytes.len() as u64 > MAX_MANIFEST {
        return Err(NativeError::Update("update job exceeds bound".to_string()));
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(|error| NativeError::Update(format!("create update job: {error}")))?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|error| NativeError::Update(format!("persist update job: {error}")))
}

#[cfg(unix)]
fn replace_with_probe<F>(
    staged: &Path,
    current: &Path,
    backup: &Path,
    probe: F,
) -> Result<(), NativeError>
where
    F: FnOnce(&Path) -> Result<bool, NativeError>,
{
    rename_retry(current, backup)?;
    if let Err(error) = rename_retry(staged, current) {
        let _restore = rename_retry(backup, current);
        return Err(error);
    }

    let probe_result = probe(current);
    match probe_result {
        Ok(true) => Ok(()),
        Ok(false) => {
            rename_retry(current, staged)?;
            rename_retry(backup, current)?;
            Err(NativeError::Update(
                "post-update probe failed; predecessor restored".to_string(),
            ))
        }
        Err(error) => {
            rename_retry(current, staged)?;
            rename_retry(backup, current)?;
            Err(NativeError::Update(format!(
                "post-update probe errored and predecessor was restored: {error}"
            )))
        }
    }
}

#[cfg(unix)]
fn rename_retry(from: &Path, to: &Path) -> Result<(), NativeError> {
    let mut last = None;
    for _ in 0..40 {
        match std::fs::rename(from, to) {
            Ok(()) => return Ok(()),
            Err(error) => {
                last = Some(error.to_string());
                std::thread::sleep(Duration::from_millis(250));
            }
        }
    }
    Err(NativeError::Update(format!(
        "atomic replacement failed after bounded retries: {}",
        last.unwrap_or_else(|| "unknown rename error".to_string())
    )))
}

fn equivalent(left: &Path, right: &Path) -> bool {
    match (std::fs::canonicalize(left), std::fs::canonicalize(right)) {
        (Ok(left), Ok(right)) => left == right,
        _ => left == right,
    }
}

fn stable_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
}

fn parse_hex<const N: usize>(value: &str) -> Result<[u8; N], NativeError> {
    if value.len() != N * 2 {
        return Err(NativeError::Update(format!(
            "hex value must contain {} characters",
            N * 2
        )));
    }
    let mut out = [0_u8; N];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = hex(pair[0])?;
        let low = hex(pair[1])?;
        out[index] = (high << 4) | low;
    }
    Ok(out)
}

fn hex(value: u8) -> Result<u8, NativeError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(NativeError::Update("invalid lowercase hex".to_string())),
    }
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    #[cfg(unix)]
    #[test]
    fn failed_post_update_probe_restores_predecessor_without_losing_candidate(
    ) -> Result<(), NativeError> {
        let temp = tempfile::TempDir::new()
            .map_err(|error| NativeError::Update(format!("create temp dir: {error}")))?;
        let current = temp.path().join("hepta-native");
        let staged = temp.path().join("staged");
        let backup = temp.path().join("backup");
        std::fs::write(&current, b"old")
            .map_err(|error| NativeError::Update(format!("write predecessor: {error}")))?;
        std::fs::write(&staged, b"new")
            .map_err(|error| NativeError::Update(format!("write candidate: {error}")))?;

        let result = replace_with_probe(&staged, &current, &backup, |_new_binary| Ok(false));
        assert!(result.is_err());
        assert_eq!(
            std::fs::read(&current)
                .map_err(|error| NativeError::Update(format!("read predecessor: {error}")))?,
            b"old"
        );
        assert_eq!(
            std::fs::read(&staged)
                .map_err(|error| NativeError::Update(format!("read staged candidate: {error}")))?,
            b"new"
        );
        assert!(!backup.exists());
        Ok(())
    }

    #[test]
    fn signature_binds_manifest_and_independent_selector() -> Result<(), NativeError> {
        let key = SigningKey::from_bytes(&[9_u8; 32]);
        let manifest = UpdateManifest {
            schema_version: SCHEMA,
            version: "1.0.0".to_string(),
            package_path: std::env::current_exe()
                .map_err(|error| NativeError::Update(error.to_string()))?,
            package_sha256: Sha256Digest::for_bytes(b"candidate"),
            predecessor_sha256: Sha256Digest::for_bytes(b"predecessor"),
            target_os: std::env::consts::OS.to_string(),
            target_arch: std::env::consts::ARCH.to_string(),
            backend_protocol_version: 1,
            selected_by: "reviewer.1".to_string(),
            generator_principal: "generator.1".to_string(),
            restart_args: Vec::new(),
        };
        let signature = key.sign(&manifest.signing_bytes()?);
        let signed = SignedUpdateManifest {
            manifest,
            signature_hex: encode_hex(&signature.to_bytes()),
        };
        verify_signature(key.verifying_key().to_bytes(), &signed)?;

        let mut tampered = signed;
        tampered.manifest.selected_by = "generator.1".to_string();
        assert!(verify_signature(key.verifying_key().to_bytes(), &tampered).is_err());
        Ok(())
    }
}
