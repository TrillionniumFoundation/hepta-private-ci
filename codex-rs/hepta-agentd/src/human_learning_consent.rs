//! Purpose-specific consent through the existing protected human text issuer.

use std::sync::Arc;

use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdFinalUseIssuerError;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::AuthBusTextIngress;
use crate::authbus_trust::invalid;
use crate::notes_thread_tool::human::retained_text_ingress;
use crate::text_session::AgentdTextSessionConfig;
use crate::text_session::TextOwnerReceipt;

/// Failure, correction and task are data.record_digest of the complete v1
/// records. Freeze is the canonical digest emitted by paired_freeze.freeze.
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
    RequestConsumerRun {
        operation: Digest32,
        pair: Digest32,
        candidate: Digest32,
        task: Digest32,
    },
    ReportConsumerOutcome {
        operation: Digest32,
        pair: Digest32,
        candidate: Digest32,
        task: Digest32,
        run_receipt: Digest32,
        output: Digest32,
        effect: Digest32,
        accepted: bool,
    },
}

impl PairedLearningDataUse {
    /// Display the exact consent statement in the original human-facing UI.
    /// The caller retains the underlying records separately from this message.
    pub fn consent_text(self, study: Digest32) -> String {
        // Subsequent use has a separate signed text domain. Neither consumer
        // statement grants training rights, transfers funds or verifies execution.
        let consumer_context = |operation, pair, candidate, task| {
            format!(
                "Hepta paired consumer use v1\nStudy SHA-256: {study}\nOperation SHA-256: {operation}\nPaired request SHA-256: {pair}\nSelected model manifest SHA-256: {candidate}\nSubsequent task SHA-256: {task}"
            )
        };
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
            Self::RequestConsumerRun {
                operation,
                pair,
                candidate,
                task,
            } => {
                let context = consumer_context(operation, pair, candidate, task);
                return format!(
                    "{context}\nI request one use of this selected model on this subsequent task. This authorizes neither training nor payment."
                );
            }
            Self::ReportConsumerOutcome {
                operation,
                pair,
                candidate,
                task,
                run_receipt,
                output,
                effect,
                accepted,
            } => {
                let context = consumer_context(operation, pair, candidate, task);
                let decision = if accepted { "accepted" } else { "rejected" };
                return format!(
                    "{context}\nI report my decision about this specific delivered result. This authorizes neither training nor payment.\nRun receipt SHA-256: {run_receipt}\nOutput bytes SHA-256: {output}\nOutcome material SHA-256: {effect}\nMy decision: {decision}"
                );
            }
        };
        format!("Hepta paired learning consent v1\nStudy SHA-256: {study}\n{use_text}")
    }
}

impl AgentdUnixFinalUseGrantProvider {
    /// Resolve exactly one consent message by private AuthBus delivery ID in
    /// the host's existing evidence store. The original UI route and protected
    /// issuer channel are provided by the already attached host. Pass the
    /// consent delivery ID. Task records named by its digests remain unopened.
    pub async fn verify_retained_paired_learning_consent(
        self: &Arc<Self>,
        evidence: &HeptaEvidenceStore,
        route: &AgentdTextSessionConfig,
        delivery_id: Digest32,
        study: Digest32,
        expected: PairedLearningDataUse,
    ) -> Result<TextOwnerReceipt, AgentdError> {
        let retained = evidence
            .retained_authbus_delivery(delivery_id)
            .await
            .map_err(|_| invalid("paired consent delivery unavailable"))?;
        let ingress =
            retained_text_ingress(route, &format!("hepta.authbus:{delivery_id}"), retained)?;
        let issuer = Arc::clone(self);
        let owner = tokio::task::spawn_blocking(move || {
            issuer.verify_paired_learning_consent(&ingress, study, expected)
        })
        .await
        .map_err(|_| invalid("paired consent verification worker unavailable"))?
        .map_err(|_| invalid("paired consent was not verified by the protected issuer"))?;
        if owner.route != *route {
            return Err(invalid("paired consent owner route differs"));
        }
        Ok(owner)
    }

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
