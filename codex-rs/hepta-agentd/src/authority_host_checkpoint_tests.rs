//! Explicit root/data backend qualification, not a production writer fixture.
#[path = "authority_host_checkpoint_material_tests.rs"]
mod material_tests;

use super::*;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ObjectiveSenderWriterFence;
use codex_hepta_paths::HeptaFleetRoot;
use std::os::unix::fs::PermissionsExt;
use std::sync::Barrier;
use std::sync::atomic::AtomicU64;

#[derive(Default)]
struct ControlledClock {
    reads: AtomicU64,
    expire_on: AtomicU64,
}

impl AuthorityClock for ControlledClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let read = self.reads.fetch_add(1, Ordering::SeqCst) + 1;
        let expiry = self.expire_on.load(Ordering::SeqCst);
        Ok(if expiry != 0 && read >= expiry {
            10_000
        } else {
            1_000
        })
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    path: std::path::PathBuf,
    clock: Arc<ControlledClock>,
    registration: HostCognitiveCheckpointRegistration,
    initial_cut: CognitiveRecoveryAnchor,
    backend: Arc<HostCognitiveCheckpoint>,
}

impl Fixture {
    async fn new() -> Self {
        let root = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
            .expect("explicit existing root-owned data-bind qualification root required");
        let temp = tempfile::tempdir_in(root).unwrap();
        std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let fleet = temp.path().join("fleet");
        std::fs::create_dir(&fleet).unwrap();
        std::fs::set_permissions(&fleet, std::fs::Permissions::from_mode(0o700)).unwrap();
        let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
        let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&agent);
        // Original migrations, original coherent capture and awaited pool
        // close. This is a genuinely fresh private test directory, never a
        // fallback from an existing DB whose recovery failed.
        let store = CognitiveStore::open(&layout).await.unwrap();
        let initial_cut = store.recovery_anchor().await.unwrap();
        store.close().await;
        let path = temp.path().join("checkpoint");
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let registration = HostCognitiveCheckpointRegistration {
            owner_agent_id: agent,
            publisher_epoch: 7,
            writer_binding: CognitiveCheckpointWriterBinding {
                lease_id: "original-local-writer".into(),
                generation: 3,
                authority_epoch: 1,
                owner_epoch: 2,
                authority_grant_digest: Sha256Digest::for_bytes(b"qualification-grant"),
                fencing_token_digest: Sha256Digest::for_bytes(b"qualification-token"),
                expires_at_unix_seconds: 10,
            },
            peer_lifetime: CognitiveCheckpointPeerLifetime {
                uid: 60001,
                pid: 12345,
                boot_id: "00000000-0000-4000-8000-000000000001".into(),
                process_start_ticks: 12,
            },
        };
        let clock = Arc::new(ControlledClock::default());
        let backend = Arc::new(
            HostCognitiveCheckpoint::initialize_fresh(
                RootAuthorityDirectory::open(&path).unwrap(),
                registration.clone(),
                initial_cut.clone(),
                clock.clone(),
            )
            .unwrap(),
        );
        Self {
            _temp: temp,
            path,
            clock,
            registration,
            initial_cut,
            backend,
        }
    }

    fn reopen(&self) -> HostCognitiveCheckpoint {
        HostCognitiveCheckpoint::open(
            RootAuthorityDirectory::open(&self.path).unwrap(),
            self.registration.clone(),
            self.clock.clone(),
        )
        .unwrap()
    }

    fn request(
        &self,
        sequence: u64,
        command: CognitiveCheckpointCommand,
        expected: Option<CognitiveCheckpointToken>,
        proposal: Option<CognitiveCheckpointProposal>,
    ) -> CognitiveCheckpointRequest {
        CognitiveCheckpointRequest {
            schema_version: 1,
            operation: OPERATION.into(),
            request_id: format!("{:016x}{sequence:016x}", self.registration.publisher_epoch),
            command,
            expected,
            proposal,
        }
    }

    fn proposal(&self) -> CognitiveCheckpointProposal {
        let writer = &self.registration.writer_binding;
        CognitiveCheckpointProposal {
            cut: self.initial_cut.clone(),
            writer_fence: ObjectiveSenderWriterFence {
                owner_agent_id: self.registration.owner_agent_id.clone(),
                lease_id: writer.lease_id.clone(),
                lease_sha256: Sha256Digest::for_bytes(
                    b"actual lease record belongs to the original writer; qualification only",
                ),
                generation: writer.generation,
                authority_epoch: writer.authority_epoch,
                owner_epoch: writer.owner_epoch,
                authority_grant_digest: writer.authority_grant_digest.clone(),
                fencing_token_digest: writer.fencing_token_digest.clone(),
                expires_at_unix_seconds: writer.expires_at_unix_seconds,
            },
        }
    }
}

