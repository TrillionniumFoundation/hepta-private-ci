//! Non-rollback frontier for the supervisor-owned durable allocation state.
//!
//! The established snapshot implementation lives in `durable_owner_core.rs`.
//! This wrapper adds one independently fsynced latest-generation frontier. A
//! retained snapshot chain may advance that frontier, but it may never move it
//! backwards. The only automatic repair is a verifiable descendant chain from
//! the pinned frontier, covering a crash after state publication and before the
//! frontier rename becomes durable.

#[path = "durable_owner_core.rs"]
mod core;

#[path = "durable_owner_readonly.rs"]
mod readonly;

pub use readonly::FleetReadOnlyFenceV1;
pub use readonly::FleetReadOnlySnapshotV1;
pub use readonly::lock_fleet_snapshot;
pub use readonly::read_fleet_snapshot;

pub use core::DURABLE_FLEET_STATE_SCHEMA_VERSION;
pub use core::DurableFleetError;
pub use core::DurableFleetIssueReceiptV1;
pub use core::DurableFleetMutationReceiptV1;
pub use core::DurableFleetStateV1;
pub use core::FleetExecutionContextV1;
pub use core::FleetExecutionHoldV1;
pub use core::FleetHostIncarnationV1;
pub use core::FleetHostRecordV1;
pub use core::FleetOperationKindV1;
pub use core::FleetOperationReceiptV1;
pub use core::FleetOperationalMetricsV1;
pub use core::FleetQuiescenceProbe;
pub use core::FleetResultCountersV1;
pub use core::MAX_DURABLE_OPERATION_RECEIPTS;

#[cfg(test)]
pub(crate) use core::fail_next_commit_after_state_link;

use crate::AllocationGrant;
use crate::FleetAuthorityPort;
use crate::FleetCapacityObserverV1;
use crate::FleetClock;
use crate::FleetRevocationSnapshotV1;
use crate::GrantUseWitnessV1;
use crate::LeaseDisposition;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

const DURABLE_FLEET_DIRECTORY: &str = "fleet-allocation-v1";
const DURABLE_FLEET_LOCK: &str = "owner.lock";
const STATE_FILE_PREFIX: &str = "generation-";
const STATE_FILE_SUFFIX: &str = ".json";
const LATEST_FRONTIER_FILE: &str = "latest-frontier-v1.json";
const LATEST_FRONTIER_SCHEMA_VERSION: u32 = 1;
static FRONTIER_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableFleetLatestFrontierV1 {
    schema_version: u32,
    generation: u64,
    state_sha256: String,
    previous_state_sha256: String,
    content_sha256: String,
}

impl DurableFleetLatestFrontierV1 {
    fn from_state(state: &DurableFleetStateV1) -> Result<Self, DurableFleetError> {
        let mut frontier = Self {
            schema_version: LATEST_FRONTIER_SCHEMA_VERSION,
            generation: state.generation,
            state_sha256: state.content_sha256.clone(),
            previous_state_sha256: state.previous_state_sha256.clone(),
            content_sha256: String::new(),
        };
        frontier.content_sha256 = frontier_digest(&frontier)?;
        Ok(frontier)
    }

    fn validate(&self) -> Result<(), DurableFleetError> {
        if self.schema_version != LATEST_FRONTIER_SCHEMA_VERSION
            || !valid_digest(&self.state_sha256)
            || !valid_digest(&self.previous_state_sha256)
            || self.content_sha256 != frontier_digest(self)?
        {
            return Err(DurableFleetError::CorruptState);
        }
        Ok(())
    }
}

pub struct DurableFleetOwner {
    inner: core::DurableFleetOwner,
    root: PathBuf,
}

impl fmt::Debug for DurableFleetOwner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurableFleetOwner")
            .field("root", &self.root)
            .field("generation", &self.inner.state().generation)
            .finish()
    }
}

impl DurableFleetOwner {
    pub fn open_supervisor_state_root(
        supervisor_state_root: impl Into<PathBuf>,
        clock: Arc<dyn FleetClock>,
    ) -> Result<Self, DurableFleetError> {
        let supervisor_state_root = supervisor_state_root.into();
        let root = supervisor_state_root.join(DURABLE_FLEET_DIRECTORY);
        let inner =
            core::DurableFleetOwner::open_supervisor_state_root(&supervisor_state_root, clock)?;
        let mut owner = Self { inner, root };
        owner.reconcile_latest_frontier("open")?;
        Ok(owner)
    }

