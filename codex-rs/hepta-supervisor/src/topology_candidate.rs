//! Durable append-only topology candidate journal owned by Supervisor.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use codex_hepta_fleet::RuntimeTopologyCandidateV1;
use codex_hepta_fleet::RuntimeTopologyStageV1;
use serde::{Deserialize, Serialize};

use crate::SupervisorError;

const TOPOLOGY_CANDIDATE_FILE: &str = "topology-candidates-v1.jsonl";
const TOPOLOGY_CANDIDATE_SCHEMA_VERSION: u32 = 1;
const MAX_JOURNAL_BYTES: u64 = 1024 * 1024;
const MAX_RECORD_BYTES: usize = 16 * 1024;
const MAX_RECORDS: usize = 1024;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct FrameV1 {
    schema_version: u32,
    candidate: RuntimeTopologyCandidateV1,
}

pub(crate) fn read_latest_topology_candidate(
    run_root: &Path,
) -> Result<Option<RuntimeTopologyCandidateV1>, SupervisorError> {
    let path = journal_path(run_root);
    let metadata = match std::fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(invalid("topology candidate journal is not a regular file"));
    }
    if metadata.len() > MAX_JOURNAL_BYTES {
        return Err(invalid("topology candidate journal exceeds its bounded size"));
    }
    let mut file = OpenOptions::new().read(true).write(true).open(&path)?;
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    file.read_to_end(&mut bytes)?;
    repair_torn_tail(&mut file, &mut bytes)?;

    let mut latest = None;
    let mut count = 0_usize;
    for line in bytes.split(|byte| *byte == b'\n').filter(|line| !line.is_empty()) {
        count = count.checked_add(1).ok_or_else(|| invalid("topology journal count overflow"))?;
        if count > MAX_RECORDS || line.len() > MAX_RECORD_BYTES {
            return Err(invalid("topology candidate journal record bound exceeded"));
        }
        let frame: FrameV1 =
            serde_json::from_slice(line).map_err(|error| invalid(format!("topology candidate decode: {error}")))?;
        if frame.schema_version != TOPOLOGY_CANDIDATE_SCHEMA_VERSION {
            return Err(invalid("unsupported topology candidate journal schema"));
        }
        frame
            .candidate
            .validate_recovered()
            .map_err(|error| invalid(format!("topology candidate validation: {error}")))?;
        validate_chain(latest.as_ref(), &frame.candidate)?;
        latest = Some(frame.candidate);
    }
    Ok(latest)
}

pub(crate) fn append_topology_candidate(
    run_root: &Path,
    candidate: &RuntimeTopologyCandidateV1,
) -> Result<(), SupervisorError> {
    candidate
        .validate_recovered()
        .map_err(|error| invalid(format!("topology candidate validation: {error}")))?;
    let latest = read_latest_topology_candidate(run_root)?;
    validate_chain(latest.as_ref(), candidate)?;

    let path = journal_path(run_root);
    let existed = path.exists();
    let frame = FrameV1 {
        schema_version: TOPOLOGY_CANDIDATE_SCHEMA_VERSION,
        candidate: candidate.clone(),
    };
    let mut bytes =
        serde_json::to_vec(&frame).map_err(|error| invalid(format!("topology candidate encode: {error}")))?;
    if bytes.len() > MAX_RECORD_BYTES {
        return Err(invalid("topology candidate record exceeds its bounded size"));
    }
    bytes.push(b'\n');

    let current_len = std::fs::metadata(&path).map(|metadata| metadata.len()).unwrap_or(0);
    if current_len.saturating_add(bytes.len() as u64) > MAX_JOURNAL_BYTES {
        return Err(invalid("topology candidate journal capacity exhausted"));
    }

    let mut options = OpenOptions::new();
    options.create(true).append(true).read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    if !existed {
        sync_parent(run_root)?;
    }
    Ok(())
}

