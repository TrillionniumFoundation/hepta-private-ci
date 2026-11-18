//! A synchronous borrow of one actual Root observation. The higher-ranked
//! callback cannot return this lifetime, and the token cannot cross threads.
//! Pure checks may repeat inside it; another operation must query Root again.

use std::io::Write;
use std::marker::PhantomData;
use std::rc::Rc;

use super::*;

pub(crate) struct OriginalHistoricalOperationV1<'read> {
    trust: &'read OriginalHistoricalLearningTrustV1,
    data: &'read RootHistoricalLedgerReadDataV1,
    local: PhantomData<Rc<()>>,
}

impl OriginalHistoricalLearningTrustV1 {
    /// Two actual complete Root observations enclose this one synchronous
    /// operation, including its error path. Current recipient activation is
    /// checked independently on both sides. No borrowed authority is retained.
    pub(crate) fn with_original_operation<T, E>(
        &self,
        action: impl for<'read> FnOnce(&OriginalHistoricalOperationV1<'read>) -> Result<T, E>,
    ) -> io::Result<Result<T, E>> {
        let result =
            OriginalHistoricalTaskReadReceiptV1::with_current_read(&self.receipt, |data| {
                self.current_operation_activation().inspect_err(|_| {
                    let _ = std::io::stderr()
                        .write_all(b"daemon_stage=historical.operation.activation_before\n");
                })?;
                let operation = OriginalHistoricalOperationV1 {
                    trust: self,
                    data,
                    local: PhantomData,
                };
                let value = action(&operation).inspect_err(|_| {
                    let _ =
                        std::io::stderr().write_all(b"daemon_stage=historical.operation.action\n");
                });
                self.current_operation_activation().inspect_err(|_| {
                    let _ = std::io::stderr()
                        .write_all(b"daemon_stage=historical.operation.activation_after\n");
                })?;
                Ok(value)
            })
            .inspect_err(|_| {
                let _ = std::io::stderr().write_all(b"daemon_stage=historical.operation.result\n");
            });
        if !matches!(&result, Ok(Ok(_))) {
            let _ = std::io::stderr().write_all(b"daemon_stage=historical.operation.fence\n");
            self.receipt.client.fence();
        }
        result
    }

    fn current_operation_activation(
        &self,
    ) -> io::Result<(ActivatedLearningTrustV1, TrustedLearningSignerV1, u64)> {
        let now =
            OriginalHistoricalLearningTrustV1::original_unix_seconds(self).inspect_err(|_| {
                let _ = std::io::stderr().write_all(b"daemon_stage=historical.activation.clock\n");
            })?;
        let (activated, evaluator) = self
            .payload
            .activate_for_recipient(self.initial_snapshot(), now)
            .inspect_err(|_| {
                let _ =
                    std::io::stderr().write_all(b"daemon_stage=historical.activation.activate\n");
            })?;
        self.require_same_activation(&activated, &evaluator)
            .inspect_err(|_| {
                let _ = std::io::stderr().write_all(b"daemon_stage=historical.activation.pin\n");
            })?;
        Ok((activated, evaluator, now))
    }
}

impl OriginalHistoricalOperationV1<'_> {
    /// Only the exact current trust and receipt may use this borrow. The image
    /// is Root-observed data; every use still checks the actual session clock,
    /// current signed distribution and fixed Evaluator before and after.
    pub(crate) fn read_for<T>(
        &self,
        trust: &OriginalHistoricalLearningTrustV1,
        receipt: &Arc<OriginalHistoricalTaskReadReceiptV1>,
        action: impl FnOnce(
            &RootHistoricalLedgerReadDataV1,
            &LearningEvidenceVerifierV1,
            &TrustedLearningSignerV1,
            u64,
        ) -> io::Result<T>,
    ) -> io::Result<T> {
        let result = (|| {
            if !std::ptr::eq(self.trust, trust) || !Arc::ptr_eq(&self.trust.receipt, receipt) {
                return Err(refused()).inspect_err(|_| {
                    let _ =
                        std::io::stderr().write_all(b"daemon_stage=historical.read_for.identity\n");
                });
            }
            let (activated, evaluator, now) =
                self.trust.current_operation_activation().inspect_err(|_| {
                    let _ = std::io::stderr()
                        .write_all(b"daemon_stage=historical.read_for.activation_before\n");
                })?;
            let value =
                action(self.data, activated.verifier(), &evaluator, now).inspect_err(|_| {
                    let _ =
                        std::io::stderr().write_all(b"daemon_stage=historical.read_for.action\n");
                });
            self.trust.current_operation_activation().inspect_err(|_| {
                let _ = std::io::stderr()
                    .write_all(b"daemon_stage=historical.read_for.activation_after\n");
            })?;
            value
        })()
        .inspect_err(|_| {
            let _ = std::io::stderr().write_all(b"daemon_stage=historical.read_for.result\n");
        });
        if result.is_err() {
            let _ = std::io::stderr().write_all(b"daemon_stage=historical.read_for.fence\n");
            self.trust.receipt.client.fence();
        }
        result
    }
}
