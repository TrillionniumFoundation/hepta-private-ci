//! One activation transaction retains the caller's pinned update namespace.
use super::PendingUpdateStatus;
use super::PendingUpdateV1;
use super::UpdateManager;
use super::backup_policy;
use super::rollback_after_activation_failure;
use super::transition_pending;
use super::validate_pending;
use crate::error::ShellError;
use crate::private_state::PrivateStateRoot;
use crate::security::TrustedKeySet;
use crate::update_storage::copy_and_sync;
use crate::update_storage::copy_from_private_root;
use crate::update_storage::digest_file;
use crate::update_storage::digest_private_file;
use crate::update_storage::lock_update_root;
use crate::update_storage::read_private_json;
use std::path::Path;

impl UpdateManager {
    pub fn activate_staged_update(&self, target: &Path, protocol: u32) -> Result<(), ShellError> {
        activate_in_root(
            &self.private_root,
            &self.pending_path(),
            &self.trusted_keys,
            target,
            protocol,
        )
    }
}

/// A standalone caller establishes one root identity at entry. Existing owners
/// use UpdateManager::activate_staged_update instead of reopening this namespace.
pub fn activate_staged_update(
    pending_path: &Path,
    trusted_keys: &TrustedKeySet,
    target_path: &Path,
    backend_protocol_version: u32,
) -> Result<(), ShellError> {
    let parent = pending_path
        .parent()
        .ok_or_else(|| ShellError::Update("pending update has no parent directory".into()))?;
    let root = PrivateStateRoot::open_existing(parent.to_path_buf())?;
    activate_in_root(
        &root,
        pending_path,
        trusted_keys,
        target_path,
        backend_protocol_version,
    )
}

fn activate_in_root(
    private_root: &PrivateStateRoot,
    pending_path: &Path,
    trusted_keys: &TrustedKeySet,
    target_path: &Path,
    backend_protocol_version: u32,
) -> Result<(), ShellError> {
    if !pending_path.is_absolute() || !target_path.is_absolute() {
        return Err(ShellError::InvalidInput(
            "updater paths must be absolute".into(),
        ));
    }
    private_root.verify()?;
    let _lock = lock_update_root(private_root)?;
    let mut pending: PendingUpdateV1 = read_private_json(private_root, pending_path, 64 * 1024)?
        .ok_or_else(|| ShellError::Update("pending activation record is missing".into()))?;
    validate_pending(&pending)?;
    if pending.status != PendingUpdateStatus::Staged {
        return Err(ShellError::Update(format!(
            "native update activation requires staged state, found {:?}",
            pending.status
        )));
    }
    pending.manifest.validate(backend_protocol_version)?;
    trusted_keys.verify_message(
        &pending.manifest.key_id,
        &pending.manifest.signature_base64,
        pending.manifest.signing_message().as_bytes(),
    )?;
    let staged_root = private_root.child_create("staged")?;
    let owned_package = staged_root
        .path()
        .join(format!("{}.package", pending.manifest.package_digest));
    if pending.staged_package != owned_package
        || digest_private_file(&staged_root, &owned_package)? != pending.manifest.package_digest
    {
        return Err(ShellError::Security(
            "staged update changed after verification or left its private root".to_owned(),
        ));
    }
    private_root.verify()?;
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
    backup_policy::admit_predecessor_backup(
        target_path,
        &backup,
        &pending.manifest.predecessor_digest,
    )?;
    copy_and_sync(target_path, &backup, &pending.manifest.predecessor_digest)?;
    pending.target_path = Some(target_path.to_owned());
    pending.backup_path = Some(backup.clone());
    transition_pending(
        private_root,
        pending_path,
        &mut pending,
        PendingUpdateStatus::ActivationStarted,
        None,
    )?;

    if let Err(error) = copy_from_private_root(
        &staged_root,
        &pending.staged_package,
        target_path,
        &pending.manifest.package_digest,
    ) {
        let reason = format!("native update activation copy failed: {error}");
        rollback_after_activation_failure(
            private_root,
            pending_path,
            &mut pending,
            target_path,
            &backup,
            &reason,
        )?;
        return Err(error);
    }
    let installed = match digest_file(target_path) {
        Ok(digest) => digest,
        Err(error) => {
            rollback_after_activation_failure(
                private_root,
                pending_path,
                &mut pending,
                target_path,
                &backup,
                &format!("installed candidate could not be read after replacement: {error}"),
            )?;
            return Err(error);
        }
    };
    if installed != pending.manifest.package_digest {
        let reason = "installed native update digest mismatch after replacement";
        rollback_after_activation_failure(
            private_root,
            pending_path,
            &mut pending,
            target_path,
            &backup,
            reason,
        )?;
        return Err(ShellError::Security(
            "installed native update digest mismatch; predecessor rollback recorded".to_owned(),
        ));
    }
    transition_pending(
        private_root,
        pending_path,
        &mut pending,
        PendingUpdateStatus::ActivatedUnconfirmed,
        None,
    )?;
    Ok(())
}
