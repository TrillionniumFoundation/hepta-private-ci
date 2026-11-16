//! Actual external PQ clock/frontier clients. No local substitute is selected.
//! The service owns protected time or durable CAS; signed responses attest to
//! that service's answer, not to its operational independence or durability.
//! Those properties require deployment qualification outside this client.
#[cfg(unix)]
use std::io::Read;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use crate::AuthorityClock;
use crate::AuthorityFrontierStore;
use crate::AuthorityTrustError;
use crate::FinalUseFrontier;
use crate::LearningTrustFrontier;
use crate::pq_auth::PqNativeVerifier;
use serde::Deserialize;
use serde::Serialize;

mod transport;

const MAX_REQUEST_BYTES: usize = 16 * 1024;
#[cfg(target_os = "linux")]
const MAX_RESPONSE_BYTES: usize = 64 * 1024;
const DOMAIN: &[u8] = b"hepta.kernel.authority.external-trust.pq.v2\0";

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UnixPqTrustEndpointConfig {
    pub socket_path: PathBuf,
    pub peer_uid: u32,
    pub service_id: String,
    pub key_generation: u64,
    pub public_key_id: [u8; 32],
    pub public_key_spki: Vec<u8>,
    pub timeout_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PqTrustRequestV2 {
    pub schema_version: u32,
    pub service_id: String,
    pub key_generation: u64,
    pub challenge: [u8; 32],
    pub operation: PqTrustOperationV2,
}
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PqTrustOperationV2 {
    ClockNow,
    FrontierLoad {
        owner_id: String,
    },
    FrontierCompareAndSet {
        owner_id: String,
        expected: FinalUseFrontier,
        next: FinalUseFrontier,
    },
    LearningFrontierLoad {
        owner_id: String,
    },
    LearningFrontierCompareAndSet {
        owner_id: String,
        expected: LearningTrustFrontier,
        next: LearningTrustFrontier,
    },
}
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PqTrustOutcomeV2 {
    Clock { unix_ms: u64 },
    Frontier { value: FinalUseFrontier },
    CompareAndSetApplied { value: FinalUseFrontier },
    LearningFrontier { value: LearningTrustFrontier },
    LearningCompareAndSetApplied { value: LearningTrustFrontier },
    Conflict,
    Unavailable,
}
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PqTrustResponseBodyV2 {
    pub schema_version: u32,
    pub request: PqTrustRequestV2,
    /// Conservatively measured from the client's original request start.
    /// This relative lease does not rely on the untrusted host wall clock.
    pub valid_for_ms: u64,
    pub outcome: PqTrustOutcomeV2,
}
impl PqTrustResponseBodyV2 {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, AuthorityTrustError> {
        if self.schema_version != 2
            || self.request.schema_version != 2
            || !(1..=30_000).contains(&self.valid_for_ms)
            || !identifier(&self.request.service_id)
            || self.request.key_generation == 0
            || self.request.challenge == [0; 32]
        {
            return Err(AuthorityTrustError::Invalid);
        }
        validate_operation(&self.request.operation)?;
        let mut bytes = DOMAIN.to_vec();
        bytes.extend(serde_json::to_vec(self).map_err(|_| AuthorityTrustError::Invalid)?);
        if bytes.len() > MAX_REQUEST_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(bytes)
    }
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedPqTrustResponseV2 {
    pub body: PqTrustResponseBodyV2,
    pub signature: Vec<u8>,
}

struct Endpoint {
    config: UnixPqTrustEndpointConfig,
    key: PqNativeVerifier,
}
impl Endpoint {
    fn new(config: UnixPqTrustEndpointConfig) -> Result<Self, AuthorityTrustError> {
        if !config.socket_path.is_absolute()
            || !identifier(&config.service_id)
            || config.key_generation == 0
            || !(1..=30_000).contains(&config.timeout_ms)
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let key = PqNativeVerifier::from_pinned_spki(&config.public_key_spki, config.public_key_id)
            .map_err(|_| AuthorityTrustError::Invalid)?;
        Ok(Self { config, key })
    }
    fn exchange(
        &self,
        operation: PqTrustOperationV2,
    ) -> Result<PqTrustOutcomeV2, AuthorityTrustError> {
        let started = Instant::now();
        let deadline = started
            .checked_add(Duration::from_millis(self.config.timeout_ms))
            .ok_or(AuthorityTrustError::Invalid)?;
        validate_operation(&operation)?;
        let request = PqTrustRequestV2 {
            schema_version: 2,
            service_id: self.config.service_id.clone(),
            key_generation: self.config.key_generation,
            challenge: fresh_challenge()?,
            operation,
        };
        let raw = serde_json::to_vec(&request).map_err(|_| AuthorityTrustError::Invalid)?;
        if raw.len() > MAX_REQUEST_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        let bytes = transport::exchange(&self.config, &raw, deadline)?;
        let signed: SignedPqTrustResponseV2 =
            serde_json::from_slice(&bytes).map_err(|_| AuthorityTrustError::Invalid)?;
        if signed.body.request != request || signed.signature.len() != 3309 {
            return Err(AuthorityTrustError::Invalid);
        }
        // No retry, alternate algorithm, context or pre-hash on any failure.
        self.key
            .verify_exact_message(&signed.body.signing_bytes()?, &signed.signature)
            .map_err(|_| AuthorityTrustError::Invalid)?;
        let expires = started
            .checked_add(Duration::from_millis(signed.body.valid_for_ms))
            .ok_or(AuthorityTrustError::Invalid)?
            .min(deadline);
        if Instant::now() >= expires {
            return Err(AuthorityTrustError::Unavailable);
        }
        match signed.body.outcome {
            PqTrustOutcomeV2::Conflict => Err(AuthorityTrustError::Conflict),
            PqTrustOutcomeV2::Unavailable => Err(AuthorityTrustError::Unavailable),
            result => Ok(result),
        }
    }
}

pub struct UnixPqAuthorityClock {
    endpoint: Endpoint,
    last_ms: AtomicU64,
}
impl UnixPqAuthorityClock {
    pub fn new(config: UnixPqTrustEndpointConfig) -> Result<Self, AuthorityTrustError> {
        Ok(Self {
            endpoint: Endpoint::new(config)?,
            last_ms: AtomicU64::new(0),
        })
    }
}
impl AuthorityClock for UnixPqAuthorityClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let PqTrustOutcomeV2::Clock { unix_ms } =
            self.endpoint.exchange(PqTrustOperationV2::ClockNow)?
        else {
            return Err(AuthorityTrustError::Invalid);
        };
        if unix_ms == 0 {
            return Err(AuthorityTrustError::Invalid);
        }
        self.last_ms
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |previous| {
                (unix_ms >= previous).then_some(unix_ms)
            })
            .map_err(|_| AuthorityTrustError::Invalid)?;
        Ok(unix_ms)
    }
}

