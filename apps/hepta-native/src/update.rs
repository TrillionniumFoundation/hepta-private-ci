use crate::PROTOCOL_VERSION;
use crate::now_unix_ms;
use crate::types::SignedUpdateManifest;
use crate::types::StagedUpdate;
use crate::types::UpdateManifest;
use crate::types::UpdateRequest;
use crate::types::UpdateResult;
use crate::validate_digest;
use crate::validate_stable_id;
use base64::Engine as _;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore as _;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;
use std::fs::File;
use std::io::Read as _;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;
use thiserror::Error;

const UPDATE_DOMAIN: &[u8] = b"hepta.ui.native.update-manifest.v1\0";
const MAX_UPDATE_LIFETIME_MS: u64 = 7 * 24 * 60 * 60 * 1000;
const KEYRING_SERVICE: &str = "hepta.native";
const UPDATE_KEYRING_ACCOUNT: &str = "update-public-key-v1";
const MAX_PACKAGE_BYTES: u64 = 1024 * 1024 * 1024;

#[derive(Debug, Error)]
pub enum UpdateError {
    #[error("update trust root is not configured")]
    Unavailable,
    #[error("update manifest is invalid")]
    InvalidManifest,
    #[error("update signature is invalid")]
    InvalidSignature,
    #[error("update package digest does not match")]
    PackageDigest,
    #[error("update predecessor does not match the running binary")]
    Predecessor,
    #[error("update does not match this platform, architecture, channel, or backend protocol")]
    Compatibility,
    #[error("update was selected by the same principal that generated it")]
    SelfSelected,
    #[error("OS code-signing or notarization verification failed")]
    OsSignature,
    #[error("update I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("update JSON failed: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Clone)]
pub struct UpdateVerifier {
    key_id: String,
    key: VerifyingKey,
}

impl std::fmt::Debug for UpdateVerifier {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("UpdateVerifier")
            .field("key_id", &self.key_id)
            .field("key", &"[PINNED]")
            .finish()
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredUpdateTrustRoot {
    key_id: String,
    public_key_b64: String,
}

impl UpdateVerifier {
    pub fn new(key_id: String, public_key: [u8; 32]) -> Result<Self, UpdateError> {
        if !validate_stable_id(&key_id) {
            return Err(UpdateError::InvalidManifest);
        }
        let key =
            VerifyingKey::from_bytes(&public_key).map_err(|_| UpdateError::InvalidManifest)?;
        if key.is_weak() {
            return Err(UpdateError::InvalidManifest);
        }
        Ok(Self { key_id, key })
    }

    pub fn load() -> Result<Option<Self>, UpdateError> {
        let trust = if let Ok(public_key_b64) = std::env::var("HEPTA_NATIVE_UPDATE_PUBLIC_KEY_B64")
        {
            Some(StoredUpdateTrustRoot {
                key_id: std::env::var("HEPTA_NATIVE_UPDATE_KEY_ID")
                    .map_err(|_| UpdateError::InvalidManifest)?,
                public_key_b64,
            })
        } else {
            let store = DefaultKeyringStore;
            match store.load(KEYRING_SERVICE, UPDATE_KEYRING_ACCOUNT) {
                Ok(Some(value)) => Some(serde_json::from_str(&value).map_err(UpdateError::Json)?),
                Ok(None) | Err(_) => None,
            }
        };
        let Some(trust) = trust else {
            return Ok(None);
        };
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(trust.public_key_b64)
            .map_err(|_| UpdateError::InvalidManifest)?;
        let key: [u8; 32] = bytes.try_into().map_err(|_| UpdateError::InvalidManifest)?;
        Self::new(trust.key_id, key).map(Some)
    }

