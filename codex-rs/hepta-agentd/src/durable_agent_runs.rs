//! Product persistence around the existing Agentd run reducer. No effect is
//! retried by replay and no independent execution authority is minted here.
use std::collections::BTreeMap;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use super::*;

#[path = "durable_agent_run_file.rs"]
mod file;

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Image {
    schema_version: u32,
    revision: u64,
    #[serde(with = "state_image")]
    state: AgentRunCoordinator,
    retired: BTreeMap<String, RunRecord>,
}

pub(crate) struct DurableAgentRunCoordinator {
    image: Image,
    file: file::RunFile,
}

impl DurableAgentRunCoordinator {
    pub fn open(composition: RuntimeComposition, path: PathBuf) -> Result<Self, AgentRunError> {
        let state = AgentRunCoordinator::compose_runtime(composition.clone())?;
        let (mut file, bytes) = file::RunFile::open(path)?;
        let image = match bytes {
            Some(bytes) => {
                let image = serde_json::from_slice::<Image>(&bytes)
                    .map_err(|e| failure(format!("decode run store: {e}")))?;
                if image.revision == 0 {
                    return Err(failure("persisted run store revision is zero"));
                }
                image
            }
            None => Image {
                schema_version: 1,
                revision: 0,
                state,
                retired: BTreeMap::new(),
            },
        };
        validate(&image, &composition)?;
        let mut candidate = image.clone();
        candidate
            .state
            .mark_unresolved_indeterminate("process_reopened")?;
        // Any reopen consumes the old live dispatch capability, including a
        // crash after durable dispatch but before its acknowledgement.
        if candidate != image || candidate.revision == 0 {
            candidate.revision = image
                .revision
                .checked_add(1)
                .ok_or(AgentRunError::ArithmeticOverflow)?;
            file.persist(&serde_json::to_vec(&candidate).map_err(|e| failure(e.to_string()))?)?;
        }
        Ok(Self {
            image: candidate,
            file,
        })
    }

    fn mutate<T>(
        &mut self,
        f: impl FnOnce(&mut Image) -> Result<T, AgentRunError>,
    ) -> Result<T, AgentRunError> {
        self.file.verify()?;
        let mut candidate = self.image.clone();
        let result = f(&mut candidate)?;
        validate(&candidate, self.image.state.composition())?;
        if candidate != self.image {
            candidate.revision = self
                .image
                .revision
                .checked_add(1)
                .ok_or(AgentRunError::ArithmeticOverflow)?;
            self.file
                .persist(&serde_json::to_vec(&candidate).map_err(|e| failure(e.to_string()))?)?;
            self.image = candidate;
        } else {
            self.file.verify()?;
        }
        Ok(result)
    }

    pub fn verify(&mut self) -> Result<(), AgentRunError> {
        self.file.verify()
    }
    pub fn composition(&self) -> &RuntimeComposition {
        self.image.state.composition()
    }
    pub fn active_run_count(&self) -> usize {
        self.image.state.active_run_count()
    }
    pub fn unresolved_run_count(&self) -> usize {
        self.image.state.unresolved_run_count()
    }
    pub fn close_admissions(&mut self) -> Result<(), AgentRunError> {
        self.mutate(|image| {
            image.state.close_admissions();
            Ok(())
        })
    }
    pub fn start_run(
        &mut self,
        now_ms: u64,
        snapshot: RunSnapshot,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mutate(|image| {
            if let Some(old) = image.retired.get(&snapshot.run_id) {
                return if old.snapshot == snapshot {
                    Ok(receipt(old, true))
                } else {
                    Err(AgentRunError::Conflict)
                };
            }
            if !image.state.runs.contains_key(&snapshot.run_id)
                && image.state.runs.len() + image.retired.len() >= MAX_RETAINED_RUNS
            {
                return Err(AgentRunError::CapacityExceeded);
            }
            image.state.start_run(now_ms, snapshot)
        })
    }
    pub fn start_revalidated_run_start(
        &mut self,
        now_ms: u64,
        record: &RunStartRecordV1,
    ) -> Result<RunReceipt, AgentRunError> {
        // Reuse the existing canonical projection/validation, then route its
        // exact snapshot through this owner's retained identity check.
        let mut projection = AgentRunCoordinator::compose_runtime(self.composition().clone())?;
        projection.start_revalidated_run_start(now_ms, record)?;
        let snapshot = projection
            .runs
            .into_values()
            .next()
            .ok_or(AgentRunError::RunNotFound)?
            .snapshot;
        self.start_run(now_ms, snapshot)
    }
    pub fn attach_context(
        &mut self,
        now_ms: u64,
        revision: u64,
        attachment: ContextAttachment,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mutate(|image| image.state.attach_context(now_ms, revision, attachment))
    }
    pub fn mark_dispatched(
        &mut self,
        now_ms: u64,
        run_id: &str,
        revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mutate(|image| image.state.mark_dispatched(now_ms, run_id, revision))
    }
    pub fn cancel_run(
        &mut self,
        now_ms: u64,
        run_id: &str,
        revision: u64,
        reason: &str,
    ) -> Result<(CancellationDisposition, RunReceipt), AgentRunError> {
        self.mutate(|image| image.state.cancel_run(now_ms, run_id, revision, reason))
    }
    pub fn observe_terminal(
        &mut self,
        run_id: &str,
        revision: u64,
        phase: RunPhase,
        terminal_observed: bool,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mutate(|image| {
            image
                .state
                .observe_terminal(run_id, revision, phase, terminal_observed)
        })
    }
    pub fn expire_deadlines(&mut self, now_ms: u64) -> Result<usize, AgentRunError> {
        self.mutate(|image| image.state.expire_deadlines(now_ms))
    }
    pub fn begin_drain(&mut self, now_ms: u64, reason: &str) -> Result<usize, AgentRunError> {
        self.mutate(|image| image.state.begin_drain(now_ms, reason))
    }
    pub fn mark_unresolved_indeterminate(&mut self, reason: &str) -> Result<usize, AgentRunError> {
        self.mutate(|image| image.state.mark_unresolved_indeterminate(reason))
    }
    pub fn remove_closed_run(
        &mut self,
        run_id: &str,
        revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mutate(|image| {
            if let Some(old) = image.retired.get(run_id) {
                require_revision(old, revision)?;
                return Ok(receipt(old, true));
            }
            let old = image
                .state
                .runs
                .get(run_id)
                .cloned()
                .ok_or(AgentRunError::RunNotFound)?;
            let result = image.state.remove_closed_run(run_id, revision)?;
            image.retired.insert(run_id.to_owned(), old);
            Ok(result)
        })
    }
    pub fn run(&mut self, run_id: &str) -> Result<Option<RunReceipt>, AgentRunError> {
        self.file.verify()?;
        // Released records remain private deduplication tombstones, preserving
        // the public RunStatus(None) contract after successful release.
        Ok(self.image.state.run(run_id))
    }
}

