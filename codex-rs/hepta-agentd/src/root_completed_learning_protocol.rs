//! Completed learning replies carry observations from the original Root lane.
//! These strict data types do not construct a historical capability.

use std::io;

use codex_hepta_agent_protocol::OriginalQ24CompletedHistoryDataV1;
use serde::Deserialize;
use serde::Serialize;

use super::HistoricalReadOperationV1;
use super::MAX_READS;
use super::WIRE_BOUND;
use super::canonical_digest;

pub(crate) const ACCEPT_COMPLETED_PURPOSE: &str = "runtime.learning.completed-acceptance.v1";
pub(crate) const CAPTURE_COMPLETED_PURPOSE: &str = "runtime.learning.completed-history.capture.v1";
pub(crate) const READ_COMPLETED_PURPOSE: &str = "runtime.learning.completed-history.read.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum CompletedHistoryModeV1 {
    CaptureRetired,
    ReadFinalized,
}

#[derive(Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CompletedLearningAcceptanceResponseV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: String,
    pub(crate) data_cut: String,
    pub(crate) initial: String,
    pub(crate) frozen_scope: String,
    pub(crate) terminal_head: String,
    pub(crate) acceptance: String,
}

#[derive(Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CompletedLearningHistoryResponseV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: String,
    pub(crate) data_cut: String,
    pub(crate) completion: OriginalQ24CompletedHistoryDataV1,
}

pub(crate) fn require_completed_acceptance_reply(
    bytes: &[u8],
    request_id: u64,
    profile: &str,
) -> io::Result<CompletedLearningAcceptanceResponseV1> {
    if bytes.is_empty() || bytes.len() > WIRE_BOUND || !(1..=MAX_READS).contains(&request_id) {
        return Err(io::Error::other(
            "completed acceptance reply exceeds original bounds",
        ));
    }
    let response: CompletedLearningAcceptanceResponseV1 =
        serde_json::from_slice(bytes).map_err(io::Error::other)?;
    if response.schema != 1
        || response.purpose != ACCEPT_COMPLETED_PURPOSE
        || response.request_id != request_id
        || response.profile != profile
    {
        return Err(io::Error::other(
            "completed acceptance reply differs from request",
        ));
    }
    for digest in [
        profile,
        &response.data_cut,
        &response.initial,
        &response.frozen_scope,
        &response.terminal_head,
        &response.acceptance,
    ] {
        canonical_digest(digest)?;
    }
    Ok(response)
}

pub(crate) fn require_completed_history_reply(
    bytes: &[u8],
    request_id: u64,
    profile: &str,
    operation: HistoricalReadOperationV1,
) -> io::Result<CompletedLearningHistoryResponseV1> {
    let purpose = match operation {
        HistoricalReadOperationV1::CaptureCompletedHistory => CAPTURE_COMPLETED_PURPOSE,
        HistoricalReadOperationV1::ReadCompletedHistory => READ_COMPLETED_PURPOSE,
        HistoricalReadOperationV1::Task
        | HistoricalReadOperationV1::LearningTrust
        | HistoricalReadOperationV1::PostAFrozenLearning
        | HistoricalReadOperationV1::AcceptCompletedLearning => {
            return Err(io::Error::other("completed history operation required"));
        }
    };
    if bytes.is_empty() || bytes.len() > WIRE_BOUND || !(1..=MAX_READS).contains(&request_id) {
        return Err(io::Error::other(
            "completed history reply exceeds original bounds",
        ));
    }
    let response: CompletedLearningHistoryResponseV1 =
        serde_json::from_slice(bytes).map_err(io::Error::other)?;
    if response.schema != 1
        || response.purpose != purpose
        || response.request_id != request_id
        || response.profile != profile
        || response.completion.root_profile != profile
    {
        return Err(io::Error::other(
            "completed history reply differs from request",
        ));
    }
    canonical_digest(profile)?;
    canonical_digest(&response.data_cut)?;
    response
        .completion
        .validate_data()
        .map_err(io::Error::other)?;
    Ok(response)
}

#[cfg(test)]
#[path = "root_completed_learning_protocol_tests.rs"]
mod tests;
