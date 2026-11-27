#![cfg(target_os = "linux")]

use codex_arg0::Arg0DispatchPaths;
use codex_hepta_agentd::AgentdRootAuthorityPeer;
use codex_hepta_agentd::AgentdRootResidentLearningClientV3 as Resident;
use codex_hepta_agentd::LearningIterationRuntimeErrorV1 as ResidentError;
use codex_hepta_agentd::OriginalCellQ24NoUpdateTaskStreamV1 as TaskStream;
use codex_hepta_agentd::OriginalCircuitModelSelectionCommandReceiptV1 as Selection;
use codex_hepta_agentd::OriginalCircuitModelVersionErrorV1 as ModelError;
use codex_hepta_agentd::OriginalCircuitModelVersionHostV1 as ModelHost;
use codex_hepta_agentd::OriginalCircuitRetainedVersionErrorV1 as RetainedError;
use codex_hepta_agentd::OriginalCircuitRetainedVersionHostV1 as RetainedHost;
use codex_hepta_agentd::RootResidentLearningConnectionV3 as Connection;
use codex_hepta_agentd::RootResidentLearningProfileV3 as Profile;
use codex_hepta_agentd::RootResidentLearningReadbackAuthorizationV3 as Authorization;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1 as Snapshot;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1 as Verifier;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1 as SignedEvidence;
use std::future::Future;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

type PositionalRecovery<Pin> = fn(
    UnixStream,
    AgentdRootAuthorityPeer,
    OwnedFd,
    Profile,
    Authorization,
    Verifier,
    Pin,
    Duration,
    Duration,
) -> Result<Resident, ResidentError>;
type ConnectionRecovery<Pin> = fn(
    Connection,
    Profile,
    Authorization,
    Verifier,
    Pin,
    Duration,
    Duration,
) -> Result<Resident, ResidentError>;

fn check_recovery<Pin>(_: PositionalRecovery<Pin>, _: ConnectionRecovery<Pin>) {}

#[test]
fn original_and_grouped_resident_recovery_preserve_both_pin_types() {
    check_recovery::<Option<(Snapshot, Vec<SignedEvidence>)>>(
        Resident::recover_original_root_stream,
        Resident::recover_original_root_connection,
    );
    check_recovery::<(Snapshot, Vec<SignedEvidence>, Vec<u8>)>(
        Resident::recover_original_model_root_stream,
        Resident::recover_original_model_root_connection,
    );
}

type PositionalOrdinary<Host, Fut> = fn(
    Arc<Host>,
    UnixStream,
    AgentdRootAuthorityPeer,
    u32,
    OwnedFd,
    Duration,
    Duration,
    Arg0DispatchPaths,
) -> Fut;
type TaskOrdinary<Host, Fut> = fn(Arc<Host>, TaskStream, Arg0DispatchPaths) -> Fut;

fn check_ordinary<Host, Error, First, Second>(
    _: PositionalOrdinary<Host, First>,
    _: TaskOrdinary<Host, Second>,
) where
    First: Future<Output = Result<u64, Error>>,
    Second: Future<Output = Result<u64, Error>>,
{
}

#[test]
fn original_and_grouped_ordinary_services_preserve_host_and_error_types() {
    check_ordinary::<RetainedHost, RetainedError, _, _>(
        RetainedHost::serve_original_ordinary,
        RetainedHost::serve_original_ordinary_task_stream,
    );
    check_ordinary::<ModelHost, ModelError, _, _>(
        ModelHost::serve_original_ordinary,
        ModelHost::serve_original_ordinary_task_stream,
    );
}

type PositionalRead<OutputFuture> = fn(
    Arc<ModelHost>,
    Selection,
    UnixStream,
    AgentdRootAuthorityPeer,
    u32,
    OwnedFd,
    Duration,
    Duration,
) -> OutputFuture;
type TaskRead<OutputFuture> = fn(Arc<ModelHost>, Selection, TaskStream) -> OutputFuture;

fn check_selection<First, Second>(_: PositionalRead<First>, _: TaskRead<Second>)
where
    First: Future<Output = Result<u64, ModelError>>,
    Second: Future<Output = Result<u64, ModelError>>,
{
}

#[test]
fn original_and_grouped_selection_services_preserve_the_real_receipt() {
    check_selection(
        ModelHost::serve_original_next_use_readback,
        ModelHost::serve_original_next_use_readback_task_stream,
    );
    check_selection(
        ModelHost::serve_original_completion_readiness,
        ModelHost::serve_original_completion_readiness_task_stream,
    );
}
