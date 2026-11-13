//! Preserve the original invocation and input-provider interfaces in Agentd.
//! Only the fixed client is installed; its record loan originates in the
//! existing signed RunStart entry, and completion receives its real receipt.

use std::collections::BTreeMap;
use std::sync::Arc;

use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::CellStepInputV1;

use super::Error;
use super::client::DaemonClient;
use super::client::ResolvedInput;
use super::data;
use super::wire::{Frame, Operation};
use crate::{AgentdCircuitTaskInvocationProviderV1, AgentdError, AgentdIdentity,
    CircuitCellExecutionV1, CircuitTaskInputModeV1, CircuitTaskInputProviderV1,
    CircuitTaskReceiptV1, CircuitTaskRequestV1};
use crate::circuit_task::source::remote_source;

impl AgentdCircuitTaskInvocationProviderV1 for DaemonClient {
    fn build(&self, identity: &AgentdIdentity, record: &RunStartRecordV1)
        -> Result<CircuitTaskRequestV1, AgentdError>
    {
        (|| {
            if identity != &self.identity { return Err(Error::InvalidBinding); }
            let (id, encoded) = self.loans.record(record)?;
            let request = remote_source::expected_request(&self.source, self.fence.generation, record)?;
            if remote_source::encode_record(&request, record)? != encoded {
                return Err(Error::InvalidBinding);
            }
            let response = super::wire::Lane::call(&mut *self.task.try_lock().map_err(|_| Error::Unavailable)?, Frame {
                operation: Operation::Build, loan: id, body: encoded.clone(),
            })?;
            if response != encoded { return Err(Error::InvalidBinding); }
            Ok(request)
        })().map_err(agent_error)
    }

    fn publish_result(&self, identity: &AgentdIdentity, record: &RunStartRecordV1,
        receipt: &CircuitTaskReceiptV1) -> Result<(), AgentdError>
    {
        (|| {
            if identity != &self.identity { return Err(Error::InvalidBinding); }
            let (record_id, _) = self.loans.record(record)?;
            let request = remote_source::expected_request(&self.source, self.fence.generation, record)?;
            let saved_input = super::wire::Lane::call(&mut *self.task.try_lock().map_err(|_| Error::Unavailable)?, Frame {
                operation: Operation::SavedInput, loan: record_id, body: Vec::new(),
            })?;
            {
                let resolved = self.resolved.try_lock().map_err(|_| Error::Unavailable)?;
                let resolved = resolved.as_ref().ok_or(Error::ReconciliationRequired)?;
                if resolved.request != request || resolved.encoded != saved_input {
                    return Err(Error::InvalidBinding);
                }
            }
            let id = self.loans.retain_completion(request, self.registry.definition().clone(),
                saved_input, receipt)?;
            let response = super::wire::Lane::call(&mut *self.task.try_lock().map_err(|_| Error::Unavailable)?, Frame {
                operation: Operation::Publish, loan: id, body: record_id.to_be_bytes().to_vec(),
            })?;
            if response != b"HCRTPUB1" { return Err(Error::InvalidBinding); }
            Ok(())
        })().map_err(agent_error)
    }
}

impl CircuitTaskInputProviderV1 for Arc<DaemonClient> {
    fn resolve(&mut self, request: &CircuitTaskRequestV1, dispatch: &CircuitDispatchV2,
        completed: &BTreeMap<u64, CircuitCellExecutionV1>, mode: CircuitTaskInputModeV1)
        -> Result<CellStepInputV1, Error>
    {
        // This is the original one-root-Cell Source restriction, not a second
        // graph driver or a protocol that can supply arbitrary completed steps.
        if !completed.is_empty() { return Err(Error::InvalidBinding); }
        let (id, encoded_record) = super::loan::DaemonLoans::current_record(&self.loans)?;
        let record = remote_source::decode_record(&encoded_record)?;
        if remote_source::expected_request(&self.source, self.fence.generation, &record)? != *request {
            return Err(Error::InvalidBinding);
        }
        let mut bytes = vec![match mode { CircuitTaskInputModeV1::Prepare => 0,
            CircuitTaskInputModeV1::Readback => 1 }];
        bytes.extend_from_slice(&data::encode_dispatch(dispatch)?);
        let encoded = super::wire::Lane::call(&mut *self.task.try_lock().map_err(|_| Error::Unavailable)?, Frame {
            operation: Operation::Resolve, loan: id, body: bytes,
        })?;
        let input = remote_source::decode_original_input(&encoded)?;
        if remote_source::encode_original_input(dispatch, &input)? != encoded {
            return Err(Error::InvalidBinding);
        }
        self.registry.bind_input(dispatch, &input)?;
        *self.resolved.try_lock().map_err(|_| Error::Unavailable)? = Some(ResolvedInput {
            request: request.clone(), dispatch: dispatch.clone(), input: input.clone(), encoded,
        });
        Ok(input)
    }
}

fn agent_error(error: Error) -> AgentdError {
    AgentdError::Protocol(format!("original Root task: {error}"))
}
