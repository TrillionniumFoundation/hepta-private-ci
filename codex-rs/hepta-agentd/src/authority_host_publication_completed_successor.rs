//! Existing C custody used only while the original publication refusal is
//! Armed. This opener does not register a publisher or resume its execution.

use super::*;
use crate::authority_host_service::generation_publication::OriginalPublicationHistoryProofV1;
use crate::authority_host_service::generation_publication::completed_files::OriginalControlRecord;

impl RegisteredSuccessorData {
    pub(in super::super) fn open_completed_history(
        root: Arc<RootAuthorityDirectory>,
        root_path: &std::path::Path,
        proof: &OriginalPublicationHistoryProofV1<'_>,
        files: Arc<RootOriginalSuccessorFilesV1>,
        uid: u32,
        gid: u32,
    ) -> io::Result<(Self, OriginalControlRecord)> {
        original_root()?;
        let profile = proof.original_profile()?;
        let owner = format!(
            "publication-task/{}",
            Digest32::of_bytes(profile.learning_operation.as_bytes())
        );
        let pin = OriginalControlRecord::open(root_path, &owner)?;
        let store = HostAuthorityFrontierStore::<SuccessorRecord>::open(root, owner.clone())
            .map_err(io::Error::other)?;
        let record = store.load(&owner).map_err(io::Error::other)?;
        pin.require_unchanged()?;
        if record.schema != 1
            || record.purpose != SUCCESSOR_PURPOSE
            || record.profile != *proof.original_reserved()
            || record.files != files.deployment_digest()?.to_string()
            || record.publisher.uid != uid
            || record.peer_gid != gid
            || record.publisher_epoch == 0
        {
            return Err(io::Error::other(
                "original completed successor registration differs",
            ));
        }
        let held = Self {
            store,
            owner,
            original: Mutex::new(record),
            files,
        };
        RegisteredSuccessorData::require_exact(&held)?;
        Ok((held, pin))
    }
}

impl RootCompletedSuccessorDataV1 {
    /// Canonical DATA correlation for the actual complete Source/Cell cut.
    /// This digest does not construct any execution or Dataset capability.
    pub(crate) fn original_cut_digest(&self) -> io::Result<Digest32> {
        Ok(Digest32::of_parts(&[
            b"hepta.root.original-successor-cut.v1\0",
            &serde_json::to_vec(&self.cut).map_err(io::Error::other)?,
        ]))
    }
}
