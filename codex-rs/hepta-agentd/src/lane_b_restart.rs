//! Same native store, full predecessor validation and original revision CAS.
use super::*;
use crate::config::VerifiedRunStoreRestart;

#[cfg(test)]
#[path = "lane_b_restart_tests.rs"]
mod tests;

impl AgentRunCoordinator {
    pub(crate) fn open_durable_for_restart(
        composition: RuntimeComposition,
        durable_path: PathBuf,
        admission: &VerifiedRunStoreRestart,
    ) -> Result<Self, AgentRunError> {
        let mut candidate = Self::compose_runtime(composition)?;
        admission.validate_store_binding(&candidate.composition, &durable_path, None)?;
        let parent = durable_path
            .parent()
            .ok_or_else(|| AgentRunError::Persistence("run store has no parent".into()))?;
        fs::create_dir_all(parent)
            .map_err(|error| AgentRunError::Persistence(format!("create run parent: {error}")))?;
        let _lock = DurableRunStoreLock::acquire(&durable_path)?;
        let previous = load_durable_run_store(&durable_path)?;
        candidate.durable_path = Some(durable_path.clone());
        if let Some(store) = previous.as_ref() {
            // Validate against its exact original composition, never against
            // a fabricated current tuple. Every snapshot/tombstone survives.
            validate_durable_run_store(store, &store.composition)?;
            admission.validate_store_binding(
                &candidate.composition,
                &durable_path,
                Some(&store.composition),
            )?;
            candidate.runs = store.runs.clone();
            candidate.tombstones = store.tombstones.clone();
            candidate.durable_store_revision = store.store_revision;
            candidate.committed_store_sha256 = Some(durable_run_store_sha256(store)?);
            if store.composition == candidate.composition {
                candidate.accepting_runs = store.accepting_runs;
                return Ok(candidate);
            }
            if store
                .runs
                .values()
                .any(|record| record.snapshot.generation >= candidate.composition.agentd_generation)
                || store.tombstones.values().any(|record| {
                    record.snapshot.generation >= candidate.composition.agentd_generation
                })
            {
                return Err(AgentRunError::InvalidGeneration);
            }
            candidate.mark_unresolved_indeterminate("validated_process_restart")?;
            // A new real Starting owner may admit new current tuples. Old
            // unsent snapshots keep their phase and remain fenced at dispatch.
        }
        let next_revision = candidate
            .durable_store_revision
            .checked_add(1)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        let next = DurableRunStoreV1 {
            schema_version: DURABLE_RUN_STORE_SCHEMA_VERSION,
            store_revision: next_revision,
            previous_store_sha256: candidate.committed_store_sha256.clone(),
            composition: candidate.composition.clone(),
            runs: candidate.runs.clone(),
            tombstones: candidate.tombstones.clone(),
            accepting_runs: candidate.accepting_runs,
            max_active_runs: candidate.max_active_runs,
        };
        validate_durable_run_store(&next, &candidate.composition)?;
        let next_digest = durable_run_store_sha256(&next)?;
        let observed = load_durable_run_store(&durable_path)?;
        let observed_revision = observed.as_ref().map_or(0, |store| store.store_revision);
        let observed_digest = observed
            .as_ref()
            .map(durable_run_store_sha256)
            .transpose()?;
        if observed_revision != candidate.durable_store_revision
            || observed_digest != candidate.committed_store_sha256
        {
            return Err(AgentRunError::StaleRevision);
        }
        admission.validate_store_binding(
            &candidate.composition,
            &durable_path,
            observed.as_ref().map(|store| &store.composition),
        )?;
        atomic_replace_durable_run_store(&durable_path, &next)?;
        candidate.durable_store_revision = next_revision;
        candidate.committed_store_sha256 = Some(next_digest);
        Ok(candidate)
    }
}
