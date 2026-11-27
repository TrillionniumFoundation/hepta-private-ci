//! Destination observations retained by the original production writer.
//!
//! Reconciliation must not reduce a destination receipt to a bare state flag.
//! The existing event binds this payload to its owner, generation and fence;
//! the immutable operation/outbox pair retains the original request bytes.
//! Retaining an observation does not independently verify the destination or
//! authorize history retirement, redispatch or another external effect.

use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;

use super::ProductionDispatchRequest;
use super::ProductionDurableWriter;
use super::ProductionOutcomeReceipt;
use super::ProductionWriterError;
use crate::LocalReconcileOutcome;

#[derive(Serialize)]
#[serde(tag = "disposition", rename_all = "snake_case")]
pub(super) enum TerminalObservation<'a> {
    Committed { receipt: &'a str },
    NotApplied { reason: &'a str },
    Rejected { reason: &'a str },
    Quarantined { reason: &'a str },
}

#[derive(Serialize)]
struct TerminalJournalV1<'a> {
    schema_version: u32,
    namespace: &'static str,
    lease_id: &'a str,
    operation_id: &'a str,
    destination_id: &'a str,
    operation_semantic_sha256: &'a Sha256Digest,
    payload_sha256: &'a Sha256Digest,
    operation_digest: &'a Sha256Digest,
    observation: TerminalObservation<'a>,
}

impl ProductionDurableWriter {
    pub(super) async fn reconcile_terminal_observation(
        &self,
        request: &ProductionDispatchRequest,
        observation: TerminalObservation<'_>,
    ) -> Result<ProductionOutcomeReceipt, ProductionWriterError> {
        // Revalidate after the observer/target future, before the owning
        // transaction checks the current lease and predecessor fence again.
        self.verify_authority().await?;
        let (outcome, detail) = match &observation {
            TerminalObservation::Committed { receipt } => {
                (LocalReconcileOutcome::Committed, *receipt)
            }
            TerminalObservation::NotApplied { reason }
            | TerminalObservation::Rejected { reason }
            | TerminalObservation::Quarantined { reason } => {
                (LocalReconcileOutcome::Rejected, *reason)
            }
        };
        if detail.trim().is_empty() || detail.len() > 65_536 || detail.contains('\0') {
            return Err(ProductionWriterError::Invalid(
                "terminal observation must contain 1..=65536 non-NUL bytes".to_string(),
            ));
        }
        let payload = serde_json::to_string(&TerminalJournalV1 {
            schema_version: 1,
            namespace: "production_terminal_observation",
            lease_id: &request.lease_id,
            operation_id: &request.occurrence_key,
            destination_id: &request.operation_destination_id,
            operation_semantic_sha256: &request.operation_semantic_sha256,
            payload_sha256: &request.payload_sha256,
            operation_digest: &request.operation_digest,
            observation,
        })
        .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?;
        // The complete encoded payload, including escaping and bindings, must
        // fit the original 64 KiB event limit. Failure leaves the occurrence
        // indeterminate; no terminal event is committed without its receipt.
        Ok(self
            .lease
            .reconcile_with_payload(request.occurrence_key.clone(), outcome, payload)
            .await?
            .into())
    }
}
