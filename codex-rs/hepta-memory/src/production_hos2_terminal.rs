//! Complete correlated native terminal evidence stored in the original event.

use super::*;
use crate::LocalReconcileOutcome;

/// Internal evidence returned by the explicitly attached native adapter. A
/// public apply/reject string cannot use the HOS2 terminal append path.
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Hos2TerminalReceipt {
    schema_version: u32,
    request: Hos2InstallBudgetV1,
    observation: Hos2DeliveryObservation,
}

impl Hos2TerminalReceipt {
    pub(super) fn new(
        request: &Hos2InstallBudgetV1,
        observation: Hos2DeliveryObservation,
    ) -> Result<Self, String> {
        request.to_json()?;
        let valid = match &observation {
            Hos2DeliveryObservation::Applied {
                stable_object_id, previous_revision, revision, effective_ns, consumed_ns,
            } => *stable_object_id != [0; 16]
                && *previous_revision == request.expected_revision
                && previous_revision.checked_add(1) == Some(*revision)
                && *consumed_ns <= *effective_ns % HOS2_CPU_PERIOD_NS,
            Hos2DeliveryObservation::NotApplied { status: 1..=7 } => true,
            Hos2DeliveryObservation::NotApplied { .. }
            | Hos2DeliveryObservation::Reserved
            | Hos2DeliveryObservation::NotSeen
            | Hos2DeliveryObservation::Retired
            | Hos2DeliveryObservation::HistoryLost => false,
        };
        if !valid {
            return Err(format!("HOS2 D has no matching terminal outcome: {observation:?}"));
        }
        Ok(Self { schema_version: 1, request: request.clone(), observation })
    }

    pub(crate) fn from_json(payload: &str, request: &Hos2InstallBudgetV1) -> Result<Self, String> {
        let receipt: Self = serde_json::from_str(payload).map_err(|error| error.to_string())?;
        if receipt.schema_version != 1 || &receipt.request != request {
            return Err("HOS2 terminal evidence is bound to another immutable request".to_string());
        }
        let checked = Self::new(request, receipt.observation)?;
        if checked.to_json()? != payload {
            return Err("HOS2 terminal evidence is not canonical".to_string());
        }
        Ok(checked)
    }

    pub(crate) fn to_json(&self) -> Result<String, String> {
        serde_json::to_string(self).map_err(|error| error.to_string())
    }

    pub(crate) fn outcome(&self) -> LocalReconcileOutcome {
        match self.observation {
            Hos2DeliveryObservation::Applied { .. } => LocalReconcileOutcome::Committed,
            Hos2DeliveryObservation::NotApplied { .. } => LocalReconcileOutcome::Rejected,
            Hos2DeliveryObservation::Reserved
            | Hos2DeliveryObservation::NotSeen
            | Hos2DeliveryObservation::Retired
            | Hos2DeliveryObservation::HistoryLost => LocalReconcileOutcome::StillIndeterminate,
        }
    }

    pub(crate) fn matches(&self, payload: &str) -> Result<(), String> {
        if self.request.to_json()? != payload {
            return Err("HOS2 terminal evidence changed the original outbox payload".to_string());
        }
        Ok(())
    }
}
