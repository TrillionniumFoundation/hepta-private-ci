//! final use host settlement implementation.

use super::*;

pub(super) async fn settle_terminal_row<E: BaoAuthBusEvidenceProvider>(
    authbus: &AuthBusAuthorityHost,
    registry: &Mutex<DurableLeaseRegistryV1>,
    row: BaoConsumptionOperationV1,
    reservation: QuotaReservation,
    evidence: &mut E,
) -> Result<BaoSecretReceipt, BaoProductHostError> {
    let terminal = Digest32::from_array(row.terminal_evidence_sha256.ok_or(
        BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState),
    )?);
    let (status, observed_cost, success) = match row.state {
        BaoConsumptionStateV1::ConsumerSucceeded => (SettlementStatus::Completed, row.amount, true),
        BaoConsumptionStateV1::ProviderFailed => (
            SettlementStatus::Completed,
            row.terminal_observed_cost
                .ok_or(BaoProductHostError::Store(
                    LeaseRegistryErrorV1::CorruptState,
                ))?,
            false,
        ),
        BaoConsumptionStateV1::ConsumerNotApplied => (SettlementStatus::Rejected, 0, false),
        _ => {
            return Err(BaoProductHostError::Store(
                LeaseRegistryErrorV1::InvalidTransition,
            ));
        }
    };
    let expected_terminal_state = match status {
        SettlementStatus::Completed => ReservationState::Settled,
        SettlementStatus::Rejected => ReservationState::Released,
    };
    if matches!(
        reservation.state,
        ReservationState::Settled | ReservationState::Released
    ) {
        if reservation.state != expected_terminal_state
            || reservation.terminal_evidence != Some(terminal)
            || reservation.observed_cost != Some(observed_cost)
        {
            return Err(BaoProductHostError::Store(
                LeaseRegistryErrorV1::ObservationMismatch,
            ));
        }
    } else {
        if !matches!(
            reservation.state,
            ReservationState::DispatchAttempted | ReservationState::Indeterminate
        ) {
            return Err(BaoProductHostError::OutcomePending(Box::new(row)));
        }
        crate::https_consumer::settle_observed(
            authbus,
            evidence,
            &reservation,
            status,
            observed_cost,
            terminal,
            if success { row.receipt.clone() } else { None },
        )
        .await
        .map_err(BaoProductHostError::AuthBus)?;
    }
    let mut owner = registry
        .lock()
        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?;
    if success {
        owner
            .settle_consumption(&row.operation_id)
            .map_err(BaoProductHostError::Store)
    } else {
        let terminal = owner
            .settle_consumption_failure(&row.operation_id)
            .map_err(BaoProductHostError::Store)?;
        Err(BaoProductHostError::TerminalFailure(Box::new(terminal)))
    }
}

pub(super) fn validate_reservation(
    row: &BaoConsumptionOperationV1,
    reservation: &QuotaReservation,
) -> Result<(), LeaseRegistryErrorV1> {
    if reservation.operation_id.as_str() != row.operation_id
        || reservation.amount != row.amount
        || reservation.effect_digest.into_array() != row.effect_sha256
    {
        return Err(LeaseRegistryErrorV1::ObservationMismatch);
    }
    Ok(())
}

pub(super) fn abort_evidence(
    row: &BaoConsumptionOperationV1,
    code: &str,
    reservation: Option<&QuotaReservation>,
) -> [u8; 32] {
    let reservation_id = reservation
        .map(|value| value.reservation_id.as_str())
        .unwrap_or("");
    let reservation_revision = reservation.map(|value| value.revision).unwrap_or(0);
    Digest32::of_bytes(
        &serde_json::to_vec(&(
            "hepta.bao.abort.v1",
            row.operation_id.as_str(),
            row.semantic_sha256,
            row.effect_sha256,
            code,
            reservation_id,
            reservation_revision,
        ))
        .unwrap_or_default(),
    )
    .into_array()
}

pub(super) fn validate_product_admission(
    admission: &BaoAuthBusAdmission,
) -> Result<(), BaoFinalUseHostError> {
    if admission.policy_revision == 0
        || admission.expected_quota_revision == 0
        || admission.amount == 0
        || admission.expires_at_ms == 0
    {
        return Err(BaoFinalUseHostError::Client(BaoClientError::InvalidRequest));
    }
    Ok(())
}

pub(super) fn provider_failure_code(error: BaoClientError) -> Option<&'static str> {
    match error {
        BaoClientError::ProviderDenied => Some("provider_denied"),
        BaoClientError::ProviderUnavailable => Some("provider_unavailable"),
        BaoClientError::NotFound => Some("not_found"),
        BaoClientError::ResponseTooLarge => Some("response_too_large"),
        BaoClientError::InvalidResponse => Some("invalid_response"),
        BaoClientError::VersionMismatch => Some("version_mismatch"),
        BaoClientError::SecretDigestMismatch => Some("secret_digest_mismatch"),
        BaoClientError::InvalidConfiguration
        | BaoClientError::InvalidRequest
        | BaoClientError::Authority(_)
        | BaoClientError::TransportUnavailable
        | BaoClientError::TimedOut
        | BaoClientError::ConsumerIndeterminate => None,
    }
}

pub(super) fn consumer_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoFinalUseHostError {
    InvalidConsumerId,
    InvalidConsumerConfiguration,
    InvalidRuntimeConfiguration,
    DuplicateConsumer,
    EmptyConsumerRegistry,
    UnregisteredConsumer,
    StaleRevocationFeed,
    Unavailable,
    Trust(AuthorityTrustError),
    Control(FinalUseControlError),
    Client(BaoClientError),
}

