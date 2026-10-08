//! External-adapter lifecycle runner for DecisionCell target-host evidence.
//!
//! This module is an orchestration seam, not a target-host implementation. A
//! deployment owner supplies [`CellSplitTargetHostRuntimeV1`] with calls that
//! really load the child artifact, perform the CNS route cutover, recover from
//! restart/power loss, roll back, commit the tombstone, and verify that the old
//! generation cannot return. The runner only orders those calls and records
//! their externally returned receipts in the signed-evidence recorder.
//!
//! No method in this module fabricates a CAS commit, route dispatch, hardware
//! counter, fault injection or observer signature. A runtime adapter that
//! returns fixture/simulation receipts will be rejected later by the evidence
//! verifier, and this runner does not issue a production receipt.

use std::fmt::Display;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use thiserror::Error;

use crate::CellSplitTargetHostEventKindV1;
use crate::CellSplitTargetHostEvidenceErrorV1;
use crate::CellSplitTargetHostEvidenceRecorderV1;
use crate::CellSplitTargetHostEvidenceV1;
use crate::CellSplitTargetResourceSampleV1;
use sha2::Digest as _;
use sha2::Sha256;

pub const CELL_SPLIT_TARGET_HOST_LIFECYCLE_SCHEMA_V1: &str =
    "hepta.learning.cell-split.target-host-lifecycle-runner.v1";
pub const CELL_SPLIT_LOCAL_TARGET_HOST_RUNTIME_SCHEMA_V1: &str =
    "hepta.learning.cell-split.local-target-host-runtime.v1";

/// Receipt returned by one external target-host operation. The target-host
/// owner must bind these values to its durable artifact/CNS/fault/registry
/// receipt; the runner treats them as observations and never derives them.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitTargetHostOperationReceiptV1 {
    pub operation_id: String,
    pub occurred_at_unix_nanos: u128,
    pub artifact_digest: String,
    pub route_digest: String,
    pub predecessor_digest: String,
    pub tombstone_digest: String,
    pub fault_injection_digest: String,
    pub receipt_digest: String,
}

/// A hardware measurement paired with the target-host operation that produced
/// it. The sample must contain a non-simulation source and an attestation
/// digest; the evidence verifier applies the final target-host checks.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitTargetHostMeasurementV1 {
    pub operation: CellSplitTargetHostOperationReceiptV1,
    pub sample: CellSplitTargetResourceSampleV1,
}

/// Runtime owner implemented by the deployment host. Every method must call
/// the real owner and return its immutable receipt. In particular, the
/// `power_loss_recover` method must return a fault-injection witness from the
/// host, rather than a process-level restart result relabeled as power loss.
pub trait CellSplitTargetHostRuntimeV1 {
    type Error: Display;

