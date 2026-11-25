//! Backend-neutral, *non-authorizing* execution envelope for the existing owners.
//!
//! The caller controls every field in these data objects. They are neither a
//! VerifiedUseToken nor a signed effect receipt. In particular, a proposed
//! FinalUseBinding must be submitted to the independent issuer and verified
//! at the actual provider entry using the existing final-use machinery.
//!
//! This module creates no process, socket, tool, journal, issuer or new writer.

use std::fmt;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::FinalUseBinding;
use crate::Sha256Digest;

pub const EXECUTION_ENVELOPE_SCHEMA_VERSION_V1: u32 = 1;
pub const MAX_EXECUTION_PAYLOAD_BYTES_V1: u32 = 1_048_576;
pub const MAX_EXECUTION_WALL_MS_V1: u64 = 300_000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionTargetV1 {
    /// Existing App Server model-only turn; never implies tool permission.
    CodexAppServerModelOnly,
    /// Future opt-in, separately authorized process/tool provider boundary.
    CodexExecServerProcess,
}

impl ExecutionTargetV1 {
    const fn digest_tag(self) -> u8 {
        match self {
            Self::CodexAppServerModelOnly => 1,
            Self::CodexExecServerProcess => 2,
        }
    }
}

/// An unsigned request proposal. Bytes are deliberately not stored here.
///
/// The physical owner must authenticate the selected source, validate the
/// original payload bytes, persist the exact intent and consume an independent
/// final-use token at the actual effect entry. Deserializing this struct does
/// not authorize anything, including read-only tool access.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionIntentV1 {
    pub schema_version: u32,
    pub operation_id: String,
    pub subject_id: String,
    pub scope_id: String,
    pub destination_id: String,
    pub target: ExecutionTargetV1,
    pub generation: u64,
    pub fence: u64,
    pub authority_epoch: u64,
    pub payload_sha256: Sha256Digest,
    pub payload_bytes: u32,
    pub deadline_unix_ms: u64,
    pub max_wall_ms: u64,
}

/// Deterministic request identity and *unsigned* final-use binding proposal.
///
/// The proposed binding is a value, not a verified grant. In particular, no
/// function here exposes the non-constructible VerifiedUseToken.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionBindingProposalV1 {
    pub request_sha256: [u8; 32],
    pub scope_sha256: [u8; 32],
    pub proposed_final_use_binding: FinalUseBinding,
}

/// A provider/transport claim; not an authenticated terminal effect receipt.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionTransportObservationV1 {
    /// Even a "not sent" assertion needs owner-held pre-effect abort proof.
    NotSentClaimed,
    /// Transport/session acceptance is not task completion.
    AcceptedClaimed,
    /// Terminality is only claimed until the original owner verifies it.
    TerminalClaimed,
    /// Connection, timeout, cancellation or crash made the result unknown.
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionObservationV1 {
    pub schema_version: u32,
    pub operation_id: String,
    pub scope_id: String,
    pub destination_id: String,
    pub generation: u64,
    pub fence: u64,
    pub authority_epoch: u64,
    pub request_sha256: [u8; 32],
    pub transport: ExecutionTransportObservationV1,
    /// Only a digest of the *claimed* original receipt; not its authentication.
    pub claimed_original_receipt_sha256: Option<Sha256Digest>,
}

/// Deliberately no Dispatch/Retry/Complete/Authorize variant exists.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionReconcileOnlyV1 {
    /// Find the original durable operation and externally qualified status.
    LookupOriginalOperation,
    /// Verify the complete original provider/owner receipt, not this digest.
    VerifyOriginalReceipt,
}

/// A read-only reconciliation plan; not permission to mutate durable state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionReconcilePlanV1 {
    pub operation_id: String,
    pub request_sha256: [u8; 32],
    pub generation: u64,
    pub fence: u64,
    pub action: ExecutionReconcileOnlyV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionEnvelopeErrorV1 {
    InvalidVersion,
    InvalidIdentity,
    InvalidGenerationOrEpoch,
    InvalidDeadlineOrBudget,
    InvalidPayloadSize,
    InvalidDigest,
    PayloadMismatch,
    ObservationMismatch,
    InvalidObservation,
}