fn failure(message: impl Into<String>) -> AgentRunError {
    AgentRunError::Persistence(message.into())
}

fn validate(image: &Image, composition: &RuntimeComposition) -> Result<(), AgentRunError> {
    if image.schema_version != 1
        || image.state.composition() != composition
        || image.state.max_active_runs != composition.max_active_runs
        || image.state.runs.len() + image.retired.len() > MAX_RETAINED_RUNS
        || image.state.active_run_count() > composition.max_active_runs
    {
        return Err(failure(
            "run store schema, composition or capacity mismatch; independent restart/reconciliation required",
        ));
    }
    for (key, record) in image.state.runs.iter().chain(image.retired.iter()) {
        validate_snapshot_fields(&record.snapshot)?;
        if key != &record.snapshot.run_id
            || record.revision == 0
            || Some(record.snapshot.generation) != composition.supervisor_generation.checked_add(1)
        {
            return Err(failure("invalid durable run identity/revision/generation"));
        }
        match (&record.context_digest, &record.compilation_receipt_digest) {
            (Some(context), Some(compilation)) => {
                validate_digest(context, "context")?;
                validate_digest(compilation, "compilation")?;
            }
            (None, None) if matches!(record.phase, RunPhase::Admitted | RunPhase::Cancelled) => {}
            _ => return Err(failure("durable run context binding mismatch")),
        }
        if record.phase == RunPhase::Admitted && record.context_digest.is_some() {
            return Err(failure("admitted run contains context"));
        }
        if let Some(reason) = record.cancel_reason.as_deref() {
            validate_cancel_reason(reason)?;
        }
        if (record.phase == RunPhase::Cancelling) != record.cancel_ack_deadline_ms.is_some()
            || (record.phase == RunPhase::Cancelling && record.cancel_reason.is_none())
        {
            return Err(failure("durable cancellation state mismatch"));
        }
    }
    for (key, record) in &image.retired {
        if image.state.runs.contains_key(key) || !record.phase.closed() {
            return Err(failure("retired run is active or duplicated"));
        }
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "durable_agent_runs_tests.rs"]
mod tests;

// Keep unchecked deserialization private; the public reducer cannot be built
// by bypassing compose_runtime through a newly exposed serde implementation.
mod state_image {
    use super::*;
    #[derive(Deserialize, Serialize)]
    #[serde(deny_unknown_fields)]
    struct State {
        composition: RuntimeComposition,
        runs: BTreeMap<String, RunRecord>,
        accepting_runs: bool,
        max_active_runs: usize,
    }
    pub fn serialize<S: serde::Serializer>(
        value: &AgentRunCoordinator,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        State {
            composition: value.composition.clone(),
            runs: value.runs.clone(),
            accepting_runs: value.accepting_runs,
            max_active_runs: value.max_active_runs,
        }
        .serialize(serializer)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<AgentRunCoordinator, D::Error> {
        let state = State::deserialize(deserializer)?;
        Ok(AgentRunCoordinator {
            composition: state.composition,
            runs: state.runs,
            accepting_runs: state.accepting_runs,
            max_active_runs: state.max_active_runs,
        })
    }
}

impl super::bridge_admission::sealed::Sealed for DurableAgentRunCoordinator {}
impl super::bridge_admission::RunBridgeRetainedOwner for DurableAgentRunCoordinator {
    fn bridge_snapshot(
        &mut self,
        run_id: &str,
    ) -> Result<super::bridge_admission::RunBridgeRetainedView, AgentRunError> {
        self.file.verify()?;
        let record = self
            .image
            .state
            .runs
            .get(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        Ok(super::bridge_admission::RunBridgeRetainedView::new(
            &self.image.state,
            record,
        ))
    }
}
