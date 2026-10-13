//! An authenticated Unix-socket transport to four distinct durable effect owners.
//!
//! This is a client of the deployment's real CAS, migration, CNS and Supervisor
//! services, not an implementation of any of those effects. Each service must
//! perform an idempotently keyed mutation against its own durable state, sign
//! the committed receipt, and sign a fresh state readback after each lookup.
//! The transport never manufactures a receipt, advances a missing effect,
//! treats a timeout as a negative acknowledgement, or grants split authority.

use std::collections::BTreeSet;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::net::UnixStream;
use std::path::Component;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;
use thiserror::Error;

use crate::CellSplitExecutionIntentV1;
use crate::CellSplitExecutionPortV1;
use crate::CellSplitExecutionReceiptV1;
use crate::durable::canonical_json;

pub const CELL_SPLIT_EFFECT_RPC_SCHEMA_V1: &str = "hepta.learning.cell-split.effect-rpc.v1";
pub const CELL_SPLIT_EFFECT_READBACK_SCHEMA_V1: &str =
    "hepta.learning.cell-split.effect-readback.v1";
const MAX_FRAME_BYTES: usize = 256 * 1024;
const OWNER_COUNT: usize = 4;

/// Execute is permitted only for a newly prepared intent. ReadBack must
/// always be side-effect free: ambiguous/crash recovery is lookup only.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CellSplitEffectRpcActionV1 {
    Execute,
    ReadBack,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitEffectRpcRequestV1 {
    pub schema: String,
    pub action: CellSplitEffectRpcActionV1,
    pub intent: CellSplitExecutionIntentV1,
    /// A new 256-bit nonce is mandatory for each readback.
    pub challenge_nonce: Option<String>,
}

/// A real owner signs this only after reading its *current durable effect
/// state*, not from a cached copy of the former mutation acknowledgement.
/// For a committed effect, state_digest must be the exact committed result
/// digest, and the returned receipt must be the original signed receipt.
/// The nonce prevents a proxy from replaying a prior positive readback.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitEffectReadbackV1 {
    pub schema: String,
    pub intent: CellSplitExecutionIntentV1,
    pub challenge_nonce: String,
    pub committed_receipt_digest: Option<String>,
    pub state_digest: Option<String>,
    pub read_sequence: u64,
    pub owner_signature_bytes: Vec<u8>,
}

