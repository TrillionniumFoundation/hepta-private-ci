//! Frozen non-authorizing inputs shared by the original Root and Agentd owners.
//! V1 material digests name complete raw file bytes, not legacy record_digest.

use super::*;
use crate::PairedTrainingMaterialManifestV1;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PairedTrainingPlanV1 {
    pub preparation: PairedPreparationRegistration,
    pub manifest: PairedTrainingMaterialManifestV1,
    pub operation: Digest32,
}

impl PairedTrainingPlanV1 {
    /// Check fixed metadata only. No human, record, material or grant is opened.
    pub fn validate(&self) -> Result<(), AgentdError> {
        let registration = &self.preparation;
        if [
            registration.study,
            registration.enrollment,
            registration.frozen_materials,
            self.operation,
        ]
        .into_iter()
        .any(Digest32::is_zero)
            || registration.principal_id.is_empty()
            || registration.principal_id.len() > 128
            || !registration
                .principal_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
            || self
                .manifest
                .commitment()
                .map_err(|error| invalid(&error.to_string()))?
                != registration.frozen_materials
        {
            return Err(invalid(
                "paired training plan differs from its frozen material commitment",
            ));
        }
        Ok(())
    }

    /// Render only this frozen purpose; displaying it is not consent.
    pub fn consent_text(&self) -> Result<String, AgentdError> {
        self.validate()?;
        Ok(PairedLearningDataUse::TrainOnFailureAndCorrection {
            failure: self.manifest.failure_sha256,
            correction: self.manifest.correction_sha256,
        }
        .consent_text(self.preparation.study))
    }

    /// Bind observed references without treating them as proof of a Core turn.
    /// The original owner must still verify Core, AuthBus, Root and its journal.
    pub fn request_for_original(
        &self,
        turn_id: String,
        delivery_id: Digest32,
    ) -> Result<PairedPreparationRequest, AgentdError> {
        self.validate()?;
        let request = PairedPreparationRequest {
            original: PairedTurnRequest {
                turn_id,
                delivery_id,
                study: self.preparation.study,
                usage: PairedLearningDataUse::TrainOnFailureAndCorrection {
                    failure: self.manifest.failure_sha256,
                    correction: self.manifest.correction_sha256,
                },
                expected_principal: self.preparation.principal_id.clone(),
            },
            operation: self.operation,
            materials: self.preparation.frozen_materials,
        };
        request.identity(&self.preparation)?;
        Ok(request)
    }
}
