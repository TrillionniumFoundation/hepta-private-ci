//! Fresh installation of the existing Root owners, before spawning a Host.
//! This path never opens or repairs a previous installation as fresh state.
use super::*;
use crate::HostAuthorityBindIdentity;
use crate::HostAuthorityConsumerConfig;
use crate::HostAuthorityConsumersConfig;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityServiceConfig;
use crate::HostAuthoritySocketPaths;
use crate::HostAuthorityWriterRegistration;
use crate::HostCognitiveCheckpoint;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_types::Digest32;
use sha2::Digest;
use sha2::Sha256;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

/// Trusted Root installation input. The original Fleet record and empty owner
/// directory must already exist. The bundle digest names actual installed
/// bytes, not a policy template. No field is accepted on an ordinary wire.
pub struct RootNotesFreshAuthorityInput {
    pub state_dir: PathBuf,
    pub required_bind: HostAuthorityBindIdentity,
    pub identity: HostAuthorityRegisteredIdentity,
    pub installed_manifest_sha256: Digest32,
    pub signer_id: String,
    pub lease_lifetime_ms: u64,
}

/// Owns one fresh original issuer/clock/registry and a real fresh SQLite cut.
/// Consuming `assemble_for_host` prevents a second assembly from this object.
pub struct RootNotesFreshAuthority {
    config: HostAuthorityServiceConfig,
    identity: HostAuthorityRegisteredIdentity,
    clock: Arc<HostAuthorityClock>,
    leases: Arc<AuthorityLeaseRegistry>,
    issuer: Arc<DeploymentFinalUseIssuer>,
    initial: CognitiveRecoveryAnchor,
    archive: PathBuf,
}

