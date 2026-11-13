//! Load one actual Q24 task from protected records and existing descriptors.
//! Original factories perform all publication, owner and model verification.

use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_neuron::DurableInferenceControl;
use codex_hepta_neuron::FileAnchorWitnessStore;

use super::HostAuthorityService;
use super::invalid;
use crate::AgentdError;
use crate::CircuitCellTimeV1;
use crate::CircuitQ24TaskFilesV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalRootCircuitTaskInputsV1;
use crate::authority_host_config::read_root_json;

#[path = "authority_host_generation_task_model_types.rs"]
mod model_types;
#[path = "authority_host_generation_task_input_types.rs"]
mod types;
#[path = "authority_host_generation_task_input_files.rs"]
mod files;
#[path = "authority_host_generation_task_clock.rs"]
mod clock;

pub use types::RootHostQ24TaskFilesV1;
pub(crate) use types::TaskFilePurpose;
pub(crate) use clock::OriginalTaskClockStatus;

pub(crate) struct LoadedOriginalTaskInputs {
    pub(crate) inputs: OriginalRootCircuitTaskInputsV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    pub(crate) clock_status: OriginalTaskClockStatus,
}

impl HostAuthorityService {
    pub(crate) fn load_original_root_q24_task_inputs(
        &self,
        deployment: &Path,
        original_files: RootHostQ24TaskFilesV1,
        purpose: TaskFilePurpose,
        end: Instant,
    ) -> Result<LoadedOriginalTaskInputs, AgentdError> {
        require_before(end)?;
        let value: types::Deployment = read_root_json(deployment)?;
        if value.schema_version != 1
            || value.purpose != "hepta.root.original-q24-task.existing-inputs.v1"
            || value.source_mode != purpose
            || value.clock_epoch != "root_protected_unix_ms_and_micros.v1"
        {
            return Err(invalid("task deployment purpose, lifecycle or protected clock epoch differs"));
        }
        files::require_descriptors(&original_files, purpose)?;
        let definition = value.definition.into_original()?;
        let source = value.source.into_original()?;
        let bundle = value.bundle.into_original()?;
        let fence = value.fence.into_original()?;
        let routes = value.routes.into_iter().map(types::Route::into_original)
            .collect::<Result<Vec<_>, _>>()?;
        let now = self.clock.now_unix_ms().map_err(invalid)?;
        let micros = now.checked_mul(1000)
            .ok_or_else(|| invalid("the actual protected clock is outside the Cell epoch"))?;
        if source.monotonic_micros > micros || source.deadline_micros <= source.monotonic_micros
            || (purpose == TaskFilePurpose::Create && micros >= source.deadline_micros)
            || definition.bundle_digest != bundle.digest().map_err(invalid)?
            || source.scope.cell_id != definition.cell_id
        {
            return Err(invalid("actual task data is outside the original binding or clock window"));
        }
        let RootHostQ24TaskFilesV1 {
            source_journal, source_witness, cell_journal, cell_witness,
            inference_control, model,
        } = original_files;
        let model = Arc::new(LoadedCellQ24ModelV1::open_files(model).map_err(invalid)?);
        if model.components() != &bundle.components {
            return Err(invalid("actual model files differ from the complete original bundle"));
        }
        require_before(end)?;
        // Scope and generation are pre-provisioned Root data, not guessed
        // fixture labels or a manufactured Source publication. The original
        // witness checks its full physical header/history and original owners
        // subsequently bind their journals/CAS to that exact witness.
        let source_witness = FileAnchorWitnessStore::open(
            source_witness, value.source_witness.scope(),
            value.source_witness.generation()?, value.source_witness.max_records,
        ).map_err(invalid)?;
        require_before(end)?;
        let cell_witness = FileAnchorWitnessStore::open(
            cell_witness, value.cell_witness.scope(),
            value.cell_witness.generation()?, value.cell_witness.max_records,
        ).map_err(invalid)?;
        require_before(end)?;
        // The original Linux API operates exclusively on this consumed file.
        // Its diagnostic path is never opened and cannot select another store.
        let inference_control = DurableInferenceControl::open_file(
            inference_control, value.inference_control_diagnostic_path,
            value.inference_control_capacity,
        ).map_err(invalid)?;
        let original_clock = Arc::clone(&self.clock);
        let clock_status = OriginalTaskClockStatus::new(end);
        let callback_status = clock_status.clone();
        let clock = Arc::new(move || {
            if callback_status.require_healthy().is_err() {
                return fenced_time();
            }
            let circuit_millis = match original_clock.now_unix_ms() {
                Ok(value) => value,
                Err(error) => {
                    callback_status.record_original_error(error);
                    return fenced_time();
                }
            };
            let Some(cell_micros) = circuit_millis.checked_mul(1000) else {
                callback_status.record_overflow();
                return fenced_time();
            };
            if callback_status.require_healthy().is_err() {
                return fenced_time();
            }
            CircuitCellTimeV1 { circuit_millis, cell_micros }
        });
        self.clock.now_unix_ms().map_err(invalid)?;
        require_before(end)?;
        clock_status.require_healthy()?;
        let inputs = OriginalRootCircuitTaskInputsV1 {
            definition, source,
            files: CircuitQ24TaskFilesV1 {
                source_journal, source_witness, cell_journal, cell_witness, inference_control,
            },
            source_mode: match purpose {
                TaskFilePurpose::Create => CircuitQ24TaskOpenModeV1::Create,
                TaskFilePurpose::Recover => CircuitQ24TaskOpenModeV1::Recover,
            },
            fence, circuit: value.circuit, routes, bundle, model,
            worker_generation: value.worker_generation,
            maximum_cell_records: value.maximum_cell_records,
            queue_capacity: value.queue_capacity,
            clock,
        };
        Ok(LoadedOriginalTaskInputs { inputs, clock_status })
    }
}

fn require_before(end: Instant) -> Result<(), AgentdError> {
    if Instant::now() >= end { return Err(invalid("original task input deadline expired")); }
    Ok(())
}

fn fenced_time() -> CircuitCellTimeV1 {
    // The existing factory clock is infallible. MAX is an invalid-time fence,
    // not a successful sample. This loader requires the separate exact Root
    // remote and feature-control refusal increments; without them MAX could
    // reach recovery/outcome/cost state. No cached time or reset is permitted.
    // First cause is retained by the returned non-Clone task wrapper.
    CircuitCellTimeV1 { circuit_millis: u64::MAX, cell_micros: u64::MAX }
}