pub struct UnixPqFinalUseFrontier {
    endpoint: Endpoint,
}
impl UnixPqFinalUseFrontier {
    pub fn new(config: UnixPqTrustEndpointConfig) -> Result<Self, AuthorityTrustError> {
        Ok(Self {
            endpoint: Endpoint::new(config)?,
        })
    }
}
impl AuthorityFrontierStore<FinalUseFrontier> for UnixPqFinalUseFrontier {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        match self.endpoint.exchange(PqTrustOperationV2::FrontierLoad {
            owner_id: owner_id.to_string(),
        })? {
            PqTrustOutcomeV2::Frontier { value } if valid_frontier(&value) => Ok(value),
            _ => Err(AuthorityTrustError::Invalid),
        }
    }
    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        match self
            .endpoint
            .exchange(PqTrustOperationV2::FrontierCompareAndSet {
                owner_id: owner_id.to_string(),
                expected: *expected,
                next: *next,
            })? {
            PqTrustOutcomeV2::CompareAndSetApplied { value } if value == *next => Ok(()),
            _ => Err(AuthorityTrustError::Invalid),
        }
    }
}

/// Actual external adapter for the learning root/generation activation floor.
/// Its operation tags are distinct from FinalUse, even on one service socket.
pub struct UnixPqLearningTrustFrontier {
    endpoint: Endpoint,
}
impl UnixPqLearningTrustFrontier {
    pub fn new(config: UnixPqTrustEndpointConfig) -> Result<Self, AuthorityTrustError> {
        Ok(Self {
            endpoint: Endpoint::new(config)?,
        })
    }
}
impl AuthorityFrontierStore<LearningTrustFrontier> for UnixPqLearningTrustFrontier {
    fn load(&self, owner_id: &str) -> Result<LearningTrustFrontier, AuthorityTrustError> {
        match self
            .endpoint
            .exchange(PqTrustOperationV2::LearningFrontierLoad {
                owner_id: owner_id.to_string(),
            })? {
            PqTrustOutcomeV2::LearningFrontier { value } if valid_learning_frontier(&value) => {
                Ok(value)
            }
            _ => Err(AuthorityTrustError::Invalid),
        }
    }
    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &LearningTrustFrontier,
        next: &LearningTrustFrontier,
    ) -> Result<(), AuthorityTrustError> {
        match self
            .endpoint
            .exchange(PqTrustOperationV2::LearningFrontierCompareAndSet {
                owner_id: owner_id.to_string(),
                expected: *expected,
                next: *next,
            })? {
            PqTrustOutcomeV2::LearningCompareAndSetApplied { value } if value == *next => Ok(()),
            _ => Err(AuthorityTrustError::Invalid),
        }
    }
}
fn valid_learning_frontier(f: &LearningTrustFrontier) -> bool {
    f.root_digest != [0; 32]
        && f.distribution_digest != [0; 32]
        && f.generation > 0
        && f.authority_epoch > 0
}
fn learning_owner(id: &str) -> bool {
    id.strip_prefix("hepta-learning-trust:")
        .is_some_and(|binding| {
            binding.len() == 64
                && binding
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        })
}

