//! Metadata-only consumer operation saga in the existing lease writer.
//!
//! The state names intentionally distinguish durable identity, quota reservation
//! and the irreversible AuthBus dispatch fence. No state implies a later step.
use super::*;
use codex_hepta_types::Digest32;

const TERMINAL_SUCCESS: &str = "success";
const TERMINAL_PROVIDER_FAILURE: &str = "provider_failure";
const TERMINAL_CONSUMER_NOT_APPLIED: &str = "consumer_not_applied";
const TERMINAL_ABORTED_BEFORE_RESERVATION: &str = "aborted_before_reservation";
const TERMINAL_ABORTED_BEFORE_DISPATCH: &str = "aborted_before_dispatch";

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoSecretReceipt {
    pub request_sha256: [u8; 32],
    pub response_sha256: [u8; 32],
    pub secret_sha256: [u8; 32],
    pub version: u64,
    pub secret_bytes: usize,
}

/// Digest-free, bounded telemetry fields; version and size remain sensitive metadata.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BaoSecretTelemetryV1 {
    pub version: u64,
    pub secret_bytes: usize,
}

impl BaoSecretReceipt {
    #[must_use]
    pub const fn telemetry(&self) -> BaoSecretTelemetryV1 {
        BaoSecretTelemetryV1 {
            version: self.version,
            secret_bytes: self.secret_bytes,
        }
    }

    pub(crate) fn evidence_digest(&self) -> Result<[u8; 32], LeaseRegistryErrorV1> {
        receipt_digest(self)
    }
}

impl std::fmt::Debug for BaoSecretReceipt {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("BaoSecretReceipt")
            .field("request_sha256", &"[SENSITIVE DIGEST]")
            .field("response_sha256", &"[SENSITIVE DIGEST]")
            .field("secret_sha256", &"[SENSITIVE DIGEST]")
            .field("version", &self.version)
            .field("secret_bytes", &self.secret_bytes)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoConsumptionStateV1 {
    Claimed,
    Reserved,
    DispatchFenced,
    DeliveryPrepared,
    ConsumerSucceeded,
    ConsumerNotApplied,
    ProviderFailed,
    Indeterminate,
    Succeeded,
    Failed,
    /// Schema-3 compatibility only. New operations never enter this state.
    DispatchAttempted,
}

/// Coarse durable phase used consistently by admission, recovery and capacity code.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum BaoConsumptionPhaseV1 {
    Unreserved,
    Reserved,
    DispatchFenced,
    TerminalEvidence,
    Terminal,
}

/// The only recovery action permitted for a durable consumption state.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum BaoConsumptionRecoveryActionV1 {
    SealOrBindReservation,
    CancelOrExpireReservation,
    BindLegacyReservation,
    ObserveOriginalOutcome,
    SettleTerminalEvidence,
    ReturnHistoricalSuccess,
    ReturnHistoricalFailure,
}

impl BaoConsumptionStateV1 {
    #[must_use]
    pub const fn phase(self) -> BaoConsumptionPhaseV1 {
        match self {
            Self::Claimed => BaoConsumptionPhaseV1::Unreserved,
            Self::Reserved | Self::DispatchAttempted => BaoConsumptionPhaseV1::Reserved,
            Self::DispatchFenced | Self::DeliveryPrepared | Self::Indeterminate => {
                BaoConsumptionPhaseV1::DispatchFenced
            }
            Self::ConsumerSucceeded | Self::ConsumerNotApplied | Self::ProviderFailed => {
                BaoConsumptionPhaseV1::TerminalEvidence
            }
            Self::Succeeded | Self::Failed => BaoConsumptionPhaseV1::Terminal,
        }
    }

