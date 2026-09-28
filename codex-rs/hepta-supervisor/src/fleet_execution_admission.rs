//! Product-owned execution inputs and durable intent at the Unix effect boundary.
//!
//! This does not equate parent exit with descendant quiescence. Physical pins
//! are deliberately retained until the selected-host quiescence owner proves
//! the complete execution scope empty; neither a signal nor expiry releases it.
use super::FleetStartAdmission;
use crate::ProcessDriverError;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::DurableFleetOwner;
use codex_hepta_fleet::FleetAuthorityPort;
use codex_hepta_fleet::FleetExecutionContextV1;
use codex_hepta_fleet::FleetExecutionHoldV1;
use codex_hepta_fleet::FleetReadOnlyFenceV1;
use codex_hepta_fleet::LeaseLedger;
use codex_hepta_fleet::ResourceMappingPolicyV1;
use codex_hepta_fleet::RevocationBoundGrantUseWitnessV1;
use codex_hepta_fleet::SystemFleetClock;
use codex_hepta_fleet::canonical_resource_from_budget_v1;
use codex_hepta_fleet::lock_fleet_snapshot;
use codex_hepta_fleet::map_logical_to_physical_v1;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

const MAX_PROFILE_BYTES: u64 = 1_048_576;
const AUTHORITY_POLL_INTERVAL: Duration = Duration::from_millis(250);

pub(crate) struct ProcessEffect<'a> {
    pub agent_id: &'a AgentId,
    pub common: Value,
    /// None means adoption of a recorded scope, never a new spawn.
    pub dispatch: Option<Value>,
    pub workspace: Option<&'a Path>,
    pub fleet_root: Option<&'a Path>,
    pub home_root: Option<&'a Path>,
    pub run_root: Option<&'a Path>,
    pub matrix_root: Option<&'a Path>,
}

pub(crate) struct ProcessBinding {
    state_root: PathBuf,
    fleet_root: HeptaFleetRoot,
    host_id: String,
    host_generation: u64,
    boot_identity: String,
    mapping: Option<ResourceMappingPolicyV1>,
}

pub(crate) struct ProcessPermit {
    // The shared owner lock remains held until the actual synchronous effect
    // returns, not merely until the validation helper returns.
    _fence: FleetReadOnlyFenceV1,
    hold: FleetExecutionHoldV1,
}

pub(crate) struct ProcessMonitor {
    binding: Arc<ProcessBinding>,
    admission: Arc<FleetStartAdmission>,
    hold: FleetExecutionHoldV1,
    next_check: Instant,
    denied: bool,
}

impl FleetStartAdmission {
    pub(crate) fn capture_process_binding(&self) -> Result<ProcessBinding, ProcessDriverError> {
        let parent = self
            .supervisor_state_root
            .parent()
            .ok_or_else(|| reject("missing fleet root"))?;
        let fleet_root = HeptaFleetRoot::parse(parent).map_err(reject)?;
        if fleet_root.layout().state_root() != self.supervisor_state_root.as_path() {
            return Err(reject(
                "admission state root does not use the canonical fleet layout",
            ));
        }
        let boot_identity = digest_bytes(
            read_physical(Path::new("/proc/sys/kernel/random/boot_id"), 4_096)?.trim_ascii(),
        );
        let configured = (
            optional_environment("HEPTA_FLEET_HOST_ID")?,
            optional_environment("HEPTA_FLEET_FAILURE_DOMAIN_ID")?,
            optional_environment("HEPTA_FLEET_HOST_GENERATION")?,
        );
        let (host_id, failure_domain_id, requested_generation) = match configured {
            (Some(host), Some(domain), Some(generation)) => (
                host,
                domain,
                Some(generation.parse::<u64>().map_err(reject)?),
            ),
            (None, None, None) => {
                let identity =
                    digest_bytes(read_physical(Path::new("/etc/machine-id"), 4_096)?.trim_ascii());
                (
                    format!("host-{}", &identity[..16]),
                    format!("local-{}", &identity[..16]),
                    None,
                )
            }
            _ => {
                return Err(reject(
                    "host identity overrides must be configured together",
                ));
            }
        };
        let fence = lock_fleet_snapshot(&self.supervisor_state_root, Arc::new(SystemFleetClock))
            .map_err(reject)?;
        let incarnation = fence
            .snapshot
            .state
            .fleet_host_incarnations
            .get(&host_id)
            .ok_or_else(|| reject("observed local host has no committed incarnation"))?;
        if incarnation.boot_identity != boot_identity
            || incarnation.failure_domain_id != failure_domain_id
            || requested_generation
                .is_some_and(|generation| generation != incarnation.host_generation)
        {
            return Err(reject(
                "observed local boot differs from the committed incarnation",
            ));
        }
        let mapping = std::env::var_os("HEPTA_FLEET_RESOURCE_MAPPING_PROFILE")
            .map(|path| {
                let path = PathBuf::from(path);
                if !path.is_absolute() || path.starts_with(fleet_root.as_path()) {
                    return Err(reject(
                        "mapping profile must be an absolute operator path outside fleet state",
                    ));
                }
                let policy: ResourceMappingPolicyV1 =
                    serde_json::from_slice(&read_physical(&path, MAX_PROFILE_BYTES)?)
                        .map_err(reject)?;
                policy.validate().map_err(reject)?;
                Ok(policy)
            })
            .transpose()?;
        Ok(ProcessBinding {
            state_root: self.supervisor_state_root.clone(),
            fleet_root,
            host_id,
            host_generation: incarnation.host_generation,
            boot_identity,
            mapping,
        })
    }
}