/// Produce an OS-random request challenge for the shared PQ trust and issuer clients.
pub fn fresh_challenge() -> Result<[u8; 32], AuthorityTrustError> {
    #[cfg(unix)]
    {
        let mut nonce = [0; 32];
        std::fs::File::open("/dev/urandom")
            .and_then(|mut f| f.read_exact(&mut nonce))
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if nonce == [0; 32] {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(nonce)
    }
    #[cfg(not(unix))]
    {
        Err(AuthorityTrustError::Unavailable)
    }
}
fn identifier(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:/".contains(&b))
}
fn valid_frontier(f: &FinalUseFrontier) -> bool {
    f.authority_epoch > 0 && f.revocation_revision > 0 && f.state_sha256 != [0; 32]
}
fn validate_operation(operation: &PqTrustOperationV2) -> Result<(), AuthorityTrustError> {
    match operation {
        PqTrustOperationV2::ClockNow => Ok(()),
        PqTrustOperationV2::FrontierLoad { owner_id } if identifier(owner_id) => Ok(()),
        PqTrustOperationV2::FrontierCompareAndSet {
            owner_id,
            expected,
            next,
        } if identifier(owner_id)
            && valid_frontier(expected)
            && valid_frontier(next)
            && (next.authority_epoch > expected.authority_epoch
                || (next.authority_epoch == expected.authority_epoch
                    && next.revocation_revision >= expected.revocation_revision)) =>
        {
            Ok(())
        }
        PqTrustOperationV2::LearningFrontierLoad { owner_id } if learning_owner(owner_id) => Ok(()),
        PqTrustOperationV2::LearningFrontierCompareAndSet {
            owner_id,
            expected,
            next,
        } if learning_owner(owner_id)
            && valid_learning_frontier(expected)
            && valid_learning_frontier(next)
            && expected.generation.checked_add(1) == Some(next.generation)
            && next.authority_epoch >= expected.authority_epoch =>
        {
            Ok(())
        }
        _ => Err(AuthorityTrustError::Invalid),
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "authority_trust_unix_tests.rs"]
pub(crate) mod tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "authority_trust_learning_tests.rs"]
mod learning_tests;
