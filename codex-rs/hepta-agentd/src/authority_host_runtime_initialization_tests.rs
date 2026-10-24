use super::*;
use codex_hepta_contracts::FinalUseBinding;
use pretty_assertions::assert_eq;
use std::path::PathBuf;

struct Fixture {
    _directory: tempfile::TempDir,
    state: PathBuf,
    bootstrap: HostAuthorityBootstrap,
}

impl Fixture {
    fn new(with_clock: bool) -> Self {
        assert_eq!(unsafe { libc::geteuid() }, 0);
        let base = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("/run"));
        let directory = tempfile::Builder::new()
            .prefix("hepta-original-init-")
            .tempdir_in(base)
            .unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let state = directory.path().join("authority");
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&state)
            .unwrap();
        let root = RootAuthorityDirectory::open(&state).unwrap();
        if with_clock {
            HostAuthorityClock::initialize(root, CLOCK_OWNER.into()).unwrap();
        }
        let bootstrap = HostAuthorityBootstrap {
            schema_version: 1,
            // These component tests invoke resume_stores. The public wrapper
            // separately requires the original real bind identity and file.
            required_bind: HostAuthorityBindIdentity {
                mountpoint: directory.path().to_path_buf(),
                source_path: directory.path().to_path_buf(),
                device: directory.path().metadata().unwrap().dev(),
                inode: directory.path().metadata().unwrap().ino(),
            },
            signer_id: "original-partial-installation".into(),
            policies: vec![DeploymentGrantPolicy {
                subject_id: "agent.original".into(),
                destination_id: "notes.original".into(),
                scope_sha256: [2; 32],
                lifetime_ms: 5_000,
            }],
            lease_id: "original-initial-root-lease".into(),
            lease_binding: AuthorityLeaseBinding {
                principal_id: "agent.original".into(),
                operation_class: "runtime.agentd.production_operation".into(),
                destination_id: "notes.original".into(),
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            lease_lifetime_ms: 120_000,
        };
        Self {
            _directory: directory,
            state,
            bootstrap,
        }
    }

    fn original(
        &self,
    ) -> (
        Arc<HostAuthorityClock>,
        AuthorityLeaseRegistry,
        DeploymentFinalUseIssuer,
    ) {
        let root = RootAuthorityDirectory::open(&self.state).unwrap();
        let clock = Arc::new(HostAuthorityClock::open(root.clone(), CLOCK_OWNER.into()).unwrap());
        let frontier =
            Arc::new(HostAuthorityFrontierStore::open(root, LEASE_OWNER.into()).unwrap());
        let leases = AuthorityLeaseRegistry::open_state_dir_with_trust(
            &self.state.join("leases"),
            LEASE_OWNER.into(),
            clock.clone(),
            frontier,
        )
        .unwrap();
        let issuer = DeploymentFinalUseIssuer::open_protected(
            &self.state.join("issuer"),
            clock.clone(),
            leases.verifier(),
            self.bootstrap.lease_id.clone(),
            1,
        )
        .unwrap();
        (clock, leases, issuer)
    }
}

#[test]
#[ignore = "explicit Root real clock/Registry/issuer partial installation continuation"]
fn root_partial_initialization_retains_exact_original_lease_and_key() {
    let f = Fixture::new(true);
    let first = resume_stores(&f.state, &f.bootstrap).unwrap();
    assert!(!first.production_ready);
    let (_, leases, issuer) = f.original();
    let issued = leases
        .read_lease(&f.bootstrap.lease_id)
        .unwrap()
        .unwrap()
        .lease;
    let frontier = leases.verifier().frontier().unwrap();
    let key = issuer.trust_key().unwrap().verifying_key;
    let inode = f.state.join("issuer/issuer.key").metadata().unwrap().ino();
    drop(issuer);
    drop(leases);
    let resumed = resume_stores(&f.state, &f.bootstrap).unwrap();
    assert_eq!(resumed.verifying_key, first.verifying_key);
    let (_, leases, issuer) = f.original();
    assert_eq!(
        leases
            .read_lease(&f.bootstrap.lease_id)
            .unwrap()
            .unwrap()
            .lease,
        issued
    );
    assert_eq!(leases.verifier().frontier().unwrap(), frontier);
    assert_eq!(issuer.trust_key().unwrap().verifying_key, key);
    assert_eq!(
        f.state.join("issuer/issuer.key").metadata().unwrap().ino(),
        inode
    );
}

#[test]
#[ignore = "explicit Root missing original clock/frontier and changed intent fail closed"]
fn root_partial_initialization_refuses_lost_original_clock_and_changed_bootstrap() {
    let missing = Fixture::new(false);
    assert!(resume_stores(&missing.state, &missing.bootstrap).is_err());
    assert!(!missing.state.join("leases").exists());
    assert!(!missing.state.join("issuer").exists());
    let mut f = Fixture::new(true);
    resume_stores(&f.state, &f.bootstrap).unwrap();
    let key = std::fs::read(f.state.join("issuer/issuer.key")).unwrap();
    let local = std::fs::read(f.state.join("leases/authority-leases.json")).unwrap();
    f.bootstrap.lease_binding.payload_sha256[0] ^= 1;
    assert!(resume_stores(&f.state, &f.bootstrap).is_err());
    assert!(
        std::fs::read(f.state.join("issuer/issuer.key")).unwrap() == key,
        "retained private key changed"
    );
    assert_eq!(
        std::fs::read(f.state.join("leases/authority-leases.json")).unwrap(),
        local
    );
    f.bootstrap.lease_binding.payload_sha256[0] ^= 1;
    let name = format!(
        "frontier-v1-{:x}.json",
        Sha256::digest(LEASE_OWNER.as_bytes())
    );
    let bytes = std::fs::read(f.state.join(&name)).unwrap();
    std::fs::rename(f.state.join(&name), f.state.join("retained-test-frontier")).unwrap();
    assert!(resume_stores(&f.state, &f.bootstrap).is_err());
    assert!(!f.state.join(&name).exists());
    assert_eq!(
        std::fs::read(f.state.join("retained-test-frontier")).unwrap(),
        bytes
    );
}

#[test]
#[ignore = "explicit Root original used issuer is not an unused initialization"]
fn root_partial_initialization_refuses_original_issuer_after_actual_first_use() {
    let f = Fixture::new(true);
    resume_stores(&f.state, &f.bootstrap).unwrap();
    let (_, leases, issuer) = f.original();
    let granted = issuer
        .issue(&FinalUseBinding {
            subject_id: "agent.original".into(),
            destination_id: "notes.original".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        })
        .unwrap()
        .unwrap();
    let key = issuer.trust_key().unwrap().verifying_key;
    assert!(granted.grant.grant_id.ends_with(":1"));
    drop(issuer);
    drop(leases);
    assert!(resume_stores(&f.state, &f.bootstrap).is_err());
    let (_, _, issuer) = f.original();
    assert_eq!(issuer.trust_key().unwrap().verifying_key, key);
}
