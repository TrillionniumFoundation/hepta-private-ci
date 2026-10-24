use super::*;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;
use std::cell::RefCell;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::ExitStatusExt;
use std::process::Command;

type KeyCut = (&'static str, Box<dyn FnOnce()>);
std::thread_local! {
    static CUT: RefCell<Option<KeyCut>> = const { RefCell::new(None) };
}

pub(super) fn at_key_cut(stage: &'static str) {
    let callback = CUT.with(|cut| {
        let mut cut = cut.borrow_mut();
        if cut.as_ref().is_some_and(|(expected, _)| *expected == stage) {
            cut.take().map(|(_, callback)| callback)
        } else {
            None
        }
    });
    if let Some(callback) = callback {
        callback();
    }
}

fn private_directory(path: &Path) {
    std::fs::create_dir(path).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
}

fn write_private(path: &Path, bytes: &[u8]) {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)
        .unwrap();
    file.write_all(bytes).unwrap();
    file.sync_all().unwrap();
}

fn key_identity(path: &Path) -> [u8; 32] {
    let bytes: [u8; 32] = std::fs::read(path)
        .unwrap()
        .try_into()
        .unwrap_or_else(|_| panic!("incomplete test key"));
    SigningKey::from_bytes(&bytes).verifying_key().to_bytes()
}

#[test]
fn key_publication_preserves_existing_identity_on_actual_noreplace_collision() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let publication = KeyPublication::open(directory.path()).unwrap();
    let path = directory.path().join(KEY);
    let for_cut = path.clone();
    CUT.with(|cut| {
        *cut.borrow_mut() = Some((
            "prepared",
            Box::new(move || {
                write_private(&for_cut, &[0xA5; 32]);
            }),
        ))
    });
    let error = publication.create_key().unwrap_err();
    assert_eq!(error.raw_os_error(), Some(libc::EEXIST));
    assert!(std::fs::read(&path).unwrap() == [0xA5; 32]);
    let candidate = directory.path().join(KEY_NEXT);
    assert_eq!(std::fs::metadata(&candidate).unwrap().len(), 32);
    let retained_identity = key_identity(&candidate);
    assert!(publication.resume_key().is_err());
    assert!(std::fs::read(&path).unwrap() == [0xA5; 32]);
    assert_eq!(key_identity(&candidate), retained_identity);
}

#[test]
fn key_publication_refuses_partial_canonical_and_partial_candidate_without_replacement() {
    for name in [KEY, KEY_NEXT] {
        for length in [0, 1, 31, 33] {
            let directory = tempfile::tempdir().unwrap();
            std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
                .unwrap();
            let bytes = vec![0xA5; length];
            let path = directory.path().join(name);
            write_private(&path, &bytes);
            let publication = KeyPublication::open(directory.path()).unwrap();
            assert!(publication.resume_key().is_err());
            assert!(std::fs::read(&path).unwrap() == bytes);
            if name == KEY_NEXT {
                assert!(!directory.path().join(KEY).exists());
            } else {
                assert!(!directory.path().join(KEY_NEXT).exists());
            }
        }
    }
}

#[test]
fn key_initialization_holds_an_exclusive_actual_file_lock() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let first = KeyPublication::open(directory.path()).unwrap();
    let error = KeyPublication::open(directory.path()).err().unwrap();
    assert_eq!(error.kind(), io::ErrorKind::WouldBlock);
    drop(first);
    drop(KeyPublication::open(directory.path()).unwrap());
}

const CLOCK_OWNER: &str = "root-issuer-initialization-clock";
const LEASE_OWNER: &str = "root-issuer-initialization-leases";
const SIGNER: &str = "root-initial-issuer";
const LEASE: &str = "root-initial-issuer-lease";

fn policy() -> DeploymentGrantPolicy {
    DeploymentGrantPolicy {
        subject_id: "agent.original".into(),
        destination_id: "notes.original".into(),
        scope_sha256: [2; 32],
        lifetime_ms: 30_000,
    }
}

fn binding() -> FinalUseBinding {
    FinalUseBinding {
        subject_id: policy().subject_id,
        destination_id: policy().destination_id,
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    }
}

