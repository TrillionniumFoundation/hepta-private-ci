//! The Root process pumps its original Cell and Source. It never opens the
//! daemon AutomationStore or reconstructs its admissions, traces or receipts.

use std::sync::Arc;
use std::time::Instant;

use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_neuron::AnchorWitnessStore;

use super::Error;
use super::admission::ReverseClient;
use super::data;
use super::wire::{Budget, Frame, Lane, LanePurpose, Operation};
use crate::{AgentdIdentity, CircuitTaskInputModeV1, CircuitTaskSourceReadbackV1,
    DurableCircuitTaskSourceV1, PreparedRootHostCircuitTaskV1};
use crate::circuit_task::root_lane::OriginalRootCellPump;
use crate::circuit_task::source::remote_source;

pub(crate) struct OriginalRootTaskStreams {
    task: HostAuthorityPeerChannel,
    reverse: HostAuthorityPeerChannel,
    nonce: [u8; 16],
    end: Instant,
}

impl OriginalRootTaskStreams {
    pub(crate) fn new(task: HostAuthorityPeerChannel, reverse: HostAuthorityPeerChannel,
        nonce: [u8; 16], end: Instant) -> Self
    { Self { task, reverse, nonce, end } }
}

/// The Q24 factory alone fills these private fields from its same bootstrap,
/// invocation and readback. Consuming it cannot install a replacement writer.
pub(crate) struct OriginalRootTaskLane<SW: AnchorWitnessStore> {
    pump: Box<dyn OriginalRootCellPump>,
    source: Arc<DurableCircuitTaskSourceV1<SW>>,
    readback: Arc<CircuitTaskSourceReadbackV1<SW>>,
}

impl<SW: AnchorWitnessStore> OriginalRootTaskLane<SW> {
    pub(crate) fn from_original_factory(pump: Box<dyn OriginalRootCellPump>,
        source: Arc<DurableCircuitTaskSourceV1<SW>>, readback: Arc<CircuitTaskSourceReadbackV1<SW>>)
        -> Self
    { Self { pump, source, readback } }
}

struct OriginalRecord {
    id: u64,
    encoded: Vec<u8>,
    dispatch: Option<CircuitDispatchV2>,
}

pub(crate) fn serve<SW, CW>(
    root: &PreparedRootHostCircuitTaskV1<SW, CW>,
    identity: &AgentdIdentity,
    mut original: OriginalRootTaskLane<SW>,
    streams: OriginalRootTaskStreams,
) -> Result<u64, Error>
where
    SW: AnchorWitnessStore + Send + 'static,
    CW: AnchorWitnessStore + Send + 'static,
{
    root.require_original_root_task_source(&original.readback).map_err(|_| Error::Unavailable)?;
    require_root_current(root)?;
    let binding = original.source.original_remote_binding()?;
    let budget = Budget::new(streams.end)?;
    let mut task = Lane::new(streams.task, binding, streams.nonce, LanePurpose::Task, Arc::clone(&budget))?;
    let reverse = ReverseClient::new(Lane::new(streams.reverse, binding, streams.nonce, LanePurpose::Loan, budget)?, binding);
    let mut retained: Option<OriginalRecord> = None;
    let mut count = 0_u64;
    while task.serve_one(|frame| {
        require_root_current(root)?;
        original.source.require_original_remote_binding(binding)?;
        let publication = frame.operation == Operation::Publish;
        let response = handle(identity, &mut original, &reverse, &mut retained, frame)?;
        original.source.require_original_remote_binding(binding)?;
        require_root_current(root)?;
        if publication {
            root.observe_original_root_source_publication().map_err(|_| Error::Unavailable)?;
        }
        Ok(response)
    })? {
        count = count.checked_add(1).ok_or(Error::Unavailable)?;
    }
    require_root_current(root)?;
    Ok(count)
}

