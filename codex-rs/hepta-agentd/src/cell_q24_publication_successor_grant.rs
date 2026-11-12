//! Request C's grant while the actual worker still owns its prepared journals.

use super::*;
use crate::AgentdState;

impl OriginalCellQ24PreparedPublicationV1 {
    pub(crate) async fn issue_original_successor_final_use(
        self,
        state: Arc<AgentdState>,
        identity: AgentdIdentity,
        slot: Arc<crate::circuit_q24_successor::SuccessorSlot>,
    ) -> Result<(Self, SignedFinalUseGrant), Error> {
        self.original.decision.require_new_work()?;
        require_successor_admission(&state, &identity)?;
        let owners: Arc<OriginalCellQ24LearningStageOwnersV1> = Arc::clone(&self.original.owners);
        let snapshot = self.original.decision.snapshot.clone();
        let manifest = self.original.manifest.clone();
        owners
            .with_original_publication(snapshot, manifest, move || {
                self.original.decision.require_new_work()?;
                require_successor_admission(&state, &identity)?;
                slot.require_installation_open()
                    .map_err(|_| Error::CommitUncertain)?;
                let issued =
                    PreparedAgentdGenerationUpdateV1::issue_original_root_final_use(&self.prepared);
                // A failed/uncertain grant still runs the original live postchecks;
                // its consumed worker and Root attempt are never retried here.
                require_successor_admission(&state, &identity)?;
                slot.require_installation_open()
                    .map_err(|_| Error::CommitUncertain)?;
                Ok((self, issued?))
            })
            .await
    }
}
