//! Worker-only public lane observations, never a FinalUse activation token.

use super::WorkerRootRegistrationV1;
use super::refused;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::HostAuthorityClockProjection;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::path::PathBuf;

pub(crate) const WORKER_ROOT_LANES_V1: &str = "runtime.infer_worker.root_lanes.v1";
pub(crate) const WORKER_OBSERVATION_V1: &str = "runtime.infer_worker.observation.v1";
pub(crate) const WORKER_WRITER_READ_V1: &str = "runtime.infer_worker.writer_proof.read.v1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerRootLanePathsV1 {
    pub observation: PathBuf,
    pub issuer: PathBuf,
    pub consumer_frontier: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerRootLaneBootstrapV1 {
    pub schema_version: u32,
    pub purpose: String,
    pub registration: WorkerRootRegistrationV1,
    pub owner_id: String,
    pub consumer_namespace: String,
    pub slot_sequence: u64,
    pub issuer_key: crate::HostAuthorityPublicIssuerKeyV1,
    pub writer_proof: crate::HostSignedWriterAuthorizationV1,
    pub revocations: FinalUseRevocations,
    pub frontier: FinalUseFrontier,
    pub sockets: WorkerRootLanePathsV1,
    pub timeout_ms: u64,
    pub lifetime_ms: u64,
    pub observed_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub effect_authorization_available: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerRootObservationV1 {
    pub schema_version: u32,
    pub operation: String,
    pub registration_sha256: Sha256Digest,
    pub owner_id: String,
    pub consumer_namespace: String,
    pub slot_sequence: u64,
    pub revocations: FinalUseRevocations,
    pub clock: HostAuthorityClockProjection,
    pub observed_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub effect_authorization_available: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct WorkerLaneReadRequest {
    pub(crate) schema_version: u32,
    pub(crate) operation: String,
    pub(crate) slot_sequence: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct WorkerWriterReadResponse {
    pub(crate) schema_version: u32,
    pub(crate) operation: String,
    pub(crate) registration_sha256: Sha256Digest,
    pub(crate) slot_sequence: u64,
    pub(crate) proof: crate::HostSignedWriterAuthorizationV1,
    pub(crate) effect_authorization_available: bool,
}

pub(crate) fn stable_consumer_namespace(agent: &AgentId) -> io::Result<String> {
    let bytes = serde_json::to_vec(&("runtime.infer_worker.consumer_floor.v1", agent)).map_err(io::Error::other)?;
    Ok(format!("worker-consumer-v1:{}", Sha256Digest::for_bytes(&bytes).as_str()))
}

pub(crate) fn lane_paths(registration: &WorkerRootRegistrationV1, slot_sequence: u64) -> io::Result<WorkerRootLanePathsV1> {
    // Only rendezvous names vary with this actual Root incarnation. The
    // consumer namespace and durable slot are stable across Worker nonces.
    let bytes = serde_json::to_vec(&(WORKER_ROOT_LANES_V1, &registration.registered_agent_id, &registration.root, slot_sequence)).map_err(io::Error::other)?;
    let parent = PathBuf::from("/run/hepta-worker-v1").join(Sha256Digest::for_bytes(&bytes).as_str());
    Ok(WorkerRootLanePathsV1 {
        observation: parent.join("o"),
        issuer: parent.join("i"),
        consumer_frontier: parent.join("f"),
    })
}

impl WorkerRootLaneBootstrapV1 {
    pub(crate) fn validate(&self) -> io::Result<()> {
        self.registration.validate()?;
        if self.schema_version != 1
            || self.purpose != WORKER_ROOT_LANES_V1
            || self.slot_sequence == 0
            || self.owner_id != self.issuer_key.key_id
            || self.owner_id.is_empty()
            || self.owner_id.len() > 128
            || self.issuer_key.not_before_authority_epoch > self.registration.issuer_lease.authority_epoch
            || self.issuer_key.not_after_authority_epoch < self.registration.issuer_lease.authority_epoch
            || self.consumer_namespace != stable_consumer_namespace(&self.registration.registered_agent_id)?
            || self.writer_proof.sha256().map_err(io::Error::other)? != self.registration.writer_proof_sha256
            || self.sockets != lane_paths(&self.registration, self.slot_sequence)?
            || self.timeout_ms == 0 || self.timeout_ms > 5_000
            || self.lifetime_ms == 0 || self.lifetime_ms > 300_000
            || self.expires_at_unix_ms != self.registration.expires_at_unix_ms
            || self.observed_unix_ms < self.registration.observed_unix_ms
            || self.observed_unix_ms >= self.expires_at_unix_ms
            || self.revocations.authority_epoch != self.registration.issuer_lease.authority_epoch
            || self.revocations.revision == 0
            || self.frontier.authority_epoch == 0
            || self.frontier.revocation_revision == 0
            || self.frontier.state_sha256 == [0; 32]
            || self.frontier.authority_epoch > self.revocations.authority_epoch
            || (self.frontier.authority_epoch == self.revocations.authority_epoch
                && self.frontier.revocation_revision > self.revocations.revision)
            || self.effect_authorization_available
        {
            return Err(refused("Worker lane purpose, original proof, stable floor or no-effect boundary differs"));
        }
        Ok(())
    }

    pub(crate) fn registration_sha256(&self) -> io::Result<Sha256Digest> {
        Ok(Sha256Digest::for_bytes(&serde_json::to_vec(&self.registration).map_err(io::Error::other)?))
    }
}
