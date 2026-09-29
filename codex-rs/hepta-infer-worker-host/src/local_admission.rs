//! Experimental, kernel-verified preparation for a local model operation.
//!
//! This is not a physical driver or a durable execution entrypoint. In particular,
//! it deliberately exposes no method that enters the effect boundary: that must
//! consume inference.control's future local dispatch proof, not a caller boolean.
//! The legacy synchronous ModelDriver cannot consume these verified values.

use std::fmt;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use tokio::time::Instant;

use crate::model_worker::ModelManifest;

const MAX_INPUT_BYTES: usize = 32 * 1024;
const MAX_LIFETIME_MS: u64 = 300_000;

#[derive(Debug)]
pub enum LocalAdmissionError {
    InvalidRequest,
    InputMismatch,
    DeadlineElapsed,
    ArithmeticOverflow,
    Authority(FinalUseError),
    Trust(AuthorityTrustError),
}

impl fmt::Display for LocalAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LocalAdmissionError {}

type Result<T> = std::result::Result<T, LocalAdmissionError>;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalOperationKind {
    LoadModel,
    RunModel,
}

/// Untrusted proposal. Every field is signed through the scope/request binding.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct LocalResourceLimits {
    pub maximum_aggregate_memory_bytes: u64,
    pub maximum_models: u16,
    pub maximum_active_requests: u16,
    pub maximum_tokens: u32,
    pub maximum_kv_bytes: u64,
    pub maximum_transient_bytes: u64,
}

/// No field in this proposal constitutes authority before verifier.claim.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalAdmissionRequest {
    pub operation_id: String,
    pub operation: LocalOperationKind,
    pub worker_id: String,
    pub worker_generation: u64,
    pub device_lease_id: String,
    pub manifest: ModelManifest,
    pub limits: LocalResourceLimits,
    pub input_sha256: [u8; 32],
    pub deadline_unix_ms: u64,
}

impl LocalAdmissionRequest {
    /// Exact bytes for an independent issuer to authorize. This pure operation
    /// neither verifies a grant nor resolves/loads any model or device.
    pub fn binding(&self) -> Result<FinalUseBinding> {
        for id in [
            &self.operation_id,
            &self.worker_id,
            &self.device_lease_id,
            &self.manifest.model_id,
        ] {
            StableId::new(id.clone()).map_err(|_| LocalAdmissionError::InvalidRequest)?;
        }
        let manifest = &self.manifest;
        for value in [
            &manifest.model_digest,
            &manifest.weights_digest,
            &manifest.tokenizer_digest,
            &manifest.preprocessor_digest,
            &manifest.quantization_digest,
            &manifest.runtime_digest,
            &manifest.device_digest,
        ] {
            let parsed: Digest32 = value
                .parse()
                .map_err(|_| LocalAdmissionError::InvalidRequest)?;
            if parsed.is_zero() || parsed.to_string() != *value {
                return Err(LocalAdmissionError::InvalidRequest);
            }
        }
        let limits = &self.limits;
        let required = manifest
            .maximum_resident_bytes
            .checked_add(limits.maximum_kv_bytes)
            .and_then(|value| value.checked_add(limits.maximum_transient_bytes))
            .ok_or(LocalAdmissionError::ArithmeticOverflow)?;
        if self.worker_generation == 0
            || self.deadline_unix_ms == 0
            || self.input_sha256 == [0; 32]
            || manifest.maximum_resident_bytes == 0
            || manifest.maximum_tokens == 0
            || manifest.maximum_tokens > 1_000_000
            || limits.maximum_models == 0
            || limits.maximum_models > 8
            || limits.maximum_active_requests == 0
            || limits.maximum_active_requests > 256
            || limits.maximum_tokens == 0
            || limits.maximum_tokens > manifest.maximum_tokens
            || required > limits.maximum_aggregate_memory_bytes
        {
            return Err(LocalAdmissionError::InvalidRequest);
        }
        let tuple = (
            &manifest.model_id,
            &manifest.model_digest,
            &manifest.weights_digest,
            &manifest.tokenizer_digest,
            &manifest.preprocessor_digest,
            &manifest.quantization_digest,
            &manifest.runtime_digest,
            &manifest.device_digest,
            manifest.maximum_tokens,
            manifest.maximum_resident_bytes,
        );
        let scope = serde_json::to_vec(&(
            "hepta.inference.local-scope.v1",
            &self.worker_id,
            self.worker_generation,
            &self.device_lease_id,
            tuple,
            limits,
        ))
        .map_err(|_| LocalAdmissionError::InvalidRequest)?;
        let scope_sha256: [u8; 32] = Sha256::digest(scope).into();
        let request = serde_json::to_vec(&(
            "hepta.inference.local-request.v1",
            &self.operation_id,
            self.operation,
            scope_sha256,
            self.input_sha256,
            self.deadline_unix_ms,
        ))
        .map_err(|_| LocalAdmissionError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: self.worker_id.clone(),
            destination_id: "inference.worker.local-model.v1".to_string(),
            request_sha256: Sha256::digest(request).into(),
            scope_sha256,
            payload_sha256: self.input_sha256,
        })
    }
}

