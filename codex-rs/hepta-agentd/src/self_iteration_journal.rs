use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use serde::Deserialize;
use serde::Serialize;

use super::*;

static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);
const MAX_RECORD_BYTES: u64 = 16 * 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredRecord {
    version: u32,
    #[serde(with = "super::codec::digest")]
    checksum: Digest32,
    record: AgentdSelfIterationRecordV1,
}

pub(super) struct IterationJournal {
    path: PathBuf,
    _lease: File,
    current: Option<AgentdSelfIterationRecordV1>,
}

impl IterationJournal {
    pub(super) fn open(path: PathBuf) -> Result<Self, AgentdError> {
        if !path.is_absolute() || path.file_name().is_none() {
            return Err(invalid("iteration journal path must be absolute"));
        }
        let parent = path
            .parent()
            .ok_or_else(|| invalid("iteration journal parent"))?;
        let parent_metadata = std::fs::symlink_metadata(parent)?;
        if !parent_metadata.is_dir() || parent_metadata.file_type().is_symlink() {
            return Err(invalid(
                "iteration journal parent must be an existing directory",
            ));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if parent_metadata.mode() & 0o077 != 0 {
                return Err(invalid("iteration journal parent must be private"));
            }
        }
        let lease_path = path.with_extension("lease");
        if let Ok(metadata) = std::fs::symlink_metadata(&lease_path)
            && (!metadata.is_file() || metadata.file_type().is_symlink())
        {
            return Err(invalid("iteration lease must be regular"));
        }
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let lease = options.open(lease_path)?;
        lease
            .try_lock()
            .map_err(|_| invalid("iteration journal already owned"))?;
        let current = match std::fs::symlink_metadata(&path) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => return Err(error.into()),
            Ok(metadata) => {
                if !metadata.is_file()
                    || metadata.file_type().is_symlink()
                    || metadata.len() > MAX_RECORD_BYTES
                {
                    return Err(invalid("iteration journal is not a bounded regular file"));
                }
                let mut bytes = Vec::new();
                File::open(&path)?
                    .take(MAX_RECORD_BYTES + 1)
                    .read_to_end(&mut bytes)?;
                let stored: StoredRecord =
                    serde_json::from_slice(&bytes).map_err(|error| invalid(error.to_string()))?;
                if stored.version != 1 || stored.checksum != checksum(&stored.record)? {
                    return Err(invalid("iteration journal checksum"));
                }
                validate_record(&stored.record)?;
                Some(stored.record)
            }
        };
        Ok(Self {
            path,
            _lease: lease,
            current,
        })
    }

    pub(super) fn record(&self) -> Option<&AgentdSelfIterationRecordV1> {
        self.current.as_ref()
    }

    pub(super) fn pending(&self) -> bool {
        self.current.as_ref().is_some_and(|record| {
            !matches!(
                record.phase,
                AgentdSelfIterationPhaseV1::Accepted
                    | AgentdSelfIterationPhaseV1::RolledBack
                    | AgentdSelfIterationPhaseV1::Rejected
            )
        })
    }

    pub(super) fn unresolved_apply(&self) -> bool {
        self.current.as_ref().is_some_and(|record| {
            matches!(
                record.phase,
                AgentdSelfIterationPhaseV1::Applying
                    | AgentdSelfIterationPhaseV1::Canary
                    | AgentdSelfIterationPhaseV1::RollingBack
            )
        })
    }

    pub(super) fn persist(
        &mut self,
        record: &AgentdSelfIterationRecordV1,
    ) -> Result<(), AgentdError> {
        validate_record(record)?;
        if let Some(previous) = self.current.as_ref() {
            if previous.frozen_digest != record.frozen_digest && self.pending() {
                return Err(invalid("unresolved iteration cannot be replaced"));
            }
            if previous.frozen_digest == record.frozen_digest
                && !allowed_transition(previous.phase, record.phase)
            {
                return Err(invalid("iteration phase regression"));
            }
        }
        let bytes = serde_json::to_vec(&StoredRecord {
            version: 1,
            checksum: checksum(record)?,
            record: record.clone(),
        })
        .map_err(|error| invalid(error.to_string()))?;
        if bytes.len() as u64 > MAX_RECORD_BYTES {
            return Err(invalid("iteration record limit"));
        }
        let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let temporary = self
            .path
            .with_extension(format!("tmp-{}-{sequence}", std::process::id()));
        let result: Result<(), AgentdError> = (|| {
            let mut options = OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options.open(&temporary)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            std::fs::rename(&temporary, &self.path)?;
            File::open(
                self.path
                    .parent()
                    .ok_or_else(|| invalid("journal parent"))?,
            )?
            .sync_all()?;
            Ok(())
        })();
        if result.is_err() {
            let _ = std::fs::remove_file(&temporary);
        }
        result?;
        self.current = Some(record.clone());
        Ok(())
    }
}

