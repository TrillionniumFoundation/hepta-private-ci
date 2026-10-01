//! Production runtime SDK receives independently signed consumer evidence only.
use super::ConsumerPortConfig;
use super::ConsumerPortError;
use super::PreparedConnection;
use super::consumer_wire::ConsumerRequest;
use super::consumer_wire::ConsumerResponse;
use crate::BaoAuthBusError;
use crate::BaoAuthBusEvidenceProvider;
use crate::role_client::AuthorityTimeSource;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_authbus::SignedSettlementEvidence;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_types::Digest32;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ConsumerEvidenceConfig {
    pub(crate) runtime_uid: u32,
    pub(crate) authority: AuthorityTimeSource,
    pub(crate) consumer: ConsumerPortConfig,
    pub(crate) settlement_issuer_id: String,
    pub(crate) settlement_key_epoch: u64,
    pub(crate) settlement_verifying_key: [u8; 32],
    pub(crate) cost: u64,
}
impl ConsumerEvidenceConfig {
    pub fn load_root_owned(path: &Path) -> Result<Self, ConsumerPortError> {
        crate::private_files::read_root_configuration(path)
    }
}
pub struct ConsumerEvidenceClient {
    config: ConsumerEvidenceConfig,
    deadline: Option<Instant>,
}
impl ConsumerEvidenceClient {
    pub fn new(config: ConsumerEvidenceConfig) -> Result<Self, ConsumerPortError> {
        if config.runtime_uid != rustix::process::geteuid().as_raw()
            || config.consumer.service_uid == config.runtime_uid
            || config.authority.connection.peer_uid == config.runtime_uid
            || config.authority.connection.peer_uid == config.consumer.service_uid
            || config.cost == 0
            || config.consumer.timeout_ms == 0
            || config.consumer.timeout_ms > 5_000
            || config.consumer.acknowledgement_verifying_key == config.settlement_verifying_key
            || config.authority.verifying_key == config.settlement_verifying_key
        {
            return Err(ConsumerPortError::Invalid);
        }
        let key = VerifyingKey::from_bytes(&config.settlement_verifying_key)
            .map_err(|_| ConsumerPortError::Invalid)?;
        if key.is_weak() {
            return Err(ConsumerPortError::Invalid);
        }
        Ok(Self {
            config,
            deadline: None,
        })
    }
    pub(crate) fn for_original_deadline(mut self, deadline: Instant) -> Self {
        self.deadline = Some(deadline);
        self
    }
    /// Status-like evidence request. It never reads or authenticates a credential.
    /// The consumer derives the cost and receipt digest from its retained ACK.
    pub fn completed_original(
        &self,
        operation: &str,
        reservation: &str,
    ) -> Result<SignedSettlementEvidence, ConsumerPortError> {
        crate::authority_role_owner::original_id(operation)?;
        let timeout = Duration::from_millis(self.config.consumer.timeout_ms);
        let timeout = match self.deadline {
            Some(deadline) => timeout.min(
                deadline
                    .checked_duration_since(Instant::now())
                    .ok_or(ConsumerPortError::Unavailable)?,
            ),
            None => timeout,
        };
        let connection = PreparedConnection::connect(
            &self.config.consumer.socket_path,
            self.config.consumer.service_uid,
            timeout,
        )?;
        let signed = match connection.exchange(&ConsumerRequest::Settlement {
            operation_id: operation.to_owned(),
            reservation_id: reservation.to_owned(),
        })? {
            ConsumerResponse::Settlement { evidence } => evidence.verify(
                &self.config.settlement_issuer_id,
                self.config.settlement_key_epoch,
                &self.config.settlement_verifying_key,
            )?,
            ConsumerResponse::Conflict => return Err(ConsumerPortError::Conflict),
            ConsumerResponse::Rejected => return Err(ConsumerPortError::Rejected),
            ConsumerResponse::Unknown
            | ConsumerResponse::Confirmed { .. }
            | ConsumerResponse::Prepared { .. } => return Err(ConsumerPortError::Unavailable),
        };
        if signed.claims.operation_id.as_str() != operation
            || signed.claims.reservation_id.as_str() != reservation
            || signed.claims.observed_cost != self.config.cost
        {
            return Err(ConsumerPortError::Conflict);
        }
        Ok(signed)
    }
}
impl BaoAuthBusEvidenceProvider for ConsumerEvidenceClient {
    fn trusted_time(&mut self) -> Result<SignedTrustedTimeAttestation, BaoAuthBusError> {
        let result = match self.deadline {
            Some(deadline) => {
                let response: crate::role_wire::AuthorityResponse = self
                    .config
                    .authority
                    .connection
                    .call_before(&crate::role_wire::AuthorityRequest::Time, deadline)
                    .map_err(|_| {
                        BaoAuthBusError::Evidence("original protected-time budget unavailable")
                    })?;
                match response {
                    crate::role_wire::AuthorityResponse::Time { attestation } => attestation
                        .verify(
                            &self.config.authority.issuer_id,
                            self.config.authority.key_epoch,
                            &self.config.authority.verifying_key,
                        ),
                    _ => Err(ConsumerPortError::Unavailable),
                }
            }
            None => self.config.authority.trusted_time(),
        };
        result.map_err(|_| BaoAuthBusError::Evidence("independent protected time unavailable"))
    }
    fn settlement_evidence(
        &mut self,
        reservation: &QuotaReservation,
        status: SettlementStatus,
        observed_cost: u64,
        terminal: Digest32,
        observed_at: u64,
    ) -> Result<SignedSettlementEvidence, BaoAuthBusError> {
        if status != SettlementStatus::Completed
            || observed_cost != self.config.cost
            || observed_cost > reservation.amount
        {
            return Err(BaoAuthBusError::Evidence(
                "consumer has no independent evidence for requested outcome",
            ));
        }
        let signed = self
            .completed_original(
                reservation.operation_id.as_str(),
                reservation.reservation_id.as_str(),
            )
            .map_err(|_| {
                BaoAuthBusError::Evidence("original consumer ACK settlement unavailable")
            })?;
        if signed.claims.terminal_evidence_digest != terminal
            || signed.claims.observed_at_ms < observed_at
        {
            return Err(BaoAuthBusError::Evidence(
                "original consumer evidence projection mismatch",
            ));
        }
        Ok(signed)
    }
}