impl RootNotesFreshAuthority {
    /// Initialize genuinely new state. An existing bootstrap, authority child,
    /// cognitive file or partial previous attempt is an error; nothing resets.
    /// Slow original SQLite initialization precedes the real lease's clock.
    pub async fn initialize(input: RootNotesFreshAuthorityInput) -> io::Result<Self> {
        if unsafe { libc::geteuid() } != 0 || input.installed_manifest_sha256.is_zero()
            || input.identity.spawn_generation != 1 || !(1..=300_000).contains(&input.lease_lifetime_ms)
        { return Err(invalid("fresh Root Notes installation input")); }
        input.required_bind.verify()?;
        let parent = input.state_dir.parent().ok_or_else(|| invalid("authority parent"))?;
        RootAuthorityDirectory::open(parent).map_err(io::Error::other)?;
        if !input.state_dir.is_absolute() || parent.canonicalize()? != parent
            || !input.state_dir.starts_with(&input.required_bind.mountpoint)
            || input.state_dir == input.required_bind.mountpoint
        { return Err(invalid("fresh authority must be a private bound child")); }
        require_absent(&input.state_dir)?;
        let bootstrap = input.state_dir.with_extension("notes-bootstrap.json");
        require_absent(&bootstrap)?;
        let identity = input.identity.identity()?;
        let cognitive = identity.layout.cognitive_root();
        for ancestor in cognitive.ancestors() {
            let entry = std::fs::symlink_metadata(ancestor)?;
            if !entry.is_dir() || entry.uid()!=0 || entry.mode() & 0o022 != 0 {
                return Err(invalid("fresh owner ancestors must remain Root controlled until handoff"));
            }
        }
        let metadata = std::fs::symlink_metadata(cognitive)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0
            || std::fs::read_dir(cognitive)?.next().is_some()
        { return Err(invalid("fresh cognitive owner must be empty and Root controlled")); }
        let store = CognitiveStore::open(&identity.layout).await.map_err(io::Error::other)?;
        let initial = store.recovery_anchor().await.map_err(io::Error::other)?;
        store.close().await;
        let scope = crate::objective_runtime::objective_scope(&identity);
        // A real Objective profile route is the sole initial policy. There is
        // no fabricated Notes incarnation or Device target. First actual Notes
        // reservation installs its policy through the original exact CAS.
        let route = DeploymentFinalUseIssuer::OBJECTIVE_DESTINATION;
        let document = crate::authority_host_runtime::HostAuthorityBootstrap {
            schema_version:1, required_bind:input.required_bind.clone(), signer_id:input.signer_id,
            policies:vec![crate::DeploymentGrantPolicy { subject_id:identity.agent_id.to_string(),
                destination_id:route.into(), scope_sha256:*scope.as_array(), lifetime_ms:input.lease_lifetime_ms }],
            lease_id:"organ.notes.root-authorization.1".into(),
            lease_binding:AuthorityLeaseBinding { principal_id:identity.agent_id.to_string(),
                operation_class:"runtime.agentd.production_operation".into(), destination_id:route.into(),
                scope_sha256:*scope.as_array(), payload_sha256:*input.installed_manifest_sha256.as_array() },
            lease_lifetime_ms:input.lease_lifetime_ms,
        };
        write_new_root_json(&bootstrap, &document)?;
        let initialized = crate::initialize_host_authority(&input.state_dir, &bootstrap)?;
        let checkpoint = input.state_dir.join("checkpoint");
        let archive = input.state_dir.join("material");
        for path in [&checkpoint,&archive] { std::fs::DirBuilder::new().mode(0o700).create(path)?; }
        File::open(&input.state_dir)?.sync_all()?;
        let mut config = HostAuthorityServiceConfig {
            schema_version:1, state_dir:input.state_dir.clone(), required_bind:input.required_bind,
            signer_id:initialized.signer_id, expected_verifying_key:initialized.verifying_key,
            lease_id:initialized.lease_id, lease_revision:1, writer:None,
            checkpoint_state_dir:Some(checkpoint), consumers:None,
            // Filled once from the fixed actual launch locations below.
            sockets:HostAuthoritySocketPaths { observation:PathBuf::new(), issuer:PathBuf::new(),
                checkpoint:PathBuf::new(), device_frontier:None, notes_frontier:None },
            peer_uid:60001, peer_gid:60001, timeout_ms:500, lifetime_ms:input.lease_lifetime_ms,
        };
        let (clock,leases,issuer) = crate::authority_host_runtime::open_registered_issuer(&config)?;
        let now = clock.now_unix_ms().map_err(io::Error::other)?;
        // Match the actual existing administrative lease end; creating a
        // writer after I/O must not extend the installation's authorization.
        let expiry = issuer.with_live_lease(|lease| Ok(lease.expires_at_unix_ms))?;
        let registration = HostAuthorityWriterRegistration {
            registered_agent_id:identity.agent_id.clone(), spawn_generation:1, owner_epoch:1,
            local_lease_id:"organ.notes.local-writer".into(), local_lease_generation:1,
            authority_lease:AuthorityLease { schema_version:1, lease_id:"organ.notes.writer.1".into(),
                revision:1, authority_epoch:1, binding:AuthorityLeaseBinding {
                    principal_id:identity.agent_id.to_string(), operation_class:"runtime.agentd.production_writer".into(),
                    destination_id:format!("cognitive.owner:{}",identity.agent_id),
                    scope_sha256:Sha256::digest(serde_json::to_vec(&(identity.agent_id.clone(),cognitive))?).into(),
                    payload_sha256:Sha256::digest(serde_json::to_vec(&initial)?).into(),
                }, issued_at_unix_ms:now, expires_at_unix_ms:expiry },
        };
        registration.validate()?;
        leases.put_lease(registration.authority_lease.clone(), /*expected_revision*/ 0).map_err(io::Error::other)?;
        issuer.register_writer_authorization(&registration,&leases.verifier())?;
        config.writer = Some(registration);
        let key = issuer.trust_key()?;
        let head = issuer.revocations()?;
        let mut consumers = Vec::new();
        for name in ["consumer-device","consumer-notes"] {
            let path = input.state_dir.join(name);
            std::fs::DirBuilder::new().mode(0o700).create(&path)?;
            File::open(&input.state_dir)?.sync_all()?;
            crate::HostConsumerFrontier::initialize_fresh(RootAuthorityDirectory::open(&path).map_err(io::Error::other)?,
                key.key_id.clone(),&head,clock.clone(),expiry).map_err(io::Error::other)?;
            consumers.push(HostAuthorityConsumerConfig {state_dir:path,owner_id:key.key_id.clone()});
        }
        let [device,notes]: [_;2] = consumers.try_into().map_err(|_| invalid("two original consumers"))?;
        config.consumers = Some(HostAuthorityConsumersConfig {device,notes});
        Ok(Self { config, identity:input.identity, clock, leases:Arc::new(leases), issuer, initial, archive })
    }