fn exchange(
    backend: &HostCognitiveCheckpoint,
    request: &CognitiveCheckpointRequest,
) -> CognitiveCheckpointResponse {
    serde_json::from_slice(
        &backend
            .exchange(&serde_json::to_vec(request).unwrap())
            .unwrap(),
    )
    .unwrap()
}

fn ack(value: &CognitiveCheckpointResponse, phase: CognitiveCheckpointPhase, counter: u64) {
    assert_eq!(value.status, CognitiveCheckpointStatus::Ack);
    assert_eq!(value.reason, None);
    assert_eq!(value.head.as_ref().unwrap().phase, phase);
    assert_eq!(value.head.as_ref().unwrap().counter, counter);
    assert_eq!(value.token.as_ref().unwrap().counter, counter);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_cycle_is_durable_exact_and_never_implicitly_reinitialized() {
    let f = Fixture::new().await;
    let read = f.request(1, CognitiveCheckpointCommand::ReadHead, None, None);
    let first = exchange(&f.backend, &read);
    ack(&first, CognitiveCheckpointPhase::Current, 1);
    assert_eq!(first.head.as_ref().unwrap().last_current, f.initial_cut);
    let begin = f.request(
        2,
        CognitiveCheckpointCommand::BeginWrites,
        first.token,
        None,
    );
    let dirty = exchange(&f.backend, &begin);
    ack(&dirty, CognitiveCheckpointPhase::Dirty, 2);
    // Exact original raw request replays the retained ACK without another CAS.
    assert_eq!(exchange(&f.backend, &begin), dirty);
    let raw = serde_json::to_string(&begin).unwrap() + " ";
    let changed_bytes: CognitiveCheckpointResponse =
        serde_json::from_slice(&f.backend.exchange(raw.as_bytes()).unwrap()).unwrap();
    assert_eq!(changed_bytes.status, CognitiveCheckpointStatus::Refused);
    let prepare = f.request(
        3,
        CognitiveCheckpointCommand::PreparePublication,
        dirty.token,
        Some(f.proposal()),
    );
    let publishing = exchange(&f.backend, &prepare);
    ack(&publishing, CognitiveCheckpointPhase::Publishing, 3);
    assert_eq!(f.reopen().load().unwrap(), publishing.head.clone().unwrap());
    let commit = f.request(
        4,
        CognitiveCheckpointCommand::CommitPublication,
        publishing.token,
        None,
    );
    let current = exchange(&f.backend, &commit);
    ack(&current, CognitiveCheckpointPhase::Current, 4);
    assert_eq!(f.reopen().load().unwrap(), current.head.clone().unwrap());
    assert_eq!(exchange(&f.backend, &commit), current);
    assert!(
        HostCognitiveCheckpoint::initialize_fresh(
            RootAuthorityDirectory::open(&f.path).unwrap(),
            f.registration.clone(),
            f.initial_cut.clone(),
            f.clock.clone()
        )
        .is_err()
    );
    let mut wrong = f.registration.clone();
    wrong.publisher_epoch += 1;
    assert!(
        HostCognitiveCheckpoint::open(
            RootAuthorityDirectory::open(&f.path).unwrap(),
            wrong,
            f.clock.clone()
        )
        .is_err()
    );
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_read_ids_do_not_advance_mutation_highwater_or_revive_fenced_state() {
    let f = Fixture::new().await;
    let read = f.request(100, CognitiveCheckpointCommand::ReadHead, None, None);
    let first = exchange(&f.backend, &read);
    assert_eq!(first.head.as_ref().unwrap().last_mutation_sequence, 0);
    let fence = f.request(
        2,
        CognitiveCheckpointCommand::FencePublisher,
        first.token,
        None,
    );
    let fenced = exchange(&f.backend, &fence);
    ack(&fenced, CognitiveCheckpointPhase::Fenced, 2);
    assert_eq!(fenced.head.as_ref().unwrap().last_mutation_sequence, 2);
    let begin = f.request(
        3,
        CognitiveCheckpointCommand::BeginWrites,
        fenced.token,
        None,
    );
    assert_eq!(
        exchange(&f.backend, &begin).status,
        CognitiveCheckpointStatus::Refused
    );
    let observed = exchange(&f.reopen(), &read);
    ack(&observed, CognitiveCheckpointPhase::Fenced, 2);
    assert_eq!(observed.head.as_ref().unwrap().last_current, f.initial_cut);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_invalid_bindings_and_late_request_ids_leave_exact_head_unchanged() {
    let f = Fixture::new().await;
    let first = exchange(
        &f.backend,
        &f.request(1, CognitiveCheckpointCommand::ReadHead, None, None),
    );
    let begin = f.request(
        3,
        CognitiveCheckpointCommand::BeginWrites,
        first.token,
        None,
    );
    let dirty = exchange(&f.backend, &begin);
    let mut proposal = f.proposal();
    proposal.writer_fence.owner_agent_id =
        AgentId::parse("00000000-0000-4000-8000-000000000002").unwrap();
    let bad = f.request(
        4,
        CognitiveCheckpointCommand::PreparePublication,
        dirty.token.clone(),
        Some(proposal),
    );
    assert_eq!(
        exchange(&f.backend, &bad).reason,
        Some(CognitiveCheckpointReason::AuthorityDenied)
    );
    let stale = f.request(
        2,
        CognitiveCheckpointCommand::FencePublisher,
        dirty.token.clone(),
        None,
    );
    assert_eq!(
        exchange(&f.backend, &stale).reason,
        Some(CognitiveCheckpointReason::StalePublisher)
    );
    let mut epoch = f.request(
        5,
        CognitiveCheckpointCommand::FencePublisher,
        dirty.token,
        None,
    );
    epoch.request_id = "00000000000000080000000000000005".into();
    assert_eq!(
        exchange(&f.backend, &epoch).reason,
        Some(CognitiveCheckpointReason::StalePublisher)
    );
    let duplicate =
        serde_json::to_string(&begin)
            .unwrap()
            .replacen("{", "{\"schema_version\":1,", 1);
    assert_eq!(
        f.backend.exchange(duplicate.as_bytes()),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(f.reopen().load().unwrap(), dirty.head.unwrap());
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_expiry_after_actual_cas_returns_unknown_and_permanently_closes_object() {
    let f = Fixture::new().await;
    let first = exchange(
        &f.backend,
        &f.request(1, CognitiveCheckpointCommand::ReadHead, None, None),
    );
    f.clock
        .expire_on
        .store(f.clock.reads.load(Ordering::SeqCst) + 2, Ordering::SeqCst);
    let begin = f.request(
        2,
        CognitiveCheckpointCommand::BeginWrites,
        first.token,
        None,
    );
    let unknown = exchange(&f.backend, &begin);
    assert_eq!(unknown.status, CognitiveCheckpointStatus::Unknown);
    assert_eq!(unknown.head, None);
    assert_eq!(unknown.token, None);
    // The real durable mutation occurred, but there was no successful ACK.
    assert_eq!(
        f.reopen().load().unwrap().phase,
        CognitiveCheckpointPhase::Dirty
    );
    f.clock.expire_on.store(0, Ordering::SeqCst);
    assert_eq!(exchange(&f.backend, &begin), unknown);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_two_independent_handles_cannot_both_win_the_same_original_cas() {
    let f = Fixture::new().await;
    let first = exchange(
        &f.backend,
        &f.request(1, CognitiveCheckpointCommand::ReadHead, None, None),
    );
    let left = f.backend.clone();
    let right = Arc::new(f.reopen());
    let a = f.request(
        2,
        CognitiveCheckpointCommand::BeginWrites,
        first.token.clone(),
        None,
    );
    let b = f.request(
        3,
        CognitiveCheckpointCommand::BeginWrites,
        first.token,
        None,
    );
    let barrier = Arc::new(Barrier::new(3));
    let one = barrier.clone();
    let a = std::thread::spawn(move || {
        one.wait();
        exchange(&left, &a)
    });
    let two = barrier.clone();
    let b = std::thread::spawn(move || {
        two.wait();
        exchange(&right, &b)
    });
    barrier.wait();
    let values = [a.join().unwrap(), b.join().unwrap()];
    assert_eq!(
        values
            .iter()
            .filter(|value| value.status == CognitiveCheckpointStatus::Ack)
            .count(),
        1
    );
    let winner = values.iter().find(|value| value.status == CognitiveCheckpointStatus::Ack).unwrap();
    let loser = values.iter().find(|value| value.status != CognitiveCheckpointStatus::Ack).unwrap();
    assert_eq!(loser.status, CognitiveCheckpointStatus::Refused, "{values:?}");
    let head = winner.head.as_ref().unwrap();
    // When request3 wins before request2's first read, the persistent
    // highwater correctly refuses request2 as stale. If both read the old
    // head, the original CAS/publication lock refuses the loser as Conflict.
    match loser.reason {
        Some(CognitiveCheckpointReason::Conflict) => {}
        Some(CognitiveCheckpointReason::StalePublisher) => assert_eq!(head.last_mutation_sequence, 3),
        other => panic!("unexpected concurrent refusal: {other:?}; {values:?}"),
    }
    let head = f.reopen().load().unwrap();
    assert_eq!(&head, winner.head.as_ref().unwrap());
    assert_eq!(head.counter, 2);
    assert_eq!(head.phase, CognitiveCheckpointPhase::Dirty);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_unavailable_read_permanently_fences_even_after_original_file_returns() {
    let f = Fixture::new().await;
    let entries = std::fs::read_dir(&f.path).unwrap().map(|entry| entry.unwrap().path())
        .filter(|path| path.extension().is_some_and(|value| value == "json")).collect::<Vec<_>>();
    assert_eq!(entries.len(), 1);
    let original = &entries[0];
    let backup = f.path.join("retained-original-for-io-qualification");
    let bytes = std::fs::read(original).unwrap();
    std::fs::rename(original, &backup).unwrap();
    let read = f.request(1, CognitiveCheckpointCommand::ReadHead, None, None);
    let unknown = exchange(&f.backend, &read);
    assert_eq!(unknown.status, CognitiveCheckpointStatus::Unknown);
    assert_eq!(unknown.head, None);
    assert_eq!(unknown.token, None);
    std::fs::rename(&backup, original).unwrap();
    assert_eq!(std::fs::read(original).unwrap(), bytes);
    assert_eq!(exchange(&f.backend, &read), unknown);
    // A distinct explicit root open can observe the still-unmodified durable
    // original, but it cannot revive the uncertain existing publisher object.
    assert_eq!(f.reopen().load().unwrap().phase, CognitiveCheckpointPhase::Current);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_trusted_successor_keeps_global_counter_separate_from_publisher_sequence() {
    let f = Fixture::new().await;
    let previous = f.backend.load().unwrap();
    // This is an explicit root-admin state fixture, not a runtime rotation API
    // or proof that the old actual process has quiesced. Runtime has no reset.
    let mut registration = f.registration.clone();
    registration.publisher_epoch += 1;
    registration.writer_binding.owner_epoch += 1;
    let mut successor = previous.clone();
    successor.publisher_epoch = registration.publisher_epoch;
    successor.writer_binding = registration.writer_binding.clone();
    successor.counter = previous.counter + 1;
    successor.last_mutation_sequence = 0;
    successor.last_request = None;
    f.backend
        .store
        .compare_and_set(STORE_OWNER, &previous, &successor)
        .unwrap();
    let next = HostCognitiveCheckpoint::open(
        RootAuthorityDirectory::open(&f.path).unwrap(),
        registration.clone(),
        f.clock.clone(),
    )
    .unwrap();
    let request = CognitiveCheckpointRequest {
        schema_version: 1,
        operation: OPERATION.into(),
        request_id: format!("{:016x}{:016x}", registration.publisher_epoch, 1),
        command: CognitiveCheckpointCommand::BeginWrites,
        expected: Some(token_for(&successor).unwrap()),
        proposal: None,
    };
    let changed = exchange(&next, &request);
    ack(&changed, CognitiveCheckpointPhase::Dirty, 3);
    assert_eq!(changed.head.as_ref().unwrap().last_mutation_sequence, 1);
    assert!(f.backend.load().is_err());
}