struct Fixture {
    directory: tempfile::TempDir,
    clock: Arc<HostAuthorityClock>,
    frontier: Arc<HostAuthorityFrontierStore<AuthorityLeaseFrontier>>,
    issuer: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        assert_eq!(rustix::process::geteuid().as_raw(), 0);
        let directory = tempfile::Builder::new()
            .prefix("hepta-issuer-initial-")
            .tempdir_in("/run")
            .unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let authority = directory.path().join("authority");
        private_directory(&authority);
        let root = RootAuthorityDirectory::open(&authority).unwrap();
        let clock =
            Arc::new(HostAuthorityClock::initialize(root.clone(), CLOCK_OWNER.into()).unwrap());
        let frontier = Arc::new(
            HostAuthorityFrontierStore::initialize(
                root,
                LEASE_OWNER.into(),
                AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
            )
            .unwrap(),
        );
        let leases = directory.path().join("leases");
        private_directory(&leases);
        let issuer = directory.path().join("issuer");
        let fixture = Self {
            directory,
            clock,
            frontier,
            issuer,
        };
        let registry = fixture.registry();
        let now = fixture.clock.now_unix_ms().unwrap();
        let binding = binding();
        registry
            .put_lease(
                AuthorityLease {
                    schema_version: 1,
                    lease_id: LEASE.into(),
                    authority_epoch: 1,
                    revision: 1,
                    binding: AuthorityLeaseBinding {
                        principal_id: binding.subject_id,
                        operation_class: "runtime.agentd.production_operation".into(),
                        destination_id: binding.destination_id,
                        scope_sha256: binding.scope_sha256,
                        payload_sha256: binding.payload_sha256,
                    },
                    issued_at_unix_ms: now,
                    expires_at_unix_ms: now + 60_000,
                },
                0,
            )
            .unwrap();
        drop(registry);
        fixture
    }

    fn registry(&self) -> AuthorityLeaseRegistry {
        AuthorityLeaseRegistry::open_state_dir_with_trust(
            &self.directory.path().join("leases"),
            LEASE_OWNER.into(),
            self.clock.clone(),
            self.frontier.clone(),
        )
        .unwrap()
    }

    fn create(&self, registry: &AuthorityLeaseRegistry) -> DeploymentFinalUseIssuer {
        DeploymentFinalUseIssuer::create_protected(
            &self.issuer,
            SIGNER.into(),
            vec![policy()],
            self.clock.clone(),
            registry.verifier(),
            LEASE.into(),
            1,
        )
        .unwrap()
    }

    fn resume(&self, registry: &AuthorityLeaseRegistry) -> io::Result<DeploymentFinalUseIssuer> {
        DeploymentFinalUseIssuer::resume_protected_initialization(
            &self.issuer,
            SIGNER.into(),
            vec![policy()],
            self.clock.clone(),
            registry.verifier(),
            LEASE.into(),
            1,
        )
    }
}

#[test]
#[ignore = "explicit Root original complete key/genesis continuation and used-sequence rejection"]
fn root_issuer_resume_retains_identity_and_refuses_an_already_used_state() {
    let fixture = Fixture::new();
    let registry = fixture.registry();
    let original = fixture.create(&registry);
    let identity = original.trust_key().unwrap().verifying_key;
    let initial = original.store.load(STATE_OWNER).unwrap();
    drop(original);
    let resumed = fixture.resume(&registry).unwrap();
    assert_eq!(resumed.trust_key().unwrap().verifying_key, identity);
    assert!(resumed.store.load(STATE_OWNER).unwrap() == initial);
    let grant = resumed.issue(&binding()).unwrap().unwrap();
    assert!(grant.grant.grant_id.ends_with(":1"));
    let used = resumed.store.load(STATE_OWNER).unwrap();
    assert_eq!(used.sequence, 1);
    drop(resumed);
    assert!(fixture.resume(&registry).is_err());
    let ordinary = DeploymentFinalUseIssuer::open_protected(
        &fixture.issuer,
        fixture.clock.clone(),
        registry.verifier(),
        LEASE.into(),
        1,
    )
    .unwrap();
    assert!(ordinary.store.load(STATE_OWNER).unwrap() == used);
    assert_eq!(ordinary.trust_key().unwrap().verifying_key, identity);
}