pub fn cell_split_effect_readback_signing_payload_v1(
    readback: &CellSplitEffectReadbackV1,
) -> Result<Vec<u8>, CellSplitEffectRpcErrorV1> {
    let mut unsigned = readback.clone();
    unsigned.owner_signature_bytes.clear();
    let mut payload = b"hepta.learning.cell-split.effect-readback.v1\0".to_vec();
    payload.extend_from_slice(&canonical_json(&unsigned)?);
    Ok(payload)
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitEffectRpcResponseV1 {
    pub schema: String,
    pub action: CellSplitEffectRpcActionV1,
    pub receipt: Option<CellSplitExecutionReceiptV1>,
    pub readback: Option<CellSplitEffectReadbackV1>,
    pub error: Option<String>,
}

#[derive(Debug, Error)]
pub enum CellSplitEffectRpcErrorV1 {
    #[error("cell split RPC rejected configuration or response: {0}")]
    Invalid(&'static str),
    #[error("cell split RPC owner rejected effect: {0}")]
    Rejected(String),
    #[error("cell split RPC owner readback was not signed by the pinned owner")]
    UntrustedReadback,
    #[error(transparent)]
    Io(#[from] io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Durable(#[from] crate::AcceptanceError),
}

/// Four independent, pinned Unix service endpoints. This implementation
/// performs real socket requests, but deployment must supply real servers,
/// separate signing keys and state-backed readback. The coordinator also
/// independently verifies every mutation receipt against its own trust pins.
/// Locally retained, verified original-owner frontier for exactly one frozen
/// intent. This is NOT a durable high-water store and cannot establish the
/// state of a restarted coordinator by itself.
#[derive(Clone, Debug)]
struct SeenOwnerReadbackV1 {
    intent: CellSplitExecutionIntentV1,
    sequence: u64,
    committed_receipt_digest: Option<String>,
}

pub struct CellSplitUnixEffectPortV1 {
    endpoints: [PathBuf; OWNER_COUNT],
    verifying_keys: [VerifyingKey; OWNER_COUNT],
    timeout: Duration,
    seen_readbacks: [Option<SeenOwnerReadbackV1>; OWNER_COUNT],
}

impl CellSplitUnixEffectPortV1 {
    pub fn new(
        endpoints: [PathBuf; OWNER_COUNT],
        verifying_keys: [VerifyingKey; OWNER_COUNT],
        timeout: Duration,
    ) -> Result<Self, CellSplitEffectRpcErrorV1> {
        let mut paths = BTreeSet::new();
        let mut keys = BTreeSet::new();
        if timeout < Duration::from_millis(1) || timeout > Duration::from_secs(30) {
            return Err(CellSplitEffectRpcErrorV1::Invalid("RPC timeout"));
        }
        for (path, key) in endpoints.iter().zip(verifying_keys.iter()) {
            if !path.is_absolute()
                || path
                    .components()
                    .any(|part| matches!(part, Component::ParentDir))
                || !paths.insert(path)
                || key.is_weak()
                || !keys.insert(key.to_bytes())
            {
                return Err(CellSplitEffectRpcErrorV1::Invalid(
                    "effect sockets and signing keys must be distinct, absolute and pinned",
                ));
            }
        }
        Ok(Self {
            endpoints,
            verifying_keys,
            timeout,
            seen_readbacks: std::array::from_fn(|_| None),
        })
    }

    /// A live readback can only prove the original frozen owner when these
    /// socket verifier pins are identical to the coordinator's trust pins.
    pub(crate) fn uses_exact_owner_keys(&self, frozen: &[VerifyingKey; OWNER_COUNT]) -> bool {
        self.verifying_keys == *frozen
    }

    /// Do not permit a previously authenticated owner to roll its durable
    /// readback frontier backward, rebind this port to another split, or lose
    /// an original committed effect. It is an O(1), process-local defense in
    /// depth; independent rollback-resistant custody is still mandatory after
    /// restart and at production activation.
    fn retain_authenticated_readback(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        sequence: u64,
        receipt: Option<&CellSplitExecutionReceiptV1>,
    ) -> Result<(), CellSplitEffectRpcErrorV1> {
        let slot = &mut self.seen_readbacks[intent.step.index()];
        if let Some(previous) = slot.as_ref() {
            if previous.intent != *intent {
                return Err(CellSplitEffectRpcErrorV1::Invalid(
                    "effect RPC port rebound to a different original intent",
                ));
            }
            if sequence < previous.sequence {
                return Err(CellSplitEffectRpcErrorV1::Invalid(
                    "signed effect owner readback sequence regressed",
                ));
            }
            if let Some(original) = previous.committed_receipt_digest.as_deref() {
                if receipt.map(|effect| effect.receipt_digest.as_str()) != Some(original) {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "original effect disappeared or changed after a signed readback",
                    ));
                }
            } else if receipt.is_some() && sequence <= previous.sequence {
                // A durable effect must advance the original owner's frontier.
                // A fresh signature over the former negative read sequence is
                // not proof that a physical mutation occurred.
                return Err(CellSplitEffectRpcErrorV1::Invalid(
                    "signed effect appeared without durable sequence advance",
                ));
            }
        }
        *slot = Some(SeenOwnerReadbackV1 {
            intent: intent.clone(),
            sequence,
            committed_receipt_digest: receipt.map(|effect| effect.receipt_digest.clone()),
        });
        Ok(())
    }

    fn call(
        &self,
        intent: &CellSplitExecutionIntentV1,
        action: CellSplitEffectRpcActionV1,
        challenge_nonce: Option<String>,
    ) -> Result<CellSplitEffectRpcResponseV1, CellSplitEffectRpcErrorV1> {
        let path = &self.endpoints[intent.step.index()];
        // Disallow socket symlinks, including a late replacement of the endpoint.
        if !std::fs::symlink_metadata(path)?.file_type().is_socket() {
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "effect endpoint is not a Unix socket",
            ));
        }
        let mut stream = UnixStream::connect(path)?;
        stream.set_read_timeout(Some(self.timeout))?;
        stream.set_write_timeout(Some(self.timeout))?;
        let request = CellSplitEffectRpcRequestV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.to_owned(),
            action,
            intent: intent.clone(),
            challenge_nonce,
        };
        send_frame_with_deadline(&mut stream, &request, self.timeout)?;
        let response: CellSplitEffectRpcResponseV1 =
            receive_frame_with_deadline(&mut stream, self.timeout)?;
        if response.schema != CELL_SPLIT_EFFECT_RPC_SCHEMA_V1 || response.action != action {
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "RPC schema or action mismatch",
            ));
        }
        if let Some(error) = &response.error {
            if error.is_empty()
                || error.len() > 512
                || response.receipt.is_some()
                || response.readback.is_some()
            {
                return Err(CellSplitEffectRpcErrorV1::Invalid(
                    "malformed owner refusal",
                ));
            }
            return Err(CellSplitEffectRpcErrorV1::Rejected(error.clone()));
        }
        Ok(response)
    }

    // This public port must validate the original effect receipt even when
    // called without the coordinator. Reuse its canonical validation and
    // verify the step's own pinned signature; no parallel receipt grammar.
    fn verify_original_receipt(
        &self,
        intent: &CellSplitExecutionIntentV1,
        receipt: &CellSplitExecutionReceiptV1,
    ) -> Result<(), CellSplitEffectRpcErrorV1> {
        crate::cell_split_execution_owner::validate_receipt(intent, receipt).map_err(|_| {
            CellSplitEffectRpcErrorV1::Invalid("malformed original owner effect receipt")
        })?;
        let signature = Signature::from_slice(&receipt.owner_signature_bytes)
            .map_err(|_| CellSplitEffectRpcErrorV1::Invalid("malformed owner effect signature"))?;
        let payload = crate::cell_split_execution_signing_payload_v1(receipt).map_err(|_| {
            CellSplitEffectRpcErrorV1::Invalid("invalid owner effect signing payload")
        })?;
        self.verifying_keys[intent.step.index()]
            .verify_strict(&payload, &signature)
            .map_err(|_| CellSplitEffectRpcErrorV1::Invalid("untrusted owner effect receipt"))
    }

    /// A lookup is a fresh, nonce-bound, separately signed read from the
    /// authority currently owning the durable artifact/state/route/generation.
    fn lookup(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitExecutionReceiptV1>, CellSplitEffectRpcErrorV1> {
        let nonce = rand::random::<[u8; 32]>()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let response = self.call(
            intent,
            CellSplitEffectRpcActionV1::ReadBack,
            Some(nonce.clone()),
        )?;
        let readback = response.readback.ok_or(CellSplitEffectRpcErrorV1::Invalid(
            "missing current-owner readback",
        ))?;
        if readback.schema != CELL_SPLIT_EFFECT_READBACK_SCHEMA_V1
            || &readback.intent != intent
            || readback.challenge_nonce != nonce
            || readback.read_sequence == 0
            || readback.owner_signature_bytes.len() != 64
            || response.receipt.as_ref().map(|r| r.receipt_digest.as_str())
                != readback.committed_receipt_digest.as_deref()
            || response.receipt.as_ref().map(|r| r.output_digest.as_str())
                != readback.state_digest.as_deref()
            || response.receipt.as_ref().is_some_and(|receipt| {
                receipt.intent != *intent
                    || receipt.owner_sequence == 0
                    || receipt.owner_sequence > readback.read_sequence
            })
        {
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "owner current-state/readback mismatch",
            ));
        }
        let signature = Signature::from_slice(&readback.owner_signature_bytes)
            .map_err(|_| CellSplitEffectRpcErrorV1::UntrustedReadback)?;
        self.verifying_keys[intent.step.index()]
            .verify_strict(
                &cell_split_effect_readback_signing_payload_v1(&readback)?,
                &signature,
            )
            .map_err(|_| CellSplitEffectRpcErrorV1::UntrustedReadback)?;
        if let Some(receipt) = response.receipt.as_ref() {
            self.verify_original_receipt(intent, receipt)?;
        }
        // Mutate the local ratchet ONLY after both the fresh nonce-bound
        // readback and the original effect signature have been authenticated.
        self.retain_authenticated_readback(
            intent,
            readback.read_sequence,
            response.receipt.as_ref(),
        )?;
        Ok(response.receipt)
    }
}

