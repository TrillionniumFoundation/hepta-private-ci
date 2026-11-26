//! Owner-bound, durable recovery observations with deterministic replay.
//!
//! Callers publish this object while holding the supervisor owner boundary.
//! Recovery consumes one immutable observation instead of joining filesystem,
//! process and authority facts collected at unrelated times.

use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::AgentSupervisorSnapshot;
use crate::ProcessExitWitnessPhaseV1;
use crate::ProcessExitWitnessV1;
use crate::RecoveryBlockerKind;
use crate::RecoveryDiagnosticContext;
use crate::diagnose_recovery;
use crate::process_exit_witness::read_process_exit_witness;

pub const PRODUCTION_RECOVERY_OBSERVATION_SCHEMA_VERSION: u32 = 1;
pub const PRODUCTION_RECOVERY_OBSERVATION_FILE: &str =
    "supervisor-production-recovery-observation.json";
const RECOVERY_OBSERVATION_DOMAIN: &[u8] = b"hepta-supervisor:production-recovery-observation:v1";
const MAX_RECOVERY_OBSERVATION_BYTES: usize = 65_536;
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryReplayDecisionV1 {
    Clean,
    ContinueOwnedProcess,
    FinalizeObservedExit,
    RejectStaleGeneration,
    RequiresOperator,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionRecoveryObservationV1 {
    pub schema_version: u32,
    pub observation_id: Sha256Digest,
    pub agent_id: AgentId,
    pub supervisor_epoch: String,
    pub lifecycle: AgentLifecycle,
    pub lifecycle_generation: u64,
    pub control_revision: u64,
    pub read_snapshot_epoch: u64,
    pub process_active: bool,
    pub process_healthy: bool,
    pub process_system_id: Option<u64>,
    pub spawn_generation: Option<u64>,
    pub runtime_generation: Option<u64>,
    pub runtime_incarnation: Option<String>,
    pub runtime_fenced: bool,
    pub process_lease_present: bool,
    pub exit_witness: Option<ProcessExitWitnessV1>,
    pub recovery_required: bool,
    pub blockers: Vec<RecoveryBlockerKind>,
    pub observed_unix_ms: u64,
    pub observer_process_id: u32,
    pub record_sha256: Sha256Digest,
}

#[derive(Debug, Error)]
pub enum RecoveryObservationError {
    #[error("recovery observation is invalid: {0}")]
    Invalid(String),
    #[error("recovery observation digest mismatch")]
    DigestMismatch,
    #[error(transparent)]
    ExitWitness(#[from] crate::ProcessExitWitnessError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

// A derived tuple struct retains the canonical JSON array and nested field
// order without serde's sixteen-element anonymous-tuple implementation limit.
#[derive(Serialize)]
struct ObservationIdentityPayloadV1<'a>(
    u32,
    &'a AgentId,
    &'a str,
    AgentLifecycle,
    u64,
    u64,
    u64,
    bool,
    bool,
    Option<u64>,
    Option<u64>,
    Option<u64>,
    &'a Option<String>,
    bool,
    bool,
    &'a Option<ProcessExitWitnessV1>,
    bool,
    &'a [RecoveryBlockerKind],
    u64,
    u32,
);

impl ProductionRecoveryObservationV1 {
    fn validate(&self) -> Result<(), RecoveryObservationError> {
        if self.schema_version != PRODUCTION_RECOVERY_OBSERVATION_SCHEMA_VERSION
            || self.supervisor_epoch.is_empty()
            || self.supervisor_epoch.len() > 128
            || !self.supervisor_epoch.is_ascii()
            // A never-started Agent may legitimately remain at lifecycle generation zero.
            || self.read_snapshot_epoch < self.control_revision
            || self.observed_unix_ms == 0
            || self.observer_process_id == 0
            || self.process_active != self.process_system_id.is_some()
            || self.process_active != self.runtime_incarnation.is_some()
            || self.process_active != self.spawn_generation.is_some()
            || self.process_active != self.runtime_generation.is_some()
        {
            return Err(RecoveryObservationError::Invalid(
                "epoch, generation, process identity or observation time is outside its bounds"
                    .to_string(),
            ));
        }
        if self.observation_id != self.compute_observation_id()?
            || self.record_sha256 != self.compute_record_digest()?
        {
            return Err(RecoveryObservationError::DigestMismatch);
        }
        Ok(())
    }

    fn compute_observation_id(&self) -> Result<Sha256Digest, RecoveryObservationError> {
        let payload = serde_json::to_vec(&ObservationIdentityPayloadV1(
            self.schema_version,
            &self.agent_id,
            &self.supervisor_epoch,
            self.lifecycle,
            self.lifecycle_generation,
            self.control_revision,
            self.read_snapshot_epoch,
            self.process_active,
            self.process_healthy,
            self.process_system_id,
            self.spawn_generation,
            self.runtime_generation,
            &self.runtime_incarnation,
            self.runtime_fenced,
            self.process_lease_present,
            &self.exit_witness,
            self.recovery_required,
            &self.blockers,
            self.observed_unix_ms,
            self.observer_process_id,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [RECOVERY_OBSERVATION_DOMAIN, payload.as_slice()].concat(),
        )))
    }

    fn compute_record_digest(&self) -> Result<Sha256Digest, RecoveryObservationError> {
        let payload = serde_json::to_vec(&self.observation_id)?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [RECOVERY_OBSERVATION_DOMAIN, b":record:", payload.as_slice()].concat(),
        )))
    }
}

