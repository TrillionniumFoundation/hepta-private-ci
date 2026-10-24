use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use std::os::unix::fs::PermissionsExt;
use pretty_assertions::assert_eq;

struct Installation {
    _protected:tempfile::TempDir,
    _owner:tempfile::TempDir,
    identity:HostAuthorityRegisteredIdentity,
    state:PathBuf,
    bind:HostAuthorityBindIdentity,
}

impl Installation {
    fn new() -> Self {
        assert_eq!(unsafe {libc::geteuid()},0);
        let parent = PathBuf::from(std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT").unwrap());
        let source = PathBuf::from(std::env::var_os("HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE").unwrap());
        let protected = tempfile::Builder::new().prefix("notes-fresh-authority-").tempdir_in(&parent).unwrap();
        std::fs::set_permissions(protected.path(),std::fs::Permissions::from_mode(0o700)).unwrap();
        let owner_parent = std::env::var_os("HEPTA_TEST_ROOT_OWNER_INSTALL_DESTINATION").unwrap();
        let owner = tempfile::Builder::new().prefix("notes-fresh-owner-").tempdir_in(owner_parent).unwrap();
        let workspace = owner.path().join("workspace"); std::fs::create_dir(&workspace).unwrap();
        let fleet = HeptaFleetRoot::parse(owner.path().join("fleet")).unwrap();
        let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c14").unwrap();
        registry.register(AgentManifest::new(agent.clone(),WorkspaceBinding::new(workspace.clone(),&fleet).unwrap(),
            ResourceBudget::local_default()).unwrap()).unwrap();
        registry.compare_and_transition(&agent,/*expected_generation*/0,AgentLifecycle::Starting).unwrap();
        let metadata = std::fs::metadata(&parent).unwrap();
        Self {state:protected.path().join("authority"),_protected:protected,_owner:owner,
            identity:HostAuthorityRegisteredIdentity {agent_id:agent,spawn_generation:1,fleet_root:fleet.as_path().to_path_buf(),
                workspace,resources:ResourceBudget::local_default()},
            bind:HostAuthorityBindIdentity {mountpoint:parent,source_path:source,device:metadata.dev(),inode:metadata.ino()}}
    }
    fn input(&self) -> RootNotesFreshAuthorityInput {
        RootNotesFreshAuthorityInput {state_dir:self.state.clone(),required_bind:self.bind.clone(),identity:self.identity.clone(),
            installed_manifest_sha256:Digest32::of_bytes(b"actual test-installed manifest bytes"),
            signer_id:"organ.notes.fresh-root-test".into(),lease_lifetime_ms:60000}
    }
}

fn run(future:impl std::future::Future<Output=()>) {
    tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap().block_on(future);
}

#[test]
#[ignore = "actual Root SSD fresh canonical configuration and no Device authorization"]
fn fresh_initializer_uses_actual_cut_key_registry_and_two_original_consumers() {
    let installation = Installation::new();
    run(async {
        let fresh = RootNotesFreshAuthority::initialize(installation.input()).await.unwrap();
        let writer = fresh.config.writer.as_ref().unwrap();
        let proof = fresh.issuer.retained_writer_authorization(writer).unwrap();
        assert_eq!(proof.claims.sequence,1);
        assert_eq!(proof.claims.authority_lease,writer.authority_lease);
        assert_eq!(fresh.issuer_key().unwrap().key_id,fresh.config.signer_id);
        let store = CognitiveStore::open(&installation.identity.identity().unwrap().layout).await.unwrap();
        assert_eq!(store.recovery_anchor().await.unwrap(),*fresh.initial_cut()); store.close().await;
        let state = crate::DeploymentFrontierStore::<serde_json::Value>::open_protected(&fresh.config.state_dir.join("issuer")).unwrap();
        let before = state.load("local-final-use-issuer").unwrap();
        assert_eq!(before["policies"].as_array().unwrap().len(),1);
        assert_eq!(before["policies"][0]["destination_id"],DeploymentFinalUseIssuer::OBJECTIVE_DESTINATION);
        let device = FinalUseBinding {subject_id:installation.identity.agent_id.to_string(),destination_id:"hos2.cpu.0".into(),
            request_sha256:Sha256::digest(b"actual unavailable Device request").into(),scope_sha256:Sha256::digest(b"Device scope").into(),
            payload_sha256:Sha256::digest(b"Device payload").into()};
        let error = fresh.issuer.issue(&device).unwrap_err();
        assert_eq!(error.kind(),io::ErrorKind::PermissionDenied);
        assert_eq!(state.load("local-final-use-issuer").unwrap(),before,"unattached Device must spend no canonical sequence");
        let consumers = fresh.config.consumers.as_ref().unwrap();
        assert_ne!(consumers.device.state_dir,consumers.notes.state_dir);
        for consumer in [&consumers.device,&consumers.notes] {
            let original = codex_hepta_contracts::HostAuthorityFrontierStore::<codex_hepta_contracts::FinalUseFrontier>::open(
                RootAuthorityDirectory::open(&consumer.state_dir).unwrap(),consumer.owner_id.clone()).unwrap();
            assert_eq!(original.load(&consumer.owner_id).unwrap(),codex_hepta_contracts::FinalUseFrontier::for_initial_head(&fresh.issuer.revocations().unwrap()).unwrap());
        }
        let key = fresh.issuer_key().unwrap(); let initial = fresh.initial_cut().clone();
        assert!(RootNotesFreshAuthority::initialize(installation.input()).await.is_err());
        assert_eq!(fresh.issuer_key().unwrap(),key); assert_eq!(*fresh.initial_cut(),initial);
        assert_eq!(state.load("local-final-use-issuer").unwrap(),before);
    });
}

#[test]
#[ignore = "actual Root partial or existing store is never replaced by genesis"]
fn partial_bootstrap_or_nonempty_cognitive_owner_cannot_create_new_authority() {
    for partial_bootstrap in [true,false] {
        let installation = Installation::new();
        let retained = if partial_bootstrap {installation.state.with_extension("notes-bootstrap.json")}
            else {installation.identity.identity().unwrap().layout.cognitive_root().join("retained-unknown-store")};
        std::fs::write(&retained,b"retain original partial bytes").unwrap();
        let before = std::fs::read(&retained).unwrap();
        run(async {assert!(RootNotesFreshAuthority::initialize(installation.input()).await.is_err());});
        assert_eq!(std::fs::read(&retained).unwrap(),before);
        assert!(!installation.state.exists());
    }
}