    fn load_child_artifact(&mut self)
    -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn route_cutover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn restart_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn power_loss_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn rollback(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn commit_tombstone(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;
    fn verify_no_resurrection(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error>;

    /// Return counters from the actual target host. The implementation may
    /// return one or more CPU/GPU/NPU samples, but an empty vector is rejected.
    fn measure_resources(&mut self) -> Result<Vec<CellSplitTargetHostMeasurementV1>, Self::Error>;
}

/// A file-backed deployment owner for a single target-host lifecycle.
///
/// This adapter performs real local file operations: it hashes and reads the
/// child artifact, atomically switches a route file, checkpoints a successor
/// state, reopens those files after restart, rolls both files back, and writes
/// a durable tombstone. It deliberately refuses to manufacture a power-loss
/// witness: `power_loss_recover` succeeds only after an external injector has
/// written the configured witness file. Likewise, resource counters are read
/// from the caller-supplied sample and are never synthesized here.
#[derive(Clone, Debug)]
pub struct LocalCellSplitTargetHostRuntimeV1 {
    child_artifact: PathBuf,
    state: PathBuf,
    route: PathBuf,
    tombstone: PathBuf,
    power_loss_witness: PathBuf,
    parent_route_snapshot: PathBuf,
    parent_state_snapshot: PathBuf,
    publication: PathBuf,
    parent_route_bytes: Vec<u8>,
    parent_state_bytes: Vec<u8>,
    resource_sample: CellSplitTargetResourceSampleV1,
    child_generation: u64,
    parent_generation: u64,
    child_digest: Option<String>,
    counter: u64,
    last_timestamp: u128,
}

#[derive(Debug, thiserror::Error)]
pub enum LocalCellSplitTargetHostRuntimeErrorV1 {
    #[error("local target-host runtime rejected operation: {0}")]
    Invalid(String),
    #[error("local target-host runtime I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("local target-host resource sample is invalid: {0}")]
    Resource(String),
}

impl LocalCellSplitTargetHostRuntimeV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        root: impl Into<PathBuf>,
        parent_artifact: impl Into<PathBuf>,
        child_artifact: impl Into<PathBuf>,
        state: impl Into<PathBuf>,
        route: impl Into<PathBuf>,
        tombstone: impl Into<PathBuf>,
        power_loss_witness: impl Into<PathBuf>,
        resource_sample: CellSplitTargetResourceSampleV1,
        parent_generation: u64,
    ) -> Result<Self, LocalCellSplitTargetHostRuntimeErrorV1> {
        let root = root.into();
        let parent_artifact = parent_artifact.into();
        let child_artifact = child_artifact.into();
        let state = state.into();
        let route = route.into();
        let tombstone = tombstone.into();
        let power_loss_witness = power_loss_witness.into();
        let parent_route_snapshot = route.with_extension("local-target-host.parent-route");
        let parent_state_snapshot = state.with_extension("local-target-host.parent-state");
        let publication = route.with_extension("local-target-host.publication");
        if parent_generation == 0
            || parent_generation == u64::MAX
            || resource_sample.hardware_model.is_empty()
            || resource_sample.measurement_source.is_empty()
            || resource_sample.measurement_source.contains("simulation")
            || resource_sample.measurement_source.contains("fixture")
        {
            return Err(LocalCellSplitTargetHostRuntimeErrorV1::Resource(
                "generation or externally reported measurement metadata is invalid".into(),
            ));
        }
        let root = root
            .canonicalize()
            .map_err(|error| LocalCellSplitTargetHostRuntimeErrorV1::Invalid(error.to_string()))?;
        if !root.is_dir() {
            return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                "runtime root is not a directory".into(),
            ));
        }
        for path in [
            &parent_artifact,
            &child_artifact,
            &state,
            &route,
            &tombstone,
            &power_loss_witness,
            &parent_route_snapshot,
            &parent_state_snapshot,
            &publication,
        ] {
            if !path.is_absolute() || path.parent() != Some(root.as_path()) {
                return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                    "runtime paths must be absolute direct children of root".into(),
                ));
            }
        }
        let initial_route_bytes = read_existing(&route)?;
        let initial_state_bytes = read_existing(&state)?;
        let parent_route_bytes =
            load_or_write_parent_snapshot(&parent_route_snapshot, &initial_route_bytes)?;
        let parent_state_bytes =
            load_or_write_parent_snapshot(&parent_state_snapshot, &initial_state_bytes)?;
        verify_parent_snapshot_binding(
            &initial_route_bytes,
            &initial_state_bytes,
            &parent_route_bytes,
            &parent_state_bytes,
        )?;
        let initial_publication = match read_optional(&publication)? {
            Some(bytes) => {
                verify_publication(&bytes, &initial_route_bytes, &initial_state_bytes)?;
                bytes
            }
            None => {
                let bytes = make_publication_bytes(
                    parent_generation,
                    "",
                    &initial_route_bytes,
                    &initial_state_bytes,
                    "parent",
                );
                let temporary = temporary_path(&publication);
                crate::durable::write_private_atomic_replace(&publication, &temporary, &bytes)
                    .map_err(|error| {
                        LocalCellSplitTargetHostRuntimeErrorV1::Invalid(error.to_string())
                    })?;
                bytes
            }
        };
        if initial_publication.is_empty() {
            return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                "publication fence is empty".into(),
            ));
        }
        let parent_artifact_bytes = read_existing(&parent_artifact)?;
        if parent_artifact_bytes.is_empty() {
            return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                "parent artifact is empty".into(),
            ));
        }
        let child_digest = match read_optional(&tombstone)? {
            Some(bytes) => {
                let text = String::from_utf8_lossy(&bytes);
                let digest = line_value(&text, "child").ok_or_else(|| {
                    LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                        "tombstone does not identify its child artifact".into(),
                    )
                })?;
                let generation =
                    line_value(&text, "generation").and_then(|value| value.parse::<u64>().ok());
                if generation != Some(parent_generation + 1) || digest.len() != 64 {
                    return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                        "tombstone generation or child digest is invalid".into(),
                    ));
                }
                Some(digest.to_string())
            }
            None => None,
        };
        Ok(Self {
            child_artifact,
            state,
            route,
            tombstone,
            power_loss_witness,
            parent_route_snapshot,
            parent_state_snapshot,
            parent_route_bytes,
            parent_state_bytes,
            publication,
            resource_sample,
            child_generation: parent_generation + 1,
            parent_generation,
            child_digest,
            counter: 0,
            last_timestamp: 0,
        })
    }

    fn now(&mut self) -> u128 {
        let wall = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |duration| duration.as_nanos());
        self.last_timestamp = wall.max(self.last_timestamp.saturating_add(1));
        self.last_timestamp
    }

    #[allow(clippy::too_many_arguments)]
    fn operation(
        &mut self,
        label: &str,
        artifact_digest: String,
        route_digest: String,
        predecessor_digest: String,
        tombstone_digest: String,
        fault_injection_digest: String,
        receipt_material: &[u8],
    ) -> CellSplitTargetHostOperationReceiptV1 {
        self.counter = self.counter.saturating_add(1);
        let operation_id = format!("local-target-host-operation-{}", self.counter);
        let receipt_digest =
            digest_parts(&[label.as_bytes(), operation_id.as_bytes(), receipt_material]);
        CellSplitTargetHostOperationReceiptV1 {
            operation_id,
            occurred_at_unix_nanos: self.now(),
            artifact_digest,
            route_digest,
            predecessor_digest,
            tombstone_digest,
            fault_injection_digest,
            receipt_digest,
        }
    }

    fn child_digest(&self) -> Result<String, LocalCellSplitTargetHostRuntimeErrorV1> {
        self.child_digest.clone().ok_or_else(|| {
            LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                "child artifact must be loaded before this operation".into(),
            )
        })
    }

    fn atomic_write(
        &self,
        path: &Path,
        bytes: &[u8],
    ) -> Result<(), LocalCellSplitTargetHostRuntimeErrorV1> {
        let temporary = temporary_path(path);
        crate::durable::write_private_atomic_replace(path, &temporary, bytes)
            .map_err(|error| LocalCellSplitTargetHostRuntimeErrorV1::Invalid(error.to_string()))
    }

    fn route_digest(&self) -> Result<String, LocalCellSplitTargetHostRuntimeErrorV1> {
        Ok(digest_bytes(&read_existing(&self.route)?))
    }

    fn ensure_not_tombstoned(&self) -> Result<(), LocalCellSplitTargetHostRuntimeErrorV1> {
        if read_optional(&self.tombstone)?.is_some() {
            return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                "cell generation is tombstoned and cannot be reused".into(),
            ));
        }
        Ok(())
    }

    fn publish_pair(
        &self,
        route_bytes: &[u8],
        state_bytes: &[u8],
        artifact_digest: &str,
        generation: u64,
        status: &str,
    ) -> Result<(), LocalCellSplitTargetHostRuntimeErrorV1> {
        self.atomic_write(&self.route, route_bytes)?;
        self.atomic_write(&self.state, state_bytes)?;
        let publication = make_publication_bytes(
            generation,
            artifact_digest,
            route_bytes,
            state_bytes,
            status,
        );
        self.atomic_write(&self.publication, &publication)
    }

    fn verify_active_pair(
        &self,
        artifact_digest: &str,
        generation: u64,
        status: &str,
    ) -> Result<(Vec<u8>, Vec<u8>), LocalCellSplitTargetHostRuntimeErrorV1> {
        let route = read_existing(&self.route)?;
        let state = read_existing(&self.state)?;
        let publication = read_existing(&self.publication)?;
        verify_publication(&publication, &route, &state)?;
        let publication_text = String::from_utf8_lossy(&publication);
        let expected_generation = generation.to_string();
        if line_value(&publication_text, "generation") != Some(expected_generation.as_str())
            || line_value(&publication_text, "artifact") != Some(artifact_digest)
            || line_value(&publication_text, "status") != Some(status)
        {
            return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                "durable route/state publication fence does not match expected generation".into(),
            ));
        }
        Ok((route, state))
    }
}

