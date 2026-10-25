//! Real retained pidfds and root/data CAS; writer proofs remain controlled here.
use super::*;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ObjectiveSenderWriterFence;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Barrier;
use std::sync::atomic::AtomicU64;
use std::time::Duration;
use std::time::Instant;

#[derive(Default)]
struct Clock {
    reads: AtomicU64,
    expire_on: AtomicU64,
    reject_on: AtomicU64,
}

impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let read = self.reads.fetch_add(1, Ordering::SeqCst) + 1;
        let rejection = self.reject_on.load(Ordering::SeqCst);
        if rejection != 0 && read >= rejection {
            return Err(AuthorityTrustError::Conflict);
        }
        let expiry = self.expire_on.load(Ordering::SeqCst);
        Ok(if expiry != 0 && read >= expiry {
            10_000
        } else {
            1_000
        })
    }
}

struct Publisher {
    child: Child,
    retained: RetainedCheckpointPublisher,
}

impl Publisher {
    fn spawn() -> Self {
        let mut child = Command::new("/usr/bin/setpriv")
            .args([
                "--reuid=60001",
                "--regid=60001",
                "--clear-groups",
                "--bounding-set=-all",
                "--inh-caps=-all",
                "--ambient-caps=-all",
                "--no-new-privs",
                "/usr/bin/sleep",
                "120",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let until = Instant::now() + Duration::from_secs(2);
        loop {
            assert!(child.try_wait().unwrap().is_none());
            let stat = std::fs::read_to_string(format!("/proc/{}/stat", child.id())).unwrap();
            let ticks = stat
                .rsplit_once(") ")
                .unwrap()
                .1
                .split_whitespace()
                .nth(19)
                .unwrap()
                .parse()
                .unwrap();
            let lifetime = CognitiveCheckpointPeerLifetime {
                uid: 60001,
                pid: child.id(),
                boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
                    .unwrap()
                    .trim()
                    .into(),
                process_start_ticks: ticks,
            };
            if let Ok(retained) = RetainedCheckpointPublisher::capture(lifetime) {
                return Self { child, retained };
            }
            assert!(
                Instant::now() < until,
                "dedicated child did not become ready"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
    }

    fn stop(&mut self) {
        self.child.kill().unwrap();
        assert!(!self.child.wait().unwrap().success());
        self.retained.require_exited().unwrap();
    }
}

impl Drop for Publisher {
    fn drop(&mut self) {
        if self.child.try_wait().unwrap().is_none() {
            self.child.kill().unwrap();
            self.child.wait().unwrap();
        }
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    directory: Arc<RootAuthorityDirectory>,
    previous: CognitiveCheckpointReceipt,
    registration: HostCognitiveCheckpointRegistration,
    backend: HostCognitiveCheckpoint,
    clock: Arc<Clock>,
    old: Publisher,
    new: Publisher,
}

impl Fixture {
    async fn new() -> Self {
        let root = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
            .expect("explicit root-owned data-bind qualification root required");
        let temp = tempfile::tempdir_in(root).unwrap();
        std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let fleet = temp.path().join("fleet");
        std::fs::create_dir(&fleet).unwrap();
        let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
        let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&agent);
        let store = CognitiveStore::open(&layout).await.unwrap();
        let cut = store.recovery_anchor().await.unwrap();
        store.close().await;
        let path = temp.path().join("checkpoint");
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let directory = RootAuthorityDirectory::open(&path).unwrap();
        let old = Publisher::spawn();
        let new = Publisher::spawn();
        let old_registration = HostCognitiveCheckpointRegistration {
            owner_agent_id: agent,
            publisher_epoch: 7,
            writer_binding: CognitiveCheckpointWriterBinding {
                lease_id: "original-local-writer".into(),
                generation: 3,
                authority_epoch: 1,
                owner_epoch: 2,
                authority_grant_digest: Sha256Digest::for_bytes(b"qualification-old-grant"),
                fencing_token_digest: Sha256Digest::for_bytes(b"qualification-old-token"),
                expires_at_unix_seconds: 10,
            },
            peer_lifetime: old.retained.lifetime.clone(),
        };
        let clock = Arc::new(Clock::default());
        let backend = HostCognitiveCheckpoint::initialize_fresh(
            directory.clone(),
            old_registration.clone(),
            cut,
            clock.clone(),
        )
        .unwrap();
        let head = backend.load().unwrap();
        let previous = CognitiveCheckpointReceipt {
            token: token_for(&head).unwrap(),
            head,
        };
        let mut registration = old_registration;
        registration.publisher_epoch += 1;
        registration.writer_binding.generation += 1;
        registration.writer_binding.owner_epoch += 1;
        registration.writer_binding.authority_grant_digest =
            Sha256Digest::for_bytes(b"qualification-new-grant");
        registration.writer_binding.fencing_token_digest =
            Sha256Digest::for_bytes(b"qualification-new-token");
        registration.peer_lifetime = new.retained.lifetime.clone();
        Self {
            _temp: temp,
            directory,
            previous,
            registration,
            backend,
            clock,
            old,
            new,
        }
    }

    fn adopt(&self) -> Result<HostCognitiveCheckpoint, AuthorityTrustError> {
        HostCognitiveCheckpoint::adopt_current(
            self.directory.clone(),
            &self.previous,
            &self.old.retained,
            self.registration.clone(),
            &self.new.retained,
            self.clock.clone(),
        )
    }

    fn mutate(&mut self, command: CognitiveCheckpointCommand, sequence: u64) {
        let writer = &self.previous.head.writer_binding;
        let proposal = (command == CognitiveCheckpointCommand::PreparePublication).then(|| {
            CognitiveCheckpointProposal {
                cut: self.previous.head.last_current.clone(),
                writer_fence: ObjectiveSenderWriterFence {
                    owner_agent_id: self.previous.head.owner_agent_id.clone(),
                    lease_id: writer.lease_id.clone(),
                    lease_sha256: Sha256Digest::for_bytes(b"controlled original writer record"),
                    generation: writer.generation,
                    authority_epoch: writer.authority_epoch,
                    owner_epoch: writer.owner_epoch,
                    authority_grant_digest: writer.authority_grant_digest.clone(),
                    fencing_token_digest: writer.fencing_token_digest.clone(),
                    expires_at_unix_seconds: writer.expires_at_unix_seconds,
                },
            }
        });
        let request = CognitiveCheckpointRequest {
            schema_version: 1,
            operation: OPERATION.into(),
            request_id: format!("{:016x}{sequence:016x}", self.previous.head.publisher_epoch),
            command,
            expected: Some(self.previous.token.clone()),
            proposal,
        };
        let response: CognitiveCheckpointResponse = serde_json::from_slice(
            &self
                .backend
                .exchange(&serde_json::to_vec(&request).unwrap())
                .unwrap(),
        )
        .unwrap();
        assert_eq!(response.status, CognitiveCheckpointStatus::Ack);
        self.previous = CognitiveCheckpointReceipt {
            token: response.token.unwrap(),
            head: response.head.unwrap(),
        };
    }
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_current_handoff_requires_actual_exit_and_preserves_cut_and_counter() {
    let mut f = Fixture::new().await;
    f.mutate(CognitiveCheckpointCommand::BeginWrites, 2);
    f.mutate(CognitiveCheckpointCommand::PreparePublication, 3);
    f.mutate(CognitiveCheckpointCommand::CommitPublication, 4);
    assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Conflict));
    assert_eq!(f.backend.load().unwrap(), f.previous.head);
    let mut wrong = f.old.retained.lifetime.clone();
    wrong.process_start_ticks += 1;
    assert!(RetainedCheckpointPublisher::capture(wrong).is_err());
    f.old.stop();
    assert!(RetainedCheckpointPublisher::capture(f.old.retained.lifetime.clone()).is_err());
    let adopted = f.adopt().unwrap();
    let head = adopted.load().unwrap();
    let mut expected = f.previous.head.clone();
    expected.publisher_epoch = f.registration.publisher_epoch;
    expected.counter += 1;
    expected.last_mutation_sequence = 0;
    expected.last_request = None;
    expected.writer_binding = f.registration.writer_binding.clone();
    expected.peer_lifetime = f.registration.peer_lifetime.clone();
    assert_eq!(head, expected);
    assert!(f.backend.load().is_err());
    assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Conflict));
    let reopened =
        HostCognitiveCheckpoint::open(f.directory.clone(), f.registration.clone(), f.clock.clone())
            .unwrap();
    assert_eq!(reopened.load().unwrap(), expected);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_current_handoff_refuses_changed_cut_phase_generation_and_dead_successor() {
    let mut f = Fixture::new().await;
    f.old.stop();
    let original = f.registration.clone();
    f.registration.writer_binding.generation = f.previous.head.writer_binding.generation;
    assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Invalid));
    f.registration.writer_binding.generation += 2;
    assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Invalid));
    f.registration = original;
    let previous = f.previous.clone();
    f.previous.head.last_current.state_digest =
        Sha256Digest::for_bytes(b"untrusted replacement cut");
    f.previous.token = token_for(&f.previous.head).unwrap();
    assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Conflict));
    f.previous = previous;
    f.new.stop();
    assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Conflict));
    assert_eq!(f.backend.load().unwrap(), f.previous.head);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_current_handoff_never_promotes_actual_dirty_publishing_or_fenced() {
    for phase in [
        CognitiveCheckpointPhase::Dirty,
        CognitiveCheckpointPhase::Publishing,
        CognitiveCheckpointPhase::Fenced,
    ] {
        let mut f = Fixture::new().await;
        f.mutate(CognitiveCheckpointCommand::BeginWrites, 2);
        if phase == CognitiveCheckpointPhase::Publishing {
            f.mutate(CognitiveCheckpointCommand::PreparePublication, 3);
        } else if phase == CognitiveCheckpointPhase::Fenced {
            f.mutate(CognitiveCheckpointCommand::FencePublisher, 3);
        }
        assert_eq!(f.previous.head.phase, phase);
        f.old.stop();
        assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Invalid));
        assert_eq!(f.backend.load().unwrap(), f.previous.head);
    }
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_current_handoff_post_cas_expiry_is_unknown_but_new_head_is_reconciled() {
    let mut f = Fixture::new().await;
    f.old.stop();
    f.clock
        .expire_on
        .store(f.clock.reads.load(Ordering::SeqCst) + 2, Ordering::SeqCst);
    assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Unavailable));
    let reopened =
        HostCognitiveCheckpoint::open(f.directory.clone(), f.registration.clone(), f.clock.clone())
            .unwrap();
    assert_eq!(
        reopened.load().unwrap().counter,
        f.previous.head.counter + 1
    );
    assert_eq!(
        reopened.load().unwrap().last_current,
        f.previous.head.last_current
    );
    let request = CognitiveCheckpointRequest {
        schema_version: 1,
        operation: OPERATION.into(),
        request_id: format!("{:016x}{:016x}", f.registration.publisher_epoch, 1),
        command: CognitiveCheckpointCommand::ReadHead,
        expected: None,
        proposal: None,
    };
    let response: CognitiveCheckpointResponse = serde_json::from_slice(
        &reopened
            .exchange(&serde_json::to_vec(&request).unwrap())
            .unwrap(),
    )
    .unwrap();
    assert_eq!(response.status, CognitiveCheckpointStatus::Refused);
    assert_eq!(
        response.reason,
        Some(CognitiveCheckpointReason::AuthorityDenied)
    );
    assert_eq!((response.head, response.token), (None, None));
    assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Unavailable));
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_current_handoff_two_real_cas_handles_choose_one_successor() {
    let mut f = Fixture::new().await;
    f.old.stop();
    let barrier = Barrier::new(2);
    let outcomes = std::thread::scope(|scope| {
        let first = scope.spawn(|| {
            barrier.wait();
            f.adopt().map(|_| ())
        });
        let second = scope.spawn(|| {
            barrier.wait();
            f.adopt().map(|_| ())
        });
        [first.join().unwrap(), second.join().unwrap()]
    });
    assert_eq!(outcomes.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        outcomes
            .iter()
            .filter(|result| **result == Err(AuthorityTrustError::Conflict))
            .count(),
        1
    );
    let reopened =
        HostCognitiveCheckpoint::open(f.directory.clone(), f.registration.clone(), f.clock.clone())
            .unwrap();
    assert_eq!(
        reopened.load().unwrap().counter,
        f.previous.head.counter + 1
    );
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_current_handoff_post_cas_clock_failure_is_unknown_not_definite_conflict() {
    let mut f = Fixture::new().await;
    f.old.stop();
    f.clock
        .reject_on
        .store(f.clock.reads.load(Ordering::SeqCst) + 2, Ordering::SeqCst);
    let result = f.adopt().err();
    // Observe the actual durable new registration before checking the reported
    // result. The clock remains unavailable; this is forensic readback, not
    // revival of an expired or uncertain runtime authority.
    let reopened =
        HostCognitiveCheckpoint::open(f.directory.clone(), f.registration.clone(), f.clock.clone())
            .unwrap();
    let head = reopened.load().unwrap();
    assert_eq!(head.counter, f.previous.head.counter + 1);
    assert_eq!(head.last_current, f.previous.head.last_current);
    assert_eq!(result, Some(AuthorityTrustError::Unavailable));
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_retirement_observation_refuses_live_lifetime_uid_change_and_other_boot() {
    let f = Fixture::new().await;
    let lifetime = f.old.retained.lifetime.clone();
    assert_eq!(
        RetiredCheckpointPublisher::observe(lifetime.clone()).err(),
        Some(AuthorityTrustError::Conflict)
    );
    let mut changed_uid = lifetime.clone();
    changed_uid.uid += 1;
    assert_eq!(
        RetiredCheckpointPublisher::observe(changed_uid).err(),
        Some(AuthorityTrustError::Conflict)
    );
    let mut changed_boot = lifetime;
    changed_boot.boot_id = "00000000-0000-4000-8000-000000000001".into();
    assert_eq!(
        RetiredCheckpointPublisher::observe(changed_boot).err(),
        Some(AuthorityTrustError::Invalid)
    );
    assert_eq!(f.backend.load().unwrap(), f.previous.head);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_current_adoption_without_any_retained_old_pidfd_preserves_exact_cut() {
    let mut f = Fixture::new().await;
    let lifetime = f.previous.head.peer_lifetime.clone();
    f.old.stop();
    let Fixture {
        _temp,
        directory,
        previous,
        registration,
        backend,
        clock,
        old,
        new,
    } = f;
    drop(old); // Drop the original captured pidfd, not merely its process.
    drop(backend); // No original service object survives this stage.
    assert!(RetainedCheckpointPublisher::capture(lifetime.clone()).is_err());
    let retirement = RetiredCheckpointPublisher::observe(lifetime).unwrap();
    let adopted = HostCognitiveCheckpoint::adopt_current_after_root_restart(
        directory.clone(),
        &previous,
        &retirement,
        registration.clone(),
        &new.retained,
        clock.clone(),
    )
    .unwrap();
    let head = adopted.load().unwrap();
    let mut expected = previous.head.clone();
    expected.publisher_epoch = registration.publisher_epoch;
    expected.counter += 1;
    expected.last_mutation_sequence = 0;
    expected.last_request = None;
    expected.writer_binding = registration.writer_binding.clone();
    expected.peer_lifetime = registration.peer_lifetime.clone();
    assert_eq!(head, expected);
    assert_eq!(
        HostCognitiveCheckpoint::adopt_current_after_root_restart(
            directory.clone(),
            &previous,
            &retirement,
            registration.clone(),
            &new.retained,
            clock.clone()
        )
        .err(),
        Some(AuthorityTrustError::Conflict)
    );
    let reopened = HostCognitiveCheckpoint::open(directory, registration, clock).unwrap();
    assert_eq!(reopened.load().unwrap(), expected);
    drop(_temp);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_retirement_proof_cannot_replace_protected_predecessor_lifetime() {
    let f = Fixture::new().await;
    let mut invented = f.old.retained.lifetime.clone();
    invented.process_start_ticks += 1;
    // A controlled nonmatching historical lifetime exercises the replacement
    // branch. This does not claim that the test forced actual PID reuse.
    let retirement = RetiredCheckpointPublisher::observe(invented).unwrap();
    assert_eq!(
        HostCognitiveCheckpoint::adopt_current_after_root_restart(
            f.directory.clone(),
            &f.previous,
            &retirement,
            f.registration.clone(),
            &f.new.retained,
            f.clock.clone()
        )
        .err(),
        Some(AuthorityTrustError::Invalid)
    );
    assert_eq!(f.backend.load().unwrap(), f.previous.head);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_retired_adoption_never_promotes_dirty_publishing_or_fenced() {
    for phase in [
        CognitiveCheckpointPhase::Dirty,
        CognitiveCheckpointPhase::Publishing,
        CognitiveCheckpointPhase::Fenced,
    ] {
        let mut f = Fixture::new().await;
        f.mutate(CognitiveCheckpointCommand::BeginWrites, 2);
        if phase == CognitiveCheckpointPhase::Publishing {
            f.mutate(CognitiveCheckpointCommand::PreparePublication, 3);
        } else if phase == CognitiveCheckpointPhase::Fenced {
            f.mutate(CognitiveCheckpointCommand::FencePublisher, 3);
        }
        f.old.stop();
        let retirement =
            RetiredCheckpointPublisher::observe(f.previous.head.peer_lifetime.clone()).unwrap();
        assert_eq!(
            HostCognitiveCheckpoint::adopt_current_after_root_restart(
                f.directory.clone(),
                &f.previous,
                &retirement,
                f.registration.clone(),
                &f.new.retained,
                f.clock.clone()
            )
            .err(),
            Some(AuthorityTrustError::Invalid)
        );
        assert_eq!(f.backend.load().unwrap(), f.previous.head);
    }
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_retired_adoption_post_cas_clock_error_is_unknown_and_exactly_reconciled() {
    let mut f = Fixture::new().await;
    f.old.stop();
    let retirement =
        RetiredCheckpointPublisher::observe(f.previous.head.peer_lifetime.clone()).unwrap();
    f.clock
        .reject_on
        .store(f.clock.reads.load(Ordering::SeqCst) + 2, Ordering::SeqCst);
    assert_eq!(
        HostCognitiveCheckpoint::adopt_current_after_root_restart(
            f.directory.clone(),
            &f.previous,
            &retirement,
            f.registration.clone(),
            &f.new.retained,
            f.clock.clone()
        )
        .err(),
        Some(AuthorityTrustError::Unavailable)
    );
    let reopened =
        HostCognitiveCheckpoint::open(f.directory.clone(), f.registration.clone(), f.clock.clone())
            .unwrap();
    let head = reopened.load().unwrap();
    assert_eq!(head.counter, f.previous.head.counter + 1);
    assert_eq!(head.last_current, f.previous.head.last_current);
    assert_eq!(head.peer_lifetime, f.new.retained.lifetime);
}
