//! Durable representation of the authenticated fleet revocation frontier.
//!
//! Trust roots are never serialized. A selected supervisor reconstructs the
//! coordinator with independently pinned verifiers, then replays the exact
//! signed update and acknowledgements from this snapshot.

use crate::FleetRevocationCoordinator;
use crate::FleetRevocationError;
use crate::FleetRevocationStatus;
use crate::MAX_FLEET_REVOCATION_NODES;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseRevocationConvergenceVerifier;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::SignedFinalUseRevocationAck;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fmt;
use std::sync::Arc;

pub const FLEET_REVOCATION_SNAPSHOT_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetRevocationSnapshotV1 {
    pub schema_version: u32,
    pub convergence_sla_ms: u64,
    pub current_update: Option<SignedFinalUseRevocationUpdate>,
    pub acknowledgements: Vec<SignedFinalUseRevocationAck>,
}

impl FleetRevocationSnapshotV1 {
    pub fn empty(convergence_sla_ms: u64) -> Self {
        Self {
            schema_version: FLEET_REVOCATION_SNAPSHOT_SCHEMA_VERSION,
            convergence_sla_ms,
            current_update: None,
            acknowledgements: Vec::new(),
        }
    }

    pub fn validate_shape(&self) -> Result<(), FleetRevocationSnapshotError> {
        if self.schema_version != FLEET_REVOCATION_SNAPSHOT_SCHEMA_VERSION
            || self.convergence_sla_ms == 0
            || self.acknowledgements.len() > MAX_FLEET_REVOCATION_NODES
            || (self.current_update.is_none() && !self.acknowledgements.is_empty())
        {
            return Err(FleetRevocationSnapshotError::InvalidShape);
        }
        Ok(())
    }

    pub fn restore(
        &self,
        feed_verifier: FinalUseRevocationFeedVerifier,
        convergence_verifier: FinalUseRevocationConvergenceVerifier,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<FleetRevocationCoordinator, FleetRevocationSnapshotError> {
        self.validate_shape()?;
        let mut coordinator = FleetRevocationCoordinator::new(
            feed_verifier,
            convergence_verifier,
            clock,
            self.convergence_sla_ms,
        )
        .map_err(FleetRevocationSnapshotError::Control)?;
        if let Some(update) = &self.current_update {
            coordinator
                .install_update(update.clone())
                .map_err(FleetRevocationSnapshotError::Control)?;
            for acknowledgement in &self.acknowledgements {
                coordinator
                    .record_ack(acknowledgement.clone())
                    .map_err(FleetRevocationSnapshotError::Control)?;
            }
        }
        Ok(coordinator)
    }

    pub fn current_status(
        &self,
        feed_verifier: FinalUseRevocationFeedVerifier,
        convergence_verifier: FinalUseRevocationConvergenceVerifier,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Option<FleetRevocationStatus>, FleetRevocationSnapshotError> {
        if self.current_update.is_none() {
            self.validate_shape()?;
            return Ok(None);
        }
        self.restore(feed_verifier, convergence_verifier, clock)?
            .status()
            .map(Some)
            .map_err(FleetRevocationSnapshotError::Control)
    }

    pub fn semantic_digest(&self) -> Result<String, FleetRevocationSnapshotError> {
        self.validate_shape()?;
        let encoded = serde_json::to_vec(self)
            .map_err(|_| FleetRevocationSnapshotError::Encoding)?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.runtime.fleet.revocation-snapshot.v1\0");
        digest.update(encoded);
        Ok(format!("{:x}", digest.finalize()))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FleetRevocationSnapshotError {
    InvalidShape,
    Encoding,
    Control(FleetRevocationError),
}

impl fmt::Display for FleetRevocationSnapshotError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for FleetRevocationSnapshotError {}