impl CellSplitTargetHostRuntimeV1 for LocalCellSplitTargetHostRuntimeV1 {
    type Error = LocalCellSplitTargetHostRuntimeErrorV1;

    fn load_child_artifact(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.ensure_not_tombstoned()?;
        let bytes = read_existing(&self.child_artifact)?;
        if bytes.is_empty() {
            return Err(Self::Error::Invalid("child artifact is empty".into()));
        }
        let digest = digest_bytes(&bytes);
        if let Some(previous) = self.child_digest.as_deref()
            && previous != digest
        {
            return Err(Self::Error::Invalid(
                "child artifact changed after it was loaded".into(),
            ));
        }
        self.child_digest = Some(digest.clone());
        Ok(self.operation(
            "artifact-load",
            digest,
            String::new(),
            String::new(),
            String::new(),
            String::new(),
            &bytes,
        ))
    }

    fn route_cutover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.ensure_not_tombstoned()?;
        let child = self.child_digest()?;
        let _ = self.verify_active_pair("", self.parent_generation, "parent")?;
        let previous = self.route_digest()?;
        let route_bytes = format!(
            "generation={}\nartifact={}\npredecessor={}\n",
            self.child_generation, child, previous
        )
        .into_bytes();
        let state_before = read_existing(&self.state)?;
        let state_bytes = format!(
            "predecessor={}\nroute={}\nartifact={}\nstate={}\n",
            digest_bytes(&state_before),
            digest_bytes(&route_bytes),
            child,
            digest_bytes(&state_before)
        )
        .into_bytes();
        self.publish_pair(
            &route_bytes,
            &state_bytes,
            &child,
            self.child_generation,
            "active",
        )?;
        Ok(self.operation(
            "route-cutover",
            child,
            digest_bytes(&route_bytes),
            previous,
            String::new(),
            String::new(),
            &state_bytes,
        ))
    }

    fn restart_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.ensure_not_tombstoned()?;
        let child = match self.child_digest.clone() {
            Some(digest) => digest,
            None => {
                let bytes = read_existing(&self.child_artifact)?;
                if bytes.is_empty() {
                    return Err(Self::Error::Invalid("child artifact is empty".into()));
                }
                let digest = digest_bytes(&bytes);
                self.child_digest = Some(digest.clone());
                digest
            }
        };
        let (route, state) = self.verify_active_pair(&child, self.child_generation, "active")?;
        let route_text = String::from_utf8_lossy(&route);
        let generation =
            line_value(&route_text, "generation").and_then(|value| value.parse::<u64>().ok());
        let route_artifact = line_value(&route_text, "artifact");
        let state_text = String::from_utf8_lossy(&state);
        let state_route = line_value(&state_text, "route");
        let recovered_route_digest = digest_bytes(&route);
        if generation != Some(self.child_generation)
            || route_artifact != Some(child.as_str())
            || state_route != Some(recovered_route_digest.as_str())
        {
            return Err(Self::Error::Invalid(
                "restart did not recover child route and state".into(),
            ));
        }
        Ok(self.operation(
            "restart-recover",
            child,
            digest_bytes(&route),
            digest_bytes(&state),
            String::new(),
            String::new(),
            &state,
        ))
    }

    fn power_loss_recover(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.ensure_not_tombstoned()?;
        let witness = read_existing(&self.power_loss_witness)
            .map_err(|_| Self::Error::Invalid("external power-loss witness is required".into()))?;
        if witness.is_empty() {
            return Err(Self::Error::Invalid(
                "external power-loss witness is empty".into(),
            ));
        }
        let child = self.child_digest()?;
        let (route, state) = self.verify_active_pair(&child, self.child_generation, "active")?;
        Ok(self.operation(
            "power-loss-recover",
            child,
            digest_bytes(&route),
            digest_bytes(&state),
            String::new(),
            digest_bytes(&witness),
            &witness,
        ))
    }

    fn rollback(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.ensure_not_tombstoned()?;
        let child = self.child_digest()?;
        let _ = self.verify_active_pair(&child, self.child_generation, "active")?;
        let previous = self.route_digest()?;
        let parent_route = read_existing(&self.parent_route_snapshot)?;
        let parent_state = read_existing(&self.parent_state_snapshot)?;
        if parent_route != self.parent_route_bytes || parent_state != self.parent_state_bytes {
            return Err(Self::Error::Invalid(
                "parent route/state snapshot changed after initialization".into(),
            ));
        }
        self.publish_pair(
            &parent_route,
            &parent_state,
            "",
            self.parent_generation,
            "parent",
        )?;
        let route_digest = digest_bytes(&parent_route);
        Ok(self.operation(
            "rollback",
            child,
            route_digest,
            previous,
            String::new(),
            String::new(),
            &parent_state,
        ))
    }

    fn commit_tombstone(&mut self) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        self.ensure_not_tombstoned()?;
        let child = self.child_digest()?;
        let (route, state) = self.verify_active_pair("", self.parent_generation, "parent")?;
        if route != self.parent_route_bytes {
            return Err(Self::Error::Invalid(
                "tombstone requires the parent route after rollback".into(),
            ));
        }
        let bytes = format!(
            "child={}\ngeneration={}\nroute={}\n",
            child,
            self.child_generation,
            digest_bytes(&route)
        )
        .into_bytes();
        self.atomic_write(&self.tombstone, &bytes)?;
        let publication =
            make_publication_bytes(self.child_generation, &child, &route, &state, "tombstoned");
        self.atomic_write(&self.publication, &publication)?;
        let digest = digest_bytes(&bytes);
        Ok(self.operation(
            "tombstone",
            child,
            digest_bytes(&route),
            digest_bytes(&route),
            digest,
            String::new(),
            &bytes,
        ))
    }

    fn verify_no_resurrection(
        &mut self,
    ) -> Result<CellSplitTargetHostOperationReceiptV1, Self::Error> {
        let child = self.child_digest()?;
        let route = read_existing(&self.route)?;
        let tombstone = read_existing(&self.tombstone)?;
        let parent_route = read_existing(&self.parent_route_snapshot)?;
        let publication = read_existing(&self.publication)?;
        let tombstone_text = String::from_utf8_lossy(&tombstone);
        let tombstone_child = line_value(&tombstone_text, "child");
        let tombstone_generation =
            line_value(&tombstone_text, "generation").and_then(|value| value.parse::<u64>().ok());
        let publication_text = String::from_utf8_lossy(&publication);
        let tombstoned_status = line_value(&publication_text, "status") == Some("tombstoned");
        if route != parent_route
            || tombstone.is_empty()
            || tombstone_child != Some(child.as_str())
            || tombstone_generation != Some(self.child_generation)
            || !tombstoned_status
            || String::from_utf8_lossy(&route).contains(&child)
        {
            return Err(Self::Error::Invalid(
                "old route or child generation can still resurrect".into(),
            ));
        }
        Ok(self.operation(
            "no-resurrection",
            child,
            digest_bytes(&route),
            digest_bytes(&parent_route),
            digest_bytes(&tombstone),
            String::new(),
            &tombstone,
        ))
    }

    fn measure_resources(&mut self) -> Result<Vec<CellSplitTargetHostMeasurementV1>, Self::Error> {
        if self.resource_sample.sample_count == 0
            || self.resource_sample.latency_micros == 0
            || self.resource_sample.memory_bytes == 0
            || self.resource_sample.hardware_attestation_digest.len() != 64
        {
            return Err(Self::Error::Resource(
                "resource sample lacks externally reported counters or attestation".into(),
            ));
        }
        let child = self.child_digest()?;
        let route = read_existing(&self.route)?;
        let attestation = self
            .resource_sample
            .hardware_attestation_digest
            .clone()
            .into_bytes();
        Ok(vec![CellSplitTargetHostMeasurementV1 {
            operation: self.operation(
                "resource-measurement",
                child,
                digest_bytes(&route),
                String::new(),
                String::new(),
                String::new(),
                &attestation,
            ),
            sample: self.resource_sample.clone(),
        }])
    }
}

