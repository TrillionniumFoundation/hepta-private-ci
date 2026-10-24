//! Actual original-file/CAS/process-death qualification. Root tests are explicit
//! and use protected /run fixtures; they do not claim host power-loss coverage.
use super::*;
use crate::HostAuthorityClock;
use crate::HostAuthorityFrontierStore;
use crate::RootAuthorityDirectory;
use pretty_assertions::assert_eq;
use std::cell::RefCell;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::ExitStatusExt;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

const OWNER: &str = "root-lease-initialization-test";
const CLOCK_OWNER: &str = "root-lease-initialization-clock";

std::thread_local! {
    static AFTER_RENAME: RefCell<Option<Box<dyn FnOnce()>>> = const { RefCell::new(None) };
}

// This callback exists only in the original libtest build, is scoped to the
// controlled child thread, and runs after the actual original rename.
pub(super) fn after_original_rename() {
    let callback = AFTER_RENAME.with(|slot| slot.borrow_mut().take());
    if let Some(callback) = callback {
        callback();
    }
}

fn intent() -> AuthorityLeaseInitialization {
    AuthorityLeaseInitialization {
        lease_id: "initial-root-lease".into(),
        binding: AuthorityLeaseBinding {
            principal_id: "original-root-initializer".into(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: "no-effect".into(),
            scope_sha256: [3; 32],
            payload_sha256: [4; 32],
        },
        lifetime_ms: 60_000,
    }
}

fn private_directory(path: &Path) {
    std::fs::create_dir(path).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
}

struct Fixture {
    directory: tempfile::TempDir,
    leases: PathBuf,
    clock: Arc<HostAuthorityClock>,
    frontier: Arc<HostAuthorityFrontierStore<AuthorityLeaseFrontier>>,
}

impl Fixture {
    fn new(create_local_state: bool) -> Self {
        assert_eq!(rustix::process::geteuid().as_raw(), 0);
        let directory = tempfile::Builder::new()
            .prefix("hepta-lease-initial-")
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
                OWNER.into(),
                AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
            )
            .unwrap(),
        );
        let leases = directory.path().join("leases");
        private_directory(&leases);
        let fixture = Self {
            directory,
            leases,
            clock,
            frontier,
        };
        if create_local_state {
            drop(fixture.open(fixture.frontier.clone()));
        }
        fixture
    }

    fn open(
        &self,
        frontier: Arc<dyn AuthorityFrontierStore<AuthorityLeaseFrontier>>,
    ) -> AuthorityLeaseRegistry {
        AuthorityLeaseRegistry::open_state_dir_with_trust(
            &self.leases,
            OWNER.into(),
            self.clock.clone(),
            frontier,
        )
        .unwrap()
    }

    fn first_lease(&self) -> AuthorityLease {
        let now = self.clock.now_unix_ms().unwrap();
        let initial = intent();
        AuthorityLease {
            schema_version: 1,
            lease_id: initial.lease_id,
            authority_epoch: 1,
            revision: 1,
            binding: initial.binding,
            issued_at_unix_ms: now,
            expires_at_unix_ms: now + initial.lifetime_ms,
        }
    }

    fn resume(
        &self,
        initial: &AuthorityLeaseInitialization,
    ) -> Result<AuthorityLeaseRegistry, AuthorityLeaseError> {
        AuthorityLeaseRegistry::resume_initialization_with_trust(
            &self.leases,
            OWNER.into(),
            initial,
            self.clock.clone(),
            self.frontier.clone(),
        )
    }

    fn resume_prepared(&self) -> Result<AuthorityLeaseRegistry, AuthorityLeaseError> {
        AuthorityLeaseRegistry::resume_prepared_state_with_trust(
            &self.leases,
            OWNER.into(),
            self.clock.clone(),
            self.frontier.clone(),
        )
    }

    fn candidate(&self) -> (Vec<u8>, State) {
        let bytes = std::fs::read(self.leases.join("authority-leases.next")).unwrap();
        let stored: Stored = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(stored.schema_version, STORE_SCHEMA_VERSION);
        assert_eq!(stored.owner_id, OWNER);
        (bytes, stored.state)
    }

    fn interrupted_by_error(&self) -> AuthorityLease {
        let lease = self.first_lease();
        let registry = self.open(Arc::new(ActualFrontier {
            inner: self.frontier.clone(),
            leases: self.leases.clone(),
            fault: Fault::AfterActualCas,
            ready: None,
        }));
        assert_eq!(
            registry.put_lease(lease.clone(), 0),
            Err(AuthorityLeaseError::Unavailable)
        );
        assert_eq!(
            registry.read_lease(&lease.lease_id),
            Err(AuthorityLeaseError::Unavailable)
        );
        drop(registry);
        lease
    }

    fn interrupted_revocation(&self) -> AuthorityLease {
        let lease = self.first_lease();
        let registry = self.open(self.frontier.clone());
        registry.put_lease(lease.clone(), 0).unwrap();
        drop(registry);
        let registry = self.open(Arc::new(ActualFrontier {
            inner: self.frontier.clone(),
            leases: self.leases.clone(),
            fault: Fault::AfterActualCas,
            ready: None,
        }));
        assert_eq!(
            registry.revoke(&lease.lease_id, 1, [6; 32]),
            Err(AuthorityLeaseError::Unavailable)
        );
        assert_eq!(registry.capacity(), Err(AuthorityLeaseError::Unavailable));
        drop(registry);
        lease
    }
}