impl CellSplitExecutionPortV1 for CellSplitUnixEffectPortV1 {
    type Error = CellSplitEffectRpcErrorV1;

    fn preflight_uncommitted(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<(), Self::Error> {
        // A fresh nonce-bound signed negative readback proves the owner is
        // reachable before the coordinator writes a one-shot prepared intent.
        // An existing original commit without that prepared intent is an
        // inconsistent execution history, never permission to adopt it.
        match self.lookup(intent)? {
            None => Ok(()),
            Some(_) => Err(CellSplitEffectRpcErrorV1::Invalid(
                "effect exists before coordinator prepared intent",
            )),
        }
    }

    fn execute(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<CellSplitExecutionReceiptV1, Self::Error> {
        let response = self.call(intent, CellSplitEffectRpcActionV1::Execute, None)?;
        if response.readback.is_some() {
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "mutation response cannot substitute for state readback",
            ));
        }
        let receipt = response.receipt.ok_or(CellSplitEffectRpcErrorV1::Invalid(
            "missing owner effect receipt",
        ))?;
        self.verify_original_receipt(intent, &receipt)?;
        Ok(receipt)
    }

    fn reconcile(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitExecutionReceiptV1>, Self::Error> {
        self.lookup(intent)
    }

    fn verify_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        receipt: &CellSplitExecutionReceiptV1,
    ) -> Result<(), Self::Error> {
        match self.lookup(intent)? {
            Some(current) if current == *receipt => Ok(()),
            _ => Err(CellSplitEffectRpcErrorV1::Invalid(
                "committed effect is missing or differs from live owner state",
            )),
        }
    }
}

