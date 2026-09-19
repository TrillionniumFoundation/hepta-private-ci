use std::fs::File;
use std::io::Read as _;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;

use atomic_write_file::AtomicWriteFile;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;

use crate::error::ShellError;
use crate::model::validate_digest;
use crate::model::validate_stable_id;
use crate::security::TrustedKeySet;
use crate::security::now_unix_ms;

const UPDATE_SCHEMA: &str = "hepta.native-update.v1";
const PENDING_SCHEMA: &str = "hepta.native-pending-update.v1";
const MAX_PACKAGE_BYTES: u64 = 512 * 1024 * 1024;
const PRODUCT_UPDATE_CHANNEL: &str = "stable";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SignedUpdateManifestV1 {
    pub schema: String,
    pub package_digest: String,
    pub predecessor_digest: String,
    pub evidence_digest: String,
    pub platform: String,
    pub architecture: String,
    pub backend_protocol_version: u32,
    pub channel: String,
    pub selected_by: String,
    pub generator_principal: String,
    pub issued_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub key_id: String,
    pub signature_base64: String,
}

impl SignedUpdateManifestV1 {
    pub fn signing_message(&self) -> String {
        format!(
            "hepta.native-update.v1\npackage_digest={}\npredecessor_digest={}\nevidence_digest={}\nplatform={}\narchitecture={}\nbackend_protocol_version={}\nchannel={}\nselected_by={}\ngenerator_principal={}\nissued_unix_ms={}\nexpires_unix_ms={}\nkey_id={}\n",
            self.package_digest,
            self.predecessor_digest,
            self.evidence_digest,
            self.platform,
            self.architecture,
            self.backend_protocol_version,
            self.channel,
            self.selected_by,
            self.generator_principal,
            self.issued_unix_ms,
            self.expires_unix_ms,
            self.key_id
        )
    }