pub fn publish_production_recovery_observation(
    run_root: &Path,
    agent_id: &AgentId,
    supervisor_epoch: &str,
    lifecycle: AgentLifecycle,
    lifecycle_generation: u64,
    snapshot: &AgentSupervisorSnapshot,
    current_authority_epoch: Option<u64>,
    current_admission_frontier_sha256: Option<Sha256Digest>,
) -> Result<ProductionRecoveryObservationV1, RecoveryObservationError> {
    let exit_witness = read_process_exit_witness(run_root)?;
    let process_lease_present = crate::lease::read_lease(run_root)
        .map_err(|error| RecoveryObservationError::Invalid(error.to_string()))?
        .is_some();
    let diagnostic = diagnose_recovery(
        run_root,
        &RecoveryDiagnosticContext {
            live_process_present: snapshot.active,
            observed_release: snapshot.runtime_release.clone(),
            current_authority_epoch,
            current_admission_frontier_sha256,
        },
    );
    let observed_unix_ms = unix_ms_now()?;
    let observer_process_id = std::process::id();
    let mut observation = ProductionRecoveryObservationV1 {
        schema_version: PRODUCTION_RECOVERY_OBSERVATION_SCHEMA_VERSION,
        observation_id: Sha256Digest::for_bytes(b"pending"),
        agent_id: agent_id.clone(),
        supervisor_epoch: supervisor_epoch.to_string(),
        lifecycle,
        lifecycle_generation,
        control_revision: snapshot.control_revision,
        read_snapshot_epoch: snapshot.control_revision,
        process_active: snapshot.active,
        process_healthy: snapshot.healthy,
        process_system_id: snapshot.process_system_id,
        spawn_generation: snapshot.spawn_generation,
        runtime_generation: snapshot.runtime_generation,
        runtime_incarnation: snapshot.runtime_incarnation.clone(),
        runtime_fenced: snapshot.runtime_fenced,
        process_lease_present,
        exit_witness,
        recovery_required: diagnostic.recovery_required,
        blockers: diagnostic
            .blockers
            .into_iter()
            .map(|blocker| blocker.kind)
            .collect(),
        observed_unix_ms,
        observer_process_id,
        record_sha256: Sha256Digest::for_bytes(b"pending"),
    };
    observation.observation_id = observation.compute_observation_id()?;
    observation.record_sha256 = observation.compute_record_digest()?;
    observation.validate()?;
    write_observation(run_root, &observation)?;
    Ok(observation)
}