#[cfg(test)]
pub(crate) fn send_frame<T: Serialize>(
    stream: &mut UnixStream,
    value: &T,
) -> Result<(), CellSplitEffectRpcErrorV1> {
    let body = serde_json::to_vec(value)?;
    if body.is_empty() || body.len() > MAX_FRAME_BYTES {
        return Err(CellSplitEffectRpcErrorV1::Invalid(
            "outbound RPC frame too large",
        ));
    }
    stream.write_all(&(body.len() as u32).to_be_bytes())?;
    stream.write_all(&body)?;
    stream.flush()?;
    Ok(())
}

#[cfg(test)]
pub(crate) fn receive_frame<T: DeserializeOwned>(
    stream: &mut UnixStream,
) -> Result<T, CellSplitEffectRpcErrorV1> {
    let mut length = [0u8; 4];
    stream.read_exact(&mut length)?;
    let length = u32::from_be_bytes(length) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err(CellSplitEffectRpcErrorV1::Invalid(
            "inbound RPC frame too large",
        ));
    }
    let mut body = vec![0u8; length];
    stream.read_exact(&mut body)?;
    Ok(serde_json::from_slice(&body)?)
}

/// Bound the entire inbound frame, including both header and body.
/// A slow peer cannot indefinitely extend a socket timeout by trickling bytes.
pub(crate) fn receive_frame_with_deadline<T: DeserializeOwned>(
    stream: &mut UnixStream,
    timeout: Duration,
) -> Result<T, CellSplitEffectRpcErrorV1> {
    let deadline = frame_deadline(timeout)?;
    let mut header = [0u8; 4];
    read_until_deadline(stream, &mut header, deadline)?;
    let len = u32::from_be_bytes(header) as usize;
    if len == 0 || len > MAX_FRAME_BYTES {
        return Err(CellSplitEffectRpcErrorV1::Invalid(
            "inbound RPC frame too large",
        ));
    }
    let mut body = vec![0u8; len];
    read_until_deadline(stream, &mut body, deadline)?;
    Ok(serde_json::from_slice(&body)?)
}

