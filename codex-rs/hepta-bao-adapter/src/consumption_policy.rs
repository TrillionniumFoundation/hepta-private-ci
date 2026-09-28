//! Shared stage, retry and resource classification. No variant grants authority.
use super::{BaoConsumptionOperationV1, BaoConsumptionStateV1};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoConsumptionPhase {
    Unreserved,
    Reserved,
    Fenced,
    AwaitingSettlement,
    Terminal,
    LegacyRequalification,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoRecoveryAction {
    SealAdmission,
    CancelHeldReservation,
    ProviderEvidenceRequired,
    ObserveConsumer,
    SettleOriginalReservation,
    RequalifyLegacyResult,
    ReturnHistorical,
}

impl BaoConsumptionStateV1 {
    pub const fn phase(self) -> BaoConsumptionPhase {
        match self {
            Self::Claimed => BaoConsumptionPhase::Unreserved,
            Self::Reserved => BaoConsumptionPhase::Reserved,
            Self::DispatchFenced | Self::DeliveryPrepared | Self::Indeterminate
            | Self::DispatchAttempted => BaoConsumptionPhase::Fenced,
            Self::ConsumerSucceeded | Self::ConsumerNotApplied | Self::ProviderFailed => {
                BaoConsumptionPhase::AwaitingSettlement
            }
            Self::Succeeded | Self::Failed => BaoConsumptionPhase::Terminal,
            Self::LegacyConsumerSucceeded | Self::LegacySucceeded => {
                BaoConsumptionPhase::LegacyRequalification
            }
        }
    }

    pub const fn is_terminal(self) -> bool {
        matches!(self.phase(), BaoConsumptionPhase::Terminal)
    }
}

impl BaoConsumptionOperationV1 {
    /// Owner-only recovery advice; never permission to execute the effect again.
    pub fn recovery_action(&self) -> BaoRecoveryAction {
        match self.state {
            BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted => {
                BaoRecoveryAction::SealAdmission
            }
            BaoConsumptionStateV1::Reserved => BaoRecoveryAction::CancelHeldReservation,
            BaoConsumptionStateV1::DispatchFenced | BaoConsumptionStateV1::Indeterminate
            | BaoConsumptionStateV1::DeliveryPrepared => {
                if self.receipt.is_some() {
                    BaoRecoveryAction::ObserveConsumer
                } else {
                    BaoRecoveryAction::ProviderEvidenceRequired
                }
            }
            BaoConsumptionStateV1::ConsumerSucceeded | BaoConsumptionStateV1::ConsumerNotApplied
            | BaoConsumptionStateV1::ProviderFailed => BaoRecoveryAction::SettleOriginalReservation,
            BaoConsumptionStateV1::LegacyConsumerSucceeded | BaoConsumptionStateV1::LegacySucceeded => {
                BaoRecoveryAction::RequalifyLegacyResult
            }
            BaoConsumptionStateV1::Succeeded | BaoConsumptionStateV1::Failed => BaoRecoveryAction::ReturnHistorical,
        }
    }
}

impl crate::BaoAuthBusAdmission {
    /// Pure pre-admission checks, shared by the host and the quota saga.
    pub(crate) fn validate(&self) -> Result<(), crate::BaoClientError> {
        if self.policy_revision == 0 || self.expected_quota_revision == 0
            || self.amount == 0 || self.expires_at_ms == 0
        {
            return Err(crate::BaoClientError::InvalidRequest);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum BaoAbortStage { BeforeReservation, BeforeDispatch }