    pub fn resolve_host_incarnation(
        &mut self,
        host_id: &str,
        failure_domain_id: &str,
        boot_identity: &str,
        requested_generation: Option<u64>,
    ) -> Result<FleetHostIncarnationV1, DurableFleetError> {
        let result = self.inner.resolve_host_incarnation(
            host_id,
            failure_domain_id,
            boot_identity,
            requested_generation,
        );
        self.finish_mutation("resolve-host-incarnation", result)
    }

    pub fn prepare_execution(
        &mut self,
        effect_id: &str,
        context: FleetExecutionContextV1,
        witness: &crate::RevocationBoundGrantUseWitnessV1,
    ) -> Result<FleetExecutionHoldV1, DurableFleetError> {
        let result = self.inner.prepare_execution(effect_id, context, witness);
        self.finish_mutation(effect_id, result)
    }

    pub fn reconcile_execution_group<P: FleetQuiescenceProbe>(
        &mut self,
        allocation_id: &str,
        probe: &P,
    ) -> Result<bool, DurableFleetError> {
        let result = self.inner.reconcile_execution_group(allocation_id, probe);
        self.finish_mutation("execution-quiescence", result)
    }

    pub fn state(&self) -> &DurableFleetStateV1 {
        self.inner.state()
    }

    pub fn refresh_capacity<O: FleetCapacityObserverV1>(
        &mut self,
        operation_id: &str,
        observer: &O,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let result = self.inner.refresh_capacity(operation_id, observer);
        self.finish_mutation(operation_id, result)
    }

    pub fn issue_with_authority(
        &mut self,
        operation_id: &str,
        authority: &FleetAuthorityPort,
        lease_id: &str,
        expected_lease_revision: u64,
        grant: AllocationGrant,
    ) -> Result<DurableFleetIssueReceiptV1, DurableFleetError> {
        let result = self.inner.issue_with_authority(
            operation_id,
            authority,
            lease_id,
            expected_lease_revision,
            grant,
        );
        self.finish_mutation(operation_id, result)
    }

    pub fn renew_or_revoke(
        &mut self,
        operation_id: &str,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: LeaseDisposition,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let result = self.inner.renew_or_revoke(
            operation_id,
            allocation_id,
            expected_lease_generation,
            authority_epoch,
            semantic_digest,
            disposition,
        );
        self.finish_mutation(operation_id, result)
    }

    pub fn reconcile_expired(
        &mut self,
        operation_id: &str,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let result = self.inner.reconcile_expired(operation_id);
        self.finish_mutation(operation_id, result)
    }

    pub fn persist_revocation_snapshot(
        &mut self,
        operation_id: &str,
        snapshot: FleetRevocationSnapshotV1,
    ) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
        let result = self
            .inner
            .persist_revocation_snapshot(operation_id, snapshot);
        self.finish_mutation(operation_id, result)
    }

    pub fn verify_final_use(
        &mut self,
        allocation_id: &str,
        expected_lease_generation: u64,
        expected_host_id: &str,
        expected_host_generation: u64,
        semantic_digest: &str,
    ) -> Result<GrantUseWitnessV1, DurableFleetError> {
        let result = self.inner.verify_final_use(
            allocation_id,
            expected_lease_generation,
            expected_host_id,
            expected_host_generation,
            semantic_digest,
        );
        self.reconcile_latest_frontier("verify-final-use")?;
        result
    }

    pub fn metrics(&mut self) -> Result<FleetOperationalMetricsV1, DurableFleetError> {
        let result = self.inner.metrics();
        self.reconcile_latest_frontier("metrics")?;
        result
    }

    pub fn note_registry_conflict(&mut self) {
        self.inner.note_registry_conflict();
    }

    pub fn note_indeterminate_commit(&mut self) {
        self.inner.note_indeterminate_commit();
    }

    fn finish_mutation<T>(
        &mut self,
        operation_id: &str,
        result: Result<T, DurableFleetError>,
    ) -> Result<T, DurableFleetError> {
        match result {
            Ok(value) => {
                self.reconcile_latest_frontier(operation_id)?;
                Ok(value)
            }
            Err(error @ DurableFleetError::IndeterminateCommit { .. }) => {
                // The state file may already be visible. Pin whichever complete
                // descendant generation is actually present before returning
                // the original indeterminate result to the caller.
                self.reconcile_latest_frontier(operation_id)?;
                Err(error)
            }
            Err(error) => Err(error),
        }
    }

    fn reconcile_latest_frontier(&mut self, operation_id: &str) -> Result<(), DurableFleetError> {
        let _guard = FrontierOwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        let states = load_retained_states(&self.root)?;
        let latest = states.last().ok_or(DurableFleetError::MissingState)?;
        let frontier_path = self.root.join(LATEST_FRONTIER_FILE);
        let current = load_frontier(&frontier_path)?;

        match current {
            None if latest.generation == 0 => publish_frontier(
                &self.root,
                &DurableFleetLatestFrontierV1::from_state(latest)?,
            )
            .map_err(|error| DurableFleetError::IndeterminateCommit {
                operation_id: operation_id.to_string(),
                generation: latest.generation,
                detail: error.to_string(),
            }),
            None => Err(DurableFleetError::CorruptState),
            Some(frontier) if latest.generation < frontier.generation => {
                Err(DurableFleetError::CorruptState)
            }
            Some(frontier) if latest.generation == frontier.generation => {
                if latest.content_sha256 == frontier.state_sha256
                    && latest.previous_state_sha256 == frontier.previous_state_sha256
                {
                    Ok(())
                } else {
                    Err(DurableFleetError::CorruptState)
                }
            }
            Some(frontier) => {
                verify_descends_from_frontier(&frontier, &states)?;
                publish_frontier(
                    &self.root,
                    &DurableFleetLatestFrontierV1::from_state(latest)?,
                )
                .map_err(|error| DurableFleetError::IndeterminateCommit {
                    operation_id: operation_id.to_string(),
                    generation: latest.generation,
                    detail: error.to_string(),
                })
            }
        }
    }
}

