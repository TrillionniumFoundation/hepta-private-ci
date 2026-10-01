use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use crate::error::ShellError;
use crate::model::validate_digest;
use crate::model::validate_stable_id;
use crate::private_state::PrivateStateRoot;
use crate::security::TrustedKeySet;
use crate::security::now_unix_ms;

const UPDATE_SCHEMA: &str = "hepta.native-update.v1";
const PENDING_SCHEMA: &str = "hepta.native-pending-update.v1";
use crate::update_handoff::UpdateHandoff;
use crate::update_handoff::UpdateReadiness;
#[path = "update_activation.rs"]
mod activation;
#[path = "update_backup_policy.rs"]
mod backup_policy;
#[path = "update_confirmation.rs"]
mod confirmation;
#[path = "update_stage_policy.rs"]
mod stage_policy;
pub use crate::update_lock::UpdateLock;
use crate::update_storage::MAX_PACKAGE_BYTES;
use crate::update_storage::copy_and_sync;
use crate::update_storage::copy_to_private_root;
pub use crate::update_storage::digest_file;
use crate::update_storage::digest_private_file;
use crate::update_storage::lock_update_root;
use crate::update_storage::lock_update_runner;
use crate::update_storage::persist_json_atomic;
use crate::update_storage::read_private_json;
use crate::update_storage::remove_private_file;
pub use activation::activate_staged_update;
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PendingUpdateStatus {
    Staged,
    ActivationStarted,
    ActivatedUnconfirmed,
    RollbackStarted,
    RolledBack,
    RecoveryRequired,
    Confirmed,
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
    #[serde(default)]
    pub transition_unix_ms: u64,
    #[serde(default)]
    pub recovery_reason: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub handoff: Option<UpdateHandoff>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub readiness: Option<UpdateReadiness>,
}

#[derive(Debug, Clone)]
pub struct UpdateManager {
    trusted_keys: TrustedKeySet,
    root: PathBuf,
    private_root: PrivateStateRoot,
}

impl UpdateManager {
    pub fn new(trusted_keys: TrustedKeySet, root: PathBuf) -> Result<Self, ShellError> {
        if !root.is_absolute() {
            return Err(ShellError::InvalidInput(
                "native update root must be absolute".to_owned(),
            ));
        }
        let private_root = PrivateStateRoot::open(root.clone())?;
        Ok(Self {
            trusted_keys,
            root,
            private_root,
        })
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
        self.verify_and_stage_at_boundary(manifest, package_path, backend_protocol_version, || {
            Ok(())
        })
    }

    fn verify_and_stage_at_boundary(
        &self,
        manifest: SignedUpdateManifestV1,
        package_path: &Path,
        backend_protocol_version: u32,
        observe: impl FnOnce() -> Result<(), ShellError>,
    ) -> Result<PendingUpdateV1, ShellError> {
        self.private_root.verify()?;
        let _lock = lock_update_root(&self.private_root)?;
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
        if let Some(existing) = self.load_pending()? {
            if !matches!(
                existing.status,
                PendingUpdateStatus::RolledBack | PendingUpdateStatus::Confirmed
            ) {
                return Err(ShellError::Update(
                    "an unresolved native update already exists; reconcile it before staging another"
                        .to_owned(),
                ));
            }
            persist_json_atomic(
                &self.private_root,
                &self.root.join("last-update-result.json"),
                &existing,
            )?;
            self.clear_pending_locked()?;
        }
        let staged_root = self.private_root.child_create("staged")?;
        stage_policy::admit_staged_package(&staged_root, &manifest.package_digest)?;
        let staged_package = staged_root
            .path()
            .join(format!("{}.package", manifest.package_digest));
        copy_to_private_root(
            &staged_root,
            package_path,
            &staged_package,
            &manifest.package_digest,
        )?;
        self.private_root.verify()?;
        if digest_private_file(&staged_root, &staged_package)? != manifest.package_digest {
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
            transition_unix_ms: now_unix_ms()?,
            recovery_reason: None,
            handoff: None,
            readiness: None,
        };
        observe()?;
        persist_json_atomic(&self.private_root, &self.pending_path(), &pending)?;
        Ok(pending)
    }