/// Write header and body against a single deadline, even if the peer drains
/// the socket in arbitrarily small increments.
pub(crate) fn send_frame_with_deadline<T: Serialize>(
    stream: &mut UnixStream,
    value: &T,
    timeout: Duration,
) -> Result<(), CellSplitEffectRpcErrorV1> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.is_empty() || bytes.len() > MAX_FRAME_BYTES {
        return Err(CellSplitEffectRpcErrorV1::Invalid(
            "outbound RPC frame too large",
        ));
    }
    let deadline = frame_deadline(timeout)?;
    write_until_deadline(stream, &(bytes.len() as u32).to_be_bytes(), deadline)?;
    write_until_deadline(stream, &bytes, deadline)
}

fn frame_deadline(timeout: Duration) -> Result<Instant, CellSplitEffectRpcErrorV1> {
    if timeout < Duration::from_millis(1) || timeout > Duration::from_secs(30) {
        return Err(CellSplitEffectRpcErrorV1::Invalid("RPC frame timeout"));
    }
    Instant::now()
        .checked_add(timeout)
        .ok_or(CellSplitEffectRpcErrorV1::Invalid("RPC deadline overflow"))
}

fn read_until_deadline(
    stream: &mut UnixStream,
    buffer: &mut [u8],
    deadline: Instant,
) -> Result<(), CellSplitEffectRpcErrorV1> {
    let mut offset = 0;
    while offset < buffer.len() {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "RPC frame deadline exceeded",
            ));
        }
        stream.set_read_timeout(Some(remaining))?;
        match stream.read(&mut buffer[offset..]) {
            Ok(0) => return Err(io::Error::from(io::ErrorKind::UnexpectedEof).into()),
            Ok(count) => offset += count,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error.into()),
        }
    }
    if Instant::now() >= deadline {
        return Err(CellSplitEffectRpcErrorV1::Invalid(
            "RPC frame deadline exceeded",
        ));
    }
    Ok(())
}

