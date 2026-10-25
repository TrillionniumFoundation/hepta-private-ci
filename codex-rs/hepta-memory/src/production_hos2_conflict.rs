//! A protocol contradiction disables only the original local intent. It is
//! neither a native terminal receipt nor evidence that an effect was undone.

use super::*;

/// Synchronous InstallBudget observations, kept separate from native history
/// states because a rejected duplicate can still have an older Applied D.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Hos2InstallOutcome {
    Observed(Hos2DeliveryObservation),
    Contradiction(Hos2InstallContradiction),
}

/// Concrete contradictory bytes or status observed by the retained adapter.
/// No variant is created from a timeout, NotSeen or an arbitrary reason string.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Hos2InstallContradiction {
    ConflictStatus,
    RequestBindingMismatch,
    BudgetExceedsGrant {
        maximum_cap_ns: u64,
    },
    InvalidAcknowledgement {
        revision: u64,
        payload: Vec<u8>,
    },
    AcknowledgementMismatch {
        previous_revision: u64,
        revision: u64,
        effective_ns: u64,
        consumed_ns: u64,
        observation: Hos2DeliveryObservation,
    },
}

/// An opaque request-bound record produced only by the original HOS2 target.
/// It cannot authorize an effect, prove NotApplied, or acknowledge retirement.
/// Only serialization is supported: caller-supplied JSON cannot create one.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct Hos2ProtocolConflict {
    schema_version: u32,
    operation_id: String,
    request: Hos2InstallBudgetV1,
    contradiction: Hos2InstallContradiction,
}

impl Hos2ProtocolConflict {
    pub(super) fn new(
        operation_id: &str,
        request: &Hos2InstallBudgetV1,
        contradiction: Hos2InstallContradiction,
    ) -> Result<Self, String> {
        request.to_json()?;
        if operation_id.is_empty() || operation_id.len() > 512 {
            return Err("HOS2 contradiction has an invalid original K".to_string());
        }
        if let Hos2InstallContradiction::InvalidAcknowledgement { payload, .. } = &contradiction
            && payload.len() > 64
        {
            return Err("HOS2 contradiction exceeds the bounded response frame".to_string());
        }
        Ok(Self {
            schema_version: 1,
            operation_id: operation_id.to_string(),
            request: request.clone(),
            contradiction,
        })
    }

    pub(crate) fn matches(&self, operation_id: &str, payload: &str) -> Result<(), String> {
        if self.operation_id != operation_id || self.request.to_json()? != payload {
            return Err("HOS2 contradiction changed its original K/D/request binding".to_string());
        }
        Ok(())
    }

    pub(crate) fn to_json(&self) -> Result<String, String> {
        serde_json::to_string(self).map_err(|error| error.to_string())
    }
}
