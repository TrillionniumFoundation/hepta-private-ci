//! Install late owners through the already authenticated historical lane.
//! The original freeze writer must be released before this zero-payload call;
//! Root's independent physical lock/read decides whether it can acknowledge.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_types::Digest32;

use super::*;

pub(crate) struct OriginalPostAFrozenLearningAckV1 {
    receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
    frozen_scope: Digest32,
}

impl OriginalHistoricalTaskReadReceiptV1 {
    pub(crate) fn install_original_post_a_learning(
        self: &Arc<Self>,
        client: &Arc<RootHistoricalTaskReadClientV1>,
        session: &AgentdRootAuthoritySession,
    ) -> io::Result<OriginalPostAFrozenLearningAckV1> {
        let result = (|| {
            OriginalHistoricalTaskReadReceiptV1::require_original_client(self, client, session)
                .map_err(io::Error::other)?;
            if self.client.observe()? != self.data {
                return Err(refused());
            }
            let response = match RootHistoricalTaskReadClientV1::exchange(
                &self.client,
                HistoricalReadOperationV1::PostAFrozenLearning,
            )? {
                Reply::PostAFrozenLearning(response) => response,
                Reply::Task(_) | Reply::LearningTrust(_) => return Err(refused()),
            };
            if response.data_cut != self.data.data_cut.to_string()
                || self.client.observe()? != self.data
            {
                return Err(refused());
            }
            OriginalHistoricalTaskReadReceiptV1::require_original_client(self, client, session)
                .map_err(io::Error::other)?;
            Ok(OriginalPostAFrozenLearningAckV1 {
                receipt: Arc::clone(self),
                frozen_scope: crate::root_historical_task_read_protocol::canonical_digest(
                    &response.frozen_scope,
                )?,
            })
        })();
        if result.is_err() {
            self.client.fence();
        }
        result
    }
}

impl OriginalPostAFrozenLearningAckV1 {
    pub(crate) fn require_prepared_scope(&self, scope: &FrozenLearningScopeV2) -> io::Result<()> {
        let result = (|| {
            self.receipt
                .client
                .connection
                .require_original_session()
                .map_err(io::Error::other)?;
            scope
                .validate_snapshot(self.receipt.initial_snapshot())
                .map_err(io::Error::other)?;
            if self.receipt.client.fenced.load(Ordering::Acquire)
                || scope.binding() != self.frozen_scope
            {
                return Err(refused());
            }
            self.receipt
                .client
                .connection
                .require_original_session()
                .map_err(io::Error::other)
        })();
        if result.is_err() {
            self.receipt.client.fence();
        }
        result
    }
}