#[test]
#[ignore = "explicit Root changed policy/signer, missing identity and damaged identity remain errors"]
fn root_issuer_resume_preserves_wrong_or_incomplete_initialization_evidence() {
    for case in [
        "policy",
        "signer",
        "short-key",
        "missing-key",
        "state-with-candidate-only",
    ] {
        let fixture = Fixture::new();
        let registry = fixture.registry();
        let original = fixture.create(&registry);
        let state = original.store.load(STATE_OWNER).unwrap();
        drop(original);
        let key = fixture.issuer.join(KEY);
        let mut policies = vec![policy()];
        let mut signer = SIGNER.to_owned();
        if case == "policy" {
            policies[0].scope_sha256 = [9; 32];
        } else if case == "signer" {
            signer = "different-initial-signer".into();
        } else if case == "short-key" {
            std::fs::write(&key, [0xA5; 31]).unwrap();
        } else {
            std::fs::rename(
                &key,
                fixture.directory.path().join("retained-identity-evidence"),
            )
            .unwrap();
            if case == "state-with-candidate-only" {
                std::fs::copy(
                    fixture.directory.path().join("retained-identity-evidence"),
                    fixture.issuer.join(KEY_NEXT),
                )
                .unwrap();
            }
        }
        let key_before = std::fs::read(&key).ok();
        let candidate_before = std::fs::read(fixture.issuer.join(KEY_NEXT)).ok();
        assert!(
            DeploymentFinalUseIssuer::resume_protected_initialization(
                &fixture.issuer,
                signer,
                policies,
                fixture.clock.clone(),
                registry.verifier(),
                LEASE.into(),
                1,
            )
            .is_err(),
            "negative {case} must fail closed"
        );
        assert!(std::fs::read(&key).ok() == key_before);
        assert!(std::fs::read(fixture.issuer.join(KEY_NEXT)).ok() == candidate_before);
        let store =
            DeploymentFrontierStore::<IssuerState>::open_protected(&fixture.issuer).unwrap();
        assert!(store.load(STATE_OWNER).unwrap() == state);
    }
}

#[test]
#[ignore = "explicit Root genuinely empty unused issuer directory permits only its first identity"]
fn root_issuer_empty_installation_continues_once_without_replacing_identity() {
    let fixture = Fixture::new();
    let registry = fixture.registry();
    private_directory(&fixture.issuer);
    let issuer = fixture.resume(&registry).unwrap();
    let identity = issuer.trust_key().unwrap().verifying_key;
    assert!(identity != [0; 32]);
    assert_eq!(issuer.store.load(STATE_OWNER).unwrap().sequence, 0);
    drop(issuer);
    let same = fixture.resume(&registry).unwrap();
    assert_eq!(same.trust_key().unwrap().verifying_key, identity);
    assert_eq!(same.store.load(STATE_OWNER).unwrap().sequence, 0);
}

struct OwnedChild(std::process::Child);
impl Drop for OwnedChild {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}

#[test]
#[ignore = "explicit Root actual child SIGKILL after complete key candidate file and directory sync"]
fn root_issuer_sigkill_after_complete_candidate_resumes_the_same_key() {
    kill_at_original_initialization_cut("prepared");
}

#[test]
#[ignore = "explicit Root actual child SIGKILL after key publication before original state provision"]
fn root_issuer_sigkill_after_key_publication_resumes_the_same_key() {
    kill_at_original_initialization_cut("published");
}

#[test]
#[ignore = "explicit Root actual child SIGKILL after original genesis state publication before return"]
fn root_issuer_sigkill_after_state_publication_reads_the_same_genesis() {
    kill_at_original_initialization_cut("state-published");
}

