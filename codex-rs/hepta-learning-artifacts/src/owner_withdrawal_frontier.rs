//! The same exclusive Artifact writer durably publishes its withdrawal
//! frontier. Original readers refuse unresolved intent; only that writer repairs.

use crate::durable_snapshots::decode_withdrawal_snapshot;
use crate::durable_snapshots::encode_withdrawal_snapshot;

use super::*;

const CURRENT: &str = "withdrawal.CURRENT";
const PENDING: &str = "withdrawal.pending";
const NEXT: &str = "withdrawal.next";
const LIMIT: usize = 8 * 1024 * 1024;

pub(super) fn require_extension(
    before: &DatasetWithdrawalRegistry,
    next: &DatasetWithdrawalRegistry,
) -> Result<(), ArtifactOwnerHostError> {
    let old = before.snapshot();
    let new = next.snapshot();
    if before.scope_digest().is_none()
        || before.scope_digest() != next.scope_digest()
        || !new.records().starts_with(old.records())
    {
        return Err(ArtifactOwnerHostError::CurrentHeadRollback);
    }
    Ok(())
}

fn encode(
    value: &DatasetWithdrawalRegistry,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactOwnerHostError> {
    if binding.is_zero() {
        return Err(ArtifactOwnerHostError::CurrentHeadContext);
    }
    Ok(encode_withdrawal_snapshot(value, binding)?)
}

fn decode(
    bytes: &[u8],
    binding: Digest32,
) -> Result<DatasetWithdrawalRegistry, ArtifactOwnerHostError> {
    let value = decode_withdrawal_snapshot(bytes, binding)?;
    if encode(&value, binding)? != bytes {
        return Err(ArtifactOwnerHostError::CurrentHeadContext);
    }
    Ok(value)
}

fn optional(root: &Path, name: &str) -> Result<Option<Vec<u8>>, ArtifactOwnerHostError> {
    match fs::symlink_metadata(root.join(name)) {
        Ok(_) => Ok(Some(read_small_record(&root.join(name), LIMIT)?)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}

fn sync_root(root: &Path) -> Result<(), ArtifactOwnerHostError> {
    #[cfg(unix)]
    File::open(root)?
        .sync_all()
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    #[cfg(not(unix))]
    let _ = root;
    Ok(())
}

fn intent(binding: Digest32, before: Option<&[u8]>, next: &[u8]) -> Vec<u8> {
    format!(
        "HEPTA-WITHDRAWAL-PUBLISH-V1\n{binding}\n{}\n{}\n",
        before.map_or(Digest32::ZERO, Digest32::of_bytes),
        Digest32::of_bytes(next)
    )
    .into_bytes()
}

fn parse_intent(
    bytes: &[u8],
    binding: Digest32,
) -> Result<(Digest32, Digest32), ArtifactOwnerHostError> {
    let raw = std::str::from_utf8(bytes).map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
    let fields: Vec<_> = raw.lines().collect();
    if fields.len() != 4
        || fields[0] != "HEPTA-WITHDRAWAL-PUBLISH-V1"
        || fields[1] != binding.to_string()
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    let before = parse_digest(fields[2])?;
    let next = parse_digest(fields[3])?;
    if next.is_zero()
        || format!("HEPTA-WITHDRAWAL-PUBLISH-V1\n{binding}\n{before}\n{next}\n").as_bytes() != bytes
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    Ok((before, next))
}

/// Only the same exclusive writer may complete its exact incomplete staging
/// prefix. CURRENT is never truncated or repaired by this helper.
fn complete_staging(path: &Path, expected: &[u8]) -> Result<(), ArtifactOwnerHostError> {
    match fs::symlink_metadata(path) {
        Ok(_) => {
            let existing = read_small_record(path, LIMIT)?;
            if !expected.starts_with(&existing) {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true).truncate(true);
    #[cfg(unix)]
    options.mode(0o600);
    let mut file = options.open(path)?;
    file.write_all(expected)
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    file.sync_all()
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    Ok(())
}

fn commit(
    root: &Path,
    binding: Digest32,
    before: Option<&[u8]>,
    next: &[u8],
) -> Result<(), ArtifactOwnerHostError> {
    let request = intent(binding, before, next);
    complete_staging(&root.join(PENDING), &request)?;
    sync_root(root)?;
    let actual = optional(root, CURRENT)?;
    if actual.as_deref() != before && actual.as_deref() != Some(next) {
        return Err(ArtifactOwnerHostError::CurrentHeadConflict);
    }
    if actual.as_deref() != Some(next) {
        complete_staging(&root.join(NEXT), next)?;
        fs::rename(root.join(NEXT), root.join(CURRENT))
            .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        sync_root(root)?;
    } else if let Some(staged) = optional(root, NEXT)? {
        if !next.starts_with(&staged) {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        fs::remove_file(root.join(NEXT))?;
    }
    if optional(root, CURRENT)?.as_deref() != Some(next) {
        return Err(ArtifactOwnerHostError::Indeterminate);
    }
    fs::remove_file(root.join(PENDING)).map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    sync_root(root)?;
    Ok(())
}

/// Reads the original current physical frontier, never a caller-supplied
/// immutable snapshot. Any unresolved staging or changing bytes are refused.
pub(super) fn read_original(
    root: &Path,
    binding: Digest32,
) -> Result<DatasetWithdrawalRegistry, ArtifactOwnerHostError> {
    if optional(root, PENDING)?.is_some() || optional(root, NEXT)?.is_some() {
        return Err(ArtifactOwnerHostError::Indeterminate);
    }
    let first = optional(root, CURRENT)?.ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
    let value = decode(&first, binding)?;
    if optional(root, CURRENT)?.as_ref() != Some(&first)
        || optional(root, PENDING)?.is_some()
        || optional(root, NEXT)?.is_some()
    {
        return Err(ArtifactOwnerHostError::Indeterminate);
    }
    Ok(value)
}

impl LearningArtifactOwnerHost {
    pub(crate) fn recover_original_withdrawal_frontier(
        &self,
        configured: &DatasetWithdrawalRegistry,
        binding: Digest32,
    ) -> Result<DatasetWithdrawalRegistry, ArtifactOwnerHostError> {
        if configured.scope_digest() != Some(self.verifier.trust.withdrawal_scope_digest) {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        let target = encode(configured, binding)?;
        let current = optional(&self.root, CURRENT)?;
        let retained = current
            .as_ref()
            .map(|bytes| decode(bytes, binding))
            .transpose()?;
        if let Some(pending) = optional(&self.root, PENDING)? {
            // Complete intent plus already-renamed CURRENT: recover that same
            // exact target even if the startup floor was the older prefix.
            if let Ok((_, target_digest)) = parse_intent(&pending, binding)
                && current
                    .as_ref()
                    .is_some_and(|bytes| Digest32::of_bytes(bytes) == target_digest)
            {
                let actual = retained
                    .as_ref()
                    .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
                require_extension(configured, actual)?;
                if let Some(staged) = optional(&self.root, NEXT)? {
                    if !current
                        .as_ref()
                        .is_some_and(|bytes| bytes.starts_with(&staged))
                    {
                        return Err(ArtifactOwnerHostError::CheckpointMismatch);
                    }
                    fs::remove_file(self.root.join(NEXT))?;
                }
                fs::remove_file(self.root.join(PENDING))?;
                sync_root(&self.root)?;
                return Ok(actual.clone());
            }
            if let Some(old) = &retained {
                require_extension(old, configured)?;
            }
            // For an incomplete intent, only the exact configured target and
            // actual predecessor can finish its original prefix.
            commit(&self.root, binding, current.as_deref(), &target)?;
            return read_original(&self.root, binding);
        }
        if optional(&self.root, NEXT)?.is_some() {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        match retained {
            None => {
                commit(&self.root, binding, /*before*/ None, &target)?;
                read_original(&self.root, binding)
            }
            Some(actual) => {
                if require_extension(configured, &actual).is_ok() {
                    return Ok(actual);
                }
                require_extension(&actual, configured)?;
                commit(&self.root, binding, current.as_deref(), &target)?;
                read_original(&self.root, binding)
            }
        }
    }

    pub(crate) fn install_original_withdrawal_frontier(
        &self,
        before: &DatasetWithdrawalRegistry,
        next: &DatasetWithdrawalRegistry,
        binding: Digest32,
    ) -> Result<(), ArtifactOwnerHostError> {
        require_extension(before, next)?;
        let old = encode(before, binding)?;
        let target = encode(next, binding)?;
        commit(&self.root, binding, Some(&old), &target)?;
        self.require_original_withdrawal_frontier(next, binding)
    }

    pub(crate) fn require_original_withdrawal_frontier(
        &self,
        expected: &DatasetWithdrawalRegistry,
        binding: Digest32,
    ) -> Result<(), ArtifactOwnerHostError> {
        if read_original(&self.root, binding)?.snapshot() != expected.snapshot() {
            return Err(ArtifactOwnerHostError::CurrentHeadRollback);
        }
        Ok(())
    }
}
