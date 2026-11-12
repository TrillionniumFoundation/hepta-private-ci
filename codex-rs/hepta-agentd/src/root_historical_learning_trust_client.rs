//! Current recipient authority obtained only from the same Root historical
//! connection. Old A's signed Ledger data cannot construct this capability.

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;

use super::*;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustPayloadV1;

pub(crate) struct OriginalHistoricalLearningTrustV1 {
    receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
    clock: Arc<dyn AuthorityClock>,
    payload: HistoricalLearningTrustPayloadV1,
    activated: ActivatedLearningTrustV1,
    evaluator: TrustedLearningSignerV1,
}

impl OriginalHistoricalTaskReadReceiptV1 {
    pub(crate) fn activate_current_learning_trust(
        self: &Arc<Self>,
        client: &Arc<RootHistoricalTaskReadClientV1>,
        session: &AgentdRootAuthoritySession,
    ) -> io::Result<Arc<OriginalHistoricalLearningTrustV1>> {
        let result = (|| {
            OriginalHistoricalTaskReadReceiptV1::require_original_client(self, client, session)
                .map_err(io::Error::other)?;
            let clock = session.clock();
            let response = match RootHistoricalTaskReadClientV1::exchange(
                &self.client,
                HistoricalReadOperationV1::LearningTrust,
            )? {
                Reply::LearningTrust(response) => *response,
                Reply::Task(_) | Reply::PostAFrozenLearning(_) => return Err(refused()),
            };
            if response.data_cut != self.data.data_cut.to_string() {
                return Err(refused());
            }
            let (activated, evaluator) =
                OriginalHistoricalTaskReadReceiptV1::with_current_read(self, |_| {
                    let now = clock.now_unix_ms().map_err(io::Error::other)? / 1_000;
                    let (activated, evaluator) = response
                        .payload
                        .activate_for_recipient(&self.client.initial, now)?;
                    response.payload.require_activation_pin(
                        &self.client.initial,
                        &activated,
                        &self.client.learning_trust,
                    )?;
                    Ok((activated, evaluator))
                })?;
            OriginalHistoricalTaskReadReceiptV1::require_original_client(self, client, session)
                .map_err(io::Error::other)?;
            Ok(Arc::new(OriginalHistoricalLearningTrustV1 {
                receipt: Arc::clone(self),
                clock,
                payload: response.payload,
                activated,
                evaluator,
            }))
        })();
        if result.is_err() {
            self.client.fence();
        }
        result
    }
}

impl OriginalHistoricalLearningTrustV1 {
    pub(crate) fn original_unix_seconds(&self) -> io::Result<u64> {
        let result = (|| {
            if self.receipt.client.fenced.load(Ordering::Acquire) {
                return Err(refused());
            }
            self.receipt
                .client
                .connection
                .require_original_session()
                .map_err(io::Error::other)?;
            let observed = self.clock.now_unix_ms().map_err(io::Error::other)? / 1_000;
            self.receipt
                .client
                .connection
                .require_original_session()
                .map_err(io::Error::other)?;
            Ok(observed)
        })();
        if result.is_err() {
            self.receipt.client.fence();
        }
        result
    }

    pub(crate) fn require_original_receipt(
        &self,
        receipt: &Arc<OriginalHistoricalTaskReadReceiptV1>,
    ) -> io::Result<()> {
        if !Arc::ptr_eq(&self.receipt, receipt) {
            self.receipt.client.fence();
            return Err(refused());
        }
        Ok(())
    }

    pub(crate) fn initial_snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.receipt.client.initial
    }

    /// Only current same-Root reads surround the pure data/signature operation.
    /// Both activations use the original session clock; dropping that session
    /// fences this clock even if the capsule or a verifier clone is retained.
    pub(crate) fn with_current_trust<T>(
        &self,
        action: impl FnOnce(
            &RootHistoricalLedgerReadDataV1,
            &LearningEvidenceVerifierV1,
            &TrustedLearningSignerV1,
            u64,
        ) -> io::Result<T>,
    ) -> io::Result<T> {
        OriginalHistoricalTaskReadReceiptV1::with_current_read(&self.receipt, |data| {
            let now = self.clock.now_unix_ms().map_err(io::Error::other)? / 1_000;
            let (activated, evaluator) = self
                .payload
                .activate_for_recipient(self.initial_snapshot(), now)?;
            self.require_same_activation(&activated, &evaluator)?;
            let value = action(data, activated.verifier(), &evaluator, now)?;
            let after = self.clock.now_unix_ms().map_err(io::Error::other)? / 1_000;
            let (activated, evaluator) = self
                .payload
                .activate_for_recipient(self.initial_snapshot(), after)?;
            self.require_same_activation(&activated, &evaluator)?;
            Ok(value)
        })
    }

    fn require_same_activation(
        &self,
        activated: &ActivatedLearningTrustV1,
        evaluator: &TrustedLearningSignerV1,
    ) -> io::Result<()> {
        self.payload.require_activation_pin(
            self.initial_snapshot(),
            activated,
            &self.receipt.client.learning_trust,
        )?;
        if activated.root_digest() != self.activated.root_digest()
            || activated.distribution_digest() != self.activated.distribution_digest()
            || activated.verifier().trust_digest() != self.activated.verifier().trust_digest()
            || evaluator != &self.evaluator
        {
            return Err(refused());
        }
        Ok(())
    }
}