impl fmt::Display for ExecutionEnvelopeErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for ExecutionEnvelopeErrorV1 {}

impl ExecutionIntentV1 {
    pub fn validate(&self) -> Result<(), ExecutionEnvelopeErrorV1> {
        if self.schema_version != EXECUTION_ENVELOPE_SCHEMA_VERSION_V1 {
            return Err(ExecutionEnvelopeErrorV1::InvalidVersion);
        }
        if !valid_identifier(&self.operation_id)
            || !valid_identifier(&self.subject_id)
            || !valid_identifier(&self.scope_id)
            || !valid_identifier(&self.destination_id)
        {
            return Err(ExecutionEnvelopeErrorV1::InvalidIdentity);
        }
        if self.generation == 0 || self.fence == 0 || self.authority_epoch == 0 {
            return Err(ExecutionEnvelopeErrorV1::InvalidGenerationOrEpoch);
        }
        if self.deadline_unix_ms == 0
            || self.max_wall_ms == 0
            || self.max_wall_ms > MAX_EXECUTION_WALL_MS_V1
        {
            return Err(ExecutionEnvelopeErrorV1::InvalidDeadlineOrBudget);
        }
        if self.payload_bytes == 0 || self.payload_bytes > MAX_EXECUTION_PAYLOAD_BYTES_V1 {
            return Err(ExecutionEnvelopeErrorV1::InvalidPayloadSize);
        }
        self.decoded_payload_digest()?;
        Ok(())
    }

    /// Check exact physical bytes before any request to an existing owner.
    /// Matching bytes are *not* an admission or authorization decision.
    pub fn verify_payload(&self, payload: &[u8]) -> Result<(), ExecutionEnvelopeErrorV1> {
        self.validate()?;
        if payload.len() != self.payload_bytes as usize {
            return Err(ExecutionEnvelopeErrorV1::PayloadMismatch);
        }
        let calculated: [u8; 32] = Sha256::digest(payload).into();
        if calculated != self.decoded_payload_digest()? {
            return Err(ExecutionEnvelopeErrorV1::PayloadMismatch);
        }
        Ok(())
    }

    /// Domain-separated, length-delimited request identity independent of
    /// JSON field order, serialization environment, and runtime transport.
    pub fn binding_proposal(&self) -> Result<ExecutionBindingProposalV1, ExecutionEnvelopeErrorV1> {
        self.validate()?;
        let mut request = Sha256::new();
        request.update(b"hepta.execution.intent.v1\0");
        request.update(self.schema_version.to_be_bytes());
        hash_field(&mut request, &self.operation_id);
        hash_field(&mut request, &self.subject_id);
        hash_field(&mut request, &self.scope_id);
        hash_field(&mut request, &self.destination_id);
        request.update([self.target.digest_tag()]);
        request.update(self.generation.to_be_bytes());
        request.update(self.fence.to_be_bytes());
        request.update(self.authority_epoch.to_be_bytes());
        let payload_sha256 = self.decoded_payload_digest()?;
        request.update(payload_sha256);
        request.update(self.payload_bytes.to_be_bytes());
        request.update(self.deadline_unix_ms.to_be_bytes());
        request.update(self.max_wall_ms.to_be_bytes());
        let request_sha256: [u8; 32] = request.finalize().into();

        let mut scope = Sha256::new();
        scope.update(b"hepta.execution.scope.v1\0");
        hash_field(&mut scope, &self.subject_id);
        hash_field(&mut scope, &self.scope_id);
        hash_field(&mut scope, &self.destination_id);
        scope.update(self.generation.to_be_bytes());
        scope.update(self.fence.to_be_bytes());
        scope.update(self.authority_epoch.to_be_bytes());
        let scope_sha256: [u8; 32] = scope.finalize().into();

        Ok(ExecutionBindingProposalV1 {
            request_sha256,
            scope_sha256,
            proposed_final_use_binding: FinalUseBinding {
                subject_id: self.subject_id.clone(),
                destination_id: self.destination_id.clone(),
                request_sha256,
                scope_sha256,
                payload_sha256,
            },
        })
    }

