//! Terminal DATA after the original source exchange has returned, including
//! its final peer check. Receiving this notice permits source teardown only;
//! it is neither a completed evaluation nor authority to release a holdout.

use std::io;

use serde::Deserialize;
use serde::Serialize;

use crate::OriginalRootBCandidateDataV1;
use crate::root_independent_b_source_protocol::SourceAcknowledgement;
use crate::root_independent_b_source_ready::SourceReadyData;

const PURPOSE: &str = "runtime.learning.independent-b-source-finalized.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct FinalizedData {
    schema: u8,
    purpose: String,
    source: SourceReadyData,
}

pub(crate) fn encode_original_source_finalized(source: &SourceReadyData) -> io::Result<Vec<u8>> {
    let bytes = serde_json::to_vec(&FinalizedData {
        schema: 1,
        purpose: PURPOSE.into(),
        source: source.clone(),
    })
    .map_err(io::Error::other)?;
    if bytes.is_empty() || bytes.len() > crate::root_independent_b_notice::BOUND {
        return Err(io::Error::other(
            "bounded original source finalization required",
        ));
    }
    Ok(bytes)
}

pub(crate) fn require_original_source_finalized(
    bytes: &[u8],
    candidate: &OriginalRootBCandidateDataV1,
    source: &SourceAcknowledgement,
) -> io::Result<()> {
    if bytes.is_empty() || bytes.len() > crate::root_independent_b_notice::BOUND {
        return Err(io::Error::other(
            "bounded original source finalization required",
        ));
    }
    let data: FinalizedData = serde_json::from_slice(bytes).map_err(io::Error::other)?;
    if serde_json::to_vec(&data).map_err(io::Error::other)? != bytes
        || data.schema != 1
        || data.purpose != PURPOSE
    {
        return Err(io::Error::other(
            "canonical original source finalization required",
        ));
    }
    data.source.require_original_observation(
        candidate.initial(),
        candidate.binding(),
        candidate.scope(),
        candidate.training_head(),
        candidate
            .candidate_bundle()
            .digest()
            .map_err(io::Error::other)?,
        source,
    )
}