fn validate_record(record: &AgentdSelfIterationRecordV1) -> Result<(), AgentdError> {
    use AgentdSelfIterationPhaseV1::*;
    let has_evaluation = record.evaluation_digest.is_some();
    let has_selection = record.selection_digest.is_some();
    let has_probe = record.canary_operation_digest.is_some();
    let has_observer = record.observer_digest.is_some();
    let phase_valid = match record.phase {
        Frozen => !has_evaluation && !has_selection && !has_probe && !has_observer,
        Evaluated => has_evaluation && !has_selection && !has_probe && !has_observer,
        Applying => has_evaluation && has_selection && !has_probe && !has_observer,
        Canary => has_evaluation && has_selection && has_probe && !has_observer,
        Accepted => has_evaluation && has_selection && has_probe && has_observer,
        RollingBack | RolledBack => has_evaluation && has_selection,
        Rejected => !has_selection && !has_probe && !has_observer,
    };
    if !phase_valid
        || record.canary_operation_digest.is_some() != record.canary_checkpoint_digest.is_some()
        || record.canary_operation_digest.is_some() != record.canary_observation.is_some()
        || record
            .canary_observation
            .as_ref()
            .is_some_and(|value| value.confidence_ppm > 1_000_000 || value.ood_ppm > 1_000_000)
        || codex_hepta_agent_components::types::StableId::new(&record.candidate_id).is_err()
        || record.base_generation == 0
        || record.base_generation.checked_add(1) != Some(record.successor_generation)
        || record.base_generation.checked_add(2) != Some(record.rollback_generation)
        || record.expires_at == 0
        || [
            Some(record.frozen_digest),
            Some(record.objective_digest),
            Some(record.successor_configuration),
            Some(record.rollback_configuration),
            Some(record.successor_body),
            Some(record.rollback_body),
            record.evaluation_digest,
            record.selection_digest,
            record.canary_operation_digest,
            record.canary_checkpoint_digest,
            record.observer_digest,
        ]
        .into_iter()
        .flatten()
        .any(codex_hepta_agent_components::types::Digest32::is_zero)
    {
        return Err(invalid(
            "iteration record identity or phase evidence incomplete",
        ));
    }
    Ok(())
}

fn checksum(record: &AgentdSelfIterationRecordV1) -> Result<Digest32, AgentdError> {
    let bytes = serde_json::to_vec(record).map_err(|error| invalid(error.to_string()))?;
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.self-iteration-record.v1",
        &bytes,
    ]))
}

fn allowed_transition(from: AgentdSelfIterationPhaseV1, to: AgentdSelfIterationPhaseV1) -> bool {
    use AgentdSelfIterationPhaseV1::*;
    from == to
        || matches!(
            (from, to),
            (Frozen | Evaluated, Rejected)
                | (Frozen, Evaluated)
                | (Evaluated, Applying)
                | (Applying, Canary)
                | (Canary, Accepted)
                | (Applying | Canary, RollingBack)
                | (RollingBack, RolledBack)
        )
}

#[cfg(test)]
#[path = "self_iteration_journal_tests.rs"]
mod tests;
