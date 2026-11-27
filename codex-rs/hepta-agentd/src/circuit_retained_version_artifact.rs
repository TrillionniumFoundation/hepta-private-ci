//! Pure original artifact checkpoint and signed-selection observation.
//! This never calls publish, resume, repair, admission or writer extraction.
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::OriginalArtifactPublicationReadbackV1;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;

use super::super::Error;
use super::OriginalCircuitRetainedArtifactCheckpointV1;
use super::RetainedVersionArtifactOwnerV1;

impl RetainedVersionArtifactOwnerV1 {
    pub(super) fn new(
        owner: Arc<Mutex<LearningArtifactOwnerService>>,
        checkpoint: OriginalCircuitRetainedArtifactCheckpointV1,
        selection: SignedArtifactSelectionV1,
        verifier: ArtifactSelectionVerifierV1,
    ) -> Result<Self, Error> {
        if checkpoint.intent_digest.is_zero() {
            return Err(Error::Binding("original artifact checkpoint intent"));
        }
        let (withdrawal_scope, withdrawal_head) = {
            let original = owner.try_lock().map_err(|_| Error::Busy)?;
            let withdrawal = original.withdrawal_registry();
            (
                withdrawal
                    .scope_digest()
                    .ok_or(Error::Binding("original withdrawal scope"))?,
                withdrawal.head_digest(),
            )
        };
        let value = Self {
            owner,
            checkpoint,
            selection,
            verifier,
            withdrawal_scope,
            withdrawal_head,
        };
        value.read_current()?;
        Ok(value)
    }

    pub(super) fn read_current(&self) -> Result<OriginalArtifactPublicationReadbackV1, Error> {
        let original = self.owner.try_lock().map_err(|_| Error::Busy)?;
        if original.recovery_required().is_some()
            || original.withdrawal_registry().scope_digest() != Some(self.withdrawal_scope)
            || original.withdrawal_registry().head_digest() != self.withdrawal_head
            || self.selection.withdrawal_scope_digest != self.withdrawal_scope
        {
            return Err(Error::Binding("same current artifact and withdrawal owner"));
        }
        let read = LearningArtifactOwnerService::read_original_publication_current(
            &original,
            &self.checkpoint.operation_id,
            self.checkpoint.intent_digest,
        )?;
        self.verifier
            .verify(&self.selection, read.current(), read.observed_unix_millis())
            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        if original.withdrawal_registry().head_digest() != self.withdrawal_head {
            return Err(Error::Binding(
                "artifact withdrawal changed during current read",
            ));
        }
        Ok(read)
    }
}

pub(super) fn require_same(
    before: &OriginalArtifactPublicationReadbackV1,
    after: &OriginalArtifactPublicationReadbackV1,
) -> Result<(), Error> {
    if before.checkpoint() != after.checkpoint()
        || before.current().receipt() != after.current().receipt()
        || before.current().witness_digest() != after.current().witness_digest()
        || before.current().trust_digest() != after.current().trust_digest()
        || after.observed_unix_millis() < before.observed_unix_millis()
    {
        return Err(Error::Binding(
            "original artifact checkpoint or CURRENT changed",
        ));
    }
    Ok(())
}