    pub fn load_pending(&self) -> Result<Option<PendingUpdateV1>, ShellError> {
        self.private_root.verify()?;
        let path = self.pending_path();
        let Some(pending): Option<PendingUpdateV1> =
            read_private_json(&self.private_root, &path, 64 * 1024)?
        else {
            return Ok(None);
        };
        validate_pending(&pending)?;
        // Expired admitted requests may recover, but cannot freshly activate.
        self.trusted_keys.verify_message(
            &pending.manifest.key_id,
            &pending.manifest.signature_base64,
            pending.manifest.signing_message().as_bytes(),
        )?;
        Ok(Some(pending))
    }

    pub fn clear_pending(&self) -> Result<(), ShellError> {
        self.private_root.verify()?;
        let _lock = lock_update_root(&self.private_root)?;
        if self.load_pending()?.is_some_and(|pending| {
            !matches!(
                pending.status,
                PendingUpdateStatus::Staged
                    | PendingUpdateStatus::RolledBack
                    | PendingUpdateStatus::Confirmed
            )
        }) {
            return Err(ShellError::Update(
                "cannot erase unresolved activation or recovery state".to_owned(),
            ));
        }
        self.clear_pending_locked()
    }

    fn clear_pending_locked(&self) -> Result<(), ShellError> {
        self.private_root.verify()?;
        if let Some(pending) = self.load_pending()? {
            let owned_package = self
                .root
                .join("staged")
                .join(format!("{}.package", pending.manifest.package_digest));
            // Only the exact private, digest-bound staging file belongs to this
            // lifecycle. Foreign paths or replaced content are preserved.
            if pending.staged_package == owned_package {
                let staged_root = match self.private_root.child_open("staged") {
                    Ok(root) => Some(root),
                    // Earlier versions created this child with the default
                    // directory mode. Migrate only a verified, owned child.
                    Err(ShellError::Security(_)) => Some(self.private_root.child_create("staged")?),
                    Err(ShellError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
                        None
                    }
                    Err(error) => return Err(error),
                };
                if let Some(root) = staged_root
                    && matches!(digest_private_file(&root, &owned_package), Ok(digest) if digest == pending.manifest.package_digest)
                {
                    self.private_root.verify()?;
                    remove_private_file(&root, &owned_package)?;
                    self.private_root.verify()?;
                }
            }
            // Predecessor backups live beside the operator-selected installed
            // binary. Preserve rollback evidence until an explicit retention
            // policy authorizes discarding it; pending clearance is not that
            // authority.
        }
        remove_private_file(&self.private_root, &self.pending_path())
    }

    pub fn recover_interrupted_activation(&self) -> Result<bool, ShellError> {
        self.private_root.verify()?;
        let Some(pending) = self.load_pending()? else {
            return Ok(false);
        };
        match pending.status {
            PendingUpdateStatus::Staged
            | PendingUpdateStatus::RolledBack
            | PendingUpdateStatus::Confirmed => Ok(false),
            PendingUpdateStatus::ActivationStarted
            | PendingUpdateStatus::ActivatedUnconfirmed
            | PendingUpdateStatus::RollbackStarted
            | PendingUpdateStatus::RecoveryRequired => self.rollback_unconfirmed(),
        }
    }

