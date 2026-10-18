//! The existing writer owns withdrawal restart state, including an interrupted
//! replacement. Caller snapshots can extend that history but cannot replace it
//! with an older or divergent frontier. A nonempty legacy owner without this
//! history requires explicit recovery; it is never initialized from a claim.

use super::*;
use crate::DatasetWithdrawalRegistry;
use crate::durable_snapshots::decode_withdrawal_snapshot;
use crate::durable_snapshots::encode_withdrawal_snapshot;

const MAX_FRONTIER_BYTES: usize = 8 * 1024 * 1024;

impl LearningArtifactOwnerHost {
    pub(crate) fn persist_withdrawal_frontier(
        &self,
        next: &DatasetWithdrawalRegistry,
        binding: Digest32,
        registry_is_empty: bool,
        now: u64,
    ) -> Result<(), ArtifactOwnerHostError> {
        self.require_current_writer(now)?;
        if next.scope_digest() != Some(self.verifier.trust.withdrawal_scope_digest) {
            return Err(ArtifactOwnerHostError::WriterLeaseContext);
        }
        let current = self.root.join("writer/withdrawal-frontier.snapshot");
        let pending = self.root.join("writer/withdrawal-frontier.pending");
        let marker = self.root.join("writer/withdrawal-frontier.initialized");
        let marker_bytes = marker_bytes(binding, self.verifier.trust.withdrawal_scope_digest);
        let initialized = match fs::symlink_metadata(&marker) {
            Ok(_) => {
                if read_small_record(&marker, MAX_SMALL_RECORD_BYTES)? != marker_bytes {
                    return Err(ArtifactOwnerHostError::IdentityConflict);
                }
                true
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
            Err(error) => return Err(error.into()),
        };
        let mut previous: Option<DatasetWithdrawalRegistry> = None;
        let mut pending_exists = false;
        for path in [&current, &pending] {
            match fs::symlink_metadata(path) {
                Ok(_) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
                Err(error) => return Err(error.into()),
            }
            let bytes = read_small_record(path, MAX_FRONTIER_BYTES)?;
            let frontier = decode_withdrawal_snapshot(&bytes, binding)?;
            if encode_withdrawal_snapshot(&frontier, binding)? != bytes
                || previous
                    .as_ref()
                    .is_some_and(|old| !extends(old, &frontier))
                || !extends(&frontier, next)
            {
                return Err(ArtifactOwnerHostError::IdentityConflict);
            }
            // Readable bytes after failed sync are not an acknowledgement.
            durability::sync_file_and_parent(path)?;
            previous = Some(frontier);
            pending_exists = path == &pending;
        }
        if previous.is_none() && (initialized || !self.new_writer_store || !registry_is_empty) {
            return Err(ArtifactOwnerHostError::IdentityConflict);
        }
        write_create_only_or_exact(&marker, &marker_bytes)?;
        if pending_exists {
            fs::rename(&pending, &current).map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
            durability::sync_parent(&current)?;
        }
        if previous
            .as_ref()
            .is_some_and(|old| old.head_digest() == next.head_digest())
        {
            return Ok(());
        }
        crate::write_dataset_withdrawal_snapshot_beneath(
            &self.root,
            "writer/withdrawal-frontier.pending",
            next,
            binding,
        )?;
        durability::sync_parent(&pending)?;
        fs::rename(&pending, &current).map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        durability::sync_parent(&current)
    }
}

pub(super) fn read_current_frontier(
    root: &Path,
    binding: Digest32,
    scope: Digest32,
) -> Result<DatasetWithdrawalRegistry, ArtifactOwnerHostError> {
    let marker = root.join("writer/withdrawal-frontier.initialized");
    if read_small_record(&marker, MAX_SMALL_RECORD_BYTES)? != marker_bytes(binding, scope) {
        return Err(ArtifactOwnerHostError::IdentityConflict);
    }
    match fs::symlink_metadata(root.join("writer/withdrawal-frontier.pending")) {
        Ok(_) => return Err(ArtifactOwnerHostError::CurrentObservationUnsettled),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let path = root.join("writer/withdrawal-frontier.snapshot");
    let bytes = read_small_record(&path, MAX_FRONTIER_BYTES)?;
    let frontier = decode_withdrawal_snapshot(&bytes, binding)?;
    if frontier.scope_digest() != Some(scope)
        || encode_withdrawal_snapshot(&frontier, binding)? != bytes
    {
        return Err(ArtifactOwnerHostError::IdentityConflict);
    }
    durability::sync_file_and_parent(&path)?;
    durability::sync_file_and_parent(&marker)?;
    Ok(frontier)
}

fn marker_bytes(binding: Digest32, scope: Digest32) -> Vec<u8> {
    format!("HEPTA-ARTIFACT-WITHDRAWAL-FRONTIER-V1\n{binding}\n{scope}\n").into_bytes()
}

fn extends(previous: &DatasetWithdrawalRegistry, next: &DatasetWithdrawalRegistry) -> bool {
    let previous_snapshot = previous.snapshot();
    let next_snapshot = next.snapshot();
    previous.scope_digest() == next.scope_digest()
        && next_snapshot
            .records()
            .starts_with(previous_snapshot.records())
}