/// Host configuration, not request metadata. Private signing keys are absent.
/// The same protected clock is installed in both this adapter and the kernel.
pub struct LocalAuthorityConfig {
    pub state_directory: PathBuf,
    pub signer_id: String,
    pub verifying_key: [u8; 32],
    pub revocations: FinalUseRevocations,
    pub worker_id: String,
    pub worker_generation: u64,
    pub device_lease_id: String,
}

#[derive(Default)]
struct ClockState {
    last: Option<u64>,
    fenced: bool,
}

struct GuardedClock {
    source: Arc<dyn AuthorityClock>,
    state: Mutex<ClockState>,
}

impl AuthorityClock for GuardedClock {
    fn now_unix_ms(&self) -> std::result::Result<u64, AuthorityTrustError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if state.fenced {
            return Err(AuthorityTrustError::Unavailable);
        }
        let now = match self.source.now_unix_ms() {
            Ok(now) => now,
            Err(error) => {
                state.fenced = true;
                return Err(error);
            }
        };
        if state.last.is_some_and(|last| now < last) {
            state.fenced = true;
            return Err(AuthorityTrustError::Conflict);
        }
        state.last = Some(now);
        Ok(now)
    }
}

/// A fixed monotonic deadline plus the exact signed absolute deadline. It is
/// not serializable, cloneable, caller-constructible or resettable on retry.
pub struct TrustedDeadline {
    absolute_unix_ms: u64,
    monotonic: Instant,
    clock: Arc<GuardedClock>,
}

impl TrustedDeadline {
    pub fn remaining(&self) -> Result<Duration> {
        let now = self
            .clock
            .now_unix_ms()
            .map_err(LocalAdmissionError::Trust)?;
        let wall = self
            .absolute_unix_ms
            .checked_sub(now)
            .filter(|remaining| *remaining > 0)
            .ok_or(LocalAdmissionError::DeadlineElapsed)?;
        let monotonic = self
            .monotonic
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or(LocalAdmissionError::DeadlineElapsed)?;
        Ok(monotonic.min(Duration::from_millis(wall)))
    }

    pub fn absolute_unix_ms(&self) -> u64 {
        self.absolute_unix_ms
    }
}

/// Kernel-authorized manifest identity, NOT proof of physical artifact loading.
/// Constructors are private; the only origin is a successfully claimed grant.
pub struct VerifiedModelManifest {
    value: ModelManifest,
}

impl VerifiedModelManifest {
    pub fn manifest(&self) -> &ModelManifest {
        &self.value
    }
}

/// Owned, immutable input bytes actually hashed by the verifier. No digest-only
/// out-of-band payload channel is used by this preparation contract.
pub struct VerifiedInput {
    bytes: Arc<[u8]>,
    sha256: [u8; 32],
}

impl VerifiedInput {
    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn sha256(&self) -> [u8; 32] {
        self.sha256
    }
}

/// This evidence is not an authority-bearing handle and cannot enter an effect.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct LocalGrantWitness {
    pub signer_id: String,
    pub grant_id: String,
    pub nonce: [u8; 32],
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub revocation_head_sha256: [u8; 32],
    pub authority_witness_sha256: [u8; 32],
    pub semantic_sha256: [u8; 32],
}

/// A non-cloneable, non-serializable kernel claim for ONE exact local operation.
/// It intentionally has no public effect-entry or conversion-to-raw-grant API.
pub struct VerifiedResourceGrant {
    token: VerifiedUseToken,
    binding: FinalUseBinding,
    authority: FinalUseAuthority,
    signer_id: String,
    grant_id: String,
    nonce: [u8; 32],
    manifest: VerifiedModelManifest,
    input: VerifiedInput,
    deadline: TrustedDeadline,
    limits: LocalResourceLimits,
}

impl VerifiedResourceGrant {
    pub fn check_live(&self) -> Result<()> {
        self.deadline.remaining()?;
        let head = self
            .authority
            .revocation_head()
            .map_err(LocalAdmissionError::Authority)?;
        if head.authority_epoch != self.token.claimed_authority_epoch()
            || head.revision != self.token.claimed_revocation_revision()
            || head.revoked_grant_ids.contains(&self.grant_id)
        {
            return Err(LocalAdmissionError::Authority(
                FinalUseError::StaleRevocationHead,
            ));
        }
        Ok(())
    }

    pub fn manifest(&self) -> &VerifiedModelManifest {
        &self.manifest
    }

    pub fn input(&self) -> &VerifiedInput {
        &self.input
    }

    pub fn deadline(&self) -> &TrustedDeadline {
        &self.deadline
    }

    pub fn limits(&self) -> &LocalResourceLimits {
        &self.limits
    }

