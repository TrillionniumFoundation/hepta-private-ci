//! Read-only Unix transport to an independently administered Supervisor
//! monotonic high-water service. The query contains only a journal domain
//! and a fresh challenge: the caller cannot suggest an expected epoch,
//! revision, or checkpoint digest to be signed by the external authority.
//!
//! This client neither hosts the service nor persists/advances a frontier.
//! The deployment must pin an independently controlled service key and use
//! genuinely rollback-resistant server storage. An authenticated response
//! is evidence, not permission to promote or physically split a Cell.

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::os::unix::fs::FileTypeExt as _;
use std::os::unix::net::UnixStream;
use std::path::Component;
use std::path::PathBuf;
use std::time::Duration;

use ed25519_dalek::Signature;
use ed25519_dalek::Signer as _;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::CELL_SPLIT_SUPERVISOR_MONOTONIC_FRONTIER_SCHEMA_V1;
use crate::CellSplitSupervisorMonotonicFrontierPortV1;
use crate::CellSplitSupervisorMonotonicFrontierV1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcErrorV1;
use crate::cell_split_effect_rpc::receive_frame_with_deadline;
use crate::cell_split_effect_rpc::send_frame_with_deadline;
use crate::cell_split_supervisor_monotonic_frontier_signing_payload_v1;

pub const CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1: &str =
    "hepta.learning.cell-split.monotonic-frontier-rpc.v1";