fn write_until_deadline(
    stream: &mut UnixStream,
    buffer: &[u8],
    deadline: Instant,
) -> Result<(), CellSplitEffectRpcErrorV1> {
    let mut offset = 0;
    while offset < buffer.len() {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "RPC frame deadline exceeded",
            ));
        }
        stream.set_write_timeout(Some(remaining))?;
        match stream.write(&buffer[offset..]) {
            Ok(0) => return Err(io::Error::from(io::ErrorKind::WriteZero).into()),
            Ok(count) => offset += count,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error.into()),
        }
    }
    if Instant::now() >= deadline {
        return Err(CellSplitEffectRpcErrorV1::Invalid(
            "RPC frame deadline exceeded",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cell_split_execution_signing_payload_v1;
    use crate::durable::sha256;
    use ed25519_dalek::Signer as _;
    use ed25519_dalek::SigningKey;
    use std::os::unix::net::UnixListener;
    use std::thread;

    fn intent() -> CellSplitExecutionIntentV1 {
        CellSplitExecutionIntentV1 {
            schema: "hepta.learning.cell-split.execution-owner.v1".into(),
            plan_digest: "11".repeat(32),
            step: crate::CellSplitExecutionStepV1::ArtifactCas,
            owner_id: "real-cas-owner".into(),
            idempotency_key: "22".repeat(32),
            previous_receipt_digest: "33".repeat(32),
        }
    }

    fn committed(
        intent: &CellSplitExecutionIntentV1,
        key: &SigningKey,
    ) -> CellSplitExecutionReceiptV1 {
        let bytes = serde_json::to_vec(intent).expect("receipt bytes");
        let mut receipt = CellSplitExecutionReceiptV1 {
            intent: intent.clone(),
            owner_sequence: 7,
            output_digest: sha256(&bytes),
            owner_receipt_bytes: bytes,
            owner_signature_bytes: Vec::new(),
            receipt_digest: String::new(),
        };
        receipt.owner_signature_bytes = key
            .sign(&cell_split_execution_signing_payload_v1(&receipt).expect("payload"))
            .to_bytes()
            .to_vec();
        let mut unsigned = receipt.clone();
        unsigned.receipt_digest.clear();
        receipt.receipt_digest = sha256(&canonical_json(&unsigned).expect("canonical"));
        receipt
    }

    #[test]
    fn real_socket_owner_receipt_requires_fresh_signed_state_readback() {
        let root = tempfile::tempdir().expect("root");
        let cas_socket = root.path().join("cas.sock");
        let listener = UnixListener::bind(&cas_socket).expect("owner socket");
        let signer = SigningKey::from_bytes(&[1u8; 32]);
        let keys = [1u8, 2, 3, 4].map(|v| SigningKey::from_bytes(&[v; 32]).verifying_key());
        let thread = thread::spawn(move || {
            let mut committed_receipt = None;
            for _ in 0..3 {
                let (mut socket, _) = listener.accept().expect("accepted");
                let request: CellSplitEffectRpcRequestV1 =
                    receive_frame(&mut socket).expect("request");
                let (receipt, readback) = match request.action {
                    CellSplitEffectRpcActionV1::Execute => {
                        let receipt = committed(&request.intent, &signer);
                        committed_receipt = Some(receipt.clone());
                        (Some(receipt), None)
                    }
                    CellSplitEffectRpcActionV1::ReadBack => {
                        let receipt = committed_receipt.clone().expect("owner committed");
                        let mut proof = CellSplitEffectReadbackV1 {
                            schema: CELL_SPLIT_EFFECT_READBACK_SCHEMA_V1.into(),
                            intent: request.intent,
                            challenge_nonce: request.challenge_nonce.expect("nonce"),
                            committed_receipt_digest: Some(receipt.receipt_digest.clone()),
                            state_digest: Some(receipt.output_digest.clone()),
                            read_sequence: 8,
                            owner_signature_bytes: Vec::new(),
                        };
                        proof.owner_signature_bytes = signer
                            .sign(
                                &cell_split_effect_readback_signing_payload_v1(&proof)
                                    .expect("payload"),
                            )
                            .to_bytes()
                            .to_vec();
                        (Some(receipt), Some(proof))
                    }
                };
                send_frame(
                    &mut socket,
                    &CellSplitEffectRpcResponseV1 {
                        schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
                        action: request.action,
                        receipt,
                        readback,
                        error: None,
                    },
                )
                .expect("response");
            }
        });
        let mut client = CellSplitUnixEffectPortV1::new(
            [
                cas_socket,
                root.path().join("migration.sock"),
                root.path().join("cns.sock"),
                root.path().join("supervisor.sock"),
            ],
            keys,
            Duration::from_secs(3),
        )
        .expect("trusted distinct endpoints");
        let intent = intent();
        let receipt = client.execute(&intent).expect("real socket execute");
        client
            .verify_committed(&intent, &receipt)
            .expect("first readback");
        assert_eq!(
            client.reconcile(&intent).expect("recovery readback"),
            Some(receipt)
        );
        thread.join().expect("owner done");
    }

    #[test]
    fn fresh_signed_readbacks_cannot_rewind_or_erase_a_live_original_effect() {
        for case in 0..2 {
            let root = tempfile::tempdir().expect("private owner socket");
            let cas_socket = root.path().join("cas.sock");
            let listener = UnixListener::bind(&cas_socket).expect("real socket");
            let signing_key = SigningKey::from_bytes(&[1_u8; 32]);
            let schedule = if case == 0 {
                // A valid positive observation must not be followed by an
                // older positive revision or a newer but missing original.
                [(9_u64, true), (8_u64, true), (10_u64, false)]
            } else {
                // A committed effect may appear only after a durable frontier
                // advance, not at the old, signed negative revision.
                [(9_u64, false), (9_u64, true), (10_u64, true)]
            };
            let server = thread::spawn(move || {
                for (sequence, present) in schedule {
                    let (mut socket, _) = listener.accept().expect("readback connection");
                    let request: CellSplitEffectRpcRequestV1 =
                        receive_frame(&mut socket).expect("readback request");
                    assert_eq!(request.action, CellSplitEffectRpcActionV1::ReadBack);
                    let receipt = present.then(|| committed(&request.intent, &signing_key));
                    let mut readback = CellSplitEffectReadbackV1 {
                        schema: CELL_SPLIT_EFFECT_READBACK_SCHEMA_V1.into(),
                        intent: request.intent.clone(),
                        challenge_nonce: request.challenge_nonce.expect("fresh nonce"),
                        committed_receipt_digest: receipt
                            .as_ref()
                            .map(|effect| effect.receipt_digest.clone()),
                        state_digest: receipt
                            .as_ref()
                            .map(|effect| effect.output_digest.clone()),
                        read_sequence: sequence,
                        owner_signature_bytes: Vec::new(),
                    };
                    readback.owner_signature_bytes = signing_key
                        .sign(
                            &cell_split_effect_readback_signing_payload_v1(&readback)
                                .expect("signed current-owner payload"),
                        )
                        .to_bytes()
                        .to_vec();
                    send_frame(
                        &mut socket,
                        &CellSplitEffectRpcResponseV1 {
                            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
                            action: request.action,
                            receipt,
                            readback: Some(readback),
                            error: None,
                        },
                    )
                    .expect("authenticated owner reply");
                }
            });
            let keys =
                [1_u8, 2, 3, 4].map(|value| SigningKey::from_bytes(&[value; 32]).verifying_key());
            let mut client = CellSplitUnixEffectPortV1::new(
                [
                    cas_socket,
                    root.path().join("migration.sock"),
                    root.path().join("cns.sock"),
                    root.path().join("supervisor.sock"),
                ],
                keys,
                Duration::from_secs(3),
            )
            .expect("pinned effect owners");
            let intent = intent();
            if case == 0 {
                assert!(client.reconcile(&intent).expect("signed commit").is_some());
                assert!(matches!(
                    client.reconcile(&intent),
                    Err(CellSplitEffectRpcErrorV1::Invalid(
                        "signed effect owner readback sequence regressed"
                    ))
                ));
                assert!(matches!(
                    client.reconcile(&intent),
                    Err(CellSplitEffectRpcErrorV1::Invalid(
                        "original effect disappeared or changed after a signed readback"
                    ))
                ));
            } else {
                assert!(client.reconcile(&intent).expect("signed absence").is_none());
                assert!(matches!(
                    client.reconcile(&intent),
                    Err(CellSplitEffectRpcErrorV1::Invalid(
                        "signed effect appeared without durable sequence advance"
                    ))
                ));
                assert!(
                    client
                        .reconcile(&intent)
                        .expect("newer signed original effect")
                        .is_some()
                );
            }
            server.join().expect("scripted owner readback only");
        }
    }

    #[test]
    fn refuse_missing_owner_without_synthesizing_an_effect() {
        let root = tempfile::tempdir().expect("root");
        let keys = [1u8, 2, 3, 4].map(|v| SigningKey::from_bytes(&[v; 32]).verifying_key());
        let mut client = CellSplitUnixEffectPortV1::new(
            [
                root.path().join("cas.sock"),
                root.path().join("migration.sock"),
                root.path().join("cns.sock"),
                root.path().join("supervisor.sock"),
            ],
            keys,
            Duration::from_secs(1),
        )
        .expect("configuration");
        assert!(client.execute(&intent()).is_err());
        assert!(client.reconcile(&intent()).is_err());
    }

    #[test]
    fn execute_rejects_real_socket_reply_signed_by_the_wrong_owner() {
        let root = tempfile::tempdir().expect("root");
        let cas_socket = root.path().join("cas.sock");
        let listener = UnixListener::bind(&cas_socket).expect("socket");
        let server = thread::spawn(move || {
            let (mut socket, _) = listener.accept().expect("accepted");
            let request: CellSplitEffectRpcRequestV1 = receive_frame(&mut socket).expect("request");
            assert_eq!(request.action, CellSplitEffectRpcActionV1::Execute);
            let forged = committed(&request.intent, &SigningKey::from_bytes(&[9_u8; 32]));
            send_frame(
                &mut socket,
                &CellSplitEffectRpcResponseV1 {
                    schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
                    action: request.action,
                    receipt: Some(forged),
                    readback: None,
                    error: None,
                },
            )
            .expect("forged response sent");
        });
        let keys = [1_u8, 2, 3, 4].map(|v| SigningKey::from_bytes(&[v; 32]).verifying_key());
        let mut client = CellSplitUnixEffectPortV1::new(
            [
                cas_socket,
                root.path().join("migration.sock"),
                root.path().join("cns.sock"),
                root.path().join("supervisor.sock"),
            ],
            keys,
            Duration::from_secs(3),
        )
        .expect("pinned real RPC port");
        assert!(matches!(
            client.execute(&intent()),
            Err(CellSplitEffectRpcErrorV1::Invalid(
                "untrusted owner effect receipt"
            ))
        ));
        server.join().expect("server done");
    }

    #[test]
    fn public_rpc_port_rejects_forged_original_receipt_before_returning_it() {
        let root = tempfile::tempdir().expect("root");
        let keys = [1_u8, 2, 3, 4].map(|v| SigningKey::from_bytes(&[v; 32]).verifying_key());
        let port = CellSplitUnixEffectPortV1::new(
            [0, 1, 2, 3].map(|i| root.path().join(format!("{i}.sock"))),
            keys,
            Duration::from_secs(1),
        )
        .expect("four pinned owners");
        let intent = intent();
        let forged = committed(&intent, &SigningKey::from_bytes(&[9_u8; 32]));
        assert!(matches!(
            port.verify_original_receipt(&intent, &forged),
            Err(CellSplitEffectRpcErrorV1::Invalid(
                "untrusted owner effect receipt"
            ))
        ));
        let genuine = committed(&intent, &SigningKey::from_bytes(&[1_u8; 32]));
        port.verify_original_receipt(&intent, &genuine)
            .expect("correct signer and canonical receipt");
        let mut tampered = genuine;
        tampered.owner_receipt_bytes.push(0);
        assert!(matches!(
            port.verify_original_receipt(&intent, &tampered),
            Err(CellSplitEffectRpcErrorV1::Invalid(
                "malformed original owner effect receipt"
            ))
        ));
    }

    #[test]
    fn rpc_port_rejects_weak_pinned_owner_key() {
        let root = tempfile::tempdir().expect("root");
        let mut keys = [1_u8, 2, 3, 4].map(|v| SigningKey::from_bytes(&[v; 32]).verifying_key());
        let mut identity = [0_u8; 32];
        identity[0] = 1;
        let weak = VerifyingKey::from_bytes(&identity).expect("valid compressed identity");
        assert!(weak.is_weak());
        keys[2] = weak;
        assert!(
            CellSplitUnixEffectPortV1::new(
                [0, 1, 2, 3].map(|i| root.path().join(format!("{i}.sock"))),
                keys,
                Duration::from_secs(1),
            )
            .is_err()
        );
    }

    #[test]
    fn shared_owner_identity_or_unbounded_timeout_is_rejected() {
        let root = tempfile::tempdir().expect("root");
        let key = SigningKey::from_bytes(&[1u8; 32]).verifying_key();
        let paths = [0, 1, 2, 3].map(|i| root.path().join(format!("{i}.sock")));
        assert!(CellSplitUnixEffectPortV1::new(paths, [key; 4], Duration::from_secs(1)).is_err());
    }

    #[test]
    fn rpc_client_refuses_trickled_response() {
        use std::io::Write as _;
        let root = tempfile::tempdir().expect("root");
        let socket = root.path().join("cas.sock");
        let listener = UnixListener::bind(&socket).expect("socket");
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accepted");
            let _: CellSplitEffectRpcRequestV1 = receive_frame(&mut stream).expect("request");
            for byte in [0_u8, 0, 0, 4, b'n', b'u', b'l', b'l'] {
                if stream.write_all(&[byte]).is_err() {
                    break;
                }
                thread::sleep(Duration::from_millis(10));
            }
        });
        let keys = [1_u8, 2, 3, 4].map(|v| SigningKey::from_bytes(&[v; 32]).verifying_key());
        let mut client = CellSplitUnixEffectPortV1::new(
            [
                socket,
                root.path().join("migration.sock"),
                root.path().join("cns.sock"),
                root.path().join("supervisor.sock"),
            ],
            keys,
            Duration::from_millis(45),
        )
        .expect("client");
        assert!(matches!(
            client.execute(&intent()),
            Err(CellSplitEffectRpcErrorV1::Invalid(
                "RPC frame deadline exceeded"
            )) | Err(CellSplitEffectRpcErrorV1::Io(_))
        ));
        server.join().expect("server");
    }
}