impl fmt::Display for BaoFinalUseHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for BaoFinalUseHostError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoProductErrorClassV1 {
    AdmissionRejected,
    ReconciliationRequired,
    AwaitingOriginalEvidence,
    AwaitingSettlement,
    HistoricalTerminalFailure,
    IdentityConflict,
    CapacityRejected,
    OwnerBusy,
    CommitIndeterminate,
    DurableOwnerFailure,
    ExternalControlFailure,
}

#[derive(Debug)]
pub enum BaoProductHostError {
    Host(BaoFinalUseHostError),
    AuthBus(BaoAuthBusError),
    Store(LeaseRegistryErrorV1),
    SqliteStore(crate::SqliteBaoOwnerErrorV1),
    ConsumerProfileRequired,
    OutcomePending(Box<BaoConsumptionOperationV1>),
    TerminalFailure(Box<BaoConsumptionOperationV1>),
}

impl BaoProductHostError {
    #[must_use]
    pub fn class(&self) -> BaoProductErrorClassV1 {
        match self {
            Self::ConsumerProfileRequired
            | Self::Host(BaoFinalUseHostError::InvalidConsumerId)
            | Self::Host(BaoFinalUseHostError::InvalidConsumerConfiguration)
            | Self::Host(BaoFinalUseHostError::InvalidRuntimeConfiguration)
            | Self::Host(BaoFinalUseHostError::UnregisteredConsumer)
            | Self::Host(BaoFinalUseHostError::Client(BaoClientError::InvalidRequest)) => {
                BaoProductErrorClassV1::AdmissionRejected
            }
            Self::OutcomePending(row) => match row.state.recovery_action() {
                BaoConsumptionRecoveryActionV1::ObserveOriginalOutcome => {
                    BaoProductErrorClassV1::AwaitingOriginalEvidence
                }
                BaoConsumptionRecoveryActionV1::SettleTerminalEvidence => {
                    BaoProductErrorClassV1::AwaitingSettlement
                }
                _ => BaoProductErrorClassV1::ReconciliationRequired,
            },
            Self::TerminalFailure(_) => BaoProductErrorClassV1::HistoricalTerminalFailure,
            Self::Store(
                LeaseRegistryErrorV1::OperationConflict | LeaseRegistryErrorV1::ObservationMismatch,
            ) => BaoProductErrorClassV1::IdentityConflict,
            Self::Store(LeaseRegistryErrorV1::CapacityExceeded) => {
                BaoProductErrorClassV1::CapacityRejected
            }
            Self::Store(LeaseRegistryErrorV1::WriterBusy) => BaoProductErrorClassV1::OwnerBusy,
            Self::Store(LeaseRegistryErrorV1::CommitIndeterminate) => {
                BaoProductErrorClassV1::CommitIndeterminate
            }
            Self::Store(_) => BaoProductErrorClassV1::DurableOwnerFailure,
            Self::SqliteStore(error) => sqlite_owner_error_class(error),
            Self::AuthBus(BaoAuthBusError::DurableOwner(error)) => sqlite_owner_error_class(error),
            Self::AuthBus(BaoAuthBusError::Indeterminate { .. }) => {
                BaoProductErrorClassV1::AwaitingOriginalEvidence
            }
            Self::AuthBus(BaoAuthBusError::SettlementPending { .. }) => {
                BaoProductErrorClassV1::AwaitingSettlement
            }
            Self::Host(_) | Self::AuthBus(_) => BaoProductErrorClassV1::ExternalControlFailure,
        }
    }
}

pub(super) fn sqlite_owner_error_class(
    error: &crate::SqliteBaoOwnerErrorV1,
) -> BaoProductErrorClassV1 {
    use crate::SqliteBaoOwnerErrorV1 as Error;
    match error {
        Error::OperationConflict | Error::ObservationMismatch => {
            BaoProductErrorClassV1::IdentityConflict
        }
        Error::CapacityExceeded => BaoProductErrorClassV1::CapacityRejected,
        Error::WriterBusy | Error::RevisionConflict => BaoProductErrorClassV1::OwnerBusy,
        Error::CommitIndeterminate(_) => BaoProductErrorClassV1::CommitIndeterminate,
        Error::InvalidInput
        | Error::OperationNotFound
        | Error::InvalidTransition
        | Error::ExternalCheckpointUnavailable
        | Error::MigrationConflict
        | Error::CorruptState(_)
        | Error::RollbackDetected
        | Error::Fenced
        | Error::UnsupportedPlatform
        | Error::UnsafeStorage(_)
        | Error::Storage(_) => BaoProductErrorClassV1::DurableOwnerFailure,
    }
}

impl fmt::Display for BaoProductHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Host(error) => write!(formatter, "host admission failed: {error}"),
            Self::AuthBus(error) => write!(formatter, "AuthBus product path failed: {error}"),
            Self::Store(error) => write!(formatter, "durable reference operation failed: {error}"),
            Self::SqliteStore(error) => {
                write!(formatter, "durable SQLite operation failed: {error}")
            }
            Self::ConsumerProfileRequired => {
                formatter.write_str("matching operation-aware consumer profile required")
            }
            Self::OutcomePending(_) => {
                formatter.write_str("original operation requires reconciliation; no redispatch")
            }
            Self::TerminalFailure(row) => write!(
                formatter,
                "original operation reached immutable terminal failure ({})",
                row.terminal_code.as_deref().unwrap_or("unspecified")
            ),
        }
    }
}
impl std::error::Error for BaoProductHostError {}
