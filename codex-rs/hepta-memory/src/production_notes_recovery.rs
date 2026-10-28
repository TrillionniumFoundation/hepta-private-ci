//! Recovery of an exact original operation after application process restart.
//! This capability owns no effect descriptor, issuer, or new operation ledger.

use super::*;

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

/// A recovery-only target for one immutable original operation. Its identity
/// remains that of the previous process; it cannot authorize the new process.
pub struct ProductionNotesRecoveryTarget {
    inner: ProductionNotesTarget,
    operation_id: String,
    payload_sha256: Sha256Digest,
}

impl ProductionNotesRecoveryTarget {
    /// Attach a trusted private recovery lane to an original retained request.
    /// Construction validates all original writer/operation/payload bindings.
    /// The caller obtains the request from the original durable writer.
    pub(crate) fn from_retained_request(
        request: &ProductionDispatchRequest,
        channel: Arc<dyn NotesRecoveryChannel>,
    ) -> Result<Self, String> {
        let parsed: NotesReplace = serde_json::from_str(&request.payload_json)
            .map_err(|_| "invalid retained Notes payload")?;
        let inner =
            ProductionNotesTarget::new(parsed.target, Arc::new(RecoveryOnlyChannel(channel)))?;
        inner.decode(request)?;
        Ok(Self {
            inner,
            operation_id: request.occurrence_key.clone(),
            payload_sha256: request.payload_sha256.clone(),
        })
    }

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