#[derive(Clone, Copy)]
enum Fault {
    BeforeActualCas,
    AfterActualCas,
    PauseBeforeActualCas,
    PauseAfterActualCas,
    PassThrough,
}

// Every load and successful CAS is the real original protected filesystem
// owner. Only the controlled error/acknowledgement cut is injected here.
struct ActualFrontier {
    inner: Arc<HostAuthorityFrontierStore<AuthorityLeaseFrontier>>,
    leases: PathBuf,
    fault: Fault,
    ready: Option<PathBuf>,
}

impl AuthorityFrontierStore<AuthorityLeaseFrontier> for ActualFrontier {
    fn load(&self, owner: &str) -> Result<AuthorityLeaseFrontier, AuthorityTrustError> {
        self.inner.load(owner)
    }

    fn compare_and_set(
        &self,
        owner: &str,
        expected: &AuthorityLeaseFrontier,
        next: &AuthorityLeaseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        // The old CAS-first implementation fails here: no complete physical
        // candidate exists yet. These bytes are produced by the real registry.
        let candidate = self.leases.join("authority-leases.next");
        let bytes = std::fs::read(&candidate).unwrap();
        let stored: Stored = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(stored.owner_id, owner);
        assert_eq!(frontier_for_state(&stored.state), *next);
        let metadata = std::fs::symlink_metadata(&candidate).unwrap();
        assert!(metadata.is_file());
        assert_eq!(metadata.uid(), 0);
        assert_eq!(metadata.mode() & 0o777, 0o600);
        assert_eq!(metadata.nlink(), 1);
        assert_eq!(self.inner.load(owner)?, *expected);
        if matches!(self.fault, Fault::BeforeActualCas) {
            return Err(AuthorityTrustError::Unavailable);
        }
        if matches!(self.fault, Fault::PauseBeforeActualCas) {
            signal_then_park(self.ready.as_ref().unwrap(), b"before-cas");
        }
        self.inner.compare_and_set(owner, expected, next)?;
        if matches!(self.fault, Fault::AfterActualCas) {
            return Err(AuthorityTrustError::Unavailable);
        }
        if matches!(self.fault, Fault::PauseAfterActualCas) {
            signal_then_park(self.ready.as_ref().unwrap(), b"after-cas");
        }
        Ok(())
    }
}

fn signal_then_park(path: &Path, phase: &[u8]) -> ! {
    let next = path.with_extension("next");
    let mut ready = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&next)
        .unwrap();
    ready.write_all(phase).unwrap();
    ready.sync_all().unwrap();
    std::fs::rename(next, path).unwrap();
    loop {
        std::thread::park();
    }
}

#[test]
#[ignore = "explicit Root actual pre-CAS file preparation and original failure fence"]
fn root_prepare_failure_before_frontier_cas_does_not_commit_the_initial_lease() {
    let fixture = Fixture::new(true);
    let before = fixture.frontier.load(OWNER).unwrap();
    let canonical = std::fs::read(fixture.leases.join("authority-leases.json")).unwrap();
    let registry = fixture.open(Arc::new(ActualFrontier {
        inner: fixture.frontier.clone(),
        leases: fixture.leases.clone(),
        fault: Fault::BeforeActualCas,
        ready: None,
    }));
    assert_eq!(
        registry.put_lease(fixture.first_lease(), 0),
        Err(AuthorityLeaseError::Unavailable)
    );
    assert_eq!(
        registry.read_lease(&intent().lease_id),
        Err(AuthorityLeaseError::Unavailable)
    );
    assert_eq!(fixture.frontier.load(OWNER).unwrap(), before);
    assert_eq!(
        std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
        canonical
    );
    let (pending, state) = fixture.candidate();
    assert_ne!(frontier_for_state(&state), before);
    drop(registry);
    let resumed = fixture.resume(&intent()).unwrap();
    assert_eq!(resumed.read_lease(&intent().lease_id).unwrap(), None);
    assert_eq!(resumed.frontier().unwrap(), before);
    assert_eq!(
        std::fs::read(fixture.leases.join("authority-leases.next")).unwrap(),
        pending
    );
}

