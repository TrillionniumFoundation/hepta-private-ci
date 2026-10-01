//! Root-pinned masked calibration prompts under the installed serial owner.
use super::AgentdError;
use super::AgentdIdentity;
use super::AppServerSelfIterationModelPortV1;
use super::Digest32;
use super::PathBuf;
use super::StableId;
use super::invalid;
use super::parse_digest;
use super::private_parent;
use crate::NativeReferenceObservationV1;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;
#[path = "calibration_reference_storage.rs"]
mod storage;
use storage::SourceOwnership;
use storage::read_regular;
use storage::write_private;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CalibrationReferenceBatchConfigV1 {
    pub batch_path: PathBuf,
    pub batch_digest: String,
    pub receipt_directory: PathBuf,
    pub maximum_rows_per_tick: usize,
}
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Batch {
    schema: String,
    batch_id: String,
    source_archive_digest: String,
    source_pairs_digest: String,
    task_template_digest: String,
    task_sources: Vec<TaskSource>,
    rows: Vec<Row>,
}
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TaskSource {
    claim_id: u64,
    cited_doc_ids: Vec<u64>,
    source_claim_file_digest: String,
    source_claim_row_1based: u64,
}
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Row {
    row_id: String,
    claim_id: u64,
    doc_id: u64,
    source_record_digest: String,
    prompt: String,
    prompt_digest: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RowState {
    schema: String,
    batch_digest: String,
    host_config_digest: String,
    agent_id: String,
    worker_generation: u64,
    row_id: String,
    claim_id: u64,
    doc_id: u64,
    source_record_digest: String,
    prompt_digest: String,
    native_request_id: String,
    original_deadline_ms: u64,
    original_reserved_at_ms: u64,
    original_execution_latency_us: Option<u64>,
    phase: String,
    observation: Option<NativeReferenceObservationV1>,
    first_observation: Option<NativeReferenceObservationV1>,
    diagnostic: Option<String>,
}
pub(super) struct CalibrationReferenceBatch {
    config: CalibrationReferenceBatchConfigV1,
    batch: Batch,
    pin: Digest32,
    host_pin: Digest32,
}
fn validate_batch(batch: &Batch) -> Result<(), AgentdError> {
    if batch.schema != "hepta.masked-calibration-reference-batch.v1"
        || batch.rows.is_empty()
        || batch.rows.len() > 256
    {
        return Err(invalid("calibration reference batch schema or row budget"));
    }
    StableId::new(batch.batch_id.clone()).map_err(|error| invalid(error.to_string()))?;
    for digest in [
        &batch.source_archive_digest,
        &batch.source_pairs_digest,
        &batch.task_template_digest,
    ] {
        parse_digest(digest)?;
    }
    let mut tasks = std::collections::BTreeMap::new();
    if batch.task_sources.is_empty() || batch.task_sources.len() > 256 {
        return Err(invalid("reference source graph bounds"));
    }
    for task in &batch.task_sources {
        parse_digest(&task.source_claim_file_digest)?;
        if task.source_claim_row_1based == 0
            || task.cited_doc_ids.is_empty()
            || task.cited_doc_ids.len() > 256
            || task.cited_doc_ids.windows(2).any(|pair| pair[0] >= pair[1])
            || tasks.insert(task.claim_id, &task.cited_doc_ids).is_some()
        {
            return Err(invalid("reference complete task dependency identity"));
        }
    }
    let mut ids = BTreeSet::new();
    let mut pairs = BTreeSet::new();
    for row in &batch.rows {
        if !ids.insert(&row.row_id)
            || !pairs.insert((row.claim_id, row.doc_id))
            || !tasks
                .get(&row.claim_id)
                .is_some_and(|docs| docs.contains(&row.doc_id))
            || row.prompt.is_empty()
            || row.prompt.len() > 32 * 1024
            || parse_digest(&row.prompt_digest)? != Digest32::of_bytes(row.prompt.as_bytes())
        {
            return Err(invalid("reference row identity, prompt or digest"));
        }
        StableId::new(row.row_id.clone()).map_err(|error| invalid(error.to_string()))?;
        parse_digest(&row.source_record_digest)?;
    }
    Ok(())
}
impl CalibrationReferenceBatch {
    pub(super) fn open(
        config: CalibrationReferenceBatchConfigV1,
        identity: &AgentdIdentity,
        host_pin: Digest32,
    ) -> Result<Self, AgentdError> {
        if !(1..=8).contains(&config.maximum_rows_per_tick)
            || !config.receipt_directory.starts_with(&identity.home_root)
        {
            return Err(invalid("reference serial budget or exact Agent home"));
        }
        private_parent(&config.receipt_directory.join("owner-state"))?;
        let pin = parse_digest(&config.batch_digest)?;
        let bytes = read_regular(
            &config.batch_path,
            8 * 1024 * 1024,
            SourceOwnership::RootProtected,
        )?;
        if Digest32::of_bytes(&bytes) != pin {
            return Err(invalid("Root-pinned calibration batch changed"));
        }
        let batch: Batch =
            serde_json::from_slice(&bytes).map_err(|error| invalid(error.to_string()))?;
        validate_batch(&batch)?;
        Ok(Self {
            config,
            batch,
            pin,
            host_pin,
        })
    }
    fn request_id(&self, row: &Row, agent_id: &str, generation: u64) -> String {
        let digest = Digest32::of_parts(&[
            b"hepta.calibration.reference.native-request.v1",
            self.pin.as_array(),
            self.host_pin.as_array(),
            agent_id.as_bytes(),
            &generation.to_be_bytes(),
            row.row_id.as_bytes(),
        ]);
        format!("reference.{digest}")
    }
    fn state_path(&self, row: &Row, identity: &AgentdIdentity) -> PathBuf {
        // A new spawn or descriptor must find the original row state, rather
        // than hiding Unknown work behind a newly generated filename.
        let key = Digest32::of_parts(&[
            b"hepta.calibration.reference.row-file.v1",
            self.pin.as_array(),
            identity.agent_id.to_string().as_bytes(),
            row.row_id.as_bytes(),
        ]);
        self.config.receipt_directory.join(format!("{key}.json"))
    }
    fn state(
        &self,
        row: &Row,
        identity: &AgentdIdentity,
        timeout_seconds: u64,
    ) -> Result<RowState, AgentdError> {
        let request_id = self.request_id(
            row,
            &identity.agent_id.to_string(),
            identity.spawn_generation,
        );
        let path = self.state_path(row, identity);
        match std::fs::symlink_metadata(&path) {
            Ok(_) => {
                let state: RowState = serde_json::from_slice(&read_regular(
                    &path,
                    8 * 1024 * 1024,
                    SourceOwnership::PrivateOwner,
                )?)
                .map_err(|error| invalid(error.to_string()))?;
                if state.schema != "hepta.calibration.reference.row-state.v1"
                    || state.batch_digest != self.pin.to_string()
                    || state.host_config_digest != self.host_pin.to_string()
                    || state.agent_id != identity.agent_id.to_string()
                    || state.worker_generation == 0
                    || state.row_id != row.row_id
                    || state.claim_id != row.claim_id
                    || state.doc_id != row.doc_id
                    || state.source_record_digest != row.source_record_digest
                    || state.prompt_digest != row.prompt_digest
                    || state.native_request_id
                        != self.request_id(row, &state.agent_id, state.worker_generation)
                    || state.original_reserved_at_ms == 0
                    || state.original_deadline_ms <= state.original_reserved_at_ms
                {
                    return Err(invalid(
                        "reference receipt does not match the pinned row and owner",
                    ));
                }
                validate_state(&state)?;
                Ok(state)
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let now = unix_ms()?;
                Ok(RowState {
                    schema: "hepta.calibration.reference.row-state.v1".into(),
                    batch_digest: self.pin.to_string(),
                    host_config_digest: self.host_pin.to_string(),
                    agent_id: identity.agent_id.to_string(),
                    worker_generation: identity.spawn_generation,
                    row_id: row.row_id.clone(),
                    claim_id: row.claim_id,
                    doc_id: row.doc_id,
                    source_record_digest: row.source_record_digest.clone(),
                    prompt_digest: row.prompt_digest.clone(),
                    native_request_id: request_id,
                    original_deadline_ms: now
                        .checked_add(
                            timeout_seconds
                                .checked_mul(1000)
                                .ok_or_else(|| invalid("reference deadline"))?,
                        )
                        .ok_or_else(|| invalid("reference deadline"))?,
                    original_reserved_at_ms: now,
                    original_execution_latency_us: None,
                    phase: "prepared".into(),
                    observation: None,
                    first_observation: None,
                    diagnostic: None,
                })
            }
            Err(error) => Err(error.into()),
        }
    }
    pub(super) async fn run_step(
        &self,
        model: &mut AppServerSelfIterationModelPortV1,
        identity: &AgentdIdentity,
        timeout_seconds: u64,
        cancellation: &tokio_util::sync::CancellationToken,
        native_admission_blocked: bool,
    ) -> Result<serde_json::Value, AgentdError> {
        let mut attempted = 0;
        for row in &self.batch.rows {
            let mut state = self.state(row, identity, timeout_seconds)?;
            if matches!(
                state.phase.as_str(),
                "completed" | "failed" | "observed_missing_cost"
            ) {
                continue;
            }
            if state.worker_generation != identity.spawn_generation || cancellation.is_cancelled() {
                // Only the original native owner can resolve its dispatched
                // work. A replacement generation never submits a fresh turn.
                break;
            }
            if native_admission_blocked
                && !model
                    .reference_can_reconcile(&state.native_request_id)
                    .map_err(|error| invalid(error.to_string()))?
            {
                break;
            }
            if attempted >= self.config.maximum_rows_per_tick {
                break;
            }
            // Publish the original identity/deadline BEFORE any possible effect.
            write_private(&self.state_path(row, identity), &state)?;
            attempted += 1;
            match model
                .run_reference_prompt(
                    state.native_request_id.clone(),
                    row.prompt.clone(),
                    state.original_deadline_ms,
                )
                .await
            {
                Ok(observation) => {
                    observation
                        .validate()
                        .map_err(|error| invalid(error.to_string()))?;
                    if state.original_execution_latency_us.is_none() {
                        state.original_execution_latency_us =
                            observation.fresh_execution_latency_us;
                    }
                    if state.first_observation.is_none() {
                        state.first_observation = Some(observation.clone());
                    }
                    state.phase = phase(&observation, state.original_execution_latency_us).into();
                    state.diagnostic = observation.diagnostic.clone();
                    state.observation = Some(observation);
                }
                Err(error) => {
                    state.phase = "pending_native_recovery".into();
                    state.diagnostic = Some(error.to_string());
                }
            }
            write_private(&self.state_path(row, identity), &state)?;
            if state.phase == "pending_native_recovery" || cancellation.is_cancelled() {
                break;
            }
        }
        self.status(identity, timeout_seconds)
    }
    fn status(
        &self,
        identity: &AgentdIdentity,
        timeout_seconds: u64,
    ) -> Result<serde_json::Value, AgentdError> {
        let mut completed = 0;
        let mut failed = 0;
        let mut missing_cost = 0;
        let mut pending = 0;
        let mut unresolved_native_operations = 0;
        let mut prior_generation_pending = 0;
        for row in &self.batch.rows {
            let state = self.state(row, identity, timeout_seconds)?;
            match state.phase.as_str() {
                "completed" => completed += 1,
                "failed" => failed += 1,
                "observed_missing_cost" => missing_cost += 1,
                _ => {
                    pending += 1;
                    if state.phase == "pending_native_recovery"
                        || state.worker_generation != identity.spawn_generation
                    {
                        unresolved_native_operations += 1;
                    }
                    if state.worker_generation != identity.spawn_generation {
                        prior_generation_pending += 1;
                    }
                }
            }
        }
        Ok(
            serde_json::json!({"schema":"hepta.calibration.reference.batch-status.v1","batch_id":self.batch.batch_id,"batch_digest":self.pin.to_string(),
            "source_archive_digest":self.batch.source_archive_digest,"source_pairs_digest":self.batch.source_pairs_digest,"task_template_digest":self.batch.task_template_digest,
            "rows":self.batch.rows.len(),"completed":completed,"failed":failed,"missing_original_cost":missing_cost,"pending":pending,"unresolved_native_operations":unresolved_native_operations,"prior_generation_pending":prior_generation_pending,
            "state":if pending>0 {"collecting_native_reference"} else if failed+missing_cost>0 {"reference_observed_with_gaps"} else {"reference_observed"},
            "qualified":false,"holdout_consumed":false,"authority_grants_any":false}),
        )
    }
}
fn validate_state(state: &RowState) -> Result<(), AgentdError> {
    if let Some(first) = &state.first_observation {
        first.validate().map_err(|error| invalid(error.to_string()))?;
        if first.native_request_id != state.native_request_id || first.prompt_digest != state.prompt_digest
            || first.original_deadline_ms != state.original_deadline_ms
            || first.native_record.as_ref().is_some_and(|record| record.request.principal_id != state.agent_id || record.request.worker_generation != state.worker_generation)
            || first.native_record.as_ref().zip(state.observation.as_ref().and_then(|observation| observation.native_record.as_ref())).is_some_and(|(first, latest)| first.request != latest.request || first.dispatch.as_ref().is_some_and(|dispatch| latest.dispatch.as_ref() != Some(dispatch)))
        { return Err(invalid("reference original attempt binding")); }
    }
    match &state.observation {
        Some(observation) => {
            observation
                .validate()
                .map_err(|error| invalid(error.to_string()))?;
            if observation.native_request_id != state.native_request_id
                || observation.prompt_digest != state.prompt_digest
                || observation.original_deadline_ms != state.original_deadline_ms
                || observation.native_record.as_ref().is_some_and(|record| {
                    record.request.principal_id != state.agent_id
                        || record.request.worker_generation != state.worker_generation
                })
                || state.original_execution_latency_us != observation.fresh_execution_latency_us
                || state.phase != phase(observation, state.original_execution_latency_us)
            {
                return Err(invalid("reference native observation or phase binding"));
            }
        }
        None => {
            if !matches!(state.phase.as_str(), "prepared" | "pending_native_recovery")
                || state.original_execution_latency_us.is_some() || state.first_observation.is_some()
            {
                return Err(invalid("reference state has no native evidence"));
            }
        }
    }
    Ok(())
}
fn phase(
    observation: &NativeReferenceObservationV1,
    original_latency: Option<u64>,
) -> &'static str {
    if observation.succeeded {
        if original_latency.is_some()
            && observation
                .native_output
                .as_ref()
                .is_some_and(|o| o.observed_output_tokens.is_some())
        {
            "completed"
        } else {
            "observed_missing_cost"
        }
    } else if observation.native_record.as_ref().is_some_and(|r| {
        r.pre_dispatch_stop.is_some()
            || r.dispatch_rejection.is_some()
            || r.state
                == codex_hepta_infer_core::durable_control::native::NativeReservationState::Released
    }) && observation
        .native_output
        .as_ref()
        .is_none_or(|o| !o.succeeded())
    {
        "failed"
    } else {
        "pending_native_recovery"
    }
}
fn unix_ms() -> Result<u64, AgentdError> {
    u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|error| invalid(error.to_string()))?
            .as_millis(),
    )
    .map_err(|error| invalid(error.to_string()))
}
#[cfg(test)]
#[path = "calibration_reference_batch_tests.rs"]
mod tests;