impl ProcessBinding {
    pub(crate) fn prepare(
        &self,
        admission: &FleetStartAdmission,
        effect: ProcessEffect<'_>,
    ) -> Result<ProcessPermit, ProcessDriverError> {
        let manifest =
            AgentManifest::read_registered(&self.fleet_root, effect.agent_id).map_err(reject)?;
        let layout = self.fleet_root.layout().agent(effect.agent_id);
        for (actual, expected) in [
            (effect.workspace, manifest.workspace.as_path()),
            (effect.fleet_root, self.fleet_root.as_path()),
            (effect.home_root, layout.home_root()),
            (effect.run_root, layout.run_root()),
            (effect.matrix_root, layout.matrix_root()),
        ] {
            if actual.is_some_and(|actual| actual != expected) {
                return Err(reject(
                    "physical process specification differs from its registered layout",
                ));
            }
        }
        let logical = canonical_resource_from_budget_v1(&manifest.resources).map_err(reject)?;
        let (resources, mapping_sha256) = match &self.mapping {
            Some(policy) => {
                let mapped = map_logical_to_physical_v1(logical, policy).map_err(reject)?;
                (mapped.physical, Some(mapped.policy_sha256))
            }
            // No invented CPU conversion: a logical grant must cover all
            // logical axes, or the operator must pin a reviewed mapping.
            None => (logical, None),
        };
        let encoded = serde_json::to_vec(&json!({
            "schema": "hepta.runtime.fleet.process-context.v1",
            "fleet_root_os_bytes": self.fleet_root.as_path().as_os_str().as_encoded_bytes(),
            "manifest": manifest,
            "process": effect.common,
            "mapping_sha256": mapping_sha256,
        }))
        .map_err(reject)?;
        let context = FleetExecutionContextV1 {
            principal_id: effect.agent_id.to_string(),
            host_id: self.host_id.clone(),
            host_generation: self.host_generation,
            boot_identity: self.boot_identity.clone(),
            resources,
            execution_sha256: digest_bytes(&encoded),
        };
        let witness = admission
            .verify_agent_start(effect.agent_id)
            .map_err(reject)?;
        let hold = if let Some(dispatch) = effect.dispatch {
            let effect_id = format!(
                "process-{}",
                digest_bytes(
                    &serde_json::to_vec(&json!({
                        "schema": "hepta.runtime.fleet.unix-dispatch.v1",
                        "context": context,
                        "dispatch": dispatch,
                    }))
                    .map_err(reject)?
                )
            );
            let mut owner = DurableFleetOwner::open_supervisor_state_root(
                &self.state_root,
                Arc::new(SystemFleetClock),
            )
            .map_err(reject)?;
            owner
                .prepare_execution(&effect_id, context, &witness)
                .map_err(reject)?
        } else {
            let fence = lock_fleet_snapshot(&self.state_root, Arc::new(SystemFleetClock))
                .map_err(reject)?;
            let mut matching = fence
                .snapshot
                .state
                .fleet_execution_holds
                .values()
                .filter(|hold| {
                    hold.context == context
                        && hold.grant.allocation_id == witness.grant.allocation_id
                });
            let hold = matching
                .next()
                .cloned()
                .ok_or_else(|| reject("adoption has no matching durable execution intent"))?;
            if matching.next().is_some() {
                return Err(reject("adoption has ambiguous durable execution intents"));
            }
            hold
        };
        let fence =
            lock_fleet_snapshot(&self.state_root, Arc::new(SystemFleetClock)).map_err(reject)?;
        self.validate_fence(&fence, &hold, &witness)?;
        Ok(ProcessPermit {
            _fence: fence,
            hold,
        })
    }