#[test]
#[ignore = "explicit Root actual lost protected-CAS result with exact genesis completion"]
fn root_lost_actual_cas_result_resumes_the_same_prepared_initial_lease() {
    let fixture = Fixture::new(true);
    let lease = fixture.interrupted_by_error();
    let (candidate, state) = fixture.candidate();
    let committed = fixture.frontier.load(OWNER).unwrap();
    assert_eq!(frontier_for_state(&state), committed);
    assert!(matches!(
        AuthorityLeaseRegistry::open_state_dir_with_trust(
            &fixture.leases,
            OWNER.into(),
            fixture.clock.clone(),
            fixture.frontier.clone(),
        ),
        Err(AuthorityLeaseError::AntiRollbackViolation)
    ));
    let resumed = fixture.resume(&intent()).unwrap();
    assert_eq!(
        resumed.read_lease(&lease.lease_id).unwrap().unwrap().lease,
        lease
    );
    assert_eq!(resumed.frontier().unwrap(), committed);
    assert_eq!(fixture.frontier.load(OWNER).unwrap(), committed);
    assert_eq!(
        std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
        candidate
    );
    assert!(!fixture.leases.join("authority-leases.next").exists());
    drop(resumed);
    let reopened = fixture.open(fixture.frontier.clone());
    assert_eq!(
        reopened.read_lease(&lease.lease_id).unwrap().unwrap().lease,
        lease
    );
    drop(reopened);
    let same = fixture.resume(&intent()).unwrap();
    assert_eq!(
        same.read_lease(&lease.lease_id).unwrap().unwrap().lease,
        lease
    );
    assert_eq!(same.frontier().unwrap(), committed);
    assert_eq!(
        std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
        candidate
    );
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
#[ignore = "explicit Root actual child SIGKILL between original frontier and local publication"]
fn root_sigkill_after_original_frontier_cas_retains_and_resumes_exact_candidate() {
    kill_at_original_publication_cut("after-cas");
}

#[test]
#[ignore = "explicit Root actual child SIGKILL before original CAS must not promote an uncommitted candidate"]
fn root_sigkill_before_original_frontier_cas_never_promotes_the_candidate() {
    kill_at_original_publication_cut("before-cas");
}

#[test]
#[ignore = "explicit Root actual child SIGKILL after original rename preserves the committed original state"]
fn root_sigkill_after_original_rename_resumes_without_a_second_cas() {
    kill_at_original_publication_cut("after-rename");
}

fn kill_at_original_publication_cut(phase: &str) {
    let fixture = Fixture::new(true);
    let before = fixture.frontier.load(OWNER).unwrap();
    let before_bytes = std::fs::read(fixture.leases.join("authority-leases.json")).unwrap();
    let ready = fixture.directory.path().join("actual-cut-ready");
    let mut child = OwnedChild(
        Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "authority_lease::initialization_tests::initialization_crash_child",
                "--ignored",
                "--nocapture",
            ])
            .env("HEPTA_LEASE_INITIALIZATION_CHILD", fixture.directory.path())
            .env("HEPTA_LEASE_INITIALIZATION_CUT", phase)
            .spawn()
            .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(15);
    while !ready.exists() {
        assert!(
            child.0.try_wait().unwrap().is_none(),
            "actual child exited before original publication cut"
        );
        assert!(
            Instant::now() < deadline,
            "actual child did not reach the original publication cut"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(std::fs::read(&ready).unwrap(), phase.as_bytes());
    let candidate = if phase == "after-rename" {
        assert!(!fixture.leases.join("authority-leases.next").exists());
        std::fs::read(fixture.leases.join("authority-leases.json")).unwrap()
    } else {
        let (candidate, _) = fixture.candidate();
        assert_eq!(
            std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
            before_bytes
        );
        candidate
    };
    let stored: Stored = serde_json::from_slice(&candidate).unwrap();
    let committed = fixture.frontier.load(OWNER).unwrap();
    if phase == "before-cas" {
        assert_eq!(committed, before);
        assert_ne!(frontier_for_state(&stored.state), committed);
    } else {
        assert_eq!(frontier_for_state(&stored.state), committed);
    }
    assert!(matches!(
        fixture.resume_prepared(),
        Err(AuthorityLeaseError::StateLocked)
    ));
    child.0.kill().unwrap();
    assert_eq!(child.0.wait().unwrap().signal(), Some(9));
    if phase == "after-cas" {
        assert!(matches!(
            AuthorityLeaseRegistry::open_state_dir_with_trust(
                &fixture.leases,
                OWNER.into(),
                fixture.clock.clone(),
                fixture.frontier.clone(),
            ),
            Err(AuthorityLeaseError::AntiRollbackViolation)
        ));
    }
    let resumed = fixture.resume_prepared().unwrap();
    assert_eq!(resumed.frontier().unwrap(), committed);
    assert_eq!(fixture.frontier.load(OWNER).unwrap(), committed);
    if phase == "before-cas" {
        assert_eq!(resumed.read_lease(&intent().lease_id).unwrap(), None);
        assert_eq!(
            std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
            before_bytes
        );
        assert_eq!(
            std::fs::read(fixture.leases.join("authority-leases.next")).unwrap(),
            candidate
        );
    } else {
        let lease = resumed
            .read_lease(&intent().lease_id)
            .unwrap()
            .unwrap()
            .lease;
        assert_eq!(&lease, stored.state.leases.get(&intent().lease_id).unwrap());
        assert_eq!(
            std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
            candidate
        );
        assert!(!fixture.leases.join("authority-leases.next").exists());
    }
}

#[test]
#[ignore = "subprocess only, owned and SIGKILL/reaped by the explicit Root parent test"]
fn initialization_crash_child() {
    let Some(base) = std::env::var_os("HEPTA_LEASE_INITIALIZATION_CHILD") else {
        return;
    };
    let base = PathBuf::from(base);
    let root = RootAuthorityDirectory::open(&base.join("authority")).unwrap();
    let clock = Arc::new(HostAuthorityClock::open(root.clone(), CLOCK_OWNER.into()).unwrap());
    let frontier = Arc::new(HostAuthorityFrontierStore::open(root, OWNER.into()).unwrap());
    let phase = std::env::var("HEPTA_LEASE_INITIALIZATION_CUT").unwrap();
    let fault = match phase.as_str() {
        "before-cas" => Fault::PauseBeforeActualCas,
        "after-cas" => Fault::PauseAfterActualCas,
        "after-rename" => Fault::PassThrough,
        _ => panic!("invalid controlled child cut"),
    };
    if phase == "after-rename" {
        let frontier = frontier.clone();
        let base = base.clone();
        AFTER_RENAME.with(|slot| {
            *slot.borrow_mut() = Some(Box::new(move || {
                let bytes = std::fs::read(base.join("leases/authority-leases.json")).unwrap();
                let stored: Stored = serde_json::from_slice(&bytes).unwrap();
                assert_eq!(
                    frontier_for_state(&stored.state),
                    frontier.load(OWNER).unwrap()
                );
                assert!(!base.join("leases/authority-leases.next").exists());
                signal_then_park(&base.join("actual-cut-ready"), b"after-rename");
            }));
        });
    }
    let initial = intent();
    let now = clock.now_unix_ms().unwrap();
    let lease = AuthorityLease {
        schema_version: 1,
        lease_id: initial.lease_id,
        authority_epoch: 1,
        revision: 1,
        binding: initial.binding,
        issued_at_unix_ms: now,
        expires_at_unix_ms: now + initial.lifetime_ms,
    };
    let registry = AuthorityLeaseRegistry::open_state_dir_with_trust(
        &base.join("leases"),
        OWNER.into(),
        clock,
        Arc::new(ActualFrontier {
            inner: frontier,
            leases: base.join("leases"),
            fault,
            ready: Some(base.join("actual-cut-ready")),
        }),
    )
    .unwrap();
    let result = registry.put_lease(lease, 0);
    panic!("parent must kill the original blocked child at its actual publication cut: {result:?}");
}

#[test]
#[ignore = "explicit Root wrong full candidate/binding/missing state and advanced-owner negatives"]
fn root_initialization_resume_never_repairs_a_different_or_missing_committed_state() {
    for case in ["hash", "binding", "missing", "malformed"] {
        let fixture = Fixture::new(true);
        fixture.interrupted_by_error();
        let protected = fixture.frontier.load(OWNER).unwrap();
        let canonical = std::fs::read(fixture.leases.join("authority-leases.json")).unwrap();
        let next = fixture.leases.join("authority-leases.next");
        let mut initial = intent();
        let evidence = if case == "hash" {
            let mut stored: Stored =
                serde_json::from_slice(&std::fs::read(&next).unwrap()).unwrap();
            let lease = stored.state.leases.get_mut(&initial.lease_id).unwrap();
            lease.issued_at_unix_ms += 1;
            lease.expires_at_unix_ms += 1;
            let bytes = serde_json::to_vec(&stored).unwrap();
            std::fs::write(&next, &bytes).unwrap();
            next.clone()
        } else if case == "malformed" {
            std::fs::write(&next, b"{").unwrap();
            next.clone()
        } else if case == "missing" {
            let evidence = fixture.leases.join("retained-candidate-evidence");
            std::fs::rename(&next, &evidence).unwrap();
            evidence
        } else {
            initial.binding.scope_sha256 = [9; 32];
            next.clone()
        };
        let retained = std::fs::read(&evidence).unwrap();
        assert!(
            fixture.resume(&initial).is_err(),
            "negative {case} must be refused"
        );
        assert_eq!(fixture.frontier.load(OWNER).unwrap(), protected);
        assert_eq!(
            std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
            canonical
        );
        assert_eq!(std::fs::read(&evidence).unwrap(), retained);
    }
    let fixture = Fixture::new(true);
    let registry = fixture.open(fixture.frontier.clone());
    let first = fixture.first_lease();
    registry.put_lease(first.clone(), 0).unwrap();
    let mut second = first;
    second.lease_id = "later-original-administration".into();
    registry.put_lease(second, 0).unwrap();
    let advanced = registry.frontier().unwrap();
    drop(registry);
    let canonical = std::fs::read(fixture.leases.join("authority-leases.json")).unwrap();
    assert!(matches!(
        fixture.resume(&intent()),
        Err(AuthorityLeaseError::InvalidTrust)
    ));
    assert_eq!(fixture.frontier.load(OWNER).unwrap(), advanced);
    assert_eq!(
        std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
        canonical
    );
    assert_eq!(
        fixture.open(fixture.frontier.clone()).frontier().unwrap(),
        advanced
    );
}

#[test]
#[ignore = "explicit Root earliest lock-only initialization completion against exact empty frontier"]
fn root_lock_only_initialization_completes_only_the_original_empty_state() {
    let fixture = Fixture::new(false);
    let root = prepare_directory(&fixture.leases).unwrap();
    let lock = open_private(&root, "authority-leases.lock", Access::Create).unwrap();
    lock.try_lock().unwrap();
    drop(lock);
    let expected = fixture.frontier.load(OWNER).unwrap();
    assert_eq!(
        expected,
        AuthorityLeaseFrontier::for_empty_epoch(1).unwrap()
    );
    assert!(matches!(
        AuthorityLeaseRegistry::open_state_dir_with_trust(
            &fixture.leases,
            OWNER.into(),
            fixture.clock.clone(),
            fixture.frontier.clone(),
        ),
        Err(AuthorityLeaseError::AntiRollbackViolation)
    ));
    let resumed = fixture.resume(&intent()).unwrap();
    assert_eq!(resumed.frontier().unwrap(), expected);
    assert_eq!(resumed.read_lease(&intent().lease_id).unwrap(), None);
    assert_eq!(fixture.frontier.load(OWNER).unwrap(), expected);
}

#[test]
#[ignore = "explicit Root original later revocation resume retains complete committed state and times"]
fn root_prepared_resume_preserves_later_revocation_without_reissuing() {
    let fixture = Fixture::new(true);
    let original_lease = fixture.interrupted_revocation();
    let (candidate, state) = fixture.candidate();
    let committed = fixture.frontier.load(OWNER).unwrap();
    assert_eq!(committed.store_revision, 3);
    assert_eq!(frontier_for_state(&state), committed);
    assert_eq!(state.revocations.len(), 1);
    assert!(matches!(
        fixture.resume(&intent()),
        Err(AuthorityLeaseError::InvalidTrust)
    ));
    assert!(matches!(
        AuthorityLeaseRegistry::open_state_dir_with_trust(
            &fixture.leases,
            OWNER.into(),
            fixture.clock.clone(),
            fixture.frontier.clone(),
        ),
        Err(AuthorityLeaseError::AntiRollbackViolation)
    ));
    let resumed = fixture.resume_prepared().unwrap();
    let observed = resumed
        .read_lease(&original_lease.lease_id)
        .unwrap()
        .unwrap()
        .lease;
    assert_eq!(observed.revision, 2);
    assert_eq!(observed.issued_at_unix_ms, original_lease.issued_at_unix_ms);
    assert_eq!(
        observed.expires_at_unix_ms,
        original_lease.expires_at_unix_ms
    );
    assert_eq!(
        resumed
            .read_revocation(&original_lease.lease_id)
            .unwrap()
            .unwrap()
            .revocation,
        *state.revocations.get(&original_lease.lease_id).unwrap(),
    );
    assert_eq!(resumed.frontier().unwrap(), committed);
    assert_eq!(fixture.frontier.load(OWNER).unwrap(), committed);
    assert_eq!(
        std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
        candidate
    );
    drop(resumed);
    let reopened = fixture.open(fixture.frontier.clone());
    assert_eq!(reopened.frontier().unwrap(), committed);
    assert_eq!(reopened.capacity().unwrap().revocations, 1);
    drop(reopened);
    let replay = fixture.resume_prepared().unwrap();
    assert_eq!(replay.frontier().unwrap(), committed);
    assert_eq!(
        std::fs::read(fixture.leases.join("authority-leases.json")).unwrap(),
        candidate
    );
}

#[test]
#[ignore = "explicit Root exact committed candidate, canonical continuity and full original format negatives"]
fn root_prepared_resume_rejects_different_missing_or_corrupt_committed_bytes() {
    for case in [
        "candidate-hash",
        "candidate-missing",
        "candidate-malformed",
        "canonical-missing",
        "canonical-equal-revision",
    ] {
        let fixture = Fixture::new(true);
        fixture.interrupted_revocation();
        let protected = fixture.frontier.load(OWNER).unwrap();
        let canonical = fixture.leases.join("authority-leases.json");
        let next = fixture.leases.join("authority-leases.next");
        match case {
            "candidate-hash" => {
                let mut stored: Stored =
                    serde_json::from_slice(&std::fs::read(&next).unwrap()).unwrap();
                stored
                    .state
                    .revocations
                    .get_mut(&intent().lease_id)
                    .unwrap()
                    .reason_sha256 = [7; 32];
                std::fs::write(&next, serde_json::to_vec(&stored).unwrap()).unwrap();
            }
            "candidate-missing" => {
                std::fs::rename(&next, fixture.leases.join("retained-next-evidence")).unwrap();
            }
            "candidate-malformed" => {
                std::fs::write(&next, b"{").unwrap();
            }
            "canonical-missing" => {
                std::fs::rename(
                    &canonical,
                    fixture.leases.join("retained-canonical-evidence"),
                )
                .unwrap();
            }
            "canonical-equal-revision" => {
                let mut stored: Stored =
                    serde_json::from_slice(&std::fs::read(&canonical).unwrap()).unwrap();
                stored.state.store_revision = protected.store_revision;
                std::fs::write(&canonical, serde_json::to_vec(&stored).unwrap()).unwrap();
            }
            _ => unreachable!(),
        }
        let canonical_before = std::fs::read(&canonical).ok();
        let next_before = std::fs::read(&next).ok();
        let retained_next = std::fs::read(fixture.leases.join("retained-next-evidence")).ok();
        let retained_canonical =
            std::fs::read(fixture.leases.join("retained-canonical-evidence")).ok();
        assert!(
            fixture.resume_prepared().is_err(),
            "negative {case} must fail closed"
        );
        assert_eq!(fixture.frontier.load(OWNER).unwrap(), protected);
        assert_eq!(std::fs::read(&canonical).ok(), canonical_before);
        assert_eq!(std::fs::read(&next).ok(), next_before);
        assert_eq!(
            std::fs::read(fixture.leases.join("retained-next-evidence")).ok(),
            retained_next
        );
        assert_eq!(
            std::fs::read(fixture.leases.join("retained-canonical-evidence")).ok(),
            retained_canonical
        );
    }
}
