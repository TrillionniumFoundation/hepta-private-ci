//! A bounded blocking-I/O boundary for the existing learning host.
//! A timed-out or dropped caller cannot release the actual worker's permit.
//! Dispatch uncertainty is left in kernel.operations for exact reconciliation.

use super::*;
use codex_hepta_operations::AuthorizedDispatch;

const IO_BUDGET: Duration = Duration::from_secs(30);

impl AgentdIntelligenceLearningHostV1 {
    pub(super) async fn run_io<T, F>(&self, work: F) -> Result<T, AgentdIntelligenceLearningErrorV1>
    where
        T: Send + 'static,
        F: FnOnce() -> Result<T, AgentdIntelligenceLearningErrorV1> + Send + 'static,
    {
        let permit = Arc::clone(&self.io_slots)
            .try_acquire_owned()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::IoBusy)?;
        let worker = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            work()
        });
        match tokio::time::timeout(IO_BUDGET, worker).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) | Err(_) => Err(AgentdIntelligenceLearningErrorV1::IoIndeterminate),
        }
    }

    pub(super) async fn execute_ledger_operation(
        &self,
        authorized: AuthorizedDispatch,
        payload: PersistedLearningEnvelopeV1,
    ) -> Result<ApplyObservation, AgentdIntelligenceLearningErrorV1> {
        let operations = self.operations.clone();
        let writer = Arc::clone(&self.writer);
        let runtime = tokio::runtime::Handle::current();
        self.run_io(move || {
            runtime.block_on(async move {
                operations
                    .execute_authorized(authorized, |_| {
                        let observed = match writer.lock() {
                            Ok(mut writer) => classify_apply(apply_payload(&mut writer, &payload)),
                            Err(_) => ApplyObservation::Indeterminate(Digest32::of_bytes(
                                b"hepta.agentd.intelligence-learning.writer-poisoned.v1",
                            )),
                        };
                        match &observed {
                            ApplyObservation::Acknowledged(receipt) => DispatchEffect::Dispatched {
                                value: observed.clone(),
                                dispatch_digest: receipt.chain_digest,
                                acknowledgement_digest: Some(receipt.chain_digest),
                            },
                            ApplyObservation::Rejected(reason)
                            | ApplyObservation::Revoked(reason)
                            | ApplyObservation::Indeterminate(reason) => {
                                DispatchEffect::Indeterminate {
                                    value: observed.clone(),
                                    reason_digest: *reason,
                                }
                            }
                        }
                    })
                    .await
                    .map_err(Into::into)
            })
        })
        .await
    }
}