fn validate_chain(
    previous: Option<&RuntimeTopologyCandidateV1>,
    next: &RuntimeTopologyCandidateV1,
) -> Result<(), SupervisorError> {
    let Some(previous) = previous else {
        if next.revision == 1 && next.stage == RuntimeTopologyStageV1::Proposed {
            return Ok(());
        }
        return Err(invalid("first topology candidate journal record must be proposed revision 1"));
    };

    if previous.proposal_digest != next.proposal_digest {
        if !matches!(
            previous.stage,
            RuntimeTopologyStageV1::Promoted
                | RuntimeTopologyStageV1::RolledBack
                | RuntimeTopologyStageV1::Rejected
        ) || next.revision != 1
            || next.stage != RuntimeTopologyStageV1::Proposed
        {
            return Err(invalid("new topology proposal started before previous candidate stabilized"));
        }
        return Ok(());
    }

    if next.revision != previous.revision.saturating_add(1)
        || previous.predecessor_release != next.predecessor_release
        || previous.target_release != next.target_release
        || previous.predecessor_generation != next.predecessor_generation
        || previous.candidate_generation != next.candidate_generation
        || previous.predecessor_topology_digest != next.predecessor_topology_digest
        || previous.candidate_topology_digest != next.candidate_topology_digest
        || previous.rollback_predecessor_digest != next.rollback_predecessor_digest
        || !valid_stage_transition(previous.stage, next.stage)
    {
        return Err(invalid("topology candidate journal transition mismatch"));
    }
    Ok(())
}

fn valid_stage_transition(from: RuntimeTopologyStageV1, to: RuntimeTopologyStageV1) -> bool {
    use RuntimeTopologyStageV1 as S;
    matches!(
        (from, to),
        (S::Proposed, S::Shadow | S::Rejected)
            | (S::Shadow, S::Canary | S::Rejected)
            | (S::Canary, S::Promoted | S::RollbackRequested | S::Rejected)
            | (S::Promoted, S::RollbackRequested)
            | (S::RollbackRequested, S::RolledBack)
    )
}

fn repair_torn_tail(file: &mut File, bytes: &mut Vec<u8>) -> Result<(), SupervisorError> {
    if bytes.is_empty() || bytes.last() == Some(&b'\n') {
        return Ok(());
    }
    let keep = bytes
        .iter()
        .rposition(|byte| *byte == b'\n')
        .map_or(0, |position| position + 1);
    file.set_len(keep as u64)?;
    file.seek(SeekFrom::Start(keep as u64))?;
    file.sync_all()?;
    bytes.truncate(keep);
    Ok(())
}

fn journal_path(run_root: &Path) -> PathBuf {
    run_root.join(TOPOLOGY_CANDIDATE_FILE)
}

fn invalid(message: impl Into<String>) -> SupervisorError {
    SupervisorError::Invalid(message.into())
}

#[cfg(unix)]
fn sync_parent(run_root: &Path) -> Result<(), SupervisorError> {
    File::open(run_root)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent(_run_root: &Path) -> Result<(), SupervisorError> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_fleet::runtime_module_binding_digest_v1;
    use tempfile::TempDir;

    fn digest(label: &str) -> String {
        runtime_module_binding_digest_v1(&[label])
    }

    fn candidate() -> RuntimeTopologyCandidateV1 {
        RuntimeTopologyCandidateV1::new(
            digest("proposal"),
            "release-1".to_string(),
            "release-2".to_string(),
            1,
            2,
            digest("topology-1"),
            digest("topology-2"),
            digest("topology-1"),
        )
        .expect("candidate")
    }

    #[test]
    fn journal_replays_exact_shadow_canary_chain() {
        let temp = TempDir::new().expect("temp");
        let mut value = candidate();
        append_topology_candidate(temp.path(), &value).expect("proposed");
        value.enter_shadow(digest("qualification")).expect("shadow");
        append_topology_candidate(temp.path(), &value).expect("shadow append");
        value
            .enter_canary(digest("selection"), digest("observation"))
            .expect("canary");
        append_topology_candidate(temp.path(), &value).expect("canary append");
        assert_eq!(
            read_latest_topology_candidate(temp.path()).expect("read"),
            Some(value)
        );
    }

    #[test]
    fn torn_uncommitted_tail_is_removed_on_reopen() {
        let temp = TempDir::new().expect("temp");
        let value = candidate();
        append_topology_candidate(temp.path(), &value).expect("append");
        let path = journal_path(temp.path());
        let mut file = OpenOptions::new().append(true).open(&path).expect("open");
        file.write_all(b"{\"schema_version\":1").expect("torn");
        file.sync_all().expect("sync");
        assert_eq!(
            read_latest_topology_candidate(temp.path()).expect("recover"),
            Some(value)
        );
        assert_eq!(
            std::fs::read(path).expect("bytes").last().copied(),
            Some(b'\n')
        );
    }
}
