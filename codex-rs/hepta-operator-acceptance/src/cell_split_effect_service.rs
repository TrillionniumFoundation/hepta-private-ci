//! Fail-closed server boundary for a real durable Cell Split effect owner.
//!
//! The backend supplies actual CAS/migration/CNS/Supervisor operations. This
//! server neither interprets an opaque digest as a committed operation nor
//! caches readbacks as state. The backend must read the current owner state on
//! every query and revalidate NDU/frozen authority immediately before mutation.

use std::os::unix::net::UnixStream;
use std::time::Duration;

use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use crate::CellSplitExecutionIntentV1;
use crate::CellSplitExecutionReceiptV1;
use crate::CellSplitExecutionStepV1;
use crate::cell_split_effect_rpc::CELL_SPLIT_EFFECT_READBACK_SCHEMA_V1;
use crate::cell_split_effect_rpc::CELL_SPLIT_EFFECT_RPC_SCHEMA_V1;
use crate::cell_split_effect_rpc::CellSplitEffectReadbackV1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcActionV1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcErrorV1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcRequestV1;
use crate::cell_split_effect_rpc::CellSplitEffectRpcResponseV1;
use crate::cell_split_effect_rpc::cell_split_effect_readback_signing_payload_v1;
use crate::cell_split_effect_rpc::receive_frame_with_deadline;
use crate::cell_split_effect_rpc::send_frame_with_deadline;
#[cfg(test)]
use crate::cell_split_effect_rpc::receive_frame;
#[cfg(test)]
use crate::cell_split_effect_rpc::send_frame;
use crate::cell_split_execution_signing_payload_v1;
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
    fn commit_once(&mut self, intent: &CellSplitExecutionIntentV1) -> Result<(), Self::Error>;
    fn read_committed(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, Self::Error>;
    fn verify_current(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
        effect: &CellSplitOwnedEffectV1,
    ) -> Result<bool, Self::Error>;
    /// The original durable owner frontier, not an in-memory call counter.
    fn current_sequence(&mut self) -> Result<u64, Self::Error>;

    /// An intent-scoped frontier is needed for create-only CAS and migration
    /// owners: their immutable commit marker advances the committed revision
    /// although the predecessor artifact/checkpoint remains unchanged.
    /// Owners with a globally monotonic durable journal can use the default.
    fn current_sequence_for_intent(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<u64, Self::Error> {
        let _ = intent;
        self.current_sequence()
    }
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
    io_timeout: Duration,
}

impl<B: CellSplitDurableEffectBackendV1> CellSplitEffectServiceV1<B> {
    pub fn new(
        step: CellSplitExecutionStepV1,
        owner_id: String,
        plan_digest: String,
        signing_key: SigningKey,
        backend: B,
    ) -> Result<Self, CellSplitEffectRpcErrorV1> {
        Self::new_with_io_timeout(
            step,
            owner_id,
            plan_digest,
            signing_key,
            backend,
            Duration::from_secs(5),
        )
    }

    /// Bound a peer's time to complete each socket read/write. A malicious
    /// client sending only a frame header must not block the sole signing
    /// owner indefinitely. This limits transport stalls, not backend
    /// execution time or externally managed listener/concurrency policies.
    pub fn new_with_io_timeout(
        step: CellSplitExecutionStepV1,
        owner_id: String,
        plan_digest: String,
        signing_key: SigningKey,
        backend: B,
        io_timeout: Duration,
    ) -> Result<Self, CellSplitEffectRpcErrorV1> {
        if owner_id.is_empty() || owner_id.len() > 256 || !digest_shape(&plan_digest) {
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "effect service trust binding",
            ));
        }
        if io_timeout < Duration::from_millis(1) || io_timeout > Duration::from_secs(30) {
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "effect service transport timeout",
            ));
        }
        Ok(Self {
            step,
            owner_id,
            plan_digest,
            signing_key,
            backend,
            io_timeout,
        })
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
        stream.set_read_timeout(Some(self.io_timeout))?;
        stream.set_write_timeout(Some(self.io_timeout))?;
        let request: CellSplitEffectRpcRequestV1 =
            receive_frame_with_deadline(stream, self.io_timeout)?;
        self.validate(&request)?;
        let action = request.action;
        let (receipt, readback) = match action {
            CellSplitEffectRpcActionV1::Execute => {
                self.backend
                    .authorize_execute(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                // The coordinator dispatches Execute only once, following a
                // nonce-bound negative preflight and a durable prepared intent.
                // A previously committed effect is not evidence that *this*
                // Execute caused it: a different caller may have raced the
                // preflight. Lost acknowledgements recover only by ReadBack.
                if self.read_verified(&request.intent)?.is_some() {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "effect already committed before new execute intent",
                    ));
                }
                // The negative preflight was not an exclusive reservation.
                // Observe the original durable frontier before committing, then
                // require the resulting receipt to advance it. Otherwise an
                // existing or statically reported effect could be adopted.
                let predecessor_sequence = self
                    .backend
                    .current_sequence_for_intent(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                if predecessor_sequence == 0 {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "owner frontier unavailable before execute",
                    ));
                }
                // Another writer may commit while we read the predecessor.
                // Fail closed rather than dispatching a potentially idempotent
                // commit against an already-effectful original owner.
                if self
                    .backend
                    .read_committed(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?
                    .is_some()
                {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "effect already committed before new execute intent",
                    ));
                }
                self.backend
                    .commit_once(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                let committed = self.read_verified(&request.intent)?.ok_or(
                    CellSplitEffectRpcErrorV1::Invalid("effect absent after commit"),
                )?;
                if committed.owner_sequence <= predecessor_sequence {
                    // The effect might already exist, so require read-only
                    // reconciliation; never retry an ambiguous operation here.
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "effect did not advance original durable owner frontier",
                    ));
                }
                // Execute acknowledgements require a second current-owner
                // observation just as signed recovery readbacks do.
                let before = self
                    .backend
                    .current_sequence_for_intent(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                let observed = self
                    .backend
                    .read_committed(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                let after = self
                    .backend
                    .current_sequence_for_intent(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                if before == 0
                    || before != after
                    || committed.owner_sequence > after
                    || observed.as_ref() != Some(&committed)
                    || !self
                        .backend
                        .verify_current(&request.intent, &committed)
                        .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?
                {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "effect changed before signed execute acknowledgement",
                    ));
                }
                // Final-use may be revoked while the effect owner performs
                // durable IO. A grant checked before commit is not authority
                // to acknowledge success after its independent frontier moves.
                // Do not undo an ambiguous committed effect here: withhold
                // the signature and require read-only reconciliation.
                self.backend
                    .authorize_execute(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                (Some(self.sign_receipt(&request.intent, &committed)?), None)
            }
            CellSplitEffectRpcActionV1::ReadBack => {
                let committed = self.read_verified(&request.intent)?;
                let sequence = self
                    .backend
                    .current_sequence_for_intent(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                if sequence == 0
                    || committed
                        .as_ref()
                        .is_some_and(|r| r.owner_sequence > sequence)
                {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "owner sequence regressed",
                    ));
                }
                // The independent durable frontier read may observe a newer
                // owner state than the original receipt verification. Verify
                // the actual effect again immediately before signing: a
                // revoked route/fence must never be laundered into a fresh
                // nonce-bound positive readback by this gap.
                if let Some(ref effect) = committed
                    && !self
                        .backend
                        .verify_current(&request.intent, effect)
                        .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?
                {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "effect changed during signed readback",
                    ));
                }
                // A negative lookup is not a snapshot unless it remains
                // absent after the separate frontier query. Positive reads
                // likewise must refer to the same original effect. Never
                // sign an out-of-date absence or a mixed-generation sample.
                let observed_again = self
                    .backend
                    .read_committed(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                if observed_again != committed {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "effect changed during signed readback",
                    ));
                }
                let final_sequence = self
                    .backend
                    .current_sequence_for_intent(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                if final_sequence != sequence {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "owner frontier changed during signed readback",
                    ));
                }
                // A frontier accessor can observe a stable sequence while an
                // independent route/fence owner revokes the effect during the
                // read. Reconfirm the live effect after the final frontier
                // sample; never sign an already-revoked positive observation.
                // Production owners still require an atomic/linearizable
                // state-and-frontier snapshot for complete race freedom.
                let last_effect = self
                    .backend
                    .read_committed(&request.intent)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
                if last_effect != committed {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "effect changed after final frontier read",
                    ));
                }
                if let Some(ref effect) = committed
                    && !self
                        .backend
                        .verify_current(&request.intent, effect)
                        .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?
                {
                    return Err(CellSplitEffectRpcErrorV1::Invalid(
                        "effect changed after final frontier read",
                    ));
                }
                let receipt = committed
                    .as_ref()
                    .map(|effect| self.sign_receipt(&request.intent, effect))
                    .transpose()?;
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
                readback.owner_signature_bytes = self
                    .signing_key
                    .sign(&cell_split_effect_readback_signing_payload_v1(&readback)?)
                    .to_bytes()
                    .to_vec();
                (receipt, Some(readback))
            }
        };
        send_frame_with_deadline(
            stream,
            &CellSplitEffectRpcResponseV1 {
                schema: CELL_SPLIT_EFFECT_RPC_SCHEMA_V1.into(),
                action,
                receipt,
                readback,
                error: None,
            },
            self.io_timeout,
        )
    }

    fn validate(
        &self,
        request: &CellSplitEffectRpcRequestV1,
    ) -> Result<(), CellSplitEffectRpcErrorV1> {
        let intent = &request.intent;
        let expected = sha256(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                intent.plan_digest,
                intent.step.index(),
                intent.previous_receipt_digest
            )
            .as_bytes(),
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
            return Err(CellSplitEffectRpcErrorV1::Invalid(
                "unbound execution intent",
            ));
        }
        match (request.action, request.challenge_nonce.as_deref()) {
            (CellSplitEffectRpcActionV1::Execute, None) => {}
            (CellSplitEffectRpcActionV1::ReadBack, Some(nonce)) if digest_shape(nonce) => {}
            _ => {
                return Err(CellSplitEffectRpcErrorV1::Invalid(
                    "challenge/action mismatch",
                ));
            }
        }
        Ok(())
    }

    fn read_verified(
        &mut self,
        intent: &CellSplitExecutionIntentV1,
    ) -> Result<Option<CellSplitOwnedEffectV1>, CellSplitEffectRpcErrorV1> {
        let effect = self
            .backend
            .read_committed(intent)
            .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?;
        if let Some(ref committed) = effect {
            // The signed receipt must not outrun the real durable owner
            // frontier. Check here for both Execute and ReadBack: a backend
            // may have written a payload but lost the authoritative commit
            // before acknowledgement.
            let durable_sequence = self
                .backend
                .current_sequence_for_intent(intent)
                .map_err(|error| CellSplitEffectRpcErrorV1::Rejected(error.to_string()))?;
            if durable_sequence == 0 || committed.owner_sequence > durable_sequence {
                return Err(CellSplitEffectRpcErrorV1::Invalid(
                    "committed effect exceeds durable owner frontier",
                ));
            }
            if committed.owner_sequence == 0
                || committed.owner_receipt_bytes.is_empty()
                || committed.owner_receipt_bytes.len() > 32 * 1024
                || !self
                    .backend
                    .verify_current(intent, committed)
                    .map_err(|e| CellSplitEffectRpcErrorV1::Rejected(e.to_string()))?
            {
                return Err(CellSplitEffectRpcErrorV1::Invalid(
                    "effect no longer current",
                ));
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
        receipt.owner_signature_bytes = self
            .signing_key
            .sign(
                &cell_split_execution_signing_payload_v1(&receipt)
                    .map_err(|_| CellSplitEffectRpcErrorV1::Invalid("receipt signing payload"))?,
            )
            .to_bytes()
            .to_vec();
        let mut unsealed = receipt.clone();
        unsealed.receipt_digest.clear();
        receipt.receipt_digest = sha256(&canonical_json(&unsealed)?);
        Ok(receipt)
    }
}

fn digest_shape(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        && value.bytes().any(|byte| byte != b'0')
}

#[cfg(test)]
#[path = "cell_split_effect_service_tests.rs"]
mod tests;