    pub fn issuer_key(&self) -> io::Result<crate::HostAuthorityPublicIssuerKeyV1> {
        Ok(self.issuer.trust_key()?.into())
    }

    pub fn initial_cut(&self) -> &CognitiveRecoveryAnchor { &self.initial }

    /// The trusted launcher has now actually spawned and pinned UID60001.
    /// Root initializes the first original Current for that exact process and
    /// returns one Pending service. It cannot issue before zero-input Ready.
    pub fn assemble_for_host(
        mut self, peer:CognitiveCheckpointPeerLifetime, preheld_host_pidfd:OwnedFd,
        locations:HostAuthorityBootstrapLocations,
    ) -> io::Result<(HostAuthorityService,Arc<AuthorityLeaseRegistry>,HostAuthorityServiceConfig)> {
        if peer.uid != 60001 { return Err(invalid("actual dedicated Host required")); }
        let sockets = &locations.sockets;
        self.config.sockets = HostAuthoritySocketPaths { observation:sockets.observation.clone(), issuer:sockets.issuer.clone(),
            checkpoint:sockets.checkpoint.clone(), device_frontier:Some(sockets.device_frontier.clone()),
            notes_frontier:Some(sockets.notes_frontier.clone()) };
        let service = HostAuthorityService::from_registered_owner(self.issuer.clone(),self.clock.clone(),self.identity.identity()?)?
            .with_registered_writer(self.config.writer.as_ref().ok_or_else(|| invalid("writer registration"))?.clone(),self.leases.verifier())?;
        let registration = service.writer.as_ref().ok_or_else(|| invalid("writer registration"))?
            .checkpoint_registration(&self.issuer,/*publisher_epoch*/1,peer.clone())?;
        let directory = RootAuthorityDirectory::open(self.config.checkpoint_state_dir.as_ref()
            .ok_or_else(|| invalid("checkpoint path"))?).map_err(io::Error::other)?;
        HostCognitiveCheckpoint::initialize_fresh(directory.clone(),registration,self.initial,self.clock).map_err(io::Error::other)?;
        let service = service.with_registered_checkpoint(directory,/*publisher_epoch*/1,peer)?
            .with_registered_consumers(&self.config.state_dir,self.config.consumers.as_ref().ok_or_else(|| invalid("consumers"))?)?
            .with_required_material_startup(&self.archive)?
            .with_bootstrap_registration(locations,preheld_host_pidfd)?;
        Ok((service,self.leases,self.config))
    }
}

fn require_absent(path:&Path) -> io::Result<()> {
    match std::fs::symlink_metadata(path) {
        Err(error) if error.kind()==io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
        Ok(_) => Err(invalid("existing or partial Root installation must not be reinitialized")),
    }
}

fn write_new_root_json(path:&Path,value:&impl serde::Serialize) -> io::Result<()> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.is_empty() || bytes.len()>65_536 { return Err(invalid("bounded Root bootstrap")); }
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600)
        .custom_flags(libc::O_NOFOLLOW|libc::O_CLOEXEC).open(path)?;
    file.write_all(&bytes)?; file.sync_all()?;
    File::open(path.parent().ok_or_else(|| invalid("bootstrap parent"))?)?.sync_all()
}

fn invalid(message:&str) -> io::Error { io::Error::other(message) }

#[cfg(test)]
#[path = "root_notes_fresh_authority_tests.rs"]
mod tests;