fn verify_descends_from_frontier(
    frontier: &DurableFleetLatestFrontierV1,
    states: &[DurableFleetStateV1],
) -> Result<(), DurableFleetError> {
    if let Some(index) = states.iter().position(|state| {
        state.generation == frontier.generation && state.content_sha256 == frontier.state_sha256
    }) {
        if states[index].previous_state_sha256 != frontier.previous_state_sha256 {
            return Err(DurableFleetError::CorruptState);
        }
        return Ok(());
    }

    let first = states.first().ok_or(DurableFleetError::MissingState)?;
    if first.generation == frontier.generation.saturating_add(1)
        && first.previous_state_sha256 == frontier.state_sha256
    {
        return Ok(());
    }
    Err(DurableFleetError::CorruptState)
}

fn load_retained_states(root: &Path) -> Result<Vec<DurableFleetStateV1>, DurableFleetError> {
    let mut states = Vec::new();
    visit_retained_states(root, |state| states.push(state))?;
    Ok(states)
}

// One shared chain validator; inspection retains only the latest snapshot.
fn visit_retained_states(
    root: &Path,
    mut visit: impl FnMut(DurableFleetStateV1),
) -> Result<(), DurableFleetError> {
    let mut paths = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            return Err(DurableFleetError::CorruptState);
        };
        if let Some(generation) = parse_state_generation(&name)? {
            paths.push((generation, entry.path()));
        }
    }
    paths.sort_unstable_by_key(|(generation, _)| *generation);

    let mut previous: Option<(u64, String)> = None;
    for (generation, path) in paths {
        let metadata = std::fs::symlink_metadata(&path)?;
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return Err(DurableFleetError::CorruptState);
        }
        let state: DurableFleetStateV1 = serde_json::from_slice(&std::fs::read(path)?)?;
        if state.generation != generation || state.content_sha256 != state_digest(&state)? {
            return Err(DurableFleetError::CorruptState);
        }
        if let Some((generation, digest)) = &previous
            && (generation.checked_add(1) != Some(state.generation)
                || &state.previous_state_sha256 != digest)
        {
            return Err(DurableFleetError::CorruptState);
        }
        previous = Some((state.generation, state.content_sha256.clone()));
        visit(state);
    }
    Ok(())
}

fn load_frontier(path: &Path) -> Result<Option<DurableFleetLatestFrontierV1>, DurableFleetError> {
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(DurableFleetError::CorruptState);
    }
    let frontier: DurableFleetLatestFrontierV1 = serde_json::from_slice(&std::fs::read(path)?)?;
    frontier.validate()?;
    Ok(Some(frontier))
}

