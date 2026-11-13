//! Daemon endpoint construction and actual Cell data transport. The original
//! non-Clone admission is retained locally before its fixed Root loan is used.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_automation::CircuitComputationAdmissionV2;
use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellExecutionError;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::Error;
use super::data;
use super::loan::DaemonLoans;
use super::loan::OriginalRecordLoan;
use super::wire::{Budget, Frame, Lane, Operation, FRAME_LIMIT, TIMEOUT};
use crate::{AgentdIdentity, CircuitCellErrorV1, CircuitCellExecutionV1, CircuitCellRegistryV1,
    CircuitCellTimeV1, CircuitTaskRequestV1, CircuitTaskSourceInputV1};
use crate::circuit_task::source::remote_source;

/// Explicit transport and immutable expected data from the original trusted
/// launcher. These data grant nothing: both real streams must match the pinned
/// Root process, and that service must possess the original task/Cell/Source.
pub struct OriginalRootCircuitTaskDaemonInputsV1 {
    pub fence: TaskFlowFence,
    pub registry: CircuitCellRegistryV1,
    pub source: CircuitTaskSourceInputV1,
    pub task_stream: UnixStream,
    pub loan_stream: UnixStream,
    pub original_root: HostIssuerPeer,
    pub original_root_task_pidfd: OwnedFd,
    pub original_root_loan_pidfd: OwnedFd,
    pub session_nonce: [u8; 16],
    pub lifetime: Duration,
    pub queue_capacity: usize,
}

pub(crate) struct DaemonClient {
    pub(super) identity: AgentdIdentity,
    pub(super) fence: TaskFlowFence,
    pub(super) registry: CircuitCellRegistryV1,
    pub(super) source: CircuitTaskSourceInputV1,
    pub(super) task: Mutex<Lane>,
    pub(super) loans: Arc<DaemonLoans>,
    pub(super) resolved: Mutex<Option<ResolvedInput>>,
    reverse: Mutex<Option<Lane>>,
    stop_reverse: UnixStream,
}

pub(super) struct ResolvedInput {
    pub(super) request: CircuitTaskRequestV1,
    pub(super) dispatch: CircuitDispatchV2,
    pub(super) input: CellStepInputV1,
    pub(super) encoded: Vec<u8>,
}

impl DaemonClient {
    pub(crate) fn new(identity: &AgentdIdentity, inputs: OriginalRootCircuitTaskDaemonInputsV1,
        pending: Arc<AtomicUsize>) -> Result<(Arc<Self>, usize), Error>
    {
        if rustix::process::getuid().as_raw() == 0 || rustix::process::geteuid().as_raw() == 0
            || inputs.original_root.uid != 0 || inputs.original_root.pid == std::process::id()
            || inputs.lifetime.is_zero() || inputs.lifetime > Duration::from_secs(300)
            || !(1..=64).contains(&inputs.queue_capacity)
            || inputs.fence.owner_agent_id != identity.agent_id
            || identity.spawn_generation.checked_add(1) != Some(inputs.fence.generation)
        { return Err(Error::InvalidBinding); }
        let binding = remote_source::original_binding(identity, &inputs.fence, &inputs.registry, &inputs.source)?;
        let end = Instant::now() + inputs.lifetime;
        let budget = Budget::new(end)?;
        let policy = HostAuthorityPeerPolicy { peer: inputs.original_root, timeout: TIMEOUT,
            lifetime: inputs.lifetime, request_bound: FRAME_LIMIT, response_bound: FRAME_LIMIT };
        let stop_reverse = inputs.loan_stream.try_clone().map_err(|_| Error::Unavailable)?;
        let task = HostAuthorityPeerChannel::from_stream(inputs.task_stream, policy,
            inputs.original_root_task_pidfd).map_err(|_| Error::Unavailable)?;
        let reverse = HostAuthorityPeerChannel::from_stream(inputs.loan_stream, policy,
            inputs.original_root_loan_pidfd).map_err(|_| Error::Unavailable)?;
        let client = Self { identity: identity.clone(), fence: inputs.fence,
            registry: inputs.registry, source: inputs.source,
            task: Mutex::new(Lane::new(task, binding, inputs.session_nonce, true, Arc::clone(&budget))?),
            reverse: Mutex::new(Some(Lane::new(reverse, binding, inputs.session_nonce, false, budget)?)),
            loans: DaemonLoans::new(pending), resolved: Mutex::new(None), stop_reverse };
        Ok((Arc::new(client), inputs.queue_capacity))
    }

    pub(crate) fn begin_original_record(self: &Arc<Self>, record: &RunStartRecordV1)
        -> Result<OriginalRecordLoan, Error>
    {
        let request = remote_source::expected_request(&self.source, self.fence.generation, record)?;
        self.loans.begin_record(record, remote_source::encode_record(&request, record)?)
    }

    pub(crate) fn run_reverse(self: &Arc<Self>, state: &Arc<crate::AgentdState>,
        cancellation: tokio_util::sync::CancellationToken)
        -> Result<(std::thread::JoinHandle<Result<(), Error>>,
            tokio::sync::oneshot::Receiver<Result<(), Error>>), Error>
    {
        self.loans.attach(state, cancellation)?;
        let mut reverse = self.reverse.try_lock().map_err(|_| Error::Unavailable)?
            .take().ok_or(Error::Unavailable)?;
        let loans = Arc::clone(&self.loans);
        let (terminal, receive) = tokio::sync::oneshot::channel();
        let worker = std::thread::Builder::new().name("original-root-task-loans".into())
            .spawn(move || {
                let result: Result<(), Error> =
                    (|| { while reverse.serve_one(|frame| loans.respond(frame))? {} Ok(()) })();
                let _ = terminal.send(result.clone());
                result
            }).map_err(|_| Error::Unavailable)?;
        Ok((worker, receive))
    }

