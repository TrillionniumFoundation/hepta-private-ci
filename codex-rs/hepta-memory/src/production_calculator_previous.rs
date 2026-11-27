//! Recovery of one exact old Calculator receipt on the original source owner.
//! A recovery descriptor never grants an application effect or a new writer.
use super::*;
use crate::LocalOutcomeState;
use crate::ProductionDurableWriter;
use crate::ProductionWriterError;

struct RecoveryOnlyChannel(Arc<dyn CalculatorRecoveryChannel>);
impl CalculatorPrivateChannel for RecoveryOnlyChannel {
    fn exchange(&self, _: &[u8]) -> Result<Vec<u8>, String> {
        Err("recovery-only Calculator capability cannot dispatch".into())
    }
    fn invalidate(&self) {}
    fn recovery_handle(&self) -> Arc<dyn CalculatorRecoveryChannel> {
        Arc::clone(&self.0)
    }
}

/// One old receipt matched to an exact original retained operation. It owns
/// only the recovery descriptor; it has no effect descriptor or issuer. The
/// compatibility target trait rejects dispatch unconditionally.
pub struct ProductionCalculatorRecoveryTarget {
    inner: ProductionCalculatorTarget,
    operation_id: String,
    payload_sha256: Sha256Digest,
}

impl ProductionCalculatorRecoveryTarget {
    fn matches(&self, request: &ProductionDispatchRequest) -> bool {
        request.occurrence_key == self.operation_id && request.payload_sha256 == self.payload_sha256
    }
}

impl ProductionOutboxTarget for ProductionCalculatorRecoveryTarget {
    fn dispatch<'a>(&'a self, _: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async {
            ProductionTargetOutcome::Rejected {
                reason: "recovery-only Calculator target cannot dispatch".into(),
            }
        })
    }
}

impl FinalUseProductionOutboxTarget for ProductionCalculatorRecoveryTarget {
    fn destination_id(&self) -> &str {
        self.inner.destination_id()
    }
    fn retire_calculator_receipt(
        &self,
        permit: &crate::CalculatorRetirementPermit,
    ) -> Result<crate::ProductionRetirementAck, String> {
        if !self.matches(permit.request()) {
            return Err("Calculator recovery receipt differs from the retained operation".into());
        }
        self.inner.retire_calculator_receipt(permit)
    }
    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        if !self.matches(request) {
            return Box::pin(async {
                ProductionTerminalObservation::Unavailable {
                    reason: "Calculator recovery observation differs from the retained operation"
                        .into(),
                }
            });
        }
        self.inner.observe_terminal(request)
    }
}

impl ProductionDurableWriter {
    /// Reattach an explicitly identified retained operation through a recovery-
    /// only descriptor. The trusted host supplies the old target and original
    /// operation id; neither directory discovery nor fresh application state
    /// selects the old operation. No target I/O occurs before the
    /// original source owner verifies its immutable intent/payload/state.
    ///
    /// Committed source rows remain eligible: the application may have durably
    /// retired its receipt and lost that ACK. Its exact AlreadyRetired reply
    /// must still be reachable without redispatching or inventing a receipt.
    pub async fn calculator_recovery_target_for_retained_operation(
        &self,
        target: CalculatorTargetIdentity,
        operation_id: &str,
        channel: Arc<dyn CalculatorRecoveryChannel>,
    ) -> Result<ProductionCalculatorRecoveryTarget, ProductionWriterError> {
        self.verify_current_authority().await?;
        target.validate().map_err(ProductionWriterError::Invalid)?;
        StableId::new(operation_id)
            .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?;
        let retained = self
            .retained_operation(operation_id)
            .await?
            .ok_or_else(|| {
                ProductionWriterError::Invalid(
                    "explicit Calculator recovery has no retained operation".into(),
                )
            })?;
        let parsed = parse_evaluate(&target, &retained.payload_json)
            .map_err(ProductionWriterError::Invalid)?;
        let original = calculator_operation_intent(
            &target,
            &retained.payload_json,
            StableId::new(self.owner_agent_id().as_str())
                .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?,
            retained.operation.policy_generation(),
        )
        .map_err(ProductionWriterError::Invalid)?;
        if parsed.operation_id != operation_id
            || retained.topic != CALCULATOR_EVALUATE_TOPIC_V1
            || original != retained.operation
            || !matches!(
                retained.state,
                LocalOutcomeState::Indeterminate | LocalOutcomeState::Committed
            )
        {
            return Err(ProductionWriterError::Invalid(
                "explicit Calculator recovery differs from an executed retained operation".into(),
            ));
        }
        let recovery = ProductionCalculatorRecoveryTarget {
            inner: ProductionCalculatorTarget::new(target, Arc::new(RecoveryOnlyChannel(channel)))
                .map_err(ProductionWriterError::Invalid)?,
            operation_id: operation_id.to_owned(),
            payload_sha256: Sha256Digest::for_bytes(retained.payload_json.as_bytes()),
        };
        self.verify_current_authority().await?;
        Ok(recovery)
    }
}
