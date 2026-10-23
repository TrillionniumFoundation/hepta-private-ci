//! Signed resolution protocol for runtime.codex effects whose terminality and
//! absence are both unprovable.
//!
//! This module validates authority; it does not provide an authority service,
//! trusted clock, key custody, durable anti-rollback store, provider oracle or
//! operator acceptance. Hosts must persist and externally checkpoint the
//! returned frontier before treating a verified resolution as committed.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

pub const QUARANTINED_EFFECT_SCHEMA_VERSION: u32 = 1;
pub const QUARANTINE_RESOLUTION_SCHEMA_VERSION: u32 = 1;
const MAX_EVIDENCE_DIGESTS: usize = 256;
const MAX_USED_NONCES: usize = 1_048_576;
const MAX_DIAGNOSTIC_BYTES: usize = 1024;
const MAX_REASON_CODE_BYTES: usize = 96;
const MAX_RESOLUTION_LIFETIME_MS: u64 = 300_000;
const MAX_RECONCILIATION_ATTEMPTS: u32 = 1_000_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuarantinedEffectV1 {
    pub schema_version: u32,
    pub quarantine_revision: u64,
    pub operation_id: String,
    pub source_admission_sha256: [u8; 32],
    pub request_sha256: [u8; 32],
    pub payload_sha256: [u8; 32],
    pub local_dispatch_sha256: [u8; 32],
    pub local_dispatch_revision: u64,
    pub agent_run_id: String,
    pub agent_revision: u64,
    pub agent_dispatch_sha256: [u8; 32],
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub revocation_head_sha256: [u8; 32],
    pub authority_witness_sha256: [u8; 32],
    pub agent_generation: u64,
    pub app_server_session_id: String,
    pub app_server_version: String,
    pub codex_home_sha256: [u8; 32],
    pub connection_id: u64,
    pub thread_id: String,
    pub turn_id: Option<String>,
    pub client_user_message_id: String,
    pub user_input_sha256: [u8; 32],
    pub model_id: String,
    pub provider_id: String,
    pub first_unknown_unix_ms: u64,
    pub last_reconciled_unix_ms: u64,
    pub reconciliation_attempts: u32,
    pub evidence_sha256: BTreeSet<[u8; 32]>,
    pub reason_code: String,
    pub redacted_diagnostic: String,
}

impl QuarantinedEffectV1 {
    pub fn validate(&self) -> Result<(), QuarantineProtocolError> {
        if self.schema_version != QUARANTINED_EFFECT_SCHEMA_VERSION {
            return Err(QuarantineProtocolError::UnsupportedSchema);
        }
        for value in [
            self.operation_id.as_str(),
            self.agent_run_id.as_str(),
            self.app_server_session_id.as_str(),
            self.thread_id.as_str(),
            self.client_user_message_id.as_str(),
            self.model_id.as_str(),
            self.provider_id.as_str(),
        ] {
            require_identifier(value)?;
        }
        if let Some(turn_id) = self.turn_id.as_deref() {
            require_identifier(turn_id)?;
        }
        if self.app_server_version.is_empty()
            || self.app_server_version.len() > 256
            || self
                .app_server_version
                .bytes()
                .any(|byte| byte.is_ascii_control())
        {
            return Err(QuarantineProtocolError::InvalidAppServerVersion);
        }
        for digest in [
            self.source_admission_sha256,
            self.request_sha256,
            self.payload_sha256,
            self.local_dispatch_sha256,
            self.agent_dispatch_sha256,
            self.revocation_head_sha256,
            self.authority_witness_sha256,
            self.codex_home_sha256,
            self.user_input_sha256,
        ] {
            require_digest(digest)?;
        }
        if self.local_dispatch_sha256 != self.agent_dispatch_sha256 {
            return Err(QuarantineProtocolError::DispatchBindingMismatch);
        }
        if self.quarantine_revision == 0
            || self.local_dispatch_revision == 0
            || self.agent_revision == 0
            || self.authority_epoch == 0
            || self.agent_generation == 0
            || self.connection_id == 0
            || self.reconciliation_attempts == 0
            || self.reconciliation_attempts > MAX_RECONCILIATION_ATTEMPTS
            || self.first_unknown_unix_ms == 0
            || self.last_reconciled_unix_ms < self.first_unknown_unix_ms
        {
            return Err(QuarantineProtocolError::InvalidQuarantineState);
        }
        if self.evidence_sha256.is_empty()
            || self.evidence_sha256.len() > MAX_EVIDENCE_DIGESTS
        {
            return Err(QuarantineProtocolError::InvalidEvidenceSet);
        }
        for digest in &self.evidence_sha256 {
            require_digest(*digest)?;
        }
        require_reason_code(&self.reason_code)?;
        if self.redacted_diagnostic.len() > MAX_DIAGNOSTIC_BYTES
            || self.redacted_diagnostic.as_bytes().contains(&0)
        {
            return Err(QuarantineProtocolError::InvalidDiagnostic);
        }
        Ok(())
    }