fn kill_at_original_initialization_cut(stage: &str) {
    let fixture = Fixture::new();
    let ready = fixture.directory.path().join("actual-cut-ready");
    let mut child = OwnedChild(
        Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "deployment_issuer::initialization::tests::issuer_initialization_crash_child",
                "--ignored",
                "--nocapture",
            ])
            .env(
                "HEPTA_ISSUER_INITIALIZATION_CHILD",
                fixture.directory.path(),
            )
            .env("HEPTA_ISSUER_INITIALIZATION_CUT", stage)
            .spawn()
            .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(15);
    while !ready.exists() {
        assert!(
            child.0.try_wait().unwrap().is_none(),
            "owned child exited before original initialization cut"
        );
        assert!(
            Instant::now() < deadline,
            "owned child did not reach original initialization cut"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(std::fs::read(&ready).unwrap(), stage.as_bytes());
    let material = if stage == "prepared" {
        assert!(!fixture.issuer.join(KEY).exists());
        fixture.issuer.join(KEY_NEXT)
    } else {
        assert!(!fixture.issuer.join(KEY_NEXT).exists());
        fixture.issuer.join(KEY)
    };
    let identity = key_identity(&material);
    let metadata = std::fs::symlink_metadata(&material).unwrap();
    assert!(metadata.is_file());
    assert_eq!(metadata.uid(), 0);
    assert_eq!(metadata.mode() & 0o777, 0o600);
    assert_eq!(metadata.len(), 32);
    assert_eq!(metadata.nlink(), 1);
    let states: Vec<_> = std::fs::read_dir(&fixture.issuer)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("frontier-v1-")
                && path.extension() == Some(OsStr::new("json"))
        })
        .collect();
    if stage == "state-published" {
        assert_eq!(states.len(), 1);
    } else {
        assert!(states.is_empty());
    }
    let error = KeyPublication::open(&fixture.issuer).err().unwrap();
    assert_eq!(error.kind(), io::ErrorKind::WouldBlock);
    child.0.kill().unwrap();
    assert_eq!(child.0.wait().unwrap().signal(), Some(9));
    let registry = fixture.registry();
    let issuer = fixture.resume(&registry).unwrap();
    assert_eq!(issuer.trust_key().unwrap().verifying_key, identity);
    assert_eq!(
        std::fs::metadata(fixture.issuer.join(KEY)).unwrap().ino(),
        metadata.ino()
    );
    assert!(!fixture.issuer.join(KEY_NEXT).exists());
    let state = issuer.store.load(STATE_OWNER).unwrap();
    assert!(state == initial_state(SIGNER.into(), vec![policy()]));
    drop(issuer);
    let replay = fixture.resume(&registry).unwrap();
    assert_eq!(replay.trust_key().unwrap().verifying_key, identity);
    assert!(replay.store.load(STATE_OWNER).unwrap() == state);
}

#[test]
#[ignore = "subprocess only, killed and reaped exclusively by its explicit Root parent"]
fn issuer_initialization_crash_child() {
    let Some(base) = std::env::var_os("HEPTA_ISSUER_INITIALIZATION_CHILD") else {
        return;
    };
    let base = PathBuf::from(base);
    let stage = match std::env::var("HEPTA_ISSUER_INITIALIZATION_CUT")
        .unwrap()
        .as_str()
    {
        "prepared" => "prepared",
        "published" => "published",
        "state-published" => "state-published",
        _ => panic!("invalid controlled initialization cut"),
    };
    let root = RootAuthorityDirectory::open(&base.join("authority")).unwrap();
    let clock = Arc::new(HostAuthorityClock::open(root.clone(), CLOCK_OWNER.into()).unwrap());
    let frontier = Arc::new(HostAuthorityFrontierStore::open(root, LEASE_OWNER.into()).unwrap());
    let registry = AuthorityLeaseRegistry::open_state_dir_with_trust(
        &base.join("leases"),
        LEASE_OWNER.into(),
        clock.clone(),
        frontier,
    )
    .unwrap();
    let barrier_base = base.clone();
    CUT.with(|cut| {
        *cut.borrow_mut() = Some((
            stage,
            Box::new(move || {
                let next = barrier_base.join("actual-cut-ready.next");
                write_private(&next, stage.as_bytes());
                std::fs::rename(next, barrier_base.join("actual-cut-ready")).unwrap();
                loop {
                    std::thread::park();
                }
            }),
        ))
    });
    let result = DeploymentFinalUseIssuer::create_protected(
        &base.join("issuer"),
        SIGNER.into(),
        vec![policy()],
        clock,
        registry.verifier(),
        LEASE.into(),
        1,
    );
    assert!(
        result.is_ok(),
        "actual original initialization failed before the controlled child cut"
    );
    panic!("parent must kill the original blocked child at its actual initialization cut");
}