    fn decoded_payload_digest(&self) -> Result<[u8; 32], ExecutionEnvelopeErrorV1> {
        let source = self.payload_sha256.as_str();
        Sha256Digest::parse(source.to_owned())
            .map_err(|_| ExecutionEnvelopeErrorV1::InvalidDigest)?;
        let mut bytes = [0_u8; 32];
        for (byte, pair) in bytes.iter_mut().zip(source.as_bytes().chunks_exact(2)) {
            let pair =
                std::str::from_utf8(pair).map_err(|_| ExecutionEnvelopeErrorV1::InvalidDigest)?;
            *byte = u8::from_str_radix(pair, 16)
                .map_err(|_| ExecutionEnvelopeErrorV1::InvalidDigest)?;
        }
        if bytes == [0; 32] {
            return Err(ExecutionEnvelopeErrorV1::InvalidDigest);
        }
        Ok(bytes)
    }
}

/// A checked transport claim cannot close an effect. Unknown or changed
/// original-owner state must be reconciled by that owner under its own journal,
/// real signer/permission, revocation, and original provider status evidence.
pub fn plan_execution_reconciliation_v1(
    intent: &ExecutionIntentV1,
    observation: &ExecutionObservationV1,
) -> Result<ExecutionReconcilePlanV1, ExecutionEnvelopeErrorV1> {
    let binding = intent.binding_proposal()?;
    if observation.schema_version != EXECUTION_ENVELOPE_SCHEMA_VERSION_V1 {
        return Err(ExecutionEnvelopeErrorV1::InvalidVersion);
    }
    if observation.operation_id != intent.operation_id
        || observation.scope_id != intent.scope_id
        || observation.destination_id != intent.destination_id
        || observation.generation != intent.generation
        || observation.fence != intent.fence
        || observation.authority_epoch != intent.authority_epoch
        || observation.request_sha256 != binding.request_sha256
    {
        return Err(ExecutionEnvelopeErrorV1::ObservationMismatch);
    }
    let action = match observation.transport {
        ExecutionTransportObservationV1::TerminalClaimed => {
            let Some(digest) = &observation.claimed_original_receipt_sha256 else {
                return Err(ExecutionEnvelopeErrorV1::InvalidObservation);
            };
            Sha256Digest::parse(digest.as_str().to_owned())
                .map_err(|_| ExecutionEnvelopeErrorV1::InvalidDigest)?;
            if digest.as_str().bytes().all(|byte| byte == b'0') {
                return Err(ExecutionEnvelopeErrorV1::InvalidDigest);
            }
            ExecutionReconcileOnlyV1::VerifyOriginalReceipt
        }
        ExecutionTransportObservationV1::NotSentClaimed
        | ExecutionTransportObservationV1::AcceptedClaimed
        | ExecutionTransportObservationV1::Indeterminate => {
            if observation.claimed_original_receipt_sha256.is_some() {
                return Err(ExecutionEnvelopeErrorV1::InvalidObservation);
            }
            ExecutionReconcileOnlyV1::LookupOriginalOperation
        }
    };
    Ok(ExecutionReconcilePlanV1 {
        operation_id: intent.operation_id.clone(),
        request_sha256: binding.request_sha256,
        generation: intent.generation,
        fence: intent.fence,
        action,
    })
}

fn hash_field(hasher: &mut Sha256, field: &str) {
    hasher.update((field.len() as u64).to_be_bytes());
    hasher.update(field.as_bytes());
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && !value.contains("..")
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

#[cfg(test)]
#[path = "execution_contract_v1_tests.rs"]
mod tests;
