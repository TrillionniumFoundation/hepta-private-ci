//! Purpose-specific consent through the existing protected human text issuer.

use codex_hepta_types::Digest32;

use crate::AgentdFinalUseIssuerError;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::AuthBusTextIngress;
use crate::text_session::TextOwnerReceipt;

/// SHA-256 digests identify private records in an independently named study.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PairedLearningDataUse {
    TrainOnFailureAndCorrection {
        failure: Digest32,
        correction: Digest32,
    },
    EvaluateOnlyAfterFreeze {
        freeze: Digest32,
        task: Digest32,
    },
}

impl PairedLearningDataUse {
    /// Display the exact consent statement in the original human-facing UI.
    /// The caller retains the underlying records separately from this message.
    pub fn consent_text(self, study: Digest32) -> String {
        let use_text = match self {
            Self::TrainOnFailureAndCorrection {
                failure,
                correction,
            } => format!(
                "I authorize Hepta to train the study candidate using only these records.\n\
                 Failure SHA-256: {failure}\nCorrection SHA-256: {correction}"
            ),
            Self::EvaluateOnlyAfterFreeze { freeze, task } => format!(
                "I authorize Hepta to evaluate the frozen pair on this task. \
                 Training on this task is prohibited.\n\
                 Pair freeze SHA-256: {freeze}\nTask SHA-256: {task}"
            ),
        };
        format!("Hepta paired learning consent v1\nStudy SHA-256: {study}\n{use_text}")
    }
}

impl AgentdUnixFinalUseGrantProvider {
    /// Validate this exact study, permitted use and record identities against
    /// an original retained human message using the live protected Root lane.
    /// The UI owner receipt stays private to the intake. It identifies the
    /// live registered principal. Independent human enrollment, A's actual
    /// outcome, B's first arrival and payer authority require their own evidence.
    pub fn verify_paired_learning_consent(
        &self,
        ingress: &AuthBusTextIngress,
        study: Digest32,
        expected: PairedLearningDataUse,
    ) -> Result<TextOwnerReceipt, AgentdFinalUseIssuerError> {
        if ingress.body.text != expected.consent_text(study) {
            return Err(AgentdFinalUseIssuerError::BindingMismatch);
        }
        self.verify_original_human_text(ingress)
    }
}
