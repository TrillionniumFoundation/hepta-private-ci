//! Bounded read-only Unix RPC client for the separately administered Control
//! high-water Observer. This transports split/scope/challenge ONLY, never a
//! caller-selected WAL head, checkpoint or digest for the server to echo.
//!
//! Deployment must independently provision the signed, rollback-resistant
//! external store. This client owns no signer, source ledger, server, Final-use
//! authority or physical CNS route mutation.

use std::collections::BTreeMap;
use std::fs;
use std::io::Read as _;
use std::io::Write as _;
use std::os::unix::fs::FileTypeExt as _;
use std::os::unix::net::UnixStream;
use std::path::Component;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;

use crate::cell_split_cns_runtime_port::CELL_SPLIT_SIGNED_CONTROL_HIGHWATER_SCHEMA_V1;
use crate::cell_split_cns_runtime_port::CellSplitIndependentControlObserverV1;
use crate::cell_split_cns_runtime_port::CellSplitSignedControlHighwaterV1;
use crate::cell_split_cns_runtime_port::cell_split_control_highwater_signing_bytes_v1;

pub const CELL_SPLIT_CONTROL_HIGHWATER_RPC_SCHEMA_V1: &str =
    "hepta.runtime.cell-split.control-highwater-rpc.v1";
const READ_METHOD: &str = "read_control_highwater";
const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_TRACKED_SCOPES: usize = 4_096;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitControlHighwaterRpcRequestV1 {
    pub schema: String,
    pub method: String,
    pub split_id: String,
    pub scope_id: String,
    pub challenge_nonce: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitControlHighwaterRpcResponseV1 {
    pub schema: String,
    pub method: String,
    pub proof: Option<CellSplitSignedControlHighwaterV1>,
    pub error: Option<String>,
}

/// A process-local, non-authorizing defense against a still-signed rollback.
/// The independent remote service must separately persist a stronger high-water
/// through process restart, power loss and disaster recovery.
#[derive(Clone, Debug, Eq, PartialEq)]
struct ObservedControlHighwater {
    // A new Split ID does not create a new original Control WAL for its Scope.
    split_id: String,
    // A single committed original WAL sequence must correspond to exactly
    // one complete signed state. Comparing only the terminal hash lets the
    // remote signer equivocate on checkpoint/plan/fence without a new commit.
    plan_digest: String,
    ndu_owner_id: String,
    ndu_snapshot_digest: String,
    generation: u64,
    route_fence: u64,
    revocation_epoch: u64,
    sequence: u64,
    head: String,
    checkpoint_digest: String,
    wal_bytes: u64,
    wal_device: u64,
    wal_inode: u64,
    marker_device: u64,
    marker_inode: u64,
    original_cns_receipt_binding: Option<String>,
}

impl From<&CellSplitSignedControlHighwaterV1> for ObservedControlHighwater {
    fn from(proof: &CellSplitSignedControlHighwaterV1) -> Self {
        Self {
            split_id: proof.split_id.clone(),
            plan_digest: proof.plan_digest.clone(),
            ndu_owner_id: proof.ndu_owner_id.clone(),
            ndu_snapshot_digest: proof.ndu_snapshot_digest.clone(),
            generation: proof.generation,
            route_fence: proof.route_fence,
            revocation_epoch: proof.revocation_epoch,
            sequence: proof.sequence,
            head: proof.wal_head.clone(),
            checkpoint_digest: proof.checkpoint_digest.clone(),
            wal_bytes: proof.wal_bytes,
            wal_device: proof.wal_device,
            wal_inode: proof.wal_inode,
            marker_device: proof.marker_device,
            marker_inode: proof.marker_inode,
            original_cns_receipt_binding: proof.original_cns_receipt_binding.clone(),
        }
    }
}

/// Genuine read-only network client; NEVER a Control writer or signer.
/// The caller's production verifier must ALSO compare the returned proof with
/// the actual original Control WAL Actor before and after the RPC.
pub struct CellSplitControlHighwaterUnixPortV1 {
    socket_path: PathBuf,
    verifying_key: VerifyingKey,
    observer_id: String,
    timeout: Duration,
    // Exactly one monotonic original WAL frontier per Scope across all Split IDs.
    seen: BTreeMap<String, ObservedControlHighwater>,
}

impl CellSplitControlHighwaterUnixPortV1 {
    pub fn new(
        socket_path: PathBuf,
        verifying_key: VerifyingKey,
        observer_id: String,
        timeout: Duration,
    ) -> Result<Self, String> {
        if !socket_path.is_absolute()
            || socket_path
                .components()
                .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
            || verifying_key.is_weak()
            || StableId::new(observer_id.clone()).is_err()
            || observer_id.len() > 256
            || timeout < Duration::from_millis(1)
            || timeout > Duration::from_secs(30)
        {
            return Err("invalid independent Control Observer endpoint or verifier".into());
        }
        Ok(Self {
            socket_path,
            verifying_key,
            observer_id,
            timeout,
            seen: BTreeMap::new(),
        })
    }

    pub fn verifying_key(&self) -> &VerifyingKey {
        &self.verifying_key
    }

    pub fn observer_id(&self) -> &str {
        &self.observer_id
    }

    fn query(
        &mut self,
        split_id: &str,
        scope_id: &str,
        nonce: &str,
    ) -> Result<CellSplitSignedControlHighwaterV1, String> {
        if !valid_id(split_id)
            || !valid_id(scope_id)
            || nonce.len() != 64
            || !nonce
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return Err("unbound Control high-water request identity or challenge".into());
        }
        // An endpoint symlink is forbidden. An attacker changing a parent path
        // still cannot forge the independently pinned original signature.
        if !fs::symlink_metadata(&self.socket_path)
            .map_err(|error| error.to_string())?
            .file_type()
            .is_socket()
        {
            return Err("independent Control high-water endpoint is not a Unix socket".into());
        }
        let started = Instant::now();
        let mut stream =
            UnixStream::connect(&self.socket_path).map_err(|error| error.to_string())?;
        let request = CellSplitControlHighwaterRpcRequestV1 {
            schema: CELL_SPLIT_CONTROL_HIGHWATER_RPC_SCHEMA_V1.to_owned(),
            method: READ_METHOD.to_owned(),
            split_id: split_id.to_owned(),
            scope_id: scope_id.to_owned(),
            challenge_nonce: nonce.to_owned(),
        };
        write_frame(&mut stream, &request, started, self.timeout)?;
        let response: CellSplitControlHighwaterRpcResponseV1 =
            read_frame(&mut stream, started, self.timeout)?;
        if response.schema != CELL_SPLIT_CONTROL_HIGHWATER_RPC_SCHEMA_V1
            || response.method != READ_METHOD
        {
            return Err("independent Control high-water RPC response drift".into());
        }
        if let Some(error) = response.error {
            if response.proof.is_some() || error.is_empty() || error.len() > 512 {
                return Err("mixed or malformed Control Observer denial".into());
            }
            return Err(format!(
                "independent Control Observer refused read: {error}"
            ));
        }
        let proof = response
            .proof
            .ok_or("missing independent signed Control proof")?;
        if proof.schema != CELL_SPLIT_SIGNED_CONTROL_HIGHWATER_SCHEMA_V1
            || proof.observer_id != self.observer_id
            || proof.split_id != split_id
            || proof.scope_id != scope_id
            || proof.challenge_nonce != nonce
            || proof.sequence == 0
            || proof.generation == 0
            || proof.route_fence == 0
            || proof.revocation_epoch == 0
            || proof.wal_bytes == 0
            || proof.observer_signature_bytes.len() != 64
            || !canonical_digest(&proof.plan_digest)
            || !canonical_digest(&proof.ndu_snapshot_digest)
            || !canonical_digest(&proof.wal_head)
            || !canonical_digest(&proof.checkpoint_digest)
            || proof
                .original_cns_receipt_binding
                .as_deref()
                .is_some_and(|value| !canonical_digest(value))
        {
            return Err("independent signed Control proof has wrong source or challenge".into());
        }
        let signature = Signature::from_slice(&proof.observer_signature_bytes)
            .map_err(|error| error.to_string())?;
        self.verifying_key
            .verify_strict(
                &cell_split_control_highwater_signing_bytes_v1(&proof)?,
                &signature,
            )
            .map_err(|_| "independent Control Observer signature is invalid".to_owned())?;
        // Never evict a previously verified original domain to fit a new one.
        // A signed old or forked WAL proof is a refusal, not a new baseline.
        let key = scope_id.to_owned();
        let observed = ObservedControlHighwater::from(&proof);
        if let Some(previous) = self.seen.get(&key) {
            // A fresh challenge may attest an unchanged WAL only for the
            // SAME Split and exactly the same signed original fields. An
            // alternate Split ID cannot silently reuse/reset the same Scope
            // frontier. A newer Split may begin only after the original WAL
            // physically advances (not merely with a new plan digest).
            // Keep the original NDU owner identity fixed: a new trust root
            // needs an independently admitted handoff, not an RPC claim.
            if proof.sequence < previous.sequence
                || (proof.sequence == previous.sequence && observed != *previous)
                || (proof.sequence > previous.sequence
                    && (proof.wal_head == previous.head
                        || proof.wal_bytes <= previous.wal_bytes
                        || proof.generation < previous.generation
                        || proof.route_fence < previous.route_fence
                        || proof.revocation_epoch < previous.revocation_epoch
                        || proof.ndu_owner_id != previous.ndu_owner_id
                        // A Control C record is durable, and subsequent
                        // P/C appends never erase its original CNS binding.
                        // A signed disappearance is a rollback/fork, not
                        // permission to forget a previously witnessed effect.
                        || (previous.original_cns_receipt_binding.is_some()
                            && proof.original_cns_receipt_binding.is_none())
                        // Only a new fsynced Control B followed by C may
                        // change an original CNS runtime receipt binding.
                        // A Neuron P append cannot change it. A later C
                        // also increases the original route fence, and a
                        // second CNS cutover must have a new Split identity.
                        || (proof.original_cns_receipt_binding.is_some()
                            && proof.original_cns_receipt_binding
                                != previous.original_cns_receipt_binding
                            && (proof
                                .sequence
                                .checked_sub(previous.sequence)
                                .is_none_or(|rows| rows < 2)
                                || proof.route_fence <= previous.route_fence
                                || (previous.original_cns_receipt_binding.is_some()
                                    && proof.split_id == previous.split_id)))
                        || (proof.split_id == previous.split_id
                            && (proof.plan_digest != previous.plan_digest
                                || proof.ndu_snapshot_digest != previous.ndu_snapshot_digest))))
                || proof.wal_device != previous.wal_device
                || proof.wal_inode != previous.wal_inode
                || proof.marker_device != previous.marker_device
                || proof.marker_inode != previous.marker_inode
            {
                return Err("independent signed Control history regressed or forked".into());
            }
        } else if self.seen.len() >= MAX_TRACKED_SCOPES {
            return Err("bounded Control high-water ratchet capacity exhausted".into());
        }
        self.seen.insert(key, observed);
        Ok(proof)
    }
}