    pub fn binding(&self) -> &FinalUseBinding {
        &self.binding
    }

    pub fn witness(&self) -> LocalGrantWitness {
        LocalGrantWitness {
            signer_id: self.signer_id.clone(),
            grant_id: self.grant_id.clone(),
            nonce: self.nonce,
            authority_epoch: self.token.claimed_authority_epoch(),
            revocation_revision: self.token.claimed_revocation_revision(),
            revocation_head_sha256: self.token.claimed_revocation_head_sha256(),
            authority_witness_sha256: self.token.witness_sha256(),
            semantic_sha256: self.binding.request_sha256,
        }
    }
}

/// Trusted-host factory. Kernel-owned nonce/frontier persistence is reused;
/// this type does not create a worker execution journal or an issuer key.
pub struct LocalAdmissionVerifier {
    authority: FinalUseAuthority,
    clock: Arc<GuardedClock>,
    worker_id: String,
    worker_generation: u64,
    device_lease_id: String,
}

impl LocalAdmissionVerifier {
    pub fn open(
        config: LocalAuthorityConfig,
        clock: Arc<dyn AuthorityClock>,
        frontier: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self> {
        if !config.state_directory.is_absolute() || config.worker_generation == 0 {
            return Err(LocalAdmissionError::Trust(AuthorityTrustError::Invalid));
        }
        for id in [&config.worker_id, &config.device_lease_id] {
            StableId::new(id.clone()).map_err(|_| LocalAdmissionError::InvalidRequest)?;
        }
        let clock = Arc::new(GuardedClock {
            source: clock,
            state: Mutex::new(ClockState::default()),
        });
        let kernel_clock: Arc<dyn AuthorityClock> = clock.clone();
        let authority = FinalUseAuthority::open_state_dir_with_trust(
            &config.state_directory,
            config.signer_id,
            config.verifying_key,
            config.revocations,
            kernel_clock,
            frontier,
        )
        .map_err(LocalAdmissionError::Authority)?;
        Ok(Self {
            authority,
            clock,
            worker_id: config.worker_id,
            worker_generation: config.worker_generation,
            device_lease_id: config.device_lease_id,
        })
    }

    /// Host-owned revocation-distribution port, never a request parameter. The
    /// host must authenticate the source; the kernel enforces monotonicity/CAS.
    pub fn update_revocations(&self, head: FinalUseRevocations) -> Result<()> {
        self.authority
            .update_revocations(head)
            .map_err(LocalAdmissionError::Authority)
    }

    pub fn claim(
        &self,
        request: LocalAdmissionRequest,
        signed: &SignedFinalUseGrant,
        input: Vec<u8>,
    ) -> Result<VerifiedResourceGrant> {
        let binding = request.binding()?;
        if request.worker_id != self.worker_id
            || request.worker_generation != self.worker_generation
            || request.device_lease_id != self.device_lease_id
        {
            return Err(LocalAdmissionError::InvalidRequest);
        }
        if input.len() > MAX_INPUT_BYTES
            || (request.operation == LocalOperationKind::RunModel && input.is_empty())
            || (request.operation == LocalOperationKind::LoadModel && !input.is_empty())
            || <[u8; 32]>::from(Sha256::digest(&input)) != request.input_sha256
        {
            return Err(LocalAdmissionError::InputMismatch);
        }
        let observed_at = Instant::now();
        let now = self
            .clock
            .now_unix_ms()
            .map_err(LocalAdmissionError::Trust)?;
        let remaining = request
            .deadline_unix_ms
            .checked_sub(now)
            .filter(|remaining| *remaining > 0 && *remaining <= MAX_LIFETIME_MS)
            .ok_or(LocalAdmissionError::DeadlineElapsed)?;
        if request.deadline_unix_ms > signed.grant.expires_at_unix_ms {
            return Err(LocalAdmissionError::InvalidRequest);
        }
        let monotonic = observed_at
            .checked_add(Duration::from_millis(remaining))
            .ok_or(LocalAdmissionError::ArithmeticOverflow)?;
        let token = self
            .authority
            .claim(signed, &binding)
            .map_err(LocalAdmissionError::Authority)?;
        let verified = VerifiedResourceGrant {
            token,
            binding,
            authority: self.authority.clone(),
            signer_id: signed.grant.signer_id.clone(),
            grant_id: signed.grant.grant_id.clone(),
            nonce: signed.grant.nonce,
            manifest: VerifiedModelManifest {
                value: request.manifest,
            },
            input: VerifiedInput {
                bytes: input.into(),
                sha256: request.input_sha256,
            },
            deadline: TrustedDeadline {
                absolute_unix_ms: request.deadline_unix_ms,
                monotonic,
                clock: Arc::clone(&self.clock),
            },
            limits: request.limits,
        };
        verified.check_live()?;
        Ok(verified)
    }
}

#[cfg(test)]
#[path = "local_admission_tests.rs"]
mod tests;
