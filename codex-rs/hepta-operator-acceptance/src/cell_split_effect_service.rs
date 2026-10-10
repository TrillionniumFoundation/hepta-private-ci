//! Fail-closed server boundary for a real durable Cell Split effect owner.
//!
//! The backend supplies actual CAS/migration/CNS/Supervisor operations. This
//! server neither interprets an opaque digest as a committed operation nor
//! caches readbacks as state. The backend must read the current owner state on
//! every query and revalidate NDU/frozen authority immediately before mutation.

use std::os::unix::net::UnixStream;

use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use crate::CellSplitExecutionIntentV1;
use crate::CellSplitExecutionReceiptV1;
use crate::CellSplitExecutionStepV1;
use crate::cell_split_execution_signing_payload_v1;
use crate::cell_split_effect_rpc::CELL_SPLIT_EFFECT_READBACK_SCHEMA_V1;
use crate::cell_split_effect_rpc::CELL_SPLIT_EFFECT_RPC_SCHEMA_V1;
use crate::cell_split_effect_rpc::CellSplitEffectReadbackV1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcActionV1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcErrorV1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcRequestV1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcResponseV1;
use crate::cell_split_effect_rpc::cell_split_effect_readback_signing_payload_v1;
use crate::cell_split_effect_rpc::receive_frame;
use crate::cell_split_effect_rpc::send_frame;
use crate::durable::canonical_json;
use crate::durable::sha256;

/// Original mutation evidence recovered from the authoritative component.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitOwnedEffectV1 {
    pub owner_sequence: u64,
    pub owner_receipt_bytes: Vec<u8>,
}

/// A production implementation MUST delegate to the respective real durable
/// owner, not a map of digests or in-memory receipt store. Read-back must be
/// side-effect free and verify_current must inspect live component state,
/// including the actual artifact, migrated child state, CNS route, or fence.
/// Final-use authorization (including NDU and generation) is the backend's
/// responsibility and cannot be delegated to the RPC client's assertions.
pub trait CellSplitDurableEffectBackendV1 {
    type Error: std::fmt::Display;

    fn authorize_execute(&mut self, intent: &CellSplitExecutionIntentV1)
        -> Result<(), Self::Error>;
    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1)
        -> Result<(), Self::Error>;
    fn read_committed(&mut self, intent: &CellSplitExecutionIntentV1)
        -> Result<Option<CellSplitOwnedEffectV1>, Self::Error>;
    fn verify_current(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error>;
    /// Monotonic owner sequence, read from durable state; never zero.
    fn current_sequence(&mut self) -> Result<u64, Self::Error>;
}

/// One pinned RPC owner; four distinct instances and signing keys are required.
/// Transport listener lifecycle, peer ACLs and key provisioning are external
/// deployment responsibilities. A failed live readback can never sign success.
pub struct CellSplitEffectServiceV1<B: CellSplitDurableEffectBackendV1> {
    step: CellSplitExecutionStepV1,
    owner_id: String,
    plan_digest: String,
    signing_key: SigningKey,
    backend: B,
}

impl<B: CellSplitDurableEffectBackendV1> CellSplitEffectServiceV1<B> {
    pub fn new(
        step: CellSplitExecutionStepV1,
        owner_id: String,
        plan_digest: String,
        signing_key: SigningKey,
        backend: B,
    ) -> Result<Self, CellSplitEffectRpcErrorV1> {
        if owner_id.is_empty() || owner_id.len() > 256 || !digest_shape(&plan_digest) {
            return Err(CellSplitEffectRpcErrorV1::Invalid("effect service trust binding"));
        }
        Ok(Self { step, owner_id, plan_digest, signing_key, backend })
    }

    pub fn backend(&self) -> &B {
        &self.backend
    }