fn handle<SW: AnchorWitnessStore + Send>(identity: &AgentdIdentity,
    original: &mut OriginalRootTaskLane<SW>, reverse: &ReverseClient,
    retained: &mut Option<OriginalRecord>, frame: Frame) -> Result<Vec<u8>, Error>
{
    if frame.operation == Operation::Build {
        reverse.check_record(frame.loan, &frame.body)?;
        if retained.as_ref().is_some_and(|record| record.encoded != frame.body) {
            return Err(Error::InvalidBinding);
        }
        original.source.original_remote_request(identity, &frame.body)?;
        reverse.check_record(frame.loan, &frame.body)?;
        *retained = Some(OriginalRecord { id: frame.loan, encoded: frame.body.clone(), dispatch: None });
        return Ok(frame.body);
    }
    let record = retained.as_mut().ok_or(Error::ReconciliationRequired)?;
    reverse.check_record(record.id, &record.encoded)?;
    let response = match frame.operation {
        Operation::Clock if frame.loan == record.id && frame.body.is_empty() => {
            let clock = original.pump.clock();
            if clock.circuit_millis == u64::MAX || clock.cell_micros == u64::MAX {
                return Err(Error::ReconciliationRequired);
            }
            let mut bytes = clock.circuit_millis.to_be_bytes().to_vec();
            bytes.extend_from_slice(&clock.cell_micros.to_be_bytes());
            bytes
        }
        Operation::Resolve if frame.loan == record.id => {
            let (mode, bytes) = frame.body.split_first().ok_or(Error::InvalidBinding)?;
            let mode = match mode { 0 => CircuitTaskInputModeV1::Prepare,
                1 => CircuitTaskInputModeV1::Readback, _ => return Err(Error::InvalidBinding) };
            let dispatch = data::dispatch(bytes)?;
            let saved = original.source.original_remote_resolve(identity, &record.encoded, &dispatch, mode)?;
            record.dispatch = Some(dispatch);
            saved
        }
        Operation::Execute if frame.body == record.id.to_be_bytes() => {
            let saved = original.source.original_remote_saved_input(identity, &record.encoded)?;
            let input = remote_source::decode_original_input(&saved)?;
            let admission = reverse.open_admission(frame.loan, record.id, &record.encoded)?;
            let result = (|| {
                if record.dispatch.as_ref() != Some(admission.dispatch())
                    || remote_source::encode_original_input(admission.dispatch(), &input)? != saved
                { return Err(Error::InvalidBinding); }
                original.pump.execute(admission, input)
            })();
            // The actual synchronous operation has returned. Terminal reporting
            // is attempted even on failure, before any response can be sent.
            let terminal = reverse.terminal(frame.loan, record.id);
            let execution = result?;
            terminal?;
            data::encode_decision(&execution.decision)?
        }
        Operation::Decision if frame.loan == record.id => {
            let dispatch = data::dispatch(&frame.body)?;
            let saved = original.source.original_remote_saved_input(identity, &record.encoded)?;
            let input = remote_source::decode_original_input(&saved)?;
            if record.dispatch.as_ref() != Some(&dispatch)
                || remote_source::encode_original_input(&dispatch, &input)? != saved
            { return Err(Error::InvalidBinding); }
            data::encode_decision(&original.pump.read(&dispatch, &input)?.decision)?
        }
        Operation::SavedInput if frame.loan == record.id && frame.body.is_empty() => {
            original.source.original_remote_saved_input(identity, &record.encoded)?
        }
        Operation::Publish if frame.body == record.id.to_be_bytes() => {
            let dispatch = record.dispatch.as_ref().ok_or(Error::ReconciliationRequired)?;
            let saved = original.source.original_remote_saved_input(identity, &record.encoded)?;
            let input = remote_source::decode_original_input(&saved)?;
            if remote_source::encode_original_input(dispatch, &input)? != saved {
                return Err(Error::InvalidBinding);
            }
            let execution = original.pump.read(dispatch, &input)?;
            let completion = reverse.completion(frame.loan, record.id, &record.encoded, &saved)?;
            original.source.publish_original_remote_completion(identity, &record.encoded, completion, &execution)?;
            let again = original.pump.read(dispatch, &input)?;
            if execution != again { return Err(Error::InvalidBinding); }
            let record_data = remote_source::decode_record(&record.encoded)?;
            let publication = original.source.read_publication(identity, &record_data)?;
            publication.require_decision(&again.decision)?;
            b"HCRTPUB1".to_vec()
        }
        _ => return Err(Error::InvalidBinding),
    };
    reverse.check_record(record.id, &record.encoded)?;
    Ok(response)
}

fn require_root_current<SW, CW>(root: &PreparedRootHostCircuitTaskV1<SW, CW>) -> Result<(), Error>
where SW: AnchorWitnessStore + Send + 'static, CW: AnchorWitnessStore + Send + 'static,
{
    if !matches!(root.read_original_root_task_generation().map_err(|_| Error::Unavailable)?,
        crate::neuron_generation_current::NeuronGenerationInitialReadbackV1::Published(_))
    { return Err(Error::Unavailable); }
    Ok(())
}
