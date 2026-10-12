//! Read-only Unix transport to an independently administered Supervisor
//! monotonic high-water service. The query contains only a journal domain
//! and a fresh challenge: the caller cannot suggest an expected epoch,
//! revision, or checkpoint digest to be signed by the external authority.
//!
//! This client neither hosts the service nor persists/advances a frontier.
//! The deployment must pin an independently controlled service key and use
//! genuinely rollback-resistant server storage. An authenticated response
//! is evidence, not permission to promote or physically split a Cell.

use std::fs;
use std::io;
use std::os::unix::fs::FileTypeExt as _;
use std::os::unix::net::UnixStream;
use std::path::Component;
use std::path::PathBuf;
use std::time::Duration;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::CELL_SPLIT_SUPERVISOR_MONOTONIC_FRONTIER_SCHEMA_V1;
use crate::CellSplitSupervisorMonotonicFrontierPortV1;
use crate::CellSplitSupervisorMonotonicFrontierV1;
use crate::cell_split_supervisor_monotonic_frontier_signing_payload_v1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcErrorV1;
use crate::cell_split_effect_rpc::receive_frame_with_deadline;
use crate::cell_split_effect_rpc::send_frame_with_deadline;

pub const CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1: &str =
    "hepta.learning.cell-split.monotonic-frontier-rpc.v1";
const READ_METHOD: &str = "read_domain_frontier";

/// A remote store must derive its current high-water from *its own* durable
/// journal-domain registry. Neither revision nor digest is sent to the server.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitMonotonicRpcRequestV1 {
    pub schema: String,
    pub method: String,
    pub journal_domain_id: String,
    pub challenge_nonce: String,
}

/// The service returns a signed, freshly challenged high-water mark, or an
/// explicit denial. Both positive evidence and denial in one frame is invalid.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitMonotonicRpcResponseV1 {
    pub schema: String,
    pub method: String,
    pub proof: Option<CellSplitSupervisorMonotonicFrontierV1>,
    pub error: Option<String>,
}

#[derive(Debug, Error)]
pub enum CellSplitMonotonicRpcErrorV1 {
    #[error("monotonic frontier RPC trust binding or response is invalid")]
    Invalid,
    #[error("monotonic frontier service denied current read: {0}")]
    Denied(String),
    #[error("monotonic frontier signer is not the externally pinned authority")]
    Untrusted,
    #[error(transparent)]
    Rpc(#[from] CellSplitEffectRpcErrorV1),
    #[error(transparent)]
    Io(#[from] io::Error),
}

/// Production-facing client for an independent, non-writable frontier source.
///
/// This type stores only the externally pinned verifier key, the Unix service
/// endpoint, and an IO deadline. It cannot mint a signature, enroll a key,
/// modify a checkpoint or choose a frontier revision on behalf of the server.
pub struct CellSplitSupervisorMonotonicUnixPortV1 {
    socket_path: PathBuf,
    verifier: VerifyingKey,
    timeout: Duration,
}

impl CellSplitSupervisorMonotonicUnixPortV1 {
    pub fn new(
        socket_path: PathBuf,
        verifier: VerifyingKey,
        timeout: Duration,
    ) -> Result<Self, CellSplitMonotonicRpcErrorV1> {
        if !socket_path.is_absolute()
            || socket_path
                .components()
                .any(|component| matches!(component, Component::ParentDir))
            || verifier.is_weak()
            || timeout < Duration::from_millis(1)
            || timeout > Duration::from_secs(30)
        {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        Ok(Self {
            socket_path,
            verifier,
            timeout,
        })
    }

    pub fn verifying_key(&self) -> &VerifyingKey {
        &self.verifier
    }

    fn query(
        &mut self,
        journal_domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitSupervisorMonotonicFrontierV1, CellSplitMonotonicRpcErrorV1> {
        if journal_domain_id.is_empty()
            || journal_domain_id.len() > 256
            || codex_hepta_types::StableId::new(journal_domain_id.to_owned()).is_err()
            || !canonical_digest(challenge_nonce)
        {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        // A socket symlink can be swapped after validation; the independent
        // pinned signature must still be verified against the exact challenge.
        if !fs::symlink_metadata(&self.socket_path)?.file_type().is_socket() {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        let mut connection = UnixStream::connect(&self.socket_path)?;
        let request = CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.to_owned(),
            method: READ_METHOD.to_owned(),
            journal_domain_id: journal_domain_id.to_owned(),
            challenge_nonce: challenge_nonce.to_owned(),
        };
        send_frame_with_deadline(&mut connection, &request, self.timeout)?;
        let response: CellSplitMonotonicRpcResponseV1 =
            receive_frame_with_deadline(&mut connection, self.timeout)?;
        if response.schema != CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1
            || response.method != READ_METHOD
        {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        if let Some(reason) = response.error {
            if response.proof.is_some() || reason.is_empty() || reason.len() > 512 {
                return Err(CellSplitMonotonicRpcErrorV1::Invalid);
            }
            return Err(CellSplitMonotonicRpcErrorV1::Denied(reason));
        }
        let proof = response.proof.ok_or(CellSplitMonotonicRpcErrorV1::Invalid)?;
        if proof.schema != CELL_SPLIT_SUPERVISOR_MONOTONIC_FRONTIER_SCHEMA_V1
            || proof.journal_domain_id != journal_domain_id
            || proof.challenge_nonce != challenge_nonce
            || proof.journal_authority_epoch == 0
            || proof.journal_revision == 0
            || !canonical_digest(&proof.minimum_checkpoint_digest)
            || !canonical_digest(&proof.original_store_record_digest)
            || proof.signature_bytes.len() != 64
        {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        let signature = Signature::from_slice(&proof.signature_bytes)
            .map_err(|_| CellSplitMonotonicRpcErrorV1::Invalid)?;
        self.verifier
            .verify_strict(
                &cell_split_supervisor_monotonic_frontier_signing_payload_v1(&proof)
                    .map_err(|_| CellSplitMonotonicRpcErrorV1::Invalid)?,
                &signature,
            )
            .map_err(|_| CellSplitMonotonicRpcErrorV1::Untrusted)?;
        Ok(proof)
    }
}

impl CellSplitSupervisorMonotonicFrontierPortV1 for CellSplitSupervisorMonotonicUnixPortV1 {
    type Error = CellSplitMonotonicRpcErrorV1;

    fn read_domain_frontier(
        &mut self,
        journal_domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitSupervisorMonotonicFrontierV1, Self::Error> {
        self.query(journal_domain_id, challenge_nonce)
    }
}

fn canonical_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        && value.bytes().any(|byte| byte != b'0')
}

#[cfg(test)]
#[path = "cell_split_monotonic_rpc_tests.rs"]
mod tests;