impl CellSplitIndependentControlObserverV1 for CellSplitControlHighwaterUnixPortV1 {
    type Error = String;

    fn read_signed_highwater(
        &mut self,
        split_id: &str,
        scope_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitSignedControlHighwaterV1, Self::Error> {
        self.query(split_id, scope_id, challenge_nonce)
    }
}

fn valid_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 256 && StableId::new(id.to_owned()).is_ok()
}

fn canonical_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn remaining(started: Instant, timeout: Duration) -> Result<Duration, String> {
    timeout
        .checked_sub(started.elapsed())
        .filter(|time| !time.is_zero())
        .ok_or_else(|| "independent Control RPC deadline exceeded".to_owned())
}

/// Each read/write gets only the REMAINING total budget, so trickling header
/// or body bytes cannot extend the RPC indefinitely.
fn write_exact_until(
    stream: &mut UnixStream,
    mut data: &[u8],
    started: Instant,
    budget: Duration,
) -> Result<(), String> {
    while !data.is_empty() {
        stream
            .set_write_timeout(Some(remaining(started, budget)?))
            .map_err(|error| error.to_string())?;
        match stream.write(data) {
            Ok(0) => return Err("independent Control RPC write closed".into()),
            Ok(count) => data = &data[count..],
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.to_string()),
        }
    }
    Ok(())
}

