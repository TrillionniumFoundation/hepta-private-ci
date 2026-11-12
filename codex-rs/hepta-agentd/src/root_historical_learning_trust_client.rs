//! Current recipient authority obtained only from the same Root historical
//! connection. Old A's signed Ledger data cannot construct this capability.

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;

use super::*;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustPayloadV1;

#[path = "root_historical_learning_operation.rs"]
mod operation;
pub(crate) use operation::OriginalHistoricalOperationV1;

pub(crate) struct OriginalHistoricalLearningTrustV1 {
    receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
    clock: Arc<dyn AuthorityClock>,
    payload: HistoricalLearningTrustPayloadV1,
    activated: ActivatedLearningTrustV1,
    evaluator: TrustedLearningSignerV1,
}

pub(crate) struct OriginalHistoricalStageAuthoritiesV1 {
    pub(crate) verifier: LearningEvidenceVerifierV1,
    pub(crate) experience: TrustedLearningSignerV1,
    pub(crate) dataset: TrustedLearningSignerV1,
    pub(crate) trainer: TrustedLearningSignerV1,
    pub(crate) selector: TrustedLearningSignerV1,
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
    /// The fixed original request chooses each principal. Descriptor data can
    /// provide its existing key, but cannot select another enrolled role.
    pub(crate) fn original_stage_authorities(
        &self,
    ) -> io::Result<OriginalHistoricalStageAuthoritiesV1> {
        self.with_current_trust(|_, verifier, _, now| {
            let owners = &self.initial_snapshot().owners;
            let select = |principal: &codex_hepta_types::StableId, role| {
                let mut matches = self
                    .payload
                    .signed
                    .distribution
                    .signers
                    .iter()
                    .filter(|signer| signer.principal_id == principal.as_str());
                let signer = matches.next().ok_or_else(refused)?;
                if matches.next().is_some() {
                    return Err(refused());
                }
                let signer = signer.original_signer()?;
                verifier
                    .require_signer_binding(role, &signer, now)
                    .map_err(io::Error::other)?;
                Ok(signer)
            };
            Ok(OriginalHistoricalStageAuthoritiesV1 {
                verifier: verifier.clone(),
                experience: select(&owners.experience, LearningEvidenceRoleV1::Observer)?,
                dataset: select(&owners.dataset, LearningEvidenceRoleV1::Observer)?,
                trainer: select(&owners.trainer, LearningEvidenceRoleV1::Generator)?,
                selector: select(&owners.selector, LearningEvidenceRoleV1::Selector)?,
            })
        })
    }

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
        self.with_original_operation(|operation| operation.read_for(self, &self.receipt, action))?
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