    pub fn verify(&self, signed: &SignedUpdateManifest) -> Result<(), UpdateError> {
        let manifest = &signed.manifest;
        if manifest.schema_version != 1
            || manifest.key_id != self.key_id
            || !validate_stable_id(&manifest.version)
            || !validate_stable_id(&manifest.channel)
            || !validate_stable_id(&manifest.selected_by)
            || !validate_stable_id(&manifest.generator_principal)
            || !validate_digest(&manifest.package_sha256)
            || !validate_digest(&manifest.predecessor_sha256)
            || manifest.expires_at_unix_ms <= manifest.issued_at_unix_ms
            || manifest.expires_at_unix_ms - manifest.issued_at_unix_ms > MAX_UPDATE_LIFETIME_MS
        {
            return Err(UpdateError::InvalidManifest);
        }
        if manifest.selected_by == manifest.generator_principal {
            return Err(UpdateError::SelfSelected);
        }
        if manifest.platform != std::env::consts::OS
            || manifest.architecture != std::env::consts::ARCH
            || manifest.backend_protocol_version != PROTOCOL_VERSION
        {
            return Err(UpdateError::Compatibility);
        }
        let now = now_unix_ms().map_err(|_| UpdateError::InvalidManifest)?;
        if now < manifest.issued_at_unix_ms || now >= manifest.expires_at_unix_ms {
            return Err(UpdateError::InvalidManifest);
        }
        let signature_bytes = base64::engine::general_purpose::STANDARD
            .decode(&signed.signature_b64)
            .map_err(|_| UpdateError::InvalidSignature)?;
        let signature =
            Signature::from_slice(&signature_bytes).map_err(|_| UpdateError::InvalidSignature)?;
        self.key
            .verify_strict(&update_signing_bytes(manifest)?, &signature)
            .map_err(|_| UpdateError::InvalidSignature)
    }
}

pub struct UpdateManager {
    state_root: PathBuf,
    verifier: Option<UpdateVerifier>,
}

impl UpdateManager {
    pub fn new(state_root: PathBuf, verifier: Option<UpdateVerifier>) -> Self {
        Self {
            state_root,
            verifier,
        }
    }

    pub fn configured(&self) -> bool {
        self.verifier.is_some()
    }

    pub fn stage(
        &self,
        signed: SignedUpdateManifest,
        package_path: &Path,
        current_executable: &Path,
    ) -> Result<StagedUpdate, UpdateError> {
        let verifier = self.verifier.as_ref().ok_or(UpdateError::Unavailable)?;
        verifier.verify(&signed)?;
        let package_digest = sha256_file(package_path)?;
        if package_digest != signed.manifest.package_sha256 {
            return Err(UpdateError::PackageDigest);
        }
        let predecessor = sha256_file(current_executable)?;
        if predecessor != signed.manifest.predecessor_sha256 {
            return Err(UpdateError::Predecessor);
        }
        verify_os_signature_if_required(package_path)?;
        let stage_dir = self
            .state_root
            .join("updates")
            .join(format!("stage-{}", signed.manifest.package_sha256));
        std::fs::create_dir_all(&stage_dir)?;
        let file_name = current_executable
            .file_name()
            .ok_or(UpdateError::InvalidManifest)?;
        let staged_path = stage_dir.join(file_name);
        std::fs::copy(package_path, &staged_path)?;
        File::open(&staged_path)?.sync_all()?;
        if sha256_file(&staged_path)? != signed.manifest.package_sha256 {
            return Err(UpdateError::PackageDigest);
        }
        Ok(StagedUpdate {
            manifest: signed,
            staged_path,
            staged_sha256: package_digest,
        })
    }

