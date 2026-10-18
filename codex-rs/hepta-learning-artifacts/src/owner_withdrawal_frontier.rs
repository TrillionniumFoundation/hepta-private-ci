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
                || previous.as_ref().is_some_and(|old| !extends(old, &frontier))
                || !extends(&frontier, next)
            {
                return Err(ArtifactOwnerHostError::IdentityConflict);
            }
            // Readable bytes after failed sync are not an acknowledgement.
            durability::sync_file_and_parent(path)?;
            previous = Some(frontier);
            pending_exists = path == &pending;
        }
        if previous.is_none() && !registry_is_empty {
            return Err(ArtifactOwnerHostError::IdentityConflict);
        }
        if pending_exists {
            fs::rename(&pending, &current)
                .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
            durability::sync_parent(&current)?;
        }
        if previous.as_ref().is_some_and(|old| old.head_digest() == next.head_digest()) {
            return Ok(());
        }
        crate::write_dataset_withdrawal_snapshot_beneath(
            &self.root,
            "writer/withdrawal-frontier.pending",
            next,
            binding,
        )?;
        durability::sync_parent(&pending)?;
        fs::rename(&pending, &current)
            .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
        durability::sync_parent(&current)
    }
}

fn extends(previous: &DatasetWithdrawalRegistry, next: &DatasetWithdrawalRegistry) -> bool {
    let previous_snapshot = previous.snapshot();
    let next_snapshot = next.snapshot();
    previous.scope_digest() == next.scope_digest()
        && next_snapshot.records().starts_with(previous_snapshot.records())
}