pub fn replay_production_recovery_observation(
    observation: &ProductionRecoveryObservationV1,
) -> Result<RecoveryReplayDecisionV1, RecoveryObservationError> {
    observation.validate()?;
    if observation.recovery_required || !observation.blockers.is_empty() {
        return Ok(RecoveryReplayDecisionV1::RequiresOperator);
    }
    if observation.process_active
        && (observation.runtime_fenced
            || observation.runtime_generation != Some(observation.lifecycle_generation))
    {
        return Ok(RecoveryReplayDecisionV1::RejectStaleGeneration);
    }
    if observation.process_active {
        if let Some(witness) = observation.exit_witness.as_ref()
            && witness.phase == ProcessExitWitnessPhaseV1::Observed
            && witness.process_identity.system_id() == observation.process_system_id.unwrap_or(0)
            && witness.process_identity.incarnation()
                == observation
                    .runtime_incarnation
                    .as_deref()
                    .unwrap_or_default()
        {
            return Ok(RecoveryReplayDecisionV1::RequiresOperator);
        }
        return Ok(RecoveryReplayDecisionV1::ContinueOwnedProcess);
    }
    if observation
        .exit_witness
        .as_ref()
        .is_some_and(|witness| witness.phase == ProcessExitWitnessPhaseV1::Observed)
    {
        return Ok(RecoveryReplayDecisionV1::FinalizeObservedExit);
    }
    Ok(RecoveryReplayDecisionV1::Clean)
}