const READ_METHOD: &str = "read_domain_frontier";
// Bound the signer process's additional defense against rollback of its source.
// The independent durable registry, not this process-local floor, is authoritative.
const MAX_SIGNED_JOURNAL_DOMAINS: usize = 4096;

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
        if !fs::symlink_metadata(&self.socket_path)?
            .file_type()
            .is_socket()
        {
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
        if response.schema != CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1 || response.method != READ_METHOD {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        if let Some(reason) = response.error {
            if response.proof.is_some() || reason.is_empty() || reason.len() > 512 {
                return Err(CellSplitMonotonicRpcErrorV1::Invalid);
            }
            return Err(CellSplitMonotonicRpcErrorV1::Denied(reason));
        }
        let proof = response
            .proof
            .ok_or(CellSplitMonotonicRpcErrorV1::Invalid)?;
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

/// A typed high-water observation from the independently administered domain
/// registry. Unlike a proposed revision, this is an observation fetched by
/// domain alone from the registry's durable state. The source sequence is
/// retained for independent consistency checks, not copied from the client.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitMonotonicDurableFrontierV1 {
    pub journal_domain_id: String,
    pub journal_authority_epoch: u64,
    pub journal_revision: u64,
    pub minimum_checkpoint_digest: String,
    pub original_store_record_digest: String,
    pub durable_source_sequence: u64,
}

/// The external owner MUST read its own authoritative monotonic domain
/// registry and independently verify the committed record on every query.
/// This interface has no allow-all fallback and no mutation method. A local
/// reconstructed Supervisor checkpoint is not an acceptable implementation.
pub trait CellSplitMonotonicAuthoritativeRegistryV1 {
    type Error: std::fmt::Display;

    fn read_committed_domain(
        &mut self,
        domain: &str,
    ) -> Result<CellSplitMonotonicDurableFrontierV1, Self::Error>;

    fn verify_still_current(
        &mut self,
        committed: &CellSplitMonotonicDurableFrontierV1,
    ) -> Result<bool, Self::Error>;
}

/// One read-only signing server. It cannot let a client supply a revision,
/// epoch or expected digest: only the domain and fresh nonce cross this RPC.
/// Production must serve it as a separate process with independent signer,
/// peer ACLs and rollback-resistant registry custody.
pub struct CellSplitMonotonicRpcServiceV1<R: CellSplitMonotonicAuthoritativeRegistryV1> {
    source: R,
    signer: ed25519_dalek::SigningKey,
    timeout: Duration,
    signed_highwater: BTreeMap<String, CellSplitMonotonicDurableFrontierV1>,
}

impl<R: CellSplitMonotonicAuthoritativeRegistryV1> CellSplitMonotonicRpcServiceV1<R> {
    pub fn new(
        source: R,
        signer: ed25519_dalek::SigningKey,
        timeout: Duration,
    ) -> Result<Self, CellSplitMonotonicRpcErrorV1> {
        if signer.verifying_key().is_weak()
            || timeout < Duration::from_millis(1)
            || timeout > Duration::from_secs(30)
        {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        Ok(Self {
            source,
            signer,
            timeout,
            signed_highwater: BTreeMap::new(),
        })
    }

    /// Authenticate one request against a *currently durable* remote-domain
    /// registry entry. Sign only after repeated source reads, then recheck
    /// once more before sending: a revoked or advancing frontier never gets
    /// a positive response from this owner. This is not a cross-owner atomic
    /// snapshot; separate monotonic custody is still required.
    pub fn serve_connection(
        &mut self,
        stream: &mut UnixStream,
    ) -> Result<(), CellSplitMonotonicRpcErrorV1> {
        let request: CellSplitMonotonicRpcRequestV1 =
            receive_frame_with_deadline(stream, self.timeout)?;
        if request.schema != CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1
            || request.method != READ_METHOD
            || request.journal_domain_id.is_empty()
            || request.journal_domain_id.len() > 256
            || codex_hepta_types::StableId::new(request.journal_domain_id.clone()).is_err()
            || !canonical_digest(&request.challenge_nonce)
        {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }

        let first = self.read_verified_domain(&request.journal_domain_id)?;
        let second = self.read_verified_domain(&request.journal_domain_id)?;
        if first != second {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        let mut proof = CellSplitSupervisorMonotonicFrontierV1 {
            schema: CELL_SPLIT_SUPERVISOR_MONOTONIC_FRONTIER_SCHEMA_V1.to_owned(),
            journal_domain_id: first.journal_domain_id.clone(),
            journal_authority_epoch: first.journal_authority_epoch,
            journal_revision: first.journal_revision,
            minimum_checkpoint_digest: first.minimum_checkpoint_digest.clone(),
            original_store_record_digest: first.original_store_record_digest.clone(),
            challenge_nonce: request.challenge_nonce,
            signature_bytes: Vec::new(),
        };
        proof.signature_bytes = self
            .signer
            .sign(
                &cell_split_supervisor_monotonic_frontier_signing_payload_v1(&proof)
                    .map_err(|_| CellSplitMonotonicRpcErrorV1::Invalid)?,
            )
            .to_bytes()
            .to_vec();
        // Signing is not a commit. A fresh third read must prove the same
        // durable source before writing this positive evidence to the socket.
        if self.read_verified_domain(&first.journal_domain_id)? != first {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        // A local signed response must never regress while this signer stays
        // alive, even if its backing registry later serves a valid-looking
        // older record. This bounded floor is defense-in-depth only: after a
        // restart, rollback resistance still belongs to independent custody.
        match self.signed_highwater.get(&first.journal_domain_id) {
            Some(previous)
                if (first.journal_authority_epoch, first.journal_revision)
                    < (previous.journal_authority_epoch, previous.journal_revision)
                    || first.durable_source_sequence < previous.durable_source_sequence
                    || ((first.journal_authority_epoch, first.journal_revision)
                        == (previous.journal_authority_epoch, previous.journal_revision)
                        && (first.minimum_checkpoint_digest
                            != previous.minimum_checkpoint_digest
                            || first.original_store_record_digest
                                != previous.original_store_record_digest)) =>
            {
                return Err(CellSplitMonotonicRpcErrorV1::Invalid);
            }
            None if self.signed_highwater.len() >= MAX_SIGNED_JOURNAL_DOMAINS => {
                return Err(CellSplitMonotonicRpcErrorV1::Invalid);
            }
            _ => {}
        }
        // Record before sending: the signature already exists and a failed
        // socket acknowledgement must not allow a later downgraded signature.
        self.signed_highwater
            .insert(first.journal_domain_id.clone(), first);
        send_frame_with_deadline(
            stream,
            &CellSplitMonotonicRpcResponseV1 {
                schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.to_owned(),
                method: READ_METHOD.to_owned(),
                proof: Some(proof),
                error: None,
            },
            self.timeout,
        )?;
        Ok(())
    }

    fn read_verified_domain(
        &mut self,
        domain: &str,
    ) -> Result<CellSplitMonotonicDurableFrontierV1, CellSplitMonotonicRpcErrorV1> {
        let current = self
            .source
            .read_committed_domain(domain)
            .map_err(|error| CellSplitMonotonicRpcErrorV1::Denied(error.to_string()))?;
        if current.journal_domain_id != domain
            || current.journal_authority_epoch == 0
            || current.journal_revision == 0
            || current.durable_source_sequence == 0
            || !canonical_digest(&current.minimum_checkpoint_digest)
            || !canonical_digest(&current.original_store_record_digest)
            || !self
                .source
                .verify_still_current(&current)
                .map_err(|error| CellSplitMonotonicRpcErrorV1::Denied(error.to_string()))?
        {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        Ok(current)
    }
}

#[cfg(test)]
#[path = "cell_split_monotonic_rpc_tests.rs"]
mod tests;
