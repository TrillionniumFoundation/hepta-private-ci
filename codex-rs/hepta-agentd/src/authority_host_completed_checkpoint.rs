//! Existing Root checkpoint data. The caller holds the completed-learning
//! refusal Arm around this reader and the entire actual recipient context.

use std::io;
use std::path::Path;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_types::Digest32;

use crate::LearningIterationCheckpointRecordV1;
use crate::authority_host_service::generation_publication::OriginalControlRecord;

const OWNER: &str = "root-learning-checkpoint-v1";

pub(super) fn with_original_checkpoint<T>(
    state: &Path,
    action: impl FnOnce(&LearningIterationCheckpointRecordV1, Digest32) -> io::Result<T>,
) -> io::Result<T> {
    let path = state.join("learning-checkpoint");
    let pin = OriginalControlRecord::open(&path, OWNER)?;
    let store: HostAuthorityFrontierStore<LearningIterationCheckpointRecordV1> =
        HostAuthorityFrontierStore::open(
            RootAuthorityDirectory::open(&path).map_err(io::Error::other)?,
            OWNER.into(),
        )
        .map_err(io::Error::other)?;
    let checkpoint = store.load(OWNER).map_err(io::Error::other)?;
    pin.require_unchanged()?;
    let digest = Digest32::of_parts(&[
        b"hepta.root.completed-learning.checkpoint.v1\0",
        &serde_json::to_vec(&checkpoint).map_err(io::Error::other)?,
    ]);
    let value = action(&checkpoint, digest);
    if store.load(OWNER).map_err(io::Error::other)? != checkpoint {
        return Err(io::Error::other("original completed checkpoint changed"));
    }
    pin.require_unchanged()?;
    value
}