fn publish_frontier(
    root: &Path,
    frontier: &DurableFleetLatestFrontierV1,
) -> Result<(), std::io::Error> {
    let final_path = root.join(LATEST_FRONTIER_FILE);
    let temp_path = root.join(format!(
        ".latest-frontier-{}-{}.tmp",
        std::process::id(),
        FRONTIER_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let mut encoded = serde_json::to_vec(frontier)
        .map_err(|error| std::io::Error::new(ErrorKind::InvalidData, error))?;
    encoded.push(b'\n');
    let result = (|| -> Result<(), std::io::Error> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)?;
        file.write_all(&encoded)?;
        file.sync_all()?;
        std::fs::rename(&temp_path, &final_path)?;
        sync_directory(root)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(temp_path);
    }
    result
}

fn state_digest(state: &DurableFleetStateV1) -> Result<String, DurableFleetError> {
    let mut candidate = state.clone();
    candidate.content_sha256.clear();
    let encoded = serde_json::to_vec(&candidate)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.durable-state.v1\0");
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}

fn frontier_digest(frontier: &DurableFleetLatestFrontierV1) -> Result<String, DurableFleetError> {
    let mut candidate = frontier.clone();
    candidate.content_sha256.clear();
    let encoded = serde_json::to_vec(&candidate)?;
    let mut digest = Sha256::new();
    digest.update(b"hepta.runtime.fleet.latest-frontier.v1\0");
    digest.update(encoded);
    Ok(format!("{:x}", digest.finalize()))
}

fn parse_state_generation(name: &str) -> Result<Option<u64>, DurableFleetError> {
    if !name.starts_with(STATE_FILE_PREFIX) {
        return Ok(None);
    }
    let value = name
        .strip_prefix(STATE_FILE_PREFIX)
        .and_then(|value| value.strip_suffix(STATE_FILE_SUFFIX))
        .filter(|value| value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit()))
        .ok_or(DurableFleetError::CorruptState)?;
    value
        .parse::<u64>()
        .map(Some)
        .map_err(|_| DurableFleetError::CorruptState)
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

struct FrontierOwnerLock {
    _file: File,
}

impl FrontierOwnerLock {
    fn acquire(path: &Path) -> Result<Self, DurableFleetError> {
        let file = open_private_lock_file(path)?;
        file.lock()?;
        Ok(Self { _file: file })
    }
}

#[cfg(unix)]
fn open_private_lock_file(path: &Path) -> Result<File, DurableFleetError> {
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(file)
}

#[cfg(not(unix))]
fn open_private_lock_file(path: &Path) -> Result<File, DurableFleetError> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .map_err(Into::into)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> std::io::Result<()> {
    File::open(path)?.sync_all()
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> std::io::Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::SystemFleetClock;

    fn state_root(directory: &tempfile::TempDir) -> PathBuf {
        let root = directory.path().join("state");
        std::fs::create_dir(&root).expect("state root");
        root
    }

    fn generation_path(root: &Path, generation: u64) -> PathBuf {
        root.join(DURABLE_FLEET_DIRECTORY).join(format!(
            "{STATE_FILE_PREFIX}{generation:020}{STATE_FILE_SUFFIX}"
        ))
    }

    #[test]
    fn initial_open_pins_generation_zero_frontier() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = state_root(&directory);
        let owner =
            DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
                .expect("owner");
        let frontier = load_frontier(
            &root
                .join(DURABLE_FLEET_DIRECTORY)
                .join(LATEST_FRONTIER_FILE),
        )
        .expect("frontier")
        .expect("frontier exists");
        assert_eq!(frontier.generation, owner.state().generation);
        assert_eq!(frontier.state_sha256, owner.state().content_sha256);
    }

    #[test]
    fn one_unpinned_descendant_is_recovered_but_latest_deletion_is_rejected() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = state_root(&directory);
        DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
            .expect("initial owner");

        let mut core_owner =
            core::DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
                .expect("core owner");
        core_owner
            .persist_revocation_snapshot(
                "frontier-crash-window",
                FleetRevocationSnapshotV1::empty(1_000),
            )
            .expect("publish descendant without wrapper frontier");
        drop(core_owner);

        let recovered =
            DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
                .expect("recover one descendant");
        assert_eq!(recovered.state().generation, 1);
        drop(recovered);

        std::fs::remove_file(generation_path(&root, 1)).expect("delete latest generation");
        assert!(matches!(
            DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock),),
            Err(DurableFleetError::CorruptState)
        ));
    }

    #[test]
    fn missing_frontier_after_nonzero_generation_fails_closed() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = state_root(&directory);
        let mut owner =
            DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
                .expect("owner");
        owner
            .persist_revocation_snapshot(
                "frontier-present",
                FleetRevocationSnapshotV1::empty(1_000),
            )
            .expect("advance");
        drop(owner);
        std::fs::remove_file(
            root.join(DURABLE_FLEET_DIRECTORY)
                .join(LATEST_FRONTIER_FILE),
        )
        .expect("delete frontier");
        assert!(matches!(
            DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock),),
            Err(DurableFleetError::CorruptState)
        ));
    }
}