fn read_existing(path: &Path) -> Result<Vec<u8>, LocalCellSplitTargetHostRuntimeErrorV1> {
    crate::durable::secure_read(path, crate::durable::MAX_SMALL_FILE_BYTES)
        .map_err(|error| LocalCellSplitTargetHostRuntimeErrorV1::Invalid(error.to_string()))
}

fn read_optional(path: &Path) -> Result<Option<Vec<u8>>, LocalCellSplitTargetHostRuntimeErrorV1> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                    "optional runtime file must be a regular file".into(),
                ));
            }
            read_existing(path).map(Some)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(LocalCellSplitTargetHostRuntimeErrorV1::Io(error)),
    }
}

fn temporary_path(path: &Path) -> PathBuf {
    let file_name = path
        .file_name()
        .map_or_else(|| "runtime-file".into(), std::ffi::OsStr::to_os_string);
    let mut temporary = file_name;
    temporary.push(".tmp");
    path.with_file_name(temporary)
}

fn make_publication_bytes(
    generation: u64,
    artifact_digest: &str,
    route: &[u8],
    state: &[u8],
    status: &str,
) -> Vec<u8> {
    format!(
        "generation={generation}\nartifact={artifact_digest}\nroute={}\nstate={}\nstatus={status}\n",
        digest_bytes(route),
        digest_bytes(state),
    )
    .into_bytes()
}