pub fn read_production_recovery_observation(
    run_root: &Path,
) -> Result<Option<ProductionRecoveryObservationV1>, RecoveryObservationError> {
    let path = run_root.join(PRODUCTION_RECOVERY_OBSERVATION_FILE);
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    let mut file = match options.open(&path) {
        Ok(file) => file,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let metadata = file.metadata()?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_RECOVERY_OBSERVATION_BYTES as u64
    {
        return Err(RecoveryObservationError::Invalid(
            "recovery observation is not a bounded regular file".to_string(),
        ));
    }
    let mut bytes = Vec::new();
    (&mut file)
        .take((MAX_RECOVERY_OBSERVATION_BYTES + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_RECOVERY_OBSERVATION_BYTES || bytes.len() as u64 != metadata.len() {
        return Err(RecoveryObservationError::Invalid(
            "recovery observation changed while being read or exceeds its bound".to_string(),
        ));
    }
    let observation: ProductionRecoveryObservationV1 = serde_json::from_slice(&bytes)?;
    observation.validate()?;
    Ok(Some(observation))
}

fn write_observation(
    run_root: &Path,
    observation: &ProductionRecoveryObservationV1,
) -> Result<(), RecoveryObservationError> {
    observation.validate()?;
    std::fs::create_dir_all(run_root)?;
    let bytes = serde_json::to_vec(observation)?;
    if bytes.len() > MAX_RECOVERY_OBSERVATION_BYTES {
        return Err(RecoveryObservationError::Invalid(
            "recovery observation exceeds its file bound".to_string(),
        ));
    }
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| RecoveryObservationError::Invalid("system clock before epoch".to_string()))?
        .as_nanos();
    let staging = run_root.join(format!(
        ".{PRODUCTION_RECOVERY_OBSERVATION_FILE}.{nanos}.{sequence}.tmp"
    ));
    let destination = run_root.join(PRODUCTION_RECOVERY_OBSERVATION_FILE);
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    let mut file = options.open(&staging)?;
    if let Err(error) = (|| -> std::io::Result<()> {
        file.write_all(&bytes)?;
        file.sync_all()?;
        crate::durable_publish::publish(&staging, &destination)
    })() {
        let _ = std::fs::remove_file(&staging);
        return Err(error.into());
    }
    Ok(())
}

fn unix_ms_now() -> Result<u64, RecoveryObservationError> {
    let millis = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| RecoveryObservationError::Invalid("system clock before epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| RecoveryObservationError::Invalid("system clock exceeds u64".to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ProcessIdentity;
    use codex_hepta_fleet::ReleaseId;

    fn observation(
        incarnation: Option<&str>,
        witness_incarnation: Option<&str>,
    ) -> ProductionRecoveryObservationV1 {
        let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent");
        let exit_witness = witness_incarnation.map(|incarnation| {
            let mut witness = crate::process_exit_witness::ProcessExitWitnessV1 {
                schema_version: crate::PROCESS_EXIT_WITNESS_SCHEMA_VERSION,
                witness_id: Sha256Digest::for_bytes(b"test-witness"),
                agent_id: agent.clone(),
                lifecycle_generation: 7,
                spawn_generation: 5,
                release_id: ReleaseId::parse("release-a").expect("release"),
                process_identity: ProcessIdentity::new(41, incarnation).expect("identity"),
                success: false,
                code: None,
                observed_unix_ms: 1,
                observer_process_id: 1,
                phase: ProcessExitWitnessPhaseV1::Observed,
                record_sha256: Sha256Digest::for_bytes(b"test-record"),
            };
            // Unit replay tests construct an internally consistent observation
            // without publishing a forged witness through the filesystem API.
            witness.witness_id = witness.compute_witness_id().expect("witness id");
            witness.record_sha256 = witness.compute_record_digest().expect("record id");
            witness
        });
        let mut value = ProductionRecoveryObservationV1 {
            schema_version: PRODUCTION_RECOVERY_OBSERVATION_SCHEMA_VERSION,
            observation_id: Sha256Digest::for_bytes(b"pending"),
            agent_id: agent,
            supervisor_epoch: "00000000-0000-4000-8000-000000000002".to_string(),
            lifecycle: AgentLifecycle::Running,
            lifecycle_generation: 7,
            control_revision: 3,
            read_snapshot_epoch: 3,
            process_active: incarnation.is_some(),
            process_healthy: incarnation.is_some(),
            process_system_id: incarnation.map(|_| 41),
            spawn_generation: incarnation.map(|_| 5),
            runtime_generation: incarnation.map(|_| 7),
            runtime_incarnation: incarnation.map(str::to_string),
            runtime_fenced: false,
            process_lease_present: incarnation.is_some(),
            exit_witness,
            recovery_required: false,
            blockers: Vec::new(),
            observed_unix_ms: 1,
            observer_process_id: 1,
            record_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        value.observation_id = value.compute_observation_id().expect("observation id");
        value.record_sha256 = value.compute_record_digest().expect("record id");
        value
    }

    #[test]
    fn exact_exit_without_live_owner_is_replayed_deterministically() {
        let value = observation(None, Some("boot-a:41"));
        assert_eq!(
            replay_production_recovery_observation(&value).expect("first replay"),
            RecoveryReplayDecisionV1::FinalizeObservedExit
        );
        assert_eq!(
            replay_production_recovery_observation(&value).expect("second replay"),
            RecoveryReplayDecisionV1::FinalizeObservedExit
        );
    }

    #[test]
    fn pid_reuse_does_not_turn_an_old_exit_into_current_absence() {
        let value = observation(Some("boot-a:99"), Some("boot-a:41"));
        assert_eq!(
            replay_production_recovery_observation(&value).expect("replay"),
            RecoveryReplayDecisionV1::ContinueOwnedProcess
        );
    }

    #[test]
    fn exact_live_and_exit_identity_conflict_requires_operator() {
        let value = observation(Some("boot-a:41"), Some("boot-a:41"));
        assert_eq!(
            replay_production_recovery_observation(&value).expect("replay"),
            RecoveryReplayDecisionV1::RequiresOperator
        );
    }
}