fn read_exact_until(
    stream: &mut UnixStream,
    mut data: &mut [u8],
    started: Instant,
    budget: Duration,
) -> Result<(), String> {
    while !data.is_empty() {
        stream
            .set_read_timeout(Some(remaining(started, budget)?))
            .map_err(|error| error.to_string())?;
        match stream.read(data) {
            Ok(0) => return Err("independent Control RPC ended before full frame".into()),
            Ok(count) => {
                let (_, unread) = data.split_at_mut(count);
                data = unread;
            }
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.to_string()),
        }
    }
    Ok(())
}

fn write_frame<T: Serialize>(
    stream: &mut UnixStream,
    value: &T,
    started: Instant,
    budget: Duration,
) -> Result<(), String> {
    let data = serde_json::to_vec(value).map_err(|error| error.to_string())?;
    if data.is_empty() || data.len() > MAX_FRAME_BYTES {
        return Err("outgoing Control Observer RPC frame exceeds bound".into());
    }
    let len = u32::try_from(data.len()).map_err(|error| error.to_string())?;
    write_exact_until(stream, &len.to_be_bytes(), started, budget)?;
    write_exact_until(stream, &data, started, budget)
}

fn read_frame<T: DeserializeOwned>(
    stream: &mut UnixStream,
    started: Instant,
    budget: Duration,
) -> Result<T, String> {
    let mut len = [0_u8; 4];
    read_exact_until(stream, &mut len, started, budget)?;
    let length = u32::from_be_bytes(len) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err("incoming Control Observer RPC frame exceeds bound".into());
    }
    let mut data = vec![0_u8; length];
    read_exact_until(stream, &mut data, started, budget)?;
    serde_json::from_slice(&data).map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "cell_split_control_highwater_unix_tests.rs"]
mod tests;