    #[must_use]
    pub const fn recovery_action(self) -> BaoConsumptionRecoveryActionV1 {
        match self {
            Self::Claimed => BaoConsumptionRecoveryActionV1::SealOrBindReservation,
            Self::Reserved => BaoConsumptionRecoveryActionV1::CancelOrExpireReservation,
            Self::DispatchAttempted => BaoConsumptionRecoveryActionV1::BindLegacyReservation,
            Self::DispatchFenced | Self::DeliveryPrepared | Self::Indeterminate => {
                BaoConsumptionRecoveryActionV1::ObserveOriginalOutcome
            }
            Self::ConsumerSucceeded | Self::ConsumerNotApplied | Self::ProviderFailed => {
                BaoConsumptionRecoveryActionV1::SettleTerminalEvidence
            }
            Self::Succeeded => BaoConsumptionRecoveryActionV1::ReturnHistoricalSuccess,
            Self::Failed => BaoConsumptionRecoveryActionV1::ReturnHistoricalFailure,
        }
    }

    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed)
    }

    #[must_use]
    pub const fn has_dispatch_fence(self) -> bool {
        matches!(
            self.phase(),
            BaoConsumptionPhaseV1::DispatchFenced
                | BaoConsumptionPhaseV1::TerminalEvidence
                | BaoConsumptionPhaseV1::Terminal
        )
    }

    #[must_use]
    pub const fn requires_future_capacity(self) -> bool {
        !self.is_terminal()
    }

    /// Closed durable transition graph shared by every storage profile.
    #[must_use]
    pub(crate) const fn allows_transition_to(self, next: Self) -> bool {
        use BaoConsumptionStateV1 as S;
        matches!(
            (self, next),
            (S::Claimed, S::Reserved | S::Failed)
                | (S::Reserved, S::DispatchFenced | S::Failed)
                | (
                    S::DispatchFenced,
                    S::DeliveryPrepared | S::ProviderFailed | S::Indeterminate
                )
                | (
                    S::DeliveryPrepared,
                    S::ConsumerSucceeded | S::ConsumerNotApplied | S::Indeterminate
                )
                | (
                    S::Indeterminate,
                    S::ConsumerSucceeded | S::ConsumerNotApplied | S::ProviderFailed
                )
                | (S::ConsumerSucceeded, S::Succeeded)
                | (S::ConsumerNotApplied | S::ProviderFailed, S::Failed)
                | (
                    S::DispatchAttempted,
                    S::Reserved | S::DispatchFenced | S::Indeterminate | S::Failed
                )
        )
    }
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoConsumptionOperationV1 {
    pub operation_id: String,
    pub semantic_sha256: [u8; 32],
    pub effect_sha256: [u8; 32],
    pub request_sha256: [u8; 32],
    pub consumer_id: String,
    pub consumer_configuration_sha256: [u8; 32],
    pub amount: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reservation_id: Option<String>,
    pub state: BaoConsumptionStateV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub receipt: Option<BaoSecretReceipt>,
    /// Store revision at first durable publication. Zero is accepted only before commit.
    #[serde(default, skip_serializing_if = "is_default")]
    pub created_revision: u64,
    /// Store revision of the most recent durable transition.
    #[serde(default, skip_serializing_if = "is_default")]
    pub updated_revision: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub terminal_kind: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub terminal_code: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub terminal_evidence_sha256: Option<[u8; 32]>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub terminal_observed_cost: Option<u64>,
}

impl BaoConsumptionOperationV1 {
    pub(crate) fn validate_for_persistence(&self) -> Result<(), LeaseRegistryErrorV1> {
        validate_consumption(self)
    }

    #[must_use]
    pub(crate) fn same_identity(&self, other: &Self) -> bool {
        same_consumption_identity(self, other)
    }

    #[must_use]
    pub(crate) fn has_terminal_fields(&self) -> bool {
        has_terminal(self)
    }

    #[must_use]
    pub(crate) fn terminal_fields_differ(&self, other: &Self) -> bool {
        self.has_terminal_fields()
            && (self.terminal_kind != other.terminal_kind
                || self.terminal_code != other.terminal_code
                || self.terminal_evidence_sha256 != other.terminal_evidence_sha256
                || self.terminal_observed_cost != other.terminal_observed_cost)
    }
}

impl std::fmt::Debug for BaoConsumptionOperationV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("BaoConsumptionOperationV1")
            .field("operation_id", &self.operation_id)
            .field("semantic_sha256", &"[SENSITIVE DIGEST]")
            .field("effect_sha256", &"[SENSITIVE DIGEST]")
            .field("request_sha256", &"[SENSITIVE DIGEST]")
            .field("consumer_id", &self.consumer_id)
            .field("consumer_configuration_sha256", &"[SENSITIVE DIGEST]")
            .field("amount", &self.amount)
            .field("reservation_id", &self.reservation_id)
            .field("state", &self.state)
            .field("receipt", &self.receipt)
            .field("created_revision", &self.created_revision)
            .field("updated_revision", &self.updated_revision)
            .field("terminal_kind", &self.terminal_kind)
            .field("terminal_code", &self.terminal_code)
            .field("terminal_evidence_sha256", &"[SENSITIVE DIGEST]")
            .field("terminal_observed_cost", &self.terminal_observed_cost)
            .finish()
    }
}

#[cfg(all(test, unix))]
#[path = "consumption_lifecycle_saga_tests.rs"]
mod saga_tests;

#[path = "consumption_claim.rs"]
mod consumption_claim;
#[path = "consumption_observation.rs"]
mod consumption_observation;
#[path = "consumption_settlement.rs"]
mod consumption_settlement;

#[path = "consumption_validation.rs"]
mod consumption_validation;
use consumption_validation::has_terminal;
use consumption_validation::is_default;
pub(super) use consumption_validation::migrate_schema_three_consumptions;
use consumption_validation::provider_error_code;
use consumption_validation::receipt_digest;
use consumption_validation::same_consumption_identity;
use consumption_validation::set_terminal;
use consumption_validation::terminal_matches;
pub(super) use consumption_validation::validate_consumption;
use consumption_validation::validate_receipt_for_request;
