//! Completed history opens only the original Root-fixed files. The original
//! publication Arm surrounds all physical I/O, the entire new recipient
//! context, and its independent after-reads. No live route is enrolled.

use std::time::Instant;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_types::Digest32;

use super::*;
use crate::HostAuthorityServiceConfig;
use crate::authority_host_service::HostAuthorityService;
use crate::authority_host_service::generation_publication::OriginalCompletedPublicationModeV1;
use crate::authority_host_service::generation_publication::OriginalCompletedPublicationReadV1;
use crate::authority_host_service::generation_publication::with_original_publication_history;

/// `action` encloses the actual new recipient's whole Root context; calling
/// read.observe within it is mandatory. Its errors cannot be swallowed into a
/// successful Ready, even if the caller caught the individual read error.
pub(in crate::authority_host_runtime::session) fn with_original_completed_publication<T>(
    path: &Path,
    initial: &LearningIterationSnapshotV1,
    scope: &FrozenLearningScopeV2,
    service: &HostAuthorityService,
    config: &HostAuthorityServiceConfig,
    end: Instant,
    mode: OriginalCompletedPublicationModeV1,
    action: impl FnOnce(&mut OriginalCompletedPublicationReadV1<'_>) -> io::Result<T>,
) -> io::Result<(T, Digest32)> {
    original_root()?;
    let (metadata, bytes) = MetadataFile::open_metadata(path)?;
    let deployment: PostAPublicationData =
        serde_json::from_slice(&bytes).map_err(io::Error::other)?;
    if deployment.schema != 2
        || deployment.purpose != "runtime.learning.post-a-publication-deployment.v2"
        || deployment.initial != initial.head_digest.to_string()
        || !initial.receipts.is_empty()
    {
        return Err(io::Error::other(
            "original completed publication deployment required",
        ));
    }
    // Only the independent control directory/marker is selected before arm.
    let directory = DirectoryPin::capture_root(&deployment.inputs.current_directory)?;
    let root = RootAuthorityDirectory::open(&deployment.inputs.current_directory)
        .map_err(io::Error::other)?;
    with_original_publication_history(
        root,
        &deployment.inputs.current_directory,
        initial,
        scope,
        end,
        |proof| {
            metadata.require_metadata_unchanged()?;
            directory.require_directory()?;
            let files = OriginalPostAPublicationFiles::retain_original_publication(
                path,
                initial,
                config.peer_uid,
                config.peer_gid,
            )?;
            if files.descriptor.digest() != metadata.digest() {
                return Err(io::Error::other("original completed deployment changed"));
            }
            let material = files.material.observe_ready()?.ok_or_else(|| {
                io::Error::other("original completed publication material unavailable")
            })?;
            let data: LateMaterial =
                serde_json::from_slice(material.bytes()).map_err(io::Error::other)?;
            if serde_json::to_vec(&data).map_err(io::Error::other)? != material.bytes() {
                return Err(io::Error::other(
                    "canonical completed publication material required",
                ));
            }
            let (inputs, artifacts) = OriginalInputs::completed_inputs(
                &files.inputs,
                &files.data,
                &data,
                config.peer_uid,
                proof,
            )?;
            let mut read = OriginalCompletedPublicationReadV1::open_existing(
                proof,
                service,
                config,
                &files.data.current_directory,
                inputs,
                Arc::clone(&files.successor),
                mode,
                end,
            )?;
            let result = action(&mut read);
            let finished = OriginalCompletedPublicationReadV1::finish(&mut read);
            // These still run if the recipient context returned an error.
            files.require_original_files()?;
            material.require_unchanged()?;
            for file in &artifacts {
                file.require_original_file()?;
            }
            metadata.require_metadata_unchanged()?;
            directory.require_directory()?;
            finished?;
            result
        },
    )
}