fn verify_publication(
    publication: &[u8],
    route: &[u8],
    state: &[u8],
) -> Result<(), LocalCellSplitTargetHostRuntimeErrorV1> {
    let text = String::from_utf8_lossy(publication);
    let route_digest = line_value(&text, "route");
    let state_digest = line_value(&text, "state");
    let expected_route_digest = digest_bytes(route);
    let expected_state_digest = digest_bytes(state);
    if route_digest != Some(expected_route_digest.as_str())
        || state_digest != Some(expected_state_digest.as_str())
        || line_value(&text, "generation").is_none()
        || line_value(&text, "status").is_none()
    {
        return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
            "route/state publication fence is invalid or stale".into(),
        ));
    }
    Ok(())
}

fn load_or_write_parent_snapshot(
    path: &Path,
    initial: &[u8],
) -> Result<Vec<u8>, LocalCellSplitTargetHostRuntimeErrorV1> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
                    "parent snapshot must be a regular file".into(),
                ));
            }
            read_existing(path)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let temporary = temporary_path(path);
            crate::durable::write_private_atomic_replace(path, &temporary, initial).map_err(
                |error| LocalCellSplitTargetHostRuntimeErrorV1::Invalid(error.to_string()),
            )?;
            Ok(initial.to_vec())
        }
        Err(error) => Err(LocalCellSplitTargetHostRuntimeErrorV1::Io(error)),
    }
}

