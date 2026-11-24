//! Purpose-specific statements. Rendering a statement grants no authorization.

use codex_hepta_types::Digest32;

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