    pub fn evidence_set_sha256(&self) -> Result<[u8; 32], QuarantineProtocolError> {
        self.validate()?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.runtime.codex.quarantine-evidence-set.v1\0");
        for value in &self.evidence_sha256 {
            digest.update(value);
        }
        Ok(digest.finalize().into())
    }

    pub fn record_sha256(&self) -> Result<[u8; 32], QuarantineProtocolError> {
        self.validate()?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.runtime.codex.quarantined-effect.v1\0");
        digest.update(
            serde_json::to_vec(self).map_err(|_| QuarantineProtocolError::EncodingFailed)?,
        );
        Ok(digest.finalize().into())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QuarantineResolutionDispositionV1 {
    TerminalObserved,
    AbandonWithoutReplay,
    AuthorizeNewOperation,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QuarantineTerminalOutcomeV1 {
    Succeeded,
    Failed,
    Interrupted,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuarantineTerminalEvidenceV1 {
    pub outcome: QuarantineTerminalOutcomeV1,
    pub response_sha256: [u8; 32],
    pub correlation_sha256: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NewOperationConstraintsV1 {
    pub operation_id: String,
    pub request_sha256: [u8; 32],
    pub not_before_unix_ms: u64,
    pub maximum_attempts: u32,
    pub provider_idempotency_key_sha256: [u8; 32],
    pub compensation_prerequisite_sha256: Option<[u8; 32]>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuarantineResolutionV1 {
    pub schema_version: u32,
    pub signer_id: String,
    pub resolution_id: String,
    pub operation_id: String,
    pub quarantine_revision: u64,
    pub quarantine_record_sha256: [u8; 32],
    pub request_sha256: [u8; 32],
    pub dispatch_sha256: [u8; 32],
    pub evidence_set_sha256: [u8; 32],
    pub authority_epoch: u64,
    pub resolution_sequence: u64,
    pub nonce: [u8; 32],
    pub not_before_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub disposition: QuarantineResolutionDispositionV1,
    pub terminal: Option<QuarantineTerminalEvidenceV1>,
    pub new_operation_constraints: Option<NewOperationConstraintsV1>,
    pub reason_code: String,
}

impl QuarantineResolutionV1 {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, QuarantineProtocolError> {
        self.validate_shape()?;
        let mut bytes = b"hepta.runtime.codex.quarantine-resolution.v1\0".to_vec();
        bytes.extend(
            serde_json::to_vec(self).map_err(|_| QuarantineProtocolError::EncodingFailed)?,
        );
        Ok(bytes)
    }

    fn validate_shape(&self) -> Result<(), QuarantineProtocolError> {
        if self.schema_version != QUARANTINE_RESOLUTION_SCHEMA_VERSION {
            return Err(QuarantineProtocolError::UnsupportedSchema);
        }
        for value in [
            self.signer_id.as_str(),
            self.resolution_id.as_str(),
            self.operation_id.as_str(),
        ] {
            require_identifier(value)?;
        }
        for digest in [
            self.quarantine_record_sha256,
            self.request_sha256,
            self.dispatch_sha256,
            self.evidence_set_sha256,
            self.nonce,
        ] {
            require_digest(digest)?;
        }
        if self.quarantine_revision == 0
            || self.authority_epoch == 0
            || self.resolution_sequence == 0
            || self.not_before_unix_ms == 0
            || self.expires_at_unix_ms <= self.not_before_unix_ms
            || self.expires_at_unix_ms - self.not_before_unix_ms
                > MAX_RESOLUTION_LIFETIME_MS
        {
            return Err(QuarantineProtocolError::InvalidResolution);
        }
        require_reason_code(&self.reason_code)?;
        match self.disposition {
            QuarantineResolutionDispositionV1::TerminalObserved => {
                let terminal = self
                    .terminal
                    .as_ref()
                    .ok_or(QuarantineProtocolError::DispositionMismatch)?;
                require_digest(terminal.response_sha256)?;
                require_digest(terminal.correlation_sha256)?;
                if self.new_operation_constraints.is_some() {
                    return Err(QuarantineProtocolError::DispositionMismatch);
                }
            }
            QuarantineResolutionDispositionV1::AbandonWithoutReplay => {
                if self.terminal.is_some() || self.new_operation_constraints.is_some() {
                    return Err(QuarantineProtocolError::DispositionMismatch);
                }
            }
            QuarantineResolutionDispositionV1::AuthorizeNewOperation => {
                if self.terminal.is_some() {
                    return Err(QuarantineProtocolError::DispositionMismatch);
                }
                let constraints = self
                    .new_operation_constraints
                    .as_ref()
                    .ok_or(QuarantineProtocolError::DispositionMismatch)?;
                require_identifier(&constraints.operation_id)?;
                if constraints.operation_id == self.operation_id
                    || constraints.maximum_attempts != 1
                    || constraints.not_before_unix_ms < self.not_before_unix_ms
                {
                    return Err(QuarantineProtocolError::UnsafeNewOperation);
                }
                require_digest(constraints.request_sha256)?;
                require_digest(constraints.provider_idempotency_key_sha256)?;
                if let Some(digest) = constraints.compensation_prerequisite_sha256 {
                    require_digest(digest)?;
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedQuarantineResolutionV1 {
    pub resolution: QuarantineResolutionV1,
    pub signature: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuarantineResolutionFrontierV1 {
    pub authority_epoch: u64,
    pub resolution_sequence: u64,
    pub state_sha256: [u8; 32],
}

#[derive(Clone)]
pub struct QuarantineResolutionVerifier {
    signer_id: String,
    verifying_key: VerifyingKey,
    authority_epoch: u64,
    resolution_sequence: u64,
    used_nonces: BTreeSet<[u8; 32]>,
}

impl fmt::Debug for QuarantineResolutionVerifier {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("QuarantineResolutionVerifier")
            .field("signer_id", &self.signer_id)
            .field("authority_epoch", &self.authority_epoch)
            .field("resolution_sequence", &self.resolution_sequence)
            .field("used_nonces", &self.used_nonces.len())
            .finish_non_exhaustive()
    }
}

impl QuarantineResolutionVerifier {
    pub fn new(
        signer_id: String,
        verifying_key: [u8; 32],
        authority_epoch: u64,
        resolution_sequence: u64,
        used_nonces: BTreeSet<[u8; 32]>,
    ) -> Result<Self, QuarantineProtocolError> {
        let verifying_key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| QuarantineProtocolError::InvalidTrust)?;
        if !valid_identifier(&signer_id)
            || verifying_key.is_weak()
            || authority_epoch == 0
            || used_nonces.len() > MAX_USED_NONCES
            || used_nonces.contains(&[0; 32])
        {
            return Err(QuarantineProtocolError::InvalidTrust);
        }
        Ok(Self {
            signer_id,
            verifying_key,
            authority_epoch,
            resolution_sequence,
            used_nonces,
        })
    }

    pub fn verify(
        &mut self,
        signed: &SignedQuarantineResolutionV1,
        quarantine: &QuarantinedEffectV1,
        now_unix_ms: u64,
    ) -> Result<VerifiedQuarantineResolutionV1, QuarantineProtocolError> {
        quarantine.validate()?;
        signed.resolution.validate_shape()?;
        let resolution = &signed.resolution;
        if resolution.signer_id != self.signer_id {
            return Err(QuarantineProtocolError::SignerMismatch);
        }
        if resolution.authority_epoch != self.authority_epoch
            || resolution.authority_epoch != quarantine.authority_epoch
        {
            return Err(QuarantineProtocolError::AuthorityEpochMismatch);
        }
        if resolution.resolution_sequence <= self.resolution_sequence {
            return Err(QuarantineProtocolError::ResolutionRollback);
        }
        if self.used_nonces.contains(&resolution.nonce) {
            return Err(QuarantineProtocolError::NonceReplay);
        }
        if now_unix_ms < resolution.not_before_unix_ms
            || now_unix_ms >= resolution.expires_at_unix_ms
        {
            return Err(QuarantineProtocolError::ResolutionExpired);
        }
        let quarantine_record_sha256 = quarantine.record_sha256()?;
        if resolution.operation_id != quarantine.operation_id
            || resolution.quarantine_revision != quarantine.quarantine_revision
            || resolution.quarantine_record_sha256 != quarantine_record_sha256
            || resolution.request_sha256 != quarantine.request_sha256
            || resolution.dispatch_sha256 != quarantine.local_dispatch_sha256
            || resolution.evidence_set_sha256 != quarantine.evidence_set_sha256()?
        {
            return Err(QuarantineProtocolError::QuarantineBindingMismatch);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| QuarantineProtocolError::InvalidSignature)?;
        self.verifying_key
            .verify_strict(&resolution.signing_bytes()?, &signature)
            .map_err(|_| QuarantineProtocolError::InvalidSignature)?;
        if self.used_nonces.len() >= MAX_USED_NONCES {
            return Err(QuarantineProtocolError::CapacityExceeded);
        }
        self.used_nonces.insert(resolution.nonce);
        self.resolution_sequence = resolution.resolution_sequence;
        Ok(VerifiedQuarantineResolutionV1 {
            resolution: resolution.clone(),
            quarantine_record_sha256,
        })
    }

    pub fn frontier(&self) -> QuarantineResolutionFrontierV1 {
        let mut digest = Sha256::new();
        digest.update(b"hepta.runtime.codex.quarantine-resolution-frontier.v1\0");
        digest.update(
            u64::try_from(self.signer_id.len())
                .unwrap_or(u64::MAX)
                .to_le_bytes(),
        );
        digest.update(self.signer_id.as_bytes());
        digest.update(self.verifying_key.to_bytes());
        digest.update(self.authority_epoch.to_le_bytes());
        digest.update(self.resolution_sequence.to_le_bytes());
        for nonce in &self.used_nonces {
            digest.update(nonce);
        }
        QuarantineResolutionFrontierV1 {
            authority_epoch: self.authority_epoch,
            resolution_sequence: self.resolution_sequence,
            state_sha256: digest.finalize().into(),
        }
    }
}

pub struct VerifiedQuarantineResolutionV1 {
    resolution: QuarantineResolutionV1,
    quarantine_record_sha256: [u8; 32],
}

impl fmt::Debug for VerifiedQuarantineResolutionV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedQuarantineResolutionV1")
            .field("resolution_id", &self.resolution.resolution_id)
            .field("operation_id", &self.resolution.operation_id)
            .field("disposition", &self.resolution.disposition)
            .finish_non_exhaustive()
    }
}

impl VerifiedQuarantineResolutionV1 {
    pub fn resolution(&self) -> &QuarantineResolutionV1 {
        &self.resolution
    }

    pub fn quarantine_record_sha256(&self) -> [u8; 32] {
        self.quarantine_record_sha256
    }

    pub fn into_resolution(self) -> QuarantineResolutionV1 {
        self.resolution
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QuarantineProtocolError {
    UnsupportedSchema,
    InvalidIdentifier,
    EmptyDigest,
    InvalidAppServerVersion,
    InvalidQuarantineState,
    DispatchBindingMismatch,
    InvalidEvidenceSet,
    InvalidDiagnostic,
    InvalidResolution,
    DispositionMismatch,
    UnsafeNewOperation,
    EncodingFailed,
    InvalidTrust,
    SignerMismatch,
    AuthorityEpochMismatch,
    ResolutionRollback,
    NonceReplay,
    ResolutionExpired,
    QuarantineBindingMismatch,
    InvalidSignature,
    CapacityExceeded,
}

impl fmt::Display for QuarantineProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for QuarantineProtocolError {}

fn require_digest(value: [u8; 32]) -> Result<(), QuarantineProtocolError> {
    if value == [0; 32] {
        Err(QuarantineProtocolError::EmptyDigest)
    } else {
        Ok(())
    }
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

fn require_identifier(value: &str) -> Result<(), QuarantineProtocolError> {
    if valid_identifier(value) {
        Ok(())
    } else {
        Err(QuarantineProtocolError::InvalidIdentifier)
    }
}

fn require_reason_code(value: &str) -> Result<(), QuarantineProtocolError> {
    if !value.is_empty()
        && value.len() <= MAX_REASON_CODE_BYTES
        && value.bytes().all(|byte| {
            byte.is_ascii_uppercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-')
        })
    {
        Ok(())
    } else {
        Err(QuarantineProtocolError::InvalidDiagnostic)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    fn digest(byte: u8) -> [u8; 32] {
        [byte; 32]
    }

    fn quarantine() -> QuarantinedEffectV1 {
        QuarantinedEffectV1 {
            schema_version: 1,
            quarantine_revision: 11,
            operation_id: "operation:original".to_string(),
            source_admission_sha256: digest(1),
            request_sha256: digest(2),
            payload_sha256: digest(3),
            local_dispatch_sha256: digest(4),
            local_dispatch_revision: 7,
            agent_run_id: "run:one".to_string(),
            agent_revision: 9,
            agent_dispatch_sha256: digest(4),
            authority_epoch: 12,
            revocation_revision: 18,
            revocation_head_sha256: digest(5),
            authority_witness_sha256: digest(6),
            agent_generation: 3,
            app_server_session_id: "session:one".to_string(),
            app_server_version: "app-server-test".to_string(),
            codex_home_sha256: digest(7),
            connection_id: 55,
            thread_id: "thread:one".to_string(),
            turn_id: Some("turn:one".to_string()),
            client_user_message_id: "message:one".to_string(),
            user_input_sha256: digest(8),
            model_id: "model:test".to_string(),
            provider_id: "provider:test".to_string(),
            first_unknown_unix_ms: 1_000,
            last_reconciled_unix_ms: 2_000,
            reconciliation_attempts: 4,
            evidence_sha256: BTreeSet::from([digest(9), digest(10)]),
            reason_code: "HISTORY_UNAVAILABLE".to_string(),
            redacted_diagnostic: "original App Server history unavailable".to_string(),
        }
    }

    fn resolution(
        quarantine: &QuarantinedEffectV1,
        disposition: QuarantineResolutionDispositionV1,
    ) -> QuarantineResolutionV1 {
        let (terminal, new_operation_constraints) = match disposition {
            QuarantineResolutionDispositionV1::TerminalObserved => (
                Some(QuarantineTerminalEvidenceV1 {
                    outcome: QuarantineTerminalOutcomeV1::Succeeded,
                    response_sha256: digest(11),
                    correlation_sha256: digest(12),
                }),
                None,
            ),
            QuarantineResolutionDispositionV1::AbandonWithoutReplay => (None, None),
            QuarantineResolutionDispositionV1::AuthorizeNewOperation => (
                None,
                Some(NewOperationConstraintsV1 {
                    operation_id: "operation:new".to_string(),
                    request_sha256: digest(13),
                    not_before_unix_ms: 1_100,
                    maximum_attempts: 1,
                    provider_idempotency_key_sha256: digest(14),
                    compensation_prerequisite_sha256: Some(digest(15)),
                }),
            ),
        };
        QuarantineResolutionV1 {
            schema_version: 1,
            signer_id: "independent-quarantine-authority".to_string(),
            resolution_id: "resolution:one".to_string(),
            operation_id: quarantine.operation_id.clone(),
            quarantine_revision: quarantine.quarantine_revision,
            quarantine_record_sha256: quarantine.record_sha256().unwrap(),
            request_sha256: quarantine.request_sha256,
            dispatch_sha256: quarantine.local_dispatch_sha256,
            evidence_set_sha256: quarantine.evidence_set_sha256().unwrap(),
            authority_epoch: quarantine.authority_epoch,
            resolution_sequence: 1042,
            nonce: digest(16),
            not_before_unix_ms: 1_000,
            expires_at_unix_ms: 60_000,
            disposition,
            terminal,
            new_operation_constraints,
            reason_code: "DUAL_OPERATOR_REVIEW".to_string(),
        }
    }

    fn signed(
        key: &SigningKey,
        resolution: QuarantineResolutionV1,
    ) -> SignedQuarantineResolutionV1 {
        let signature = key.sign(&resolution.signing_bytes().unwrap()).to_bytes().to_vec();
        SignedQuarantineResolutionV1 {
            resolution,
            signature,
        }
    }

    fn verifier(key: &SigningKey) -> QuarantineResolutionVerifier {
        QuarantineResolutionVerifier::new(
            "independent-quarantine-authority".to_string(),
            key.verifying_key().to_bytes(),
            12,
            1000,
            BTreeSet::new(),
        )
        .unwrap()
    }

    #[test]
    fn terminal_resolution_is_exactly_bound_and_single_use() {
        let quarantine = quarantine();
        let key = SigningKey::from_bytes(&[71; 32]);
        let signed = signed(
            &key,
            resolution(
                &quarantine,
                QuarantineResolutionDispositionV1::TerminalObserved,
            ),
        );
        let mut verifier = verifier(&key);
        let verified = verifier.verify(&signed, &quarantine, 2_000).unwrap();
        assert_eq!(
            verified.resolution().disposition,
            QuarantineResolutionDispositionV1::TerminalObserved
        );
        assert_eq!(verifier.frontier().resolution_sequence, 1042);
        assert!(matches!(
            verifier.verify(&signed, &quarantine, 2_000),
            Err(QuarantineProtocolError::ResolutionRollback)
        ));
    }

    #[test]
    fn forged_binding_revision_and_signature_fail_closed() {
        let quarantine = quarantine();
        let key = SigningKey::from_bytes(&[72; 32]);
        let mut proposal = resolution(
            &quarantine,
            QuarantineResolutionDispositionV1::AbandonWithoutReplay,
        );
        proposal.quarantine_revision += 1;
        let signed = signed(&key, proposal);
        assert!(matches!(
            verifier(&key).verify(&signed, &quarantine, 2_000),
            Err(QuarantineProtocolError::QuarantineBindingMismatch)
        ));

        let other = SigningKey::from_bytes(&[73; 32]);
        let forged = signed(
            &other,
            resolution(
                &quarantine,
                QuarantineResolutionDispositionV1::AbandonWithoutReplay,
            ),
        );
        assert!(matches!(
            verifier(&key).verify(&forged, &quarantine, 2_000),
            Err(QuarantineProtocolError::InvalidSignature)
        ));
    }

    #[test]
    fn nonce_reuse_is_rejected_at_a_later_sequence() {
        let quarantine = quarantine();
        let key = SigningKey::from_bytes(&[74; 32]);
        let first = signed(
            &key,
            resolution(
                &quarantine,
                QuarantineResolutionDispositionV1::AbandonWithoutReplay,
            ),
        );
        let mut verifier = verifier(&key);
        verifier.verify(&first, &quarantine, 2_000).unwrap();
        let mut second = resolution(
            &quarantine,
            QuarantineResolutionDispositionV1::AbandonWithoutReplay,
        );
        second.resolution_id = "resolution:two".to_string();
        second.resolution_sequence = 1043;
        let second = signed(&key, second);
        assert!(matches!(
            verifier.verify(&second, &quarantine, 2_000),
            Err(QuarantineProtocolError::NonceReplay)
        ));
    }

    #[test]
    fn new_operation_must_be_distinct_and_one_shot() {
        let quarantine = quarantine();
        let mut proposal = resolution(
            &quarantine,
            QuarantineResolutionDispositionV1::AuthorizeNewOperation,
        );
        let constraints = proposal.new_operation_constraints.as_mut().unwrap();
        constraints.operation_id = quarantine.operation_id.clone();
        assert!(matches!(
            proposal.signing_bytes(),
            Err(QuarantineProtocolError::UnsafeNewOperation)
        ));
        constraints.operation_id = "operation:new".to_string();
        constraints.maximum_attempts = 2;
        assert!(matches!(
            proposal.signing_bytes(),
            Err(QuarantineProtocolError::UnsafeNewOperation)
        ));
    }

    #[test]
    fn unknown_fields_and_empty_evidence_are_rejected() {
        let mut value = serde_json::to_value(quarantine()).unwrap();
        value["ambientAuthority"] = serde_json::json!(true);
        assert!(serde_json::from_value::<QuarantinedEffectV1>(value).is_err());
        let mut quarantine = quarantine();
        quarantine.evidence_sha256.clear();
        assert_eq!(
            quarantine.validate(),
            Err(QuarantineProtocolError::InvalidEvidenceSet)
        );
    }
}