    pub fn rollback_unconfirmed(&self) -> Result<bool, ShellError> {
        self.private_root.verify()?;
        let _lock = lock_update_root(&self.private_root)?;
        let Some(mut pending) = self.load_pending()? else {
            return Ok(false);
        };
        if !matches!(
            pending.status,
            PendingUpdateStatus::ActivationStarted
                | PendingUpdateStatus::ActivatedUnconfirmed
                | PendingUpdateStatus::RollbackStarted
                | PendingUpdateStatus::RecoveryRequired
        ) {
            return Ok(false);
        }
        let target = pending
            .target_path
            .clone()
            .ok_or_else(|| ShellError::Update("pending update lacks target path".to_owned()))?;
        let backup = pending
            .backup_path
            .clone()
            .ok_or_else(|| ShellError::Update("pending update lacks backup path".to_owned()))?;
        transition_pending(
            &self.private_root,
            &self.pending_path(),
            &mut pending,
            PendingUpdateStatus::RollbackStarted,
            None,
        )?;
        if !backup.is_file() {
            return recovery_required(
                &self.private_root,
                &self.pending_path(),
                &mut pending,
                "native update predecessor backup is unavailable",
            );
        }
        let backup_digest = match digest_file(&backup) {
            Ok(digest) => digest,
            Err(error) => {
                return recovery_required(
                    &self.private_root,
                    &self.pending_path(),
                    &mut pending,
                    &format!("predecessor backup could not be read safely: {error}"),
                );
            }
        };
        if backup_digest != pending.manifest.predecessor_digest {
            return recovery_required(
                &self.private_root,
                &self.pending_path(),
                &mut pending,
                "native update predecessor backup digest mismatch",
            );
        }
        let current_digest = match digest_file(&target) {
            Ok(digest) => digest,
            Err(_) => {
                return recovery_required(
                    &self.private_root,
                    &self.pending_path(),
                    &mut pending,
                    "cannot identify installed binary before rollback",
                );
            }
        };
        if current_digest != pending.manifest.package_digest
            && current_digest != pending.manifest.predecessor_digest
        {
            return recovery_required(
                &self.private_root,
                &self.pending_path(),
                &mut pending,
                "rollback refused: installed binary is neither candidate nor predecessor",
            );
        }
        if let Err(error) = copy_and_sync(&backup, &target, &pending.manifest.predecessor_digest) {
            let message = format!("native update rollback copy failed: {error}");
            return recovery_required(
                &self.private_root,
                &self.pending_path(),
                &mut pending,
                &message,
            );
        }
        if digest_file(&target)? != pending.manifest.predecessor_digest {
            return recovery_required(
                &self.private_root,
                &self.pending_path(),
                &mut pending,
                "native update rollback did not restore the admitted predecessor digest",
            );
        }
        transition_pending(
            &self.private_root,
            &self.pending_path(),
            &mut pending,
            PendingUpdateStatus::RolledBack,
            None,
        )?;
        Ok(true)
    }

    /// Serialize helper orchestration and ordinary startup recovery. Short state
    /// transactions still use the separate owner lock. Retain the opaque guard
    /// until orchestration completes; dropping it explicitly releases ownership.
    pub fn lock_runner(&self) -> Result<UpdateLock, ShellError> {
        self.private_root.verify()?;
        lock_update_runner(&self.private_root)
    }

    pub fn prepare_restart(&self, arguments: &[String]) -> Result<UpdateHandoff, ShellError> {
        let _lock = lock_update_root(&self.private_root)?;
        let mut pending = self
            .load_pending()?
            .ok_or_else(|| ShellError::Update("missing pending activation".into()))?;
        if pending.status != PendingUpdateStatus::ActivatedUnconfirmed {
            return Err(ShellError::Update(
                "restart requires activated-unconfirmed state".into(),
            ));
        }
        let handoff = UpdateHandoff::issue(arguments)?;
        pending.handoff = Some(handoff.clone());
        pending.readiness = None;
        persist_json_atomic(&self.private_root, &self.pending_path(), &pending)?;
        Ok(handoff)
    }

    pub fn validate_running_handoff(&self, handoff: &UpdateHandoff) -> Result<(), ShellError> {
        let pending = self
            .load_pending()?
            .ok_or_else(|| ShellError::Update("missing pending activation".into()))?;
        validate_running_handoff(&pending, handoff)
    }
}

fn validate_pending(pending: &PendingUpdateV1) -> Result<(), ShellError> {
    if pending.schema != PENDING_SCHEMA || !pending.staged_package.is_absolute() {
        return Err(ShellError::Update(
            "pending native update record is invalid".to_owned(),
        ));
    }
    if pending.status == PendingUpdateStatus::Confirmed && pending.readiness.is_none() {
        return Err(ShellError::Update(
            "confirmed update lacks product readiness".into(),
        ));
    }
    if let Some(ready) = &pending.readiness {
        if pending.handoff.is_none()
            || !matches!(
                pending.status,
                PendingUpdateStatus::ActivatedUnconfirmed | PendingUpdateStatus::Confirmed
            )
            || ready.process_id == 0
            || ready.view_revision == 0
            || ready.binary_digest != pending.manifest.package_digest
        {
            return Err(ShellError::Update(
                "confirmed update readiness is not bound to the candidate".into(),
            ));
        }
        ready.session.validate()?;
        validate_digest(&ready.view_digest, "update readiness view digest")?;
    }
    let activated = !matches!(pending.status, PendingUpdateStatus::Staged);
    if activated
        && (!pending
            .target_path
            .as_ref()
            .is_some_and(|path| path.is_absolute())
            || !pending
                .backup_path
                .as_ref()
                .is_some_and(|path| path.is_absolute()))
    {
        return Err(ShellError::Update(
            "activated native update lacks absolute target/backup identity".to_owned(),
        ));
    }
    Ok(())
}

