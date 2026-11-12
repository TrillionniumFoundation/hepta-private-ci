//! Closed read-only command backends for the existing evidence-only interface.
//! No caller can supply a transport callback or choose a wire operation here.

use std::sync::Mutex;

use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use super::LearningIterationEvidenceClientV1;
use super::training_command::readonly::OriginalTrainingReadbackV1;
use super::unavailable;
use crate::LearningIterationRuntimeErrorV1 as Error;

pub(super) enum OriginalCommandEvidenceV1 {
    Training(OriginalTrainingReadbackV1),
}

impl LearningIterationEvidenceClientV1 {
    pub(super) async fn read_original_command(
        &self,
        slot: &Mutex<Option<OriginalCommandEvidenceV1>>,
        receipt: &LearningIterationReceiptV1,
        payload: &[u8],
        role: LearningEvidenceRoleV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        // Take before awaiting. A dropped caller, malformed result, failed
        // CURRENT or changed signature permanently consumes this connection.
        let mut original = slot.try_lock().map_err(|_| unavailable())?
            .take().ok_or_else(unavailable)?;
        let (signature, current) = match &mut original {
            OriginalCommandEvidenceV1::Training(reader) =>
                OriginalTrainingReadbackV1::readback(reader, receipt).await
                    .map_err(|_| Error::OwnerUnavailable("original Training command readback"))?,
        };
        // This private timestamp was sampled by the closed command backend
        // after all peer and original-owner I/O. D/T share that same check.
        let verified = self.verifier.verify(role, &signature, payload, current)
            .map_err(Error::Evidence)?;
        if verified.principal().principal_id != self.actor_id
            || receipt.observed_unix_seconds > current
        {
            return Err(Error::Evidence(SignedEvidenceError::ContextMismatch));
        }
        *slot.try_lock().map_err(|_| unavailable())? = Some(original);
        Ok(signature)
    }
}