    pub fn validate(&self, backend_protocol_version: u32) -> Result<(), ShellError> {
        if self.schema != UPDATE_SCHEMA {
            return Err(ShellError::Update(
                "unsupported native update manifest schema".to_owned(),
            ));
        }
        validate_digest(&self.package_digest, "update.package_digest")?;
        validate_digest(&self.predecessor_digest, "update.predecessor_digest")?;
        validate_digest(&self.evidence_digest, "update.evidence_digest")?;
        validate_stable_id(&self.channel, "update.channel")?;
        if self.channel != PRODUCT_UPDATE_CHANNEL {
            return Err(ShellError::Security(
                "native update channel is not admitted by product policy".to_owned(),
            ));
        }
        validate_stable_id(&self.selected_by, "update.selected_by")?;
        validate_stable_id(&self.generator_principal, "update.generator_principal")?;
        validate_stable_id(&self.key_id, "update.key_id")?;
        if self.selected_by == self.generator_principal {
            return Err(ShellError::Security(
                "native update cannot be selected by its generator".to_owned(),
            ));
        }
        if self.platform != std::env::consts::OS || self.architecture != std::env::consts::ARCH {
            return Err(ShellError::Update(
                "native update target platform/architecture mismatch".to_owned(),
            ));
        }
        if self.backend_protocol_version != backend_protocol_version {
            return Err(ShellError::Update(
                "native update backend protocol version mismatch".to_owned(),
            ));
        }
        let now = now_unix_ms()?;
        if self.issued_unix_ms > now.saturating_add(5 * 60 * 1000)
            || self.expires_unix_ms < now
            || self.expires_unix_ms <= self.issued_unix_ms
        {
            return Err(ShellError::Security(
                "native update manifest time window is invalid".to_owned(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PendingUpdateStatus {
    Staged,
    ActivationStarted,
    ActivatedUnconfirmed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PendingUpdateV1 {
    pub schema: String,
    pub manifest: SignedUpdateManifestV1,
    pub staged_package: PathBuf,
    pub target_path: Option<PathBuf>,
    pub backup_path: Option<PathBuf>,
    pub status: PendingUpdateStatus,
}

#[derive(Debug, Clone)]
pub struct UpdateManager {
    trusted_keys: TrustedKeySet,
    root: PathBuf,
}

impl UpdateManager {
    pub fn new(trusted_keys: TrustedKeySet, root: PathBuf) -> Result<Self, ShellError> {
        if !root.is_absolute() {
            return Err(ShellError::InvalidInput(
                "native update root must be absolute".to_owned(),
            ));
        }
        std::fs::create_dir_all(&root)?;
        Ok(Self { trusted_keys, root })
    }

    pub fn pending_path(&self) -> PathBuf {
        self.root.join("pending-update.json")
    }

    pub fn verify_and_stage(
        &self,
        manifest: SignedUpdateManifestV1,
        package_path: &Path,
        backend_protocol_version: u32,
    ) -> Result<PendingUpdateV1, ShellError> {
        manifest.validate(backend_protocol_version)?;
        self.trusted_keys.verify_message(
            &manifest.key_id,
            &manifest.signature_base64,
            manifest.signing_message().as_bytes(),
        )?;
        if !package_path.is_absolute() || !package_path.is_file() {
            return Err(ShellError::Update(
                "native update package must be an absolute regular file".to_owned(),
            ));
        }
        let metadata = std::fs::metadata(package_path)?;
        if metadata.len() == 0 || metadata.len() > MAX_PACKAGE_BYTES {
            return Err(ShellError::Update(format!(
                "native update package must be within 1..={MAX_PACKAGE_BYTES} bytes"
            )));
        }
        let observed_digest = digest_file(package_path)?;
        if observed_digest != manifest.package_digest {
            return Err(ShellError::Security(
                "native update package digest mismatch".to_owned(),
            ));
        }
        let staged_dir = self.root.join("staged");
        std::fs::create_dir_all(&staged_dir)?;
        let staged_package = staged_dir.join(format!("{}.package", manifest.package_digest));
        copy_and_sync(package_path, &staged_package)?;
        if digest_file(&staged_package)? != manifest.package_digest {
            let _ = std::fs::remove_file(&staged_package);
            return Err(ShellError::Security(
                "staged native update digest mismatch".to_owned(),
            ));
        }
        let pending = PendingUpdateV1 {
            schema: PENDING_SCHEMA.to_owned(),
            manifest,
            staged_package,
            target_path: None,
            backup_path: None,
            status: PendingUpdateStatus::Staged,
        };
        persist_json_atomic(&self.pending_path(), &pending)?;
        Ok(pending)
    }

    pub fn load_pending(&self) -> Result<Option<PendingUpdateV1>, ShellError> {
        let path = self.pending_path();
        if !path.exists() {
            return Ok(None);
        }
        let pending: PendingUpdateV1 = serde_json::from_slice(&std::fs::read(path)?)?;
        validate_pending(&pending)?;
        Ok(Some(pending))
    }

    pub fn clear_pending(&self) -> Result<(), ShellError> {
        let path = self.pending_path();
        if path.exists() {
            std::fs::remove_file(path)?;
        }
        Ok(())
    }

    pub fn rollback_unconfirmed(&self) -> Result<bool, ShellError> {
        let Some(pending) = self.load_pending()? else {
            return Ok(false);
        };
        if !matches!(
            pending.status,
            PendingUpdateStatus::ActivationStarted | PendingUpdateStatus::ActivatedUnconfirmed
        ) {
            return Ok(false);
        }
        let target = pending
            .target_path
            .as_deref()
            .ok_or_else(|| ShellError::Update("pending update lacks target path".to_owned()))?;
        let backup = pending
            .backup_path
            .as_deref()
            .ok_or_else(|| ShellError::Update("pending update lacks backup path".to_owned()))?;
        if !backup.is_file() {
            return Err(ShellError::Update(
                "native update predecessor backup is unavailable".to_owned(),
            ));
        }
        copy_and_sync(backup, target)?;
        self.clear_pending()?;
        Ok(true)
    }

    pub fn confirm_current_digest(&self, running_binary: &Path) -> Result<bool, ShellError> {
        let Some(pending) = self.load_pending()? else {
            return Ok(false);
        };
        if !matches!(pending.status, PendingUpdateStatus::ActivatedUnconfirmed) {
            return Ok(false);
        }
        if digest_file(running_binary)? != pending.manifest.package_digest {
            return Err(ShellError::Update(
                "running binary does not match the pending update digest".to_owned(),
            ));
        }
        self.clear_pending()?;
        Ok(true)
    }
}

pub fn activate_staged_update(
    pending_path: &Path,
    trusted_keys: &TrustedKeySet,
    target_path: &Path,
    backend_protocol_version: u32,
) -> Result<(), ShellError> {
    if !pending_path.is_absolute() || !target_path.is_absolute() {
        return Err(ShellError::InvalidInput(
            "updater paths must be absolute".to_owned(),
        ));
    }
    let mut pending: PendingUpdateV1 = serde_json::from_slice(&std::fs::read(pending_path)?)?;
    validate_pending(&pending)?;
    pending.manifest.validate(backend_protocol_version)?;
    trusted_keys.verify_message(
        &pending.manifest.key_id,
        &pending.manifest.signature_base64,
        pending.manifest.signing_message().as_bytes(),
    )?;
    if digest_file(&pending.staged_package)? != pending.manifest.package_digest {
        return Err(ShellError::Security(
            "staged update changed after verification".to_owned(),
        ));
    }
    if !target_path.is_file() {
        return Err(ShellError::Update(
            "native update target predecessor is unavailable".to_owned(),
        ));
    }
    let observed_predecessor = digest_file(target_path)?;
    if observed_predecessor != pending.manifest.predecessor_digest {
        return Err(ShellError::Security(
            "installed native predecessor digest mismatch".to_owned(),
        ));
    }
    let backup = target_path.with_extension(format!(
        "{}.predecessor",
        pending.manifest.predecessor_digest
    ));
    copy_and_sync(target_path, &backup)?;
    pending.target_path = Some(target_path.to_owned());
    pending.backup_path = Some(backup.clone());
    pending.status = PendingUpdateStatus::ActivationStarted;
    persist_json_atomic(pending_path, &pending)?;

    if let Err(error) = copy_and_sync(&pending.staged_package, target_path) {
        if backup.is_file() {
            let _ = copy_and_sync(&backup, target_path);
        }
        return Err(error);
    }
    if digest_file(target_path)? != pending.manifest.package_digest {
        if backup.is_file() {
            copy_and_sync(&backup, target_path)?;
        }
        return Err(ShellError::Security(
            "installed native update digest mismatch; predecessor restored".to_owned(),
        ));
    }
    pending.status = PendingUpdateStatus::ActivatedUnconfirmed;
    persist_json_atomic(pending_path, &pending)?;
    Ok(())
}

fn validate_pending(pending: &PendingUpdateV1) -> Result<(), ShellError> {
    if pending.schema != PENDING_SCHEMA || !pending.staged_package.is_absolute() {
        return Err(ShellError::Update(
            "pending native update record is invalid".to_owned(),
        ));
    }
    Ok(())
}

pub fn digest_file(path: &Path) -> Result<String, ShellError> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        total = total.saturating_add(read as u64);
        if total > MAX_PACKAGE_BYTES {
            return Err(ShellError::Update(format!(
                "file exceeds {MAX_PACKAGE_BYTES} bytes"
            )));
        }
        hasher.update(&buffer[..read]);
    }
    let digest = hasher.finalize();
    let mut out = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut out, "{byte:02x}");
    }
    Ok(out)
}

fn copy_and_sync(source: &Path, destination: &Path) -> Result<(), ShellError> {
    if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut source_file = File::open(source)?;
    let mut destination_file = AtomicWriteFile::open(destination)?;
    std::io::copy(&mut source_file, &mut destination_file)?;
    destination_file.flush()?;
    destination_file.sync_all()?;
    destination_file.commit()?;
    Ok(())
}

fn persist_json_atomic(path: &Path, value: &impl Serialize) -> Result<(), ShellError> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let bytes = serde_json::to_vec(value)?;
    let mut file = AtomicWriteFile::open(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    file.commit()?;
    Ok(())
}