    fn validate_fence(
        &self,
        fence: &FleetReadOnlyFenceV1,
        hold: &FleetExecutionHoldV1,
        witness: &RevocationBoundGrantUseWitnessV1,
    ) -> Result<(), ProcessDriverError> {
        let state = &fence.snapshot.state;
        if state.fleet_execution_holds.get(&hold.effect_id) != Some(hold) {
            return Err(reject(
                "execution intent changed before the physical effect",
            ));
        }
        let incarnation = state
            .fleet_host_incarnations
            .get(&self.host_id)
            .ok_or_else(|| reject("local host incarnation disappeared"))?;
        if incarnation.boot_identity != self.boot_identity
            || incarnation.host_generation != self.host_generation
        {
            return Err(reject(
                "local incarnation changed before the physical effect",
            ));
        }
        let revocation = state
            .fleet_revocation_frontier
            .as_ref()
            .ok_or_else(|| reject("revocation snapshot is unavailable"))?;
        if revocation.semantic_digest().map_err(reject)? != witness.revocation_snapshot_sha256 {
            return Err(reject("revocation cut changed before the physical effect"));
        }
        let ledger =
            LeaseLedger::from_snapshot(Arc::new(SystemFleetClock), state.fleet_grants.clone())
                .map_err(reject)?;
        let current = FleetAuthorityPort::verify_final_use(
            &ledger,
            &hold.grant.allocation_id,
            witness.grant.lease_generation,
            &self.host_id,
            self.host_generation,
            &hold.grant.semantic_digest,
        )
        .map_err(reject)?;
        let grant = state
            .fleet_grants
            .active_grants
            .get(&hold.grant.allocation_id)
            .ok_or_else(|| reject("grant is no longer active"))?;
        if current.principal_id != hold.context.principal_id
            || current.allocation_id != witness.grant.allocation_id
            || !hold.context.resources.fits(grant.resources)
        {
            return Err(reject(
                "execution principal or resource requirement differs from the grant",
            ));
        }
        Ok(())
    }
}

impl ProcessPermit {
    pub(crate) fn into_monitor(
        self,
        binding: Arc<ProcessBinding>,
        admission: Arc<FleetStartAdmission>,
    ) -> ProcessMonitor {
        ProcessMonitor {
            binding,
            admission,
            hold: self.hold,
            next_check: Instant::now(),
            denied: false,
        }
        // Dropping the permit's remaining fence unlocks only after spawn/adopt
        // returned. It never deletes the durable physical-use pin.
    }
}

impl ProcessMonitor {
    pub(crate) fn authority_denied(&mut self) -> bool {
        if self.denied || Instant::now() < self.next_check {
            return self.denied;
        }
        self.next_check = Instant::now() + AUTHORITY_POLL_INTERVAL;
        let result = AgentId::parse(&self.hold.context.principal_id)
            .map_err(reject)
            .and_then(|agent| self.admission.verify_agent_start(&agent).map_err(reject))
            .and_then(|witness| {
                let fence =
                    lock_fleet_snapshot(&self.binding.state_root, Arc::new(SystemFleetClock))
                        .map_err(reject)?;
                self.binding.validate_fence(&fence, &self.hold, &witness)
            });
        self.denied = result.is_err();
        self.denied
    }
}

fn digest_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn read_physical(path: &Path, maximum: u64) -> Result<Vec<u8>, ProcessDriverError> {
    use std::fs::OpenOptions;
    if !path.is_absolute() || path.canonicalize().map_err(reject)?.as_path() != path {
        return Err(reject("host input must be a physical absolute path"));
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    let file = options.open(path).map_err(reject)?;
    let metadata = file.metadata().map_err(reject)?;
    if !metadata.is_file() || metadata.len() > maximum {
        return Err(reject("host input is not a bounded regular file"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let owner = metadata.uid();
        if metadata.mode() & 0o022 != 0
            || (owner != 0 && owner != rustix::process::geteuid().as_raw())
        {
            return Err(reject(
                "host input must be operator-owned and not group/world writable",
            ));
        }
    }
    let mut bytes = Vec::new();
    file.take(
        maximum
            .checked_add(1)
            .ok_or_else(|| reject("host input bound overflow"))?,
    )
    .read_to_end(&mut bytes)
    .map_err(reject)?;
    if bytes.trim_ascii().is_empty() || u64::try_from(bytes.len()).map_err(reject)? > maximum {
        return Err(reject("host input is empty or oversized"));
    }
    Ok(bytes)
}

fn reject(error: impl std::fmt::Display) -> ProcessDriverError {
    ProcessDriverError::new(format!("runtime.fleet execution admission: {error}"))
}

fn optional_environment(name: &str) -> Result<Option<String>, ProcessDriverError> {
    match std::env::var(name) {
        Ok(value) => Ok(Some(value)),
        Err(std::env::VarError::NotPresent) => Ok(None),
        Err(std::env::VarError::NotUnicode(_)) => Err(reject(format!("{name} is not UTF-8"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn host_input_reader_is_bounded_and_does_not_create_missing_files() {
        let directory = tempfile::tempdir().expect("tempdir");
        let file = directory.path().join("input");
        assert!(read_physical(&file, 8).is_err());
        assert!(!file.exists());
        std::fs::write(&file, b"value").expect("input");
        assert_eq!(read_physical(&file, 8).expect("read"), b"value");
        assert!(read_physical(&file, 4).is_err());
        std::fs::write(&file, b" \n").expect("blank");
        assert!(read_physical(&file, 8).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn host_input_rejects_symlinks_and_writable_operator_profiles() {
        use std::os::unix::fs::PermissionsExt;
        let directory = tempfile::tempdir().expect("tempdir");
        let file = directory.path().join("profile");
        let link = directory.path().join("link");
        std::fs::write(&file, b"value").expect("profile");
        std::os::unix::fs::symlink(&file, &link).expect("link");
        assert!(read_physical(&link, 8).is_err());
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o666)).expect("mode");
        assert!(read_physical(&file, 8).is_err());
    }
}
