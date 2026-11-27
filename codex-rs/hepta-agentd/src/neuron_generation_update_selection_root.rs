//! Root uses the same actual CURRENT discovery and original selection loader.
//! This is an independent read-side capability, never a second artifact writer.

use codex_hepta_learning_artifacts::LearningArtifactReadViewV1;

use super::*;

impl AgentdSelectedGenerationV1 {
    pub(crate) fn load_from_original_artifacts(
        reader: &LearningArtifactReadViewV1,
        verifier: ArtifactSelectionVerifierV1,
        signed: SignedArtifactSelectionV1,
        files: AgentdGenerationSelectionFilesV1,
        now: u64,
    ) -> Result<Self, AgentdError> {
        let current = reader.read_original_registry(now).map_err(invalid)?;
        let withdrawal = reader.read_original_withdrawals().map_err(invalid)?;
        let mut selected =
            Self::load_at_current(verifier, signed, files, now, current, &withdrawal)?;
        selected.revalidate_original_artifacts(reader, now)?;
        Ok(selected)
    }

    pub(crate) fn revalidate_original_artifacts(
        &mut self,
        reader: &LearningArtifactReadViewV1,
        now: u64,
    ) -> Result<(), AgentdError> {
        if now < self.observed_at {
            return Err(invalid("original selection clock went backwards"));
        }
        let withdrawal = reader.read_original_withdrawals().map_err(invalid)?;
        if withdrawal.scope_digest() != Some(self.observation.withdrawal_scope)
            || withdrawal.head_digest() != self.observation.withdrawal_head
        {
            return Err(invalid("original withdrawal frontier changed"));
        }
        let current: VerifiedCurrentRegistryViewV1 =
            reader.read_original_registry(now).map_err(invalid)?;
        let verified = self
            .verifier
            .verify(&self.signed, &current, now)
            .map_err(invalid)?;
        if verified.selection_digest() != self.observation.selection {
            return Err(invalid("original artifact selection changed"));
        }
        self.candidate
            .with_current(current, |_| ())
            .map_err(invalid)?;
        let after = reader.read_original_withdrawals().map_err(invalid)?;
        if after.snapshot() != withdrawal.snapshot() {
            return Err(invalid(
                "original withdrawal frontier changed during selection",
            ));
        }
        self.observed_at = now;
        Ok(())
    }
}