    pub(crate) fn stop_reverse(&self) {
        // This duplicate descriptor is termination-only. It is never exposed,
        // used to send a frame, reconnected or turned into another channel.
        let _ = self.stop_reverse.shutdown(std::net::Shutdown::Both);
    }

    pub(crate) fn sample_original_clock(&self) -> Result<CircuitCellTimeV1, Error> {
        let (id, _) = self.loans.current_record()?;
        let bytes = self.task.try_lock().map_err(|_| Error::Unavailable)?.call(Frame {
            operation: Operation::Clock, loan: id, body: Vec::new(),
        })?;
        if bytes.len() != 16 { return Err(Error::InvalidBinding); }
        Ok(CircuitCellTimeV1 {
            circuit_millis: u64::from_be_bytes(bytes[..8].try_into().map_err(|_| Error::InvalidBinding)?),
            cell_micros: u64::from_be_bytes(bytes[8..].try_into().map_err(|_| Error::InvalidBinding)?),
        })
    }

    pub(super) fn original_execution(&self, admission: CircuitComputationAdmissionV2,
        input: CellStepInputV1, before: CircuitCellTimeV1) -> Result<CircuitCellExecutionV1, Error>
    {
        if before.circuit_millis == u64::MAX || before.cell_micros == u64::MAX {
            return Err(Error::Unavailable);
        }
        let dispatch = admission.dispatch().clone();
        let (record_id, _) = self.loans.current_record()?;
        {
            let resolved = self.resolved.try_lock().map_err(|_| Error::Unavailable)?;
            let resolved = resolved.as_ref().ok_or(Error::ReconciliationRequired)?;
            if resolved.dispatch != dispatch || resolved.input != input { return Err(Error::InvalidBinding); }
        }
        let binding = self.registry.bind_input(&dispatch, &input)?;
        let digest = canonical_cell_step_request_digest_v1(&binding.cell, &input).map_err(CircuitCellErrorV1::from)?;
        if admission.owner_agent_id().as_str() != input.scope.agent_id.as_str()
            || admission.definition_digest() != self.registry.definition_digest()
            || admission.execution_request_digest().is_none_or(|value| value.as_str() != digest.to_string())
        { return Err(Error::InvalidBinding); }
        let id = self.loans.retain_admission(admission)?;
        let bytes = self.task.try_lock().map_err(|_| Error::Unavailable)?.call(Frame {
            operation: Operation::Execute, loan: id, body: record_id.to_be_bytes().to_vec(),
        })?;
        let decision = data::decision(&bytes)?;
        crate::circuit_cell::finish(binding, &dispatch, &input, decision).map_err(Error::from)
    }

    fn lookup_original(&self, scope: &CellScopeV1, operation: &StableId, digest: Digest32)
        -> Result<CellDecisionReceiptV1, Error>
    {
        let (record_id, _) = self.loans.current_record()?;
        let (dispatch, input) = {
            let resolved = self.resolved.try_lock().map_err(|_| Error::Unavailable)?;
            let value = resolved.as_ref().ok_or(Error::ReconciliationRequired)?;
            if &value.input.scope != scope || &value.input.operation_id != operation {
                return Err(Error::InvalidBinding);
            }
            (value.dispatch.clone(), value.input.clone())
        };
        let binding = self.registry.bind_input(&dispatch, &input)?;
        if canonical_cell_step_request_digest_v1(&binding.cell, &input).map_err(CircuitCellErrorV1::from)? != digest {
            return Err(Error::InvalidBinding);
        }
        let bytes = self.task.try_lock().map_err(|_| Error::Unavailable)?.call(Frame {
            operation: Operation::Decision, loan: record_id, body: data::encode_dispatch(&dispatch)?,
        })?;
        let execution = crate::circuit_cell::finish(binding, &dispatch, &input, data::decision(&bytes)?)?;
        Ok(execution.decision)
    }
}

pub(crate) struct DaemonCellPort(pub(super) Arc<DaemonClient>);

impl DaemonCellPort {
    pub(crate) fn new(client: Arc<DaemonClient>) -> Self { Self(client) }
    pub(crate) fn original_registry(&self) -> &CircuitCellRegistryV1 { &self.0.registry }
    pub(crate) fn original_lookup(&self, scope: &CellScopeV1, operation: &StableId, request: Digest32)
        -> Result<Option<CellDecisionReceiptV1>, CellExecutionError>
    { self.0.lookup_original(scope, operation, request).map(Some).map_err(|_| CellExecutionError::InferencePending) }
    pub(crate) fn original_execute(&self, admission: CircuitComputationAdmissionV2,
        input: CellStepInputV1, before: CircuitCellTimeV1) -> Result<CircuitCellExecutionV1, CircuitCellErrorV1>
    { self.0.original_execution(admission, input, before).map_err(|_| CircuitCellErrorV1::ReconciliationRequired) }
}