fn verify_parent_snapshot_binding(
    current_route: &[u8],
    current_state: &[u8],
    parent_route: &[u8],
    parent_state: &[u8],
) -> Result<(), LocalCellSplitTargetHostRuntimeErrorV1> {
    let route_text = String::from_utf8_lossy(current_route);
    if let Some(predecessor) = line_value(&route_text, "predecessor")
        && predecessor != digest_bytes(parent_route)
    {
        return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
            "route predecessor does not bind the persisted parent route".into(),
        ));
    }
    let state_text = String::from_utf8_lossy(current_state);
    if let Some(predecessor) = line_value(&state_text, "predecessor")
        && predecessor != digest_bytes(parent_state)
    {
        return Err(LocalCellSplitTargetHostRuntimeErrorV1::Invalid(
            "state predecessor does not bind the persisted parent state".into(),
        ));
    }
    Ok(())
}

fn line_value<'a>(text: &'a str, key: &str) -> Option<&'a str> {
    text.lines().find_map(|line| {
        line.strip_prefix(key)
            .and_then(|value| value.strip_prefix('='))
    })
}

fn digest_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn digest_parts(parts: &[&[u8]]) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update(part);
    }
    format!("{:x}", hasher.finalize())
}

/// Errors from the orchestration seam. An external owner failure is retained
/// as text only; it never becomes a production receipt.
#[derive(Debug, Error)]
pub enum CellSplitTargetHostLifecycleErrorV1 {
    #[error("target-host evidence recorder rejected operation: {0}")]
    Recorder(#[from] CellSplitTargetHostEvidenceErrorV1),
    #[error("target-host runtime owner failed: {0}")]
    Runtime(String),
    #[error("target-host runtime returned no resource measurements")]
    MissingResourceMeasurements,
}

/// Runs the externally supplied host lifecycle and returns an unsigned event
/// payload. The caller must pass the payload to the host signer and an
/// independent observer before the production adapter can issue a receipt.
pub struct CellSplitTargetHostLifecycleRunnerV1<R> {
    runtime: R,
    recorder: CellSplitTargetHostEvidenceRecorderV1,
}

impl<R> CellSplitTargetHostLifecycleRunnerV1<R>
where
    R: CellSplitTargetHostRuntimeV1,
{
    #[must_use]
    pub fn new(runtime: R, recorder: CellSplitTargetHostEvidenceRecorderV1) -> Self {
        Self { runtime, recorder }
    }

    /// Execute the required lifecycle in the same order enforced by the
    /// evidence verifier. Resource samples are inserted after artifact load;
    /// their timestamps and counters come from the external owner.
    pub fn run(
        mut self,
    ) -> Result<CellSplitTargetHostEvidenceV1, CellSplitTargetHostLifecycleErrorV1> {
        let load = self.call(CellSplitTargetHostRuntimeV1::load_child_artifact)?;
        self.append(CellSplitTargetHostEventKindV1::ArtifactLoaded, load, None)?;
        self.append_resources()?;

        let route = self.call(CellSplitTargetHostRuntimeV1::route_cutover)?;
        self.append(CellSplitTargetHostEventKindV1::RouteCutover, route, None)?;
        let restart = self.call(CellSplitTargetHostRuntimeV1::restart_recover)?;
        self.append(
            CellSplitTargetHostEventKindV1::RestartRecovered,
            restart,
            None,
        )?;
        let power_loss = self.call(CellSplitTargetHostRuntimeV1::power_loss_recover)?;
        self.append(
            CellSplitTargetHostEventKindV1::PowerLossRecovered,
            power_loss,
            None,
        )?;
        let rollback = self.call(CellSplitTargetHostRuntimeV1::rollback)?;
        self.append(
            CellSplitTargetHostEventKindV1::RollbackCompleted,
            rollback,
            None,
        )?;
        let tombstone = self.call(CellSplitTargetHostRuntimeV1::commit_tombstone)?;
        self.append(
            CellSplitTargetHostEventKindV1::TombstoneCommitted,
            tombstone,
            None,
        )?;
        let no_resurrection = self.call(CellSplitTargetHostRuntimeV1::verify_no_resurrection)?;
        self.append(
            CellSplitTargetHostEventKindV1::NoResurrectionVerified,
            no_resurrection,
            None,
        )?;

        self.recorder.finish().map_err(Into::into)
    }

    fn append_resources(&mut self) -> Result<(), CellSplitTargetHostLifecycleErrorV1> {
        let measurements = self.call(CellSplitTargetHostRuntimeV1::measure_resources)?;
        if measurements.is_empty() {
            return Err(CellSplitTargetHostLifecycleErrorV1::MissingResourceMeasurements);
        }
        for measurement in measurements {
            self.append(
                CellSplitTargetHostEventKindV1::ResourceMeasurement,
                measurement.operation,
                Some(measurement.sample),
            )?;
        }
        Ok(())
    }

    fn append(
        &mut self,
        kind: CellSplitTargetHostEventKindV1,
        operation: CellSplitTargetHostOperationReceiptV1,
        resource: Option<CellSplitTargetResourceSampleV1>,
    ) -> Result<(), CellSplitTargetHostLifecycleErrorV1> {
        let (sequence, previous_event_digest) = self.recorder.next_event_context();
        let event = crate::CellSplitTargetHostEventV1 {
            sequence,
            event_kind: kind,
            occurred_at_unix_nanos: operation.occurred_at_unix_nanos,
            split_id: self.recorder.split_id().to_string(),
            target_host_id: self.recorder.target_host_id().to_string(),
            parent_generation: self.recorder.parent_generation(),
            child_generation: self.recorder.child_generation(),
            operation_id: operation.operation_id,
            artifact_digest: operation.artifact_digest,
            route_digest: operation.route_digest,
            predecessor_digest: operation.predecessor_digest,
            tombstone_digest: operation.tombstone_digest,
            fault_injection_digest: operation.fault_injection_digest,
            receipt_digest: operation.receipt_digest,
            resource,
            previous_event_digest,
            event_digest: String::new(),
        };
        self.recorder.append(event).map_err(Into::into)
    }

    fn call<T, F>(&mut self, operation: F) -> Result<T, CellSplitTargetHostLifecycleErrorV1>
    where
        F: FnOnce(&mut R) -> Result<T, R::Error>,
    {
        operation(&mut self.runtime)
            .map_err(|error| CellSplitTargetHostLifecycleErrorV1::Runtime(error.to_string()))
    }
}

#[cfg(test)]
#[path = "cell_split_target_host_runtime_tests.rs"]
mod tests;
