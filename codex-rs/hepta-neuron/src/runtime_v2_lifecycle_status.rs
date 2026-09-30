
#[derive(Default)]
struct PhaseMeasurementV2 {
    recovery_only: bool,
    admission_micros: u64,
    local_reconciliation_micros: u64,
    provider_micros: u64,
    transition_micros: u64,
    receipt_encode_micros: u64,
    full_receipt_materialize_micros: u64,
    store_commit_micros: u64,
    index_commit_micros: u64,
    witness_micros: u64,
    final_use_check_micros: u64,
    checkpoint_payload_bytes: u64,
    full_receipt_bytes: u64,
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

/// Administrative status only; this value grants no execution/use authority.
/// A read error is never converted into `NotRecorded`. `Committed` may precede
/// witness acknowledgement, so callers must not treat it as external acceptance.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronOperationStatusV2 {
    NotRecorded,
    NotExecuted,
    OutcomeUnknown,
    Failed(NeuronOperationFailureV2),
    Committed {
        commit: Box<NeuronRuntimeCommitV2>,
        witness_acknowledged: bool,
    },
}

impl NeuronOperationStatusV2 {
    /// Stable low-cardinality code for logs, metrics and host runbooks. It is
    /// deliberately independent from `Debug` formatting and grants no authority.
    #[must_use]
    pub fn stable_code(&self) -> &'static str {
        match self {
            Self::NotRecorded => "not_recorded",
            Self::NotExecuted => "reserved_not_executed",
            Self::OutcomeUnknown => "outcome_unknown",
            Self::Failed(_) => "failed",
            Self::Committed {
                witness_acknowledged: true,
                ..
            } => "committed_witnessed",
            Self::Committed {
                witness_acknowledged: false,
                ..
            } => "committed_witness_pending",
        }
    }

    /// Stable operator action for the exact status. This is advisory only:
    /// execution still requires the new-work admission boundary, recovery may
    /// only reconcile the same key, and result release still requires the
    /// current-use guard.
    #[must_use]
    pub fn action_code(&self) -> &'static str {
        match self {
            Self::NotRecorded => "admit_original_request",
            Self::NotExecuted => "resume_or_close_unexecuted",
            Self::OutcomeUnknown => "reconcile_provider",
            Self::Failed(_) => "return_terminal_failure",
            Self::Committed {
                witness_acknowledged: false,
                ..
            } => "reconcile_witness",
            Self::Committed {
                witness_acknowledged: true,
                ..
            } => "check_current_use",
        }
    }

    #[must_use]
    pub fn is_terminal(&self) -> bool {
        matches!(self, Self::Failed(_) | Self::Committed { .. })
    }

    /// True when the same exact operation still needs runtime/provider or
    /// witness reconciliation. This never authorizes a changed-input retry.
    #[must_use]
    pub fn requires_reconciliation(&self) -> bool {
        matches!(
            self,
            Self::NotExecuted
                | Self::OutcomeUnknown
                | Self::Committed {
                    witness_acknowledged: false,
                    ..
                }
        )
    }
}

impl NeuronRuntimeV2Error {
    /// Stable low-cardinality error family. Callers that need execution truth
    /// must still query the exact operation key; an error string is not state.
    #[must_use]
    pub fn stable_code(&self) -> &'static str {
        match self {
            Self::Admission(_) => "admission",
            Self::Configuration(_) => "configuration",
            Self::Store(GenerationStoreError::Backpressure) => "store_backpressure",
            Self::Store(GenerationStoreError::Capacity) => "store_capacity",
            Self::Store(GenerationStoreError::Indeterminate | GenerationStoreError::Poisoned) => {
                "store_outcome_unknown"
            }
            Self::Store(_) => "store",
            Self::Index(NeuronRuntimeIndexError::Pending) => "index_pending",
            Self::Index(NeuronRuntimeIndexError::Capacity) => "index_capacity",
            Self::Index(
                NeuronRuntimeIndexError::Indeterminate | NeuronRuntimeIndexError::Poisoned,
            ) => "index_outcome_unknown",
            Self::Index(NeuronRuntimeIndexError::TerminalFailure(_)) => "terminal_failure",
            Self::Index(_) => "index",
            Self::Witness(WitnessStoreError::Unavailable | WitnessStoreError::Busy) => {
                "witness_unavailable"
            }
            Self::Witness(WitnessStoreError::Indeterminate | WitnessStoreError::Poisoned) => {
                "witness_outcome_unknown"
            }
            Self::Witness(_) => "witness",
            Self::Model(NeuronModelError::Unavailable) => "model_unavailable",
            Self::Model(NeuronModelError::Indeterminate) => "model_outcome_unknown",
            Self::Model(NeuronModelError::Rejected) => "model_rejected",
            Self::Semantic(_) => "semantic",
            Self::Codec(_) => "codec",
            Self::ReceiptExtension(_) => "receipt_extension",
            Self::Mechanism(_) => "mechanism",
            Self::ContextMismatch => "context_mismatch",
            Self::CheckpointMismatch => "checkpoint_mismatch",
            Self::OperationConflict => "operation_conflict",
            Self::RecoveryMismatch => "recovery_mismatch",
            Self::PendingOperation => "pending_operation",
            Self::Arithmetic => "arithmetic",
            Self::TerminalFailure(_) => "terminal_failure",
        }
    }
}

#[cfg(test)]
mod status_action_tests {
    use super::*;

    #[test]
    fn operation_status_actions_do_not_collapse_recovery_boundaries() {
        assert_eq!(
            NeuronOperationStatusV2::NotRecorded.action_code(),
            "admit_original_request"
        );
        assert_eq!(
            NeuronOperationStatusV2::NotExecuted.action_code(),
            "resume_or_close_unexecuted"
        );
        assert_eq!(
            NeuronOperationStatusV2::OutcomeUnknown.action_code(),
            "reconcile_provider"
        );
        assert_eq!(
            NeuronOperationStatusV2::Failed(NeuronOperationFailureV2::AdmissionDenied)
                .action_code(),
            "return_terminal_failure"
        );
    }
}