    /// Serve exactly one authenticated request. On backend error the stream is
    /// dropped without a signed positive response. The coordinator must then
    /// reconcile by a read-only request to the original owner.
    pub fn serve_connection(
        &mut self,
        stream: &mut UnixStream,
    ) -> Result<(), CellSplitEffectRpcErrorV1> {
        let request: CellSplitEffectRpcRequestV1 = receive_frame(stream)?;
        self.validate(&request)?;
        let action = request.action;
        let (receipt, readback) = match action {
            CellSplitEffectRpcActionV1::Execute => {
                self.backend.authorize_execute(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                if self.read_verified(&request.intent)?.is_none() {
                    self.backend.commit_once(&request.intent)
                        .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                }
                let committed = self.read_verified(&request.intent)?.ok_or(
                    CellSplitEffectRpcErrorV1::Invalid("effect absent after commit"),
                )?;
                (Some(self.sign_receipt(&request.intent, &committed)?), None)
            }
            CellSplitEffectRpcActionV1::ReadBack => {
                let committed = self.read_verified(&request.intent)?;
                let receipt = committed.as_ref()
                    .map(|effect| self.sign_receipt(&request.intent, effect))
                    .transpose()?;
                let sequence = self.backend.current_sequence()
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                if sequence == 0 || committed.as_ref().is_some_and(|r| r.owner_sequence > sequence) {
                    return Err(CellSplitEffectRpcErrorV1::Invalid("owner sequence regressed"));
                }
                let mut readback = CellSplitEffectReadbackV1 {
                    schema: CELL_SPLIT_EFFECT_READBACK_SCHEMA_V1.into(),
                    intent: request.intent.clone(),
                    challenge_nonce: request.challenge_nonce.ok_or(
                        CellSplitEffectRpcErrorV1::Invalid("missing readback challenge"),
                    )?,
                    committed_receipt_digest: receipt.as_ref().map(|r| r.receipt_digest.clone()),
                    state_digest: receipt.as_ref().map(|r| r.output_digest.clone()),
                    read_sequence: sequence,
                    owner_signature_bytes: Vec::new(),
                };
                readback.owner_signature_bytes = self.signing_key.sign(
                    &cell_split_effect_readback_signing_payload_v1(&readback)?
                ).to_bytes().to_vec();
                (receipt, Some(readback))
            }
        };
        send_frame(stream, &CellSplitEffectRpcResponseV1 {
            schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
            action,
            receipt,
            readback,
            error: None,
        })
    }

    fn validate(&self, request: &CellSplitEffectRpcRequestV1)
        -> Result<(), CellSplitEffectRpcErrorV1>
    {
        let intent = &request.intent;
        let expected = sha256(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                intent.plan_digest, intent.step.index(), intent.previous_receipt_digest
            ).as_bytes(),
        );
        if request.schema != CELL_SPLIT_EFFECT_RPC_SCHEMA_V1
            || intent.schema != "hepta.learning.cell-split.execution-owner.v1"
            || intent.step != self.step
            || intent.owner_id != self.owner_id
            || intent.plan_digest != self.plan_digest
            || !digest_shape(&intent.previous_receipt_digest)
            || !digest_shape(&intent.idempotency_key)
            || intent.idempotency_key != expected
        {
            return Err(CellSplitEffectRpcErrorV1::Invalid("unbound execution intent"));
        }
        match (request.action, request.challenge_nonce.as_deref()) {
            (CellSplitEffectRpcActionV1::Execute, None) => {}
            (CellSplitEffectRpcActionV1::ReadBack, Some(nonce)) if digest_shape(nonce) => {}
            _ => return Err(CellSplitEffectRpcErrorV1::Invalid("challenge/action mismatch")),
        }
        Ok(())
    }

    fn read_verified(&mut self, intent: &CellSplitExecutionIntentV1)
        -> Result<Option<CellSplitOwnedEffectV1>, CellSplitEffectRpcErrorV1>
    {
        let effect = self.backend.read_committed(intent)
            .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
        if let Some(ref committed) = effect {
            if committed.owner_sequence == 0
                || committed.owner_receipt_bytes.is_empty()
                || committed.owner_receipt_bytes.len() > 32 * 1024
                || !self.backend.verify_current(intent, committed)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?
            {
                return Err(CellSplitEffectRpcErrorV1::Invalid("effect no longer current"));
            }
        }
        Ok(effect)
    }

    fn sign_receipt(
        &self,
        intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<CellSplitExecutionReceiptV1, CellSplitEffectRpcErrorV1> {
        let mut receipt = CellSplitExecutionReceiptV1 {
            intent: intent.clone(),
            owner_sequence: effect.owner_sequence,
            output_digest: sha256(&effect.owner_receipt_bytes),
            owner_receipt_bytes: effect.owner_receipt_bytes.clone(),
            owner_signature_bytes: Vec::new(),
            receipt_digest: String::new(),
        };
        receipt.owner_signature_bytes = self.signing_key.sign(
            &cell_split_execution_signing_payload_v1(&receipt)
                .map_err(|_| CellSplitEffectRpcErrorV1::Invalid("receipt signing payload"))?
        ).to_bytes().to_vec();
        let mut unsealed = receipt.clone();
        unsealed.receipt_digest.clear();
        receipt.receipt_digest = sha256(&canonical_json(&unsealed)?);
        Ok(receipt)
    }
}

fn digest_shape(value: &str) -> bool {
    value.len() == 64
        && value.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        && value.bytes().any(|byte| byte != b'0')
}

#[cfg(test)]
#[path = "cell_split_effect_service_tests.rs"]
mod tests;
