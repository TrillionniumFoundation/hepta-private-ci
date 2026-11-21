//! Test-only categories at existing C Observer error-collapse boundaries.
//! Payloads, signatures, identities, binding strings and panic values are never formatted.

use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use tokio::task::JoinError;

use super::OriginalCircuitNextUseCommandErrorV1;
use crate::OriginalCircuitNextUseReceiptErrorV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

pub(super) fn transport_error(phase: &'static str, error: HostIssuerTransportError) {
    let category = match error {
        HostIssuerTransportError::InvalidConfiguration => "InvalidConfiguration",
        HostIssuerTransportError::PeerDenied => "PeerDenied",
        HostIssuerTransportError::Closed => "Closed",
        HostIssuerTransportError::InvalidRequest => "InvalidRequest",
        HostIssuerTransportError::DeadlineElapsed => "DeadlineElapsed",
        HostIssuerTransportError::Unavailable => "Unavailable",
    };
    // The public transport error has already discarded any underlying OS error.
    eprintln!("HEPTA_C_OBSERVER phase={phase} transport={category} os_error=not_retained");
}

pub(super) fn join_error(phase: &'static str, error: &JoinError) {
    let panicked = error.is_panic();
    let cancelled = error.is_cancelled();
    eprintln!("HEPTA_C_OBSERVER phase={phase} panicked={panicked} cancelled={cancelled}");
}

pub(super) fn command_error(phase: &'static str, error: &OriginalCircuitNextUseCommandErrorV1) {
    use OriginalCircuitNextUseCommandErrorV1 as Command;
    let category = match error {
        Command::Binding(_) => "Binding",
        Command::Unavailable => "Unavailable",
        Command::CommitUncertain => "CommitUncertain",
        Command::ReadbackRequired => "ReadbackRequired",
        Command::Busy => "Busy",
        Command::Missing => "Missing",
        Command::Pending => "Pending",
        Command::DeadlineExceeded => "DeadlineExceeded",
        Command::Transport(_) => "Transport",
        Command::Owner(_) => "Owner",
        Command::Iteration(_) => "Iteration",
        Command::Evidence(_) => "Evidence",
        Command::Checkpoint(_) => "Checkpoint",
        Command::Encoding(_) => "Encoding",
    };
    eprintln!("HEPTA_C_OBSERVER phase={phase} command={category}");
    if let Command::Transport(transport) = error {
        transport_error(phase, *transport);
    }
    if let Command::Owner(owner) = error {
        owner_error(phase, owner);
    }
}

pub(super) fn owner_error(phase: &'static str, error: &OriginalCircuitNextUseReceiptErrorV1) {
    use LearningOriginalOwnerErrorV1 as Owner;
    use OriginalCircuitNextUseReceiptErrorV1 as Observer;
    use ProductEvaluationExecutionStoreErrorV1 as Store;

    let category = match error {
        Observer::Owner(Owner::Binding(_)) => "Owner.Binding",
        Observer::Owner(Owner::Pending) => "Owner.Pending",
        Observer::Owner(Owner::CommitUncertain) => "Owner.CommitUncertain",
        Observer::Owner(Owner::File(_)) => "Owner.File",
        Observer::Owner(Owner::Store(Store::Missing)) => "Owner.Store.Missing",
        Observer::Owner(Owner::Store(Store::Conflict)) => "Owner.Store.Conflict",
        Observer::Owner(Owner::Store(Store::Rejected)) => "Owner.Store.Rejected",
        Observer::Owner(Owner::Store(Store::Unavailable)) => "Owner.Store.Unavailable",
        Observer::Owner(Owner::Store(Store::Indeterminate)) => "Owner.Store.Indeterminate",
        Observer::Owner(Owner::Store(Store::Corrupt)) => "Owner.Store.Corrupt",
        Observer::Owner(Owner::Witness(_)) => "Owner.Witness",
        Observer::Owner(Owner::Evidence(_)) => "Owner.Evidence",
        Observer::Observation(_) => "Observation",
        Observer::Iteration(_) => "Iteration",
        Observer::Connection(_) => "Connection",
        Observer::Evidence(_) => "Evidence",
        Observer::PublishedRead(_) => "PublishedRead",
        Observer::CandidatePublishedRead(_) => "CandidatePublishedRead",
    };
    eprintln!("HEPTA_C_OBSERVER phase={phase} owner={category}");
}
