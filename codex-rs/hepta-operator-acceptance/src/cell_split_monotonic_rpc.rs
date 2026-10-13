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
use std::time::Instant;

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
const MAX_RETAINED_DOMAINS: usize = 4_096;

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
/// This type stores the externally pinned verifier, Unix endpoint, deadline
/// and a bounded process-local high-water ratchet. It cannot mint signatures,
/// enroll keys, modify checkpoints, or choose a server-side frontier value.
/// The ratchet catches a signed remote-server rollback *within this client
/// lifetime*; it does not survive client restart and is not production custody.
pub struct CellSplitSupervisorMonotonicUnixPortV1 {
    socket_path: PathBuf,
    verifier: VerifyingKey,
    timeout: Duration,
    retained_frontiers: BTreeMap<String, (u64, u64, String, String)>,
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
            retained_frontiers: BTreeMap::new(),
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
        // A single RPC budget covers both frame directions. An apparently
        // responsive server must not reset the deadline after receiving a
        // request or reserve another full interval for its signed response.
        let started_at = Instant::now();
        let mut connection = UnixStream::connect(&self.socket_path)?;
        let request = CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.to_owned(),
            method: READ_METHOD.to_owned(),
            journal_domain_id: journal_domain_id.to_owned(),
            challenge_nonce: challenge_nonce.to_owned(),
        };
        send_frame_with_deadline(
            &mut connection,
            &request,
            remaining_rpc_budget(started_at, self.timeout)?,
        )?;
        let response: CellSplitMonotonicRpcResponseV1 = receive_frame_with_deadline(
            &mut connection,
            remaining_rpc_budget(started_at, self.timeout)?,
        )?;
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
        // The separately administered signer remains the authority. Retain
        // previously verified epochs/revisions to reject a still-signed old
        // snapshot after the remote server restarts or its disk is restored.
        // Never evict an older domain entry to accommodate an untrusted new
        // domain: a bounded refusal is safer than forgetting a high-water.
        if let Some((epoch, revision, checkpoint, record)) =
            self.retained_frontiers.get(journal_domain_id)
        {
            let ahead = proof.journal_authority_epoch > *epoch
                || (proof.journal_authority_epoch == *epoch
                    && proof.journal_revision > *revision);
            let behind = proof.journal_authority_epoch < *epoch
                || (proof.journal_authority_epoch == *epoch
                    && proof.journal_revision < *revision);
            if behind
                || (ahead
                    && (proof.minimum_checkpoint_digest == *checkpoint
                        || proof.original_store_record_digest == *record))
                || (!ahead
                    && (proof.minimum_checkpoint_digest != *checkpoint
                        || proof.original_store_record_digest != *record))
            {
                return Err(CellSplitMonotonicRpcErrorV1::Invalid);
            }
        } else if self.retained_frontiers.len() >= MAX_RETAINED_DOMAINS {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        self.retained_frontiers.insert(
            journal_domain_id.to_owned(),
            (
                proof.journal_authority_epoch,
                proof.journal_revision,
                proof.minimum_checkpoint_digest.clone(),
                proof.original_store_record_digest.clone(),
            ),
        );
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

/// One wall-clock budget for both RPC frame directions and all independent
/// custody reads. This is a transport fence, not a backend cancellation token.
fn remaining_rpc_budget(
    started_at: Instant,
    total: Duration,
) -> Result<Duration, CellSplitMonotonicRpcErrorV1> {
    total
        .checked_sub(started_at.elapsed())
        .filter(|remaining| !remaining.is_zero())
        .ok_or(CellSplitMonotonicRpcErrorV1::Invalid)
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

/// The separately retained monotonic floor is independently signed under a
/// new nonce, not copied from the candidate registry or signed with the RPC
/// owner's key. The distinct custody key must be pinned by deployment.
pub const CELL_SPLIT_MONOTONIC_CUSTODY_SCHEMA_V1: &str =
    "hepta.learning.cell-split.monotonic-custody.v1";

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitMonotonicCustodyProofV1 {
    pub schema: String,
    pub current: CellSplitMonotonicDurableFrontierV1,
    pub challenge_nonce: String,
    pub signature_bytes: Vec<u8>,
}

pub fn cell_split_monotonic_custody_signing_payload_v1(
    proof: &CellSplitMonotonicCustodyProofV1,
) -> Result<Vec<u8>, CellSplitMonotonicRpcErrorV1> {
    let mut unsigned = proof.clone();
    unsigned.signature_bytes.clear();
    let mut bytes = b"hepta.learning.cell-split.monotonic-custody.v1\0".to_vec();
    bytes.extend_from_slice(
        &crate::durable::canonical_json(&unsigned)
            .map_err(|_| CellSplitMonotonicRpcErrorV1::Invalid)?,
    );
    Ok(bytes)
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

    /// Query distinct, independently signed rollback-resistant custody.
    /// The source must not simply re-sign its own candidate registry.
    /// No default implementation exists for this production gate.
    fn read_independent_custody(
        &mut self,
        journal_domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitMonotonicCustodyProofV1, Self::Error>;
}

/// One read-only signing server. It cannot let a client supply a revision,
/// epoch or expected digest: only the domain and fresh nonce cross this RPC.
/// Production must serve it as a separate process with independent signer,
/// peer ACLs and rollback-resistant registry custody.
pub struct CellSplitMonotonicRpcServiceV1<R: CellSplitMonotonicAuthoritativeRegistryV1> {
    source: R,
    signer: ed25519_dalek::SigningKey,
    custody_verifier: VerifyingKey,
    timeout: Duration,
    // Process-lifetime monotonic ratchet is defense-in-depth only. Real
    // whole-process anti-rollback requires the external registry's own
    // separately retained high-water frontier across process restarts.
    retained_frontiers: BTreeMap<String, CellSplitMonotonicDurableFrontierV1>,
}

impl<R: CellSplitMonotonicAuthoritativeRegistryV1> CellSplitMonotonicRpcServiceV1<R> {
    pub fn new(
        source: R,
        signer: ed25519_dalek::SigningKey,
        custody_verifier: VerifyingKey,
        timeout: Duration,
    ) -> Result<Self, CellSplitMonotonicRpcErrorV1> {
        if signer.verifying_key().is_weak()
            || custody_verifier.is_weak()
            || signer.verifying_key() == custody_verifier
            || timeout < Duration::from_millis(1)
            || timeout > Duration::from_secs(30)
        {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        Ok(Self {
            source,
            signer,
            custody_verifier,
            timeout,
            retained_frontiers: BTreeMap::new(),
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
        let started_at = Instant::now();
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
        // This singleton signed owner must never go backwards while running,
        // even if an uncooperative registry process restores older otherwise
        // valid bytes after the previous signed request.
        self.verify_retained_frontier(&first)?;
        // Read/write socket deadlines do not cover time spent querying the
        // separate custody and durable registry. Do not acknowledge a signed
        // high-water if that independent verification outlived the request
        // budget. This denies stale positives; hung backend calls still
        // require deployment-managed cancellation and worker limits.
        let remaining = remaining_rpc_budget(started_at, self.timeout)?;
        self.retained_frontiers
            .insert(first.journal_domain_id.clone(), first);
        send_frame_with_deadline(
            stream,
            &CellSplitMonotonicRpcResponseV1 {
                schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.to_owned(),
                method: READ_METHOD.to_owned(),
                proof: Some(proof),
                error: None,
            },
            remaining,
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
        // Three independently challenged custody readbacks per successful
        // response prohibit self-confirming old registry files after an RPC
        // process restart, provided the custody key/store really are separate.
        self.require_independent_custody(&current)?;
        self.verify_retained_frontier(&current)?;
        Ok(current)
    }

    fn require_independent_custody(
        &mut self,
        current: &CellSplitMonotonicDurableFrontierV1,
    ) -> Result<(), CellSplitMonotonicRpcErrorV1> {
        let nonce = rand::random::<[u8; 32]>()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let proof = self
            .source
            .read_independent_custody(&current.journal_domain_id, &nonce)
            .map_err(|error| CellSplitMonotonicRpcErrorV1::Denied(error.to_string()))?;
        if proof.schema != CELL_SPLIT_MONOTONIC_CUSTODY_SCHEMA_V1
            || proof.current != *current
            || proof.challenge_nonce != nonce
            || proof.signature_bytes.len() != 64
        {
            return Err(CellSplitMonotonicRpcErrorV1::Invalid);
        }
        let signature = Signature::from_slice(&proof.signature_bytes)
            .map_err(|_| CellSplitMonotonicRpcErrorV1::Invalid)?;
        self.custody_verifier
            .verify_strict(
                &cell_split_monotonic_custody_signing_payload_v1(&proof)?,
                &signature,
            )
            .map_err(|_| CellSplitMonotonicRpcErrorV1::Untrusted)
    }

    fn verify_retained_frontier(
        &self,
        observed: &CellSplitMonotonicDurableFrontierV1,
    ) -> Result<(), CellSplitMonotonicRpcErrorV1> {
        match self.retained_frontiers.get(&observed.journal_domain_id) {
            Some(previous) => {
                let moved_forward = observed.journal_authority_epoch
                    > previous.journal_authority_epoch
                    || (observed.journal_authority_epoch
                        == previous.journal_authority_epoch
                        && observed.journal_revision > previous.journal_revision);
                if observed.journal_authority_epoch < previous.journal_authority_epoch
                    || (observed.journal_authority_epoch
                        == previous.journal_authority_epoch
                        && observed.journal_revision < previous.journal_revision)
                    || observed.durable_source_sequence < previous.durable_source_sequence
                    || (moved_forward
                        && (observed.durable_source_sequence
                            <= previous.durable_source_sequence
                            || observed.minimum_checkpoint_digest
                                == previous.minimum_checkpoint_digest
                            || observed.original_store_record_digest
                                == previous.original_store_record_digest))
                    || (!moved_forward && observed != previous)
                {
                    return Err(CellSplitMonotonicRpcErrorV1::Invalid);
                }
            }
            None if self.retained_frontiers.len() >= MAX_RETAINED_DOMAINS => {
                // Never silently evict a previous source high-water to make
                // room for a caller-chosen domain; bounded denial is safer.
                return Err(CellSplitMonotonicRpcErrorV1::Invalid);
            }
            None => {}
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "cell_split_monotonic_rpc_tests.rs"]
mod tests;
