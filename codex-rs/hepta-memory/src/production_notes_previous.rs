//! Reattach one old application receipt to the original source owner. Discovery
//! confers no effect authority and never changes the live application identity.
use super::*;
use crate::LocalOutcomeState;
use crate::ProductionDurableWriter;
use crate::ProductionWriterError;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PreviousResponse {
    schema_version: u16,
    action: PreviousAction,
    target: NotesTargetIdentity,
    request_id: String,
    pending_receipt: PendingReceipt,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum PreviousAction {
    PreviousReceipt,
}

// A present JSON null is meaningful. A missing field must not silently mean
// there is no pending original receipt.
#[derive(Deserialize)]
#[serde(untagged)]
enum PendingReceipt {
    Applied(NotesResponse),
    Absent(()),
}

struct RecoveryOnlyChannel(Arc<dyn NotesRecoveryChannel>);
impl NotesPrivateChannel for RecoveryOnlyChannel {
    fn exchange(&self, _: &[u8]) -> Result<Vec<u8>, String> {
        Err("recovery-only Notes capability cannot dispatch".into())
    }
    fn invalidate(&self) {}
    fn recovery_exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        self.0.exchange(request)
    }
}

/// One old receipt matched to an exact original retained operation. It owns
/// only the recovery descriptor; it has no effect descriptor or issuer. The
/// compatibility target trait rejects dispatch unconditionally.
pub struct ProductionNotesRecoveryTarget {
    inner: ProductionNotesTarget,
    operation_id: String,
    payload_sha256: Sha256Digest,
}

impl ProductionNotesRecoveryTarget {
    fn matches(&self, request: &ProductionDispatchRequest) -> bool {
        request.occurrence_key == self.operation_id && request.payload_sha256 == self.payload_sha256
    }
}

impl ProductionOutboxTarget for ProductionNotesRecoveryTarget {
    fn dispatch<'a>(&'a self, _: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async {
            ProductionTargetOutcome::Rejected {
                reason: "recovery-only Notes target cannot dispatch".into(),
            }
        })
    }
}

impl FinalUseProductionOutboxTarget for ProductionNotesRecoveryTarget {
    fn destination_id(&self) -> &str {
        self.inner.destination_id()
    }
    fn retire_notes_receipt(&self, permit: &crate::NotesRetirementPermit) -> Result<(), String> {
        if !self.matches(permit.request()) {
            return Err("Notes recovery receipt differs from the retained operation".into());
        }
        self.inner.retire_notes_receipt(permit)
    }
    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        if !self.matches(request) {
            return Box::pin(async {
                ProductionTerminalObservation::Unavailable {
                    reason: "Notes recovery observation differs from the retained operation".into(),
                }
            });
        }
        self.inner.observe_terminal(request)
    }
}

impl ProductionDurableWriter {
    /// Discover through the current attached application's private recovery
    /// lane, then validate against this original writer's retained operation.
    /// The fresh nonce is supplied by the trusted blocking host worker. No
    /// source append, dispatch, receipt retirement or authority issuance occurs.
    pub async fn previous_notes_recovery_target(
        &self,
        observer: &ProductionNotesObserver,
        request_id: &str,
    ) -> Result<Option<ProductionNotesRecoveryTarget>, ProductionWriterError> {
        self.verify_current_authority().await?;
        if !lower_hex(request_id, 32) {
            return Err(ProductionWriterError::Invalid(
                "invalid Notes recovery nonce".into(),
            ));
        }
        let request = serde_json::to_vec(&serde_json::json!({
            "schema_version":1,"action":"read_previous_receipt",
            "target":observer.target,"request_id":request_id,
        }))
        .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?;
        // Narrow before any discovery I/O. Legacy or effect-only channels
        // cannot be converted into a recovery target by returning JSON.
        let channel = observer
            .channel
            .recovery_handle()
            .map_err(ProductionWriterError::Invalid)?;
        let raw = channel
            .exchange(&request)
            .map_err(ProductionWriterError::Durability)?;
        if raw.is_empty() || raw.len() > NOTES_RESPONSE_MAX_BYTES {
            return Err(ProductionWriterError::Invalid(
                "Notes previous receipt frame bound".into(),
            ));
        }
        let response: PreviousResponse = serde_json::from_slice(&raw).map_err(|_| {
            ProductionWriterError::Invalid("invalid Notes previous receipt schema".into())
        })?;
        if response.schema_version != 1
            || !matches!(response.action, PreviousAction::PreviousReceipt)
            || response.target != observer.target
            || response.request_id != request_id
        {
            return Err(ProductionWriterError::Invalid(
                "Notes previous receipt correlation mismatch".into(),
            ));
        }
        let PendingReceipt::Applied(receipt) = response.pending_receipt else {
            self.verify_current_authority().await?;
            return Ok(None);
        };
        if receipt.target == observer.target
            || !matches!(receipt.result, NotesResult::Applied { .. })
        {
            return Err(ProductionWriterError::Invalid(
                "Notes previous receipt is not an old applied receipt".into(),
            ));
        }
        let retained = self
            .retained_operation(&receipt.operation_id)
            .await?
            .ok_or_else(|| {
                ProductionWriterError::Invalid(
                    "Notes previous receipt has no original operation".into(),
                )
            })?;
        let original = notes_operation_intent(
            &receipt.target,
            &retained.payload_json,
            StableId::new(self.owner_agent_id().as_str())
                .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?,
            retained.operation.policy_generation(),
        )
        .map_err(ProductionWriterError::Invalid)?;
        if retained.topic != NOTES_REPLACE_TOPIC_V1
            || original != retained.operation
            || !matches!(
                retained.state,
                LocalOutcomeState::Indeterminate | LocalOutcomeState::Committed
            )
        {
            return Err(ProductionWriterError::Invalid(
                "Notes previous receipt does not bind an executed original operation".into(),
            ));
        }
        // This discovery serialization is only a validation input. Original
        // reconciliation later queries and durably retains the exact response
        // bytes from the application; discovery does not publish evidence.
        let evidence = serde_json::to_string(&receipt)
            .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?;
        NotesTerminalReceipt::from_json(&retained.payload_json, &evidence)
            .map_err(ProductionWriterError::Invalid)?;
        let payload_sha256 = Sha256Digest::for_bytes(retained.payload_json.as_bytes());
        let target = ProductionNotesRecoveryTarget {
            inner: ProductionNotesTarget::new(
                receipt.target,
                Arc::new(RecoveryOnlyChannel(channel)),
            )
            .map_err(ProductionWriterError::Invalid)?,
            operation_id: receipt.operation_id,
            payload_sha256,
        };
        self.verify_current_authority().await?;
        Ok(Some(target))
    }
}
