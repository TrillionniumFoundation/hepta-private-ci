//! Complete-task data protocol. Only the same live Root route can authorize
//! a read; these serialized values never construct an owner or a Dataset cap.

use std::fs::File;
use std::io;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdIdentity;
use crate::HostAuthorityLearningProfileV1;
use crate::HostAuthorityRegisteredIdentity;
use crate::circuit_task::RootHistoricalTaskPublicationDataV1;
use crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1;

pub(crate) const PURPOSE: &str = "runtime.learning.historical-task-read.v1";
pub(crate) const SOCKET: &str = "historical-task-read-v1.sock";
pub(crate) const MAX_READS: u64 = 64;
pub(crate) const WIRE_BOUND: usize = 16_384;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct HistoricalTaskReadProfileV1 {
    pub(crate) purpose: String,
    pub(crate) identity: String,
    pub(crate) writer: String,
    pub(crate) initial: String,
    pub(crate) deployment: String,
    pub(crate) binding: String,
}

impl HistoricalTaskReadProfileV1 {
    pub(crate) fn digest(&self) -> io::Result<String> {
        let mut value = self.clone();
        value.binding.clear();
        Ok(Digest32::of_parts(&[
            b"hepta.root.historical-task-read.profile.v1\0",
            &serde_json::to_vec(&value).map_err(io::Error::other)?,
        ])
        .to_string())
    }

    pub(crate) fn require_original_context(
        &self,
        identity: &AgentdIdentity,
        proof: &str,
        initial: &HostAuthorityLearningProfileV1,
    ) -> io::Result<LearningIterationSnapshotV1> {
        if self.purpose != PURPOSE
            || initial.schema_version != 1
            || initial.update_scope.is_some()
            || self.writer != proof
            || self.identity
                != crate::neuron_generation_process_identity_digest_v1(identity)
                    .map_err(io::Error::other)?
                    .to_string()
            || self.initial
                != Digest32::of_parts(&[
                    b"hepta.root.historical-task-read.initial.v1\0",
                    initial.encoded_initial().as_bytes(),
                ])
                .to_string()
            || self.digest()? != self.binding
        {
            return Err(io::Error::other(
                "original unfrozen historical recipient differs",
            ));
        }
        canonical_digest(&self.deployment)?;
        canonical_digest(&self.writer)?;
        initial.require_binding(identity, proof)
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct HistoricalTaskReadBootstrapV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) root: CognitiveCheckpointPeerLifetime,
    pub(crate) consumer: CognitiveCheckpointPeerLifetime,
    pub(crate) identity: HostAuthorityRegisteredIdentity,
    pub(crate) initial: HostAuthorityLearningProfileV1,
    pub(crate) profile: HistoricalTaskReadProfileV1,
    pub(crate) socket: PathBuf,
}

/// A Root-created sealed route, without signer, store, writable file or grant.
pub struct RootHistoricalTaskReadOfferV1 {
    pub(crate) bootstrap: File,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct HistoricalTaskReadRequestV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct HistoricalTaskReadResponseV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: String,
    pub(crate) data_cut: String,
    pub(crate) ledger: RootHistoricalLedgerReadDataV1,
    pub(crate) publication: RootHistoricalTaskPublicationDataV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct HistoricalTaskReadDataV1 {
    pub(crate) data_cut: Digest32,
    pub(crate) ledger: RootHistoricalLedgerReadDataV1,
    pub(crate) publication: RootHistoricalTaskPublicationDataV1,
}

pub(crate) fn require_complete_reply(
    bytes: &[u8],
    request_id: u64,
    profile: &str,
) -> io::Result<HistoricalTaskReadDataV1> {
    if bytes.is_empty() || bytes.len() > WIRE_BOUND || !(1..=MAX_READS).contains(&request_id) {
        return Err(io::Error::other(
            "historical read response exceeds original bounds",
        ));
    }
    let response: HistoricalTaskReadResponseV1 =
        serde_json::from_slice(bytes).map_err(io::Error::other)?;
    if response.schema != 1
        || response.purpose != PURPOSE
        || response.request_id != request_id
        || response.profile != profile
    {
        return Err(io::Error::other(
            "complete historical task response differs from request",
        ));
    }
    canonical_digest(profile)?;
    response.ledger.validate_data()?;
    response
        .publication
        .validate_against(&response.ledger)
        .map_err(io::Error::other)?;
    Ok(HistoricalTaskReadDataV1 {
        data_cut: canonical_digest(&response.data_cut)?,
        ledger: response.ledger,
        publication: response.publication,
    })
}

pub(crate) fn canonical_digest(value: &str) -> io::Result<Digest32> {
    let digest = value.parse::<Digest32>().map_err(io::Error::other)?;
    if digest.is_zero() || digest.to_string() != value {
        return Err(io::Error::other(
            "canonical nonzero historical digest required",
        ));
    }
    Ok(digest)
}

#[cfg(test)]
#[path = "root_historical_task_read_protocol_tests.rs"]
mod tests;
