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
pub struct CellSplitUnixEffectPortV1 {
    endpoints: [PathBuf; OWNER_COUNT],
    verifying_keys: [VerifyingKey; OWNER_COUNT],
    timeout: Duration,
}

impl CellSplitUnixEffectPortV1 {
    pub fn new(
        endpoints: [PathBuf; OWNER_COUNT],
        verifying_keys: [VerifyingKey; OWNER_COUNT],
        timeout: Duration,
    ) -> Result<Self, CellSplitEffectRpcErrorV1> {
        let mut paths = BTreeSet::new();
        let mut keys = BTreeSet::new();
        if timeout.is_zero() || timeout > Duration::from_secs(30) {
            return Err(CellSplitEffectRpcErrorV1::Invalid("RPC timeout"));
        }
        for (path, key) in endpoints.iter().zip(verifying_keys.iter()) {
            if !path.is_absolute()
                || path
                    .components()
                    .any(|part| matches!(part, Component::ParentDir))
                || !paths.insert(path)
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
        })
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
        send_frame(&mut stream, &request)?;
        let response: CellSplitEffectRpcResponseV1 = receive_frame(&mut stream)?;
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

    /// A lookup is a fresh, nonce-bound, separately signed read from the
    /// authority currently owning the durable artifact/state/route/generation.
    fn lookup(
        &self,
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
        Ok(response.receipt)
    }
}

impl CellSplitExecutionPortV1 for CellSplitUnixEffectPortV1 {
    type Error = CellSplitEffectRpcErrorV1;

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
        if receipt.intent != *intent {
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "owner committed a different intent",
            ));
        }
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
    fn shared_owner_identity_or_unbounded_timeout_is_rejected() {
        let root = tempfile::tempdir().expect("root");
        let key = SigningKey::from_bytes(&[1u8; 32]).verifying_key();
        let paths = [0, 1, 2, 3].map(|i| root.path().join(format!("{i}.sock")));
        assert!(CellSplitUnixEffectPortV1::new(paths, [key; 4], Duration::from_secs(1)).is_err());
    }
}
