//! Test-only original Root registration; never called by an ordinary launcher.
use super::*;
use crate::authority_host_config::*;
use crate::authority_host_runtime::initialize_host_authority;
use crate::authority_host_runtime::open_registered_issuer;
use crate::authority_host_runtime::register_host_writer_authorization;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;

pub(super) struct Fixture {
    pub(super) service: Arc<HostAuthorityService>,
    pub(super) directory: Arc<RootAuthorityDirectory>,
    pub(super) identity: HostAuthorityRegisteredIdentity,
    pub(super) lanes: PathBuf,
    pub(super) binary: PathBuf,
    pub(super) private_path: PathBuf,
    _state: tempfile::TempDir,
    _runtime: tempfile::TempDir,
}

impl Fixture {
    pub(super) fn create() -> anyhow::Result<Self> {
        require_root()?;
        let parent = PathBuf::from(
            std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT")
                .ok_or_else(|| io::Error::other("explicit test-only authority bind required"))?,
        );
        let source = PathBuf::from(
            std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE").ok_or_else(|| {
                io::Error::other("explicit test-only authority bind source required")
            })?,
        );
        let state = tempfile::Builder::new()
            .prefix("learning-registration-")
            .tempdir_in(&parent)?;
        std::fs::set_permissions(state.path(), std::fs::Permissions::from_mode(0o700))?;
        let runtime = tempfile::Builder::new()
            .prefix("learning-peer-")
            .tempdir_in("/run")?;
        std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o755))?;
        let workspace = runtime.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let fleet = HeptaFleetRoot::parse(runtime.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet.clone())?;
        let owner = AgentId::parse(data::AGENT)?;
        registry.register(AgentManifest::new(
            owner.clone(),
            WorkspaceBinding::new(workspace.clone(), &fleet)?,
            ResourceBudget::local_default(),
        )?)?;
        let starting = registry.compare_and_transition(&owner, 0, AgentLifecycle::Starting)?;
        let identity = HostAuthorityRegisteredIdentity {
            agent_id: owner.clone(),
            spawn_generation: starting.generation,
            fleet_root: runtime.path().join("fleet"),
            workspace,
            resources: ResourceBudget::local_default(),
        };
        let metadata = std::fs::metadata(&parent)?;
        let required_bind = HostAuthorityBindIdentity {
            mountpoint: parent,
            source_path: source,
            device: metadata.dev(),
            inode: metadata.ino(),
        };
        let bootstrap = state.path().join("bootstrap.json");
        write_json(
            &bootstrap,
            &serde_json::json!({
                "schema_version": 1, "required_bind": required_bind,
                "signer_id": "learning-root-fixture", "policies": [crate::DeploymentGrantPolicy {
                    subject_id: owner.to_string(), destination_id: "qualification.no-effect".into(),
                    scope_sha256: [2; 32], lifetime_ms: 30000,
                }], "lease_id": "learning-issuer-fixture",
                "lease_binding": AuthorityLeaseBinding {
                    principal_id: owner.to_string(), operation_class: "runtime.agentd.production_operation".into(),
                    destination_id: "qualification.no-effect".into(), scope_sha256: [2; 32], payload_sha256: [3; 32],
                }, "lease_lifetime_ms": 60000,
            }),
        )?;
        let authority = state.path().join("authority");
        let initialized = initialize_host_authority(&authority, &bootstrap)?;
        assert!(!initialized.production_ready);
        let lanes = runtime.path().join("lanes");
        std::fs::create_dir(&lanes)?;
        let lane_c = std::ffi::CString::new(lanes.as_os_str().as_encoded_bytes())?;
        // SAFETY: this NUL-free path is a fresh test-only Root directory.
        assert_eq!(unsafe { libc::chown(lane_c.as_ptr(), 0, 60001) }, 0);
        std::fs::set_permissions(&lanes, std::fs::Permissions::from_mode(0o2710))?;
        let binary = runtime.path().join("original-libtest");
        std::fs::copy(std::env::current_exe()?, &binary)?;
        std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o555))?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis() as u64;
        let writer = crate::HostAuthorityWriterRegistration {
            registered_agent_id: owner.clone(),
            spawn_generation: starting.generation,
            owner_epoch: 1,
            local_lease_id: "learning-local-fixture".into(),
            local_lease_generation: 1,
            authority_lease: AuthorityLease {
                schema_version: 1,
                lease_id: "learning-writer-fixture".into(),
                revision: 1,
                authority_epoch: 1,
                binding: AuthorityLeaseBinding {
                    principal_id: owner.to_string(),
                    operation_class: "runtime.agentd.production_writer".into(),
                    destination_id: "qualification.no-effect.cognitive-owner".into(),
                    scope_sha256: [6; 32],
                    payload_sha256: [7; 32],
                },
                issued_at_unix_ms: now,
                expires_at_unix_ms: now + 60000,
            },
        };
        let config = HostAuthorityServiceConfig {
            issuer_record_profile: HostIssuerRecordProfile::Standard,
            schema_version: 1,
            state_dir: authority.clone(),
            required_bind,
            signer_id: initialized.signer_id,
            expected_verifying_key: initialized.verifying_key,
            lease_id: initialized.lease_id,
            lease_revision: 1,
            writer: Some(writer.clone()),
            checkpoint_state_dir: None,
            consumers: None,
            sockets: HostAuthoritySocketPaths {
                observation: lanes.join("unused-observation"),
                issuer: lanes.join("unused-issuer"),
                checkpoint: lanes.join("unused-cognitive"),
                device_frontier: None,
                notes_frontier: None,
            },
            peer_uid: 60001,
            peer_gid: 60001,
            timeout_ms: 5000,
            lifetime_ms: 30000,
        };
        let config_path = state.path().join("service.json");
        write_json(&config_path, &config)?;
        register_host_writer_authorization(&config_path)?;
        // Registration released its initialization handles. Keep the sole
        // original registry and issuer across every subsequent channel.
        let (clock, leases, issuer) = open_registered_issuer(&config)?;
        let service = Arc::new(
            HostAuthorityService::from_registered_owner(issuer, clock, identity.identity()?)?
                .with_registered_writer(writer, leases.verifier())?
                .retain_original_root_registry(Arc::new(leases)),
        );
        let private_path = authority.join("learning");
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&private_path)?;
        File::open(&authority)?.sync_all()?;
        let directory = RootAuthorityDirectory::open(&private_path)?;
        let initial = data::snapshots()?.remove(0);
        let registration = HostAuthorityFrontierStore::initialize(
            directory.clone(),
            data::OWNER.into(),
            crate::LearningIterationCheckpointRecordV1::vacant(initial.request, initial.owners)?,
        )?;
        drop(registration);
        Ok(Self {
            service,
            directory,
            identity,
            lanes,
            binary,
            private_path,
            _state: state,
            _runtime: runtime,
        })
    }

    pub(super) fn owner(&self) -> anyhow::Result<LearningIterationCheckpointOwnerV1> {
        let initial = data::snapshots()?.remove(0);
        Ok(LearningIterationCheckpointOwnerV1::from_registered(
            HostAuthorityFrontierStore::open(self.directory.clone(), data::OWNER.into())?,
            data::OWNER.into(),
            initial.request,
            initial.owners,
        )?)
    }
}

fn write_json(path: &std::path::Path, value: &impl Serialize) -> io::Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(&serde_json::to_vec(value)?)?;
    file.sync_all()?;
    File::open(
        path.parent()
            .ok_or_else(|| io::Error::other("test parent"))?,
    )?
    .sync_all()
}