    pub fn launch_updater(
        &self,
        staged: &StagedUpdate,
        current_executable: &Path,
    ) -> Result<PathBuf, UpdateError> {
        let verifier = self.verifier.as_ref().ok_or(UpdateError::Unavailable)?;
        verifier.verify(&staged.manifest)?;
        let update_root = self
            .state_root
            .join("updates")
            .join(format!("apply-{}", staged.manifest.manifest.package_sha256));
        std::fs::create_dir_all(&update_root)?;
        let file_name = current_executable
            .file_name()
            .ok_or(UpdateError::InvalidManifest)?;
        let backup_path = update_root.join(format!("predecessor-{}", file_name.to_string_lossy()));
        let ready_marker = update_root.join("ready.marker");
        let result_path = update_root.join("result.json");
        let request_path = update_root.join("request.json");
        let request = UpdateRequest {
            schema: "hepta.native.update-request.v1".to_string(),
            parent_pid: std::process::id(),
            signed_manifest: staged.manifest.clone(),
            staged_path: staged.staged_path.clone(),
            target_path: current_executable.to_path_buf(),
            backup_path,
            ready_marker,
            result_path,
        };
        write_json_sync(&request_path, &request)?;
        let helper_name = if cfg!(windows) {
            "hepta-native-updater.exe"
        } else {
            "hepta-native-updater"
        };
        let helper = current_executable
            .parent()
            .ok_or(UpdateError::InvalidManifest)?
            .join(helper_name);
        if !helper.is_file() {
            return Err(UpdateError::Unavailable);
        }
        Command::new(helper)
            .arg("--request")
            .arg(&request_path)
            .spawn()?;
        Ok(request_path)
    }
}

pub fn run_update_request(request_path: &Path) -> Result<UpdateResult, UpdateError> {
    let request: UpdateRequest = serde_json::from_slice(&std::fs::read(request_path)?)?;
    if request.schema != "hepta.native.update-request.v1" {
        return Err(UpdateError::InvalidManifest);
    }
    let verifier = UpdateVerifier::load()?.ok_or(UpdateError::Unavailable)?;
    verifier.verify(&request.signed_manifest)?;
    let manifest = &request.signed_manifest.manifest;
    if sha256_file(&request.staged_path)? != manifest.package_sha256 {
        return Err(UpdateError::PackageDigest);
    }
    if sha256_file(&request.target_path)? != manifest.predecessor_sha256 {
        return Err(UpdateError::Predecessor);
    }
    verify_os_signature_if_required(&request.staged_path)?;
    std::fs::copy(&request.target_path, &request.backup_path)?;
    File::open(&request.backup_path)?.sync_all()?;

    let next_path = request.target_path.with_extension("hepta-next");
    let retired_path = request.target_path.with_extension("hepta-retired");
    let _ = std::fs::remove_file(&next_path);
    let _ = std::fs::remove_file(&retired_path);
    std::fs::copy(&request.staged_path, &next_path)?;
    File::open(&next_path)?.sync_all()?;

    if cfg!(windows) {
        retry_rename(&request.target_path, &retired_path, Duration::from_secs(30))?;
        if let Err(error) = retry_rename(&next_path, &request.target_path, Duration::from_secs(5)) {
            let _ = retry_rename(&retired_path, &request.target_path, Duration::from_secs(5));
            return Err(error);
        }
    } else {
        retry_rename(&next_path, &request.target_path, Duration::from_secs(5))?;
    }

    if sha256_file(&request.target_path)? != manifest.package_sha256 {
        restore_predecessor(&request)?;
        return Err(UpdateError::PackageDigest);
    }

    let _ = std::fs::remove_file(&request.ready_marker);
    let mut child = Command::new(&request.target_path)
        .arg("--post-update-ready")
        .arg(&request.ready_marker)
        .spawn()?;
    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        if request.ready_marker.is_file() {
            let result = UpdateResult {
                schema: "hepta.native.update-result.v1".to_string(),
                status: "succeeded".to_string(),
                package_sha256: manifest.package_sha256.clone(),
                predecessor_sha256: manifest.predecessor_sha256.clone(),
                detail: "post-update-ready observed".to_string(),
            };
            write_json_sync(&request.result_path, &result)?;
            let _ = std::fs::remove_file(&retired_path);
            return Ok(result);
        }
        if let Some(status) = child.try_wait()? {
            if !status.success() {
                break;
            }
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
    let _ = child.wait();
    restore_predecessor(&request)?;
    let result = UpdateResult {
        schema: "hepta.native.update-result.v1".to_string(),
        status: "quarantined".to_string(),
        package_sha256: manifest.package_sha256.clone(),
        predecessor_sha256: manifest.predecessor_sha256.clone(),
        detail: "post-update-ready not observed; predecessor restored".to_string(),
    };
    write_json_sync(&request.result_path, &result)?;
    Ok(result)
}

fn restore_predecessor(request: &UpdateRequest) -> Result<(), UpdateError> {
    let restore = request.target_path.with_extension("hepta-restore");
    let _ = std::fs::remove_file(&restore);
    std::fs::copy(&request.backup_path, &restore)?;
    File::open(&restore)?.sync_all()?;
    if cfg!(windows) {
        let retired = request.target_path.with_extension("hepta-failed");
        let _ = std::fs::remove_file(&retired);
        let _ = retry_rename(&request.target_path, &retired, Duration::from_secs(5));
        retry_rename(&restore, &request.target_path, Duration::from_secs(5))?;
        let _ = std::fs::remove_file(retired);
    } else {
        retry_rename(&restore, &request.target_path, Duration::from_secs(5))?;
    }
    if sha256_file(&request.target_path)? != request.signed_manifest.manifest.predecessor_sha256 {
        return Err(UpdateError::Predecessor);
    }
    Ok(())
}

fn retry_rename(source: &Path, destination: &Path, timeout: Duration) -> Result<(), UpdateError> {
    let deadline = Instant::now() + timeout;
    loop {
        match std::fs::rename(source, destination) {
            Ok(()) => return Ok(()),
            Err(error) if Instant::now() < deadline => {
                let _ = error;
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(error) => return Err(UpdateError::Io(error)),
        }
    }
}

pub fn update_signing_bytes(manifest: &UpdateManifest) -> Result<Vec<u8>, UpdateError> {
    let message = format!(
        "schema_version={}\nkey_id={}\nversion={}\nchannel={}\nplatform={}\narchitecture={}\npackage_sha256={}\npredecessor_sha256={}\nbackend_protocol_version={}\nselected_by={}\ngenerator_principal={}\nissued_at_unix_ms={}\nexpires_at_unix_ms={}\n",
        manifest.schema_version,
        manifest.key_id,
        manifest.version,
        manifest.channel,
        manifest.platform,
        manifest.architecture,
        manifest.package_sha256,
        manifest.predecessor_sha256,
        manifest.backend_protocol_version,
        manifest.selected_by,
        manifest.generator_principal,
        manifest.issued_at_unix_ms,
        manifest.expires_at_unix_ms,
    );
    let mut bytes = UPDATE_DOMAIN.to_vec();
    bytes.extend(message.as_bytes());
    Ok(bytes)
}

pub fn sha256_file(path: &Path) -> Result<String, UpdateError> {
    let metadata = std::fs::metadata(path)?;
    if !metadata.is_file() || metadata.len() > MAX_PACKAGE_BYTES {
        return Err(UpdateError::PackageDigest);
    }
    let mut file = File::open(path)?;
    let mut hash = Sha256::new();
    let mut buffer = [0_u8; 128 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
    }
    Ok(hex::encode(hash.finalize()))
}

fn write_json_sync(path: &Path, value: &impl Serialize) -> Result<(), UpdateError> {
    let bytes = serde_json::to_vec_pretty(value)?;
    let mut file = File::create(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(())
}

fn verify_os_signature_if_required(path: &Path) -> Result<(), UpdateError> {
    let required = std::env::var("HEPTA_NATIVE_REQUIRE_OS_CODESIGN").is_ok_and(|value| {
        matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes"
        )
    });
    if !required {
        return Ok(());
    }

    #[cfg(target_os = "macos")]
    {
        let code = Command::new("/usr/bin/codesign")
            .args(["--verify", "--deep", "--strict", "--verbose=2"])
            .arg(path)
            .status()?;
        let notarized = Command::new("/usr/sbin/spctl")
            .args(["--assess", "--type", "execute"])
            .arg(path)
            .status()?;
        if !code.success() || !notarized.success() {
            return Err(UpdateError::OsSignature);
        }
    }

    #[cfg(target_os = "windows")]
    {
        let escaped = path.to_string_lossy().replace('\'', "''");
        let script = format!(
            "$s=Get-AuthenticodeSignature -LiteralPath '{escaped}'; if ($s.Status -ne 'Valid') {{ exit 7 }}"
        );
        let status = Command::new("powershell.exe")
            .args(["-NoProfile", "-NonInteractive", "-Command", &script])
            .status()?;
        if !status.success() {
            return Err(UpdateError::OsSignature);
        }
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        // Linux packages are authenticated by the pinned Ed25519 update root.
        // Distribution-specific package signatures can be layered by release CI.
        let _ = path;
    }

    Ok(())
}
