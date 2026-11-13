//! Private Source operations for the two fixed task lanes. The daemon encodes
//! completion only while holding its original receipt. The Root accepts it
//! only through that live loan and its same actual Source and Cell readback.

use super::*;
use crate::circuit_task::remote::OriginalRemoteCompletion;

pub(crate) fn original_binding(
    identity: &AgentdIdentity,
    fence: &TaskFlowFence,
    registry: &CircuitCellRegistryV1,
    source: &CircuitTaskSourceInputV1,
) -> Result<Digest32, Error> {
    let (_, binding) = codec::configuration(identity, fence, registry, vec![source.clone()])?;
    Ok(binding)
}

/// This is a data projection, not a Source or RunStart owner. Only the daemon's
/// existing signed-ingress loan may use it to contact the original Root Source.
pub(crate) fn expected_request(
    source: &CircuitTaskSourceInputV1,
    generation: u64,
    record: &RunStartRecordV1,
) -> Result<CircuitTaskRequestV1, Error> {
    if source.scope.run_id != record.snapshot.run_id { return Err(Error::InvalidBinding); }
    let created_at_ms = record.admission.observed_at_unix_micros / 1_000;
    let deadline_ms = (record.admission.deadline_unix_micros / 1_000)
        .min(record.authentication.expires_at_ms);
    let request = CircuitTaskRequestV1 {
        start: CircuitStartV2 {
            run_id: record.snapshot.run_id.to_string(),
            scope_digest: circuit_cell_scope_digest_v1(&source.scope)?,
            input_digest: Sha256Digest::for_bytes(&source.observation),
            created_at_ms, lease_duration_ms: source.lease_duration_ms,
        }, objective_digest: source.objective_digest, deadline_ms,
    };
    request.validate_record(record, generation)?;
    if source.deadline_micros.checked_sub(source.monotonic_micros)
        .is_none_or(|duration| duration > deadline_ms.saturating_sub(created_at_ms).saturating_mul(1_000))
    { return Err(Error::InvalidBinding); }
    Ok(request)
}

pub(crate) fn encode_record(
    request: &CircuitTaskRequestV1, record: &RunStartRecordV1,
) -> Result<Vec<u8>, Error> { codec::request(request, record) }

pub(crate) fn decode_record(bytes: &[u8]) -> Result<RunStartRecordV1, Error> {
    codec::original_record(bytes)
}

pub(crate) fn decode_original_input(bytes: &[u8]) -> Result<CellStepInputV1, Error> {
    codec::decode_input(bytes)
}

pub(crate) fn encode_original_input(
    dispatch: &CircuitDispatchV2, input: &CellStepInputV1,
) -> Result<Vec<u8>, Error> { codec::dispatch_input(dispatch, input) }

/// The argument is the actual daemon receipt returned by the unchanged driver.
/// No wire decoder calls this function or constructs its receipt argument.
pub(crate) fn original_completion_bytes(
    definition: &BoundedCircuitDefinitionV2,
    request: &CircuitTaskRequestV1,
    saved_input: &[u8],
    receipt: &CircuitTaskReceiptV1,
) -> Result<Vec<u8>, Error> {
    let input = codec::decode_input(saved_input)?;
    codec::result(definition, request, saved_input, &input, receipt)
}

impl<W: AnchorWitnessStore + Send> DurableCircuitTaskSourceV1<W> {
    pub(crate) fn original_remote_binding(&self) -> Result<Digest32, Error> {
        let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
        owner.require_current()?;
        Ok(owner.binding)
    }

    pub(crate) fn require_original_remote_binding(&self, binding: Digest32) -> Result<(), Error> {
        let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
        owner.require_current()?;
        if owner.binding != binding { return Err(Error::InvalidBinding); }
        owner.require_current()
    }

    pub(crate) fn original_remote_request(
        &self, identity: &AgentdIdentity, encoded_record: &[u8],
    ) -> Result<CircuitTaskRequestV1, Error> {
        let record = codec::original_record(encoded_record)?;
        let request = {
            let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
            let request = owner.request(identity, &record)?;
            if codec::request(&request, &record)? != encoded_record {
                return Err(Error::InvalidBinding);
            }
            request
        };
        let actual = AgentdCircuitTaskInvocationProviderV1::build(self, identity, &record)
            .map_err(|_| Error::CommitUncertain)?;
        if actual != request { return Err(Error::InvalidBinding); }
        Ok(actual)
    }

    pub(crate) fn original_remote_saved_input(
        &self, identity: &AgentdIdentity, encoded_record: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let record = codec::original_record(encoded_record)?;
        let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
        let request = owner.request(identity, &record)?;
        if codec::request(&request, &record)? != encoded_record {
            return Err(Error::InvalidBinding);
        }
        owner.require_bytes("request", &request.start.run_id, encoded_record)?;
        let bytes = owner.read("input", &request.start.run_id)?;
        let input = codec::decode_input(&bytes)?;
        let source = owner.sources.get(&request.start.run_id).ok_or(Error::InvalidBinding)?;
        if input != source.input(input.operation_id.clone()) { return Err(Error::InvalidBinding); }
        owner.require_active(&request.start.run_id)?;
        Ok(bytes)
    }

    pub(crate) fn original_remote_resolve(
        &self, identity: &AgentdIdentity, encoded_record: &[u8],
        dispatch: &CircuitDispatchV2, mode: CircuitTaskInputModeV1,
    ) -> Result<Vec<u8>, Error> {
        let record = codec::original_record(encoded_record)?;
        let request = {
            let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
            let request = owner.request(identity, &record)?;
            if codec::request(&request, &record)? != encoded_record { return Err(Error::InvalidBinding); }
            owner.require_bytes("request", &request.start.run_id, encoded_record)?;
            request
        };
        let mut original = self.clone();
        let input = CircuitTaskInputProviderV1::resolve(&mut original, &request, dispatch,
            &BTreeMap::new(), mode)?;
        codec::dispatch_input(dispatch, &input)
    }

    /// No raw-result overload exists. This token can only be returned by the
    /// reverse lane reading the daemon's retained, actual private receipt. A
    /// local Cell decision alone and a completion ACK alone are insufficient.
    pub(crate) fn publish_original_remote_completion(
        &self,
        identity: &AgentdIdentity,
        encoded_record: &[u8],
        completion: OriginalRemoteCompletion,
        execution: &CircuitCellExecutionV1,
    ) -> Result<(), Error> {
        let record = codec::original_record(encoded_record)?;
        let mut owner = self.0.lock().map_err(|_| Error::Unavailable)?;
        let request = owner.request(identity, &record)?;
        if codec::request(&request, &record)? != encoded_record {
            return Err(Error::InvalidBinding);
        }
        owner.require_bytes("request", &request.start.run_id, encoded_record)?;
        let saved = owner.read("input", &request.start.run_id)?;
        let payload = completion.into_original_payload(owner.binding, encoded_record, &saved)?;
        let input = codec::decode_input(&saved)?;
        let source = owner.sources.get(&request.start.run_id).ok_or(Error::InvalidBinding)?;
        if input != source.input(input.operation_id.clone()) { return Err(Error::InvalidBinding); }
        codec::require_decision(&payload, &execution.decision)?;
        let (_, output) = codec::publication(&payload, &saved)?;
        if output != execution.output { return Err(Error::InvalidBinding); }
        owner.require_active(&request.start.run_id)?;
        owner.retain("result", &request.start.run_id, &payload, CircuitTaskInputModeV1::Prepare)?;
        owner.require_active(&request.start.run_id)
    }
}
