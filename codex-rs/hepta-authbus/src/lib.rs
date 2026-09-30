//! Signed admission, replay fencing and durable authorization policy state.
//!
//! The signed admission API verifies issuer-bound Ed25519 messages. The durable
//! authority store evaluates revision-bound policy against a persisted trusted-
//! time floor. Policy decisions and replay receipts do not reserve quota,
//! dispatch an effect or mint final-use authority. Successful receipts retain
//! `AuthorityPosture::DENY_ALL`.

#![forbid(unsafe_code)]

mod authority;
mod authority_schema;
mod authority_store;
mod host;
mod issuer_registry;
#[cfg(feature = "legacy-preverified-replay")]
mod legacy_replay;
mod operations;
mod owner_fence;
mod ports;
mod quota;
mod quota_store;
mod recovery;
mod settlement;
mod settlement_store;
mod signed;
mod trust;
mod trust_store;
mod worker;
pub use authority::AuthBusAuthorityError;
pub use authority::AuthBusMutationDisposition;
pub use authority::AuthPolicy;
pub use authority::PolicyDecision;
pub use authority::PolicyEffect;
pub use authority::PolicySpec;
pub use authority::TrustedTimeSample;
pub(crate) use authority_store::AuthBusAuthorityStore;
pub use host::AuthBusAuthorityHost;
pub use issuer_registry::IssuerRegistryError;
pub use issuer_registry::PrivateIssuerRegistryDocument;
#[cfg(feature = "legacy-preverified-replay")]
#[allow(deprecated)]
pub use legacy_replay::PreverifiedAuthEnvelope;
#[cfg(feature = "legacy-preverified-replay")]
#[allow(deprecated)]
pub use legacy_replay::ReplayWindow;
#[cfg(feature = "legacy-preverified-replay")]
#[allow(deprecated)]
pub use legacy_replay::TrustedReplayContext;
pub use operations::AuthBusAlertKind;
pub use operations::AuthBusAlertSeverity;
pub use operations::AuthBusBlockingReason;
pub use operations::AuthBusLatencySummary;
pub use operations::AuthBusMaintenanceReport;
pub use operations::AuthBusOperationalAlert;
pub use operations::AuthBusOperationalSnapshot;
pub use operations::AuthBusRuntimeSnapshot;
pub use operations::AuthBusSloPolicy;
pub use ports::AuthBusAdminPort;
pub use ports::AuthBusExecutionPort;
pub use ports::AuthBusMaintenancePort;
pub use ports::AuthBusReadPort;
pub use quota::ExpiredReservationSweep;
pub use quota::QuotaReservation;
pub use quota::QuotaSnapshot;
pub use quota::QuotaSpec;
pub use quota::ReservationRequest;
pub use quota::ReservationState;
pub use recovery::AuthorityCheckpoint;
pub use settlement::Settlement;
pub use settlement::SettlementEvidenceClaims;
pub use settlement::SettlementIssuerRegistration;
pub use settlement::SettlementStatus;
pub use settlement::SignedSettlementEvidence;
pub use signed::AuthenticatedMessage;
pub use signed::IssuerRegistration;
pub use signed::IssuerRegistrationView;
pub use signed::SignedMessage;
pub use signed::SignedMessageClaims;
pub use trust::IssuerLifecycleState;
pub use trust::IssuerPurpose;
pub use trust::IssuerRecord;
pub use trust::IssuerRetirement;
pub use trust::IssuerSpec;
pub use trust::SignedTrustedTimeAttestation;
pub use trust::TrustedTimeAttestationClaims;
pub use worker::AuthBusAuthorityWorker;
pub use worker::AuthBusAuthorityWorkerConfig;

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerificationReceipt {
    pub message_id: StableId,
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub subject_id: StableId,
    pub sequence: u64,
    pub envelope_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    ZeroSequence,
    Revoked,
    Expired,
    ScopeMismatch,
    SubjectMismatch,
    ExternalCheckpointRequired,
    PayloadMismatch,
    Replay,
    CapacityExceeded,
    InvalidSignature,
    IssuerMismatch,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(all(test, feature = "legacy-preverified-replay"))]
#[allow(deprecated)]
#[path = "lib_tests.rs"]
mod tests;
