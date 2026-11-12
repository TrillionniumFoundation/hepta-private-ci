//! Strict positions and access modes for the original source's five fresh
//! rights. Closed notices contain exactly bootstrap + pidfd and no data rights.

use std::os::unix::fs::FileExt;

use super::*;
use crate::root_independent_b_source_protocol::PURPOSE;
use crate::root_independent_b_source_protocol::SourceBootstrap;
use crate::root_independent_b_source_protocol::SourceMode;

pub(super) fn require_exact_source_rights(
    sealed: &File,
    source: Option<&File>,
    candidate: Option<&File>,
    notice: Option<&File>,
    root_pid: u32,
) -> Result<(), AgentdError> {
    validate_bootstrap(sealed)?;
    let mut bytes = vec![0; usize::try_from(sealed.metadata()?.len()).map_err(io::Error::other)?];
    sealed.read_exact_at(&mut bytes, /*offset*/ 0)?;
    let bootstrap: SourceBootstrap = serde_json::from_slice(&bytes)?;
    if serde_json::to_vec(&bootstrap)? != bytes
        || bootstrap.schema != 2
        || bootstrap.purpose != PURPOSE
        || bootstrap.root.uid != 0
        || bootstrap.root.pid != root_pid
    {
        return Err(refused("original B source sealed rights schema differs"));
    }
    match (bootstrap.mode, source, candidate, notice) {
        (SourceMode::FreshInput, Some(source), Some(candidate), Some(notice)) => {
            crate::root_independent_b_source_client::require_original_source_file(
                source, &bootstrap,
            )?;
            crate::root_independent_b_candidate_notice::require_candidate_file(
                candidate, &bootstrap,
            )?;
            crate::root_independent_b_notice::require_original_notice_reader(notice, root_pid)?;
            if (bootstrap.source_device, bootstrap.source_inode)
                == (
                    bootstrap.candidate_data_device,
                    bootstrap.candidate_data_inode,
                )
            {
                return Err(refused("original B candidate and source rights alias"));
            }
        }
        (SourceMode::Retained | SourceMode::NoUpdate, None, None, None) => {}
        _ => {
            return Err(refused(
                "exact original B source disposition and rights required",
            ));
        }
    }
    validate_bootstrap(sealed)
}