fn transition_pending(
    root: &PrivateStateRoot,
    pending_path: &Path,
    pending: &mut PendingUpdateV1,
    status: PendingUpdateStatus,
    recovery_reason: Option<String>,
) -> Result<(), ShellError> {
    pending.status = status;
    if matches!(
        status,
        PendingUpdateStatus::RollbackStarted
            | PendingUpdateStatus::RolledBack
            | PendingUpdateStatus::RecoveryRequired
    ) {
        pending.readiness = None;
    }
    if matches!(
        status,
        PendingUpdateStatus::RolledBack | PendingUpdateStatus::RecoveryRequired
    ) {
        // The admitted predecessor may implement the original v1 pending schema.
        pending.handoff = None;
    }
    pending.transition_unix_ms = now_unix_ms()?;
    pending.recovery_reason = recovery_reason;
    persist_json_atomic(root, pending_path, pending)
}

fn recovery_required<T>(
    root: &PrivateStateRoot,
    pending_path: &Path,
    pending: &mut PendingUpdateV1,
    reason: &str,
) -> Result<T, ShellError> {
    transition_pending(
        root,
        pending_path,
        pending,
        PendingUpdateStatus::RecoveryRequired,
        Some(reason.to_owned()),
    )?;
    Err(ShellError::Update(format!(
        "{reason}; update remains recovery_required"
    )))
}

fn rollback_after_activation_failure(
    root: &PrivateStateRoot,
    pending_path: &Path,
    pending: &mut PendingUpdateV1,
    target: &Path,
    backup: &Path,
    reason: &str,
) -> Result<(), ShellError> {
    transition_pending(
        root,
        pending_path,
        pending,
        PendingUpdateStatus::RollbackStarted,
        Some(reason.to_owned()),
    )?;
    if !matches!(digest_file(backup), Ok(digest) if digest == pending.manifest.predecessor_digest) {
        return recovery_required(
            root,
            pending_path,
            pending,
            "activation failed and predecessor backup is unavailable or invalid",
        );
    }
    let current_digest = match digest_file(target) {
        Ok(digest) => digest,
        Err(_) => {
            return recovery_required(
                root,
                pending_path,
                pending,
                "activation failed and installed binary cannot be identified before rollback",
            );
        }
    };
    if current_digest != pending.manifest.package_digest
        && current_digest != pending.manifest.predecessor_digest
    {
        return recovery_required(
            root,
            pending_path,
            pending,
            "activation failed; rollback refused because installed binary is neither candidate nor predecessor",
        );
    }
    if let Err(error) = copy_and_sync(backup, target, &pending.manifest.predecessor_digest) {
        return recovery_required(
            root,
            pending_path,
            pending,
            &format!("activation failed and predecessor rollback copy failed: {error}"),
        );
    }
    if !matches!(digest_file(target), Ok(digest) if digest == pending.manifest.predecessor_digest) {
        return recovery_required(
            root,
            pending_path,
            pending,
            "activation failed and predecessor rollback digest could not be proved",
        );
    }
    transition_pending(
        root,
        pending_path,
        pending,
        PendingUpdateStatus::RolledBack,
        Some(reason.to_owned()),
    )
}

fn validate_running_handoff(
    pending: &PendingUpdateV1,
    handoff: &UpdateHandoff,
) -> Result<(), ShellError> {
    if pending.status != PendingUpdateStatus::ActivatedUnconfirmed
        || pending.handoff.as_ref() != Some(handoff)
    {
        return Err(ShellError::Update(
            "startup does not match the pending update handoff".into(),
        ));
    }
    let running = std::env::current_exe()?;
    let target = pending
        .target_path
        .as_ref()
        .ok_or_else(|| ShellError::Update("activation lacks target identity".into()))?;
    if std::fs::canonicalize(&running)? != std::fs::canonicalize(target)?
        || crate::update_storage::running_binary_digest()? != pending.manifest.package_digest
    {
        return Err(ShellError::Update(
            "only the installed candidate process may confirm startup".into(),
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "updater_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "update_root_tests.rs"]
mod root_tests;
