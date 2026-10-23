//! Explicit root/data acceptance. Controlled clocks and frontier hashes here
//! are qualification inputs, not signed operations or production consumers.
use super::*;
use std::collections::BTreeSet;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::Barrier;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[derive(Default)]
struct Clock {
    reads: AtomicU64,
    expire_on: AtomicU64,
}
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let read = self.reads.fetch_add(1, Ordering::SeqCst) + 1;
        let expiry = self.expire_on.load(Ordering::SeqCst);
        Ok(if expiry != 0 && read >= expiry { 2_000 } else { 1_000 })
    }
}

struct Fixture {
    temp: tempfile::TempDir,
    clock: Arc<Clock>,
    head: FinalUseRevocations,
    backend: HostConsumerFrontier,
}
impl Fixture {
    fn new() -> Self {
        let parent = std::env::var_os("HEPTA_CONSUMER_TEST_ROOT")
            .expect("explicit root-owned data-bind qualification directory required");
        let temp = tempfile::tempdir_in(parent).unwrap();
        fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let clock = Arc::new(Clock::default());
        let head = FinalUseRevocations { authority_epoch: 1, revision: 1, revoked_grant_ids: BTreeSet::new() };
        let backend = HostConsumerFrontier::initialize_fresh(
            RootAuthorityDirectory::open(temp.path()).unwrap(), "original-device".into(),
            &head, clock.clone(), /*expires_at_unix_ms*/ 2_000,
        ).unwrap();
        Self { temp, clock, head, backend }
    }
    fn reopen(&self) -> HostConsumerFrontier {
        HostConsumerFrontier::open(RootAuthorityDirectory::open(self.temp.path()).unwrap(),
            "original-device".into(), self.clock.clone(), /*expires_at_unix_ms*/ 2_000).unwrap()
    }
    fn initial(&self) -> FinalUseFrontier { FinalUseFrontier::for_initial_head(&self.head).unwrap() }
    fn response(&self, id: u64, update: Option<(FinalUseFrontier, FinalUseFrontier)>) -> Response {
        exchange(&self.backend, &self.head, id, update)
    }
}
fn exchange(backend: &HostConsumerFrontier, head: &FinalUseRevocations, id: u64,
    update: Option<(FinalUseFrontier, FinalUseFrontier)>) -> Response {
    let request = match update {
        Some((expected, next)) => Request::CompareAndSet { schema_version: 1, request_id: id, expected, next },
        None => Request::Load { schema_version: 1, request_id: id },
    };
    serde_json::from_slice(&backend.exchange(&serde_json::to_vec(&request).unwrap(), head).unwrap()).unwrap()
}
fn changed(mut frontier: FinalUseFrontier, marker: u8) -> FinalUseFrontier {
    frontier.state_sha256 = [marker; 32]; frontier
}

#[test]
#[ignore = "requires explicit root-owned data bind; no production authority"]
fn root_two_original_stores_are_isolated_and_exact_cas_survives_reopen() {
    let f = Fixture::new();
    let notes = HostConsumerFrontier::initialize_fresh(
        RootAuthorityDirectory::open(f.temp.path()).unwrap(), "original-notes".into(), &f.head,
        f.clock.clone(), /*expires_at_unix_ms*/ 2_000).unwrap();
    let next = changed(f.initial(), /*marker*/ 2);
    assert_eq!(f.response(/*id*/ 1, Some((f.initial(), next))), Response {
        schema_version: 1, request_id: 1, status: Status::Ack, frontier: Some(next),
    });
    assert_eq!(exchange(&f.reopen(), &f.head, /*id*/ 1, None).frontier, Some(next));
    assert_eq!(exchange(&notes, &f.head, /*id*/ 1, None).frontier, Some(f.initial()));
    assert_eq!(f.response(/*id*/ 2, Some((f.initial(), changed(f.initial(), /*marker*/ 3)))).status, Status::Conflict);
    assert_eq!(f.response(/*id*/ 3, None).frontier, Some(next));
    assert!(matches!(HostConsumerFrontier::initialize_fresh(
        RootAuthorityDirectory::open(f.temp.path()).unwrap(), "original-device".into(), &f.head,
        f.clock.clone(), /*expires_at_unix_ms*/ 2_000), Err(AuthorityTrustError::Conflict)));
    assert!(HostConsumerFrontier::open(RootAuthorityDirectory::open(f.temp.path()).unwrap(),
        "missing-original-owner".into(), f.clock.clone(), /*expires_at_unix_ms*/ 2_000).is_err());
}

#[test]
#[ignore = "requires explicit root-owned data bind; no production authority"]
fn root_post_cas_expiry_returns_no_ack_and_never_revives_the_uncertain_object() {
    let f = Fixture::new(); let next = changed(f.initial(), /*marker*/ 2);
    f.clock.reads.store(0, Ordering::SeqCst); f.clock.expire_on.store(2, Ordering::SeqCst);
    assert_eq!(f.response(/*id*/ 1, Some((f.initial(), next))), Response {
        schema_version: 1, request_id: 1, status: Status::Unknown, frontier: None,
    });
    f.clock.expire_on.store(0, Ordering::SeqCst);
    assert_eq!(f.response(/*id*/ 2, None).status, Status::Unknown);
    assert_eq!(exchange(&f.reopen(), &f.head, /*id*/ 1, None).frontier, Some(next));
}

#[test]
#[ignore = "requires explicit root-owned data bind; no production authority"]
fn root_storage_disappearance_and_restoration_does_not_revive_a_lane() {
    let f = Fixture::new();
    let path = fs::read_dir(f.temp.path()).unwrap().map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|e| e == "json")).unwrap();
    let raw = fs::read(&path).unwrap(); fs::remove_file(&path).unwrap();
    assert_eq!(f.response(/*id*/ 1, None).status, Status::Unknown);
    fs::write(&path, &raw).unwrap(); fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    assert_eq!(f.response(/*id*/ 2, None).status, Status::Unknown);
    assert_eq!(exchange(&f.reopen(), &f.head, /*id*/ 1, None).frontier, Some(f.initial()));
}

#[test]
#[ignore = "requires explicit root-owned data bind; no production authority"]
fn root_forged_epoch_revision_namespace_and_replayed_transport_ids_do_not_mutate() {
    let f = Fixture::new(); let original = f.initial();
    for (index, mut next) in [changed(original, /*marker*/ 2), changed(original, /*marker*/ 3)].into_iter().enumerate() {
        if index == 0 { next.authority_epoch += 1; } else { next.revocation_revision += 1; }
        let request = Request::CompareAndSet { schema_version: 1, request_id: index as u64 + 1, expected: original, next };
        assert_eq!(f.backend.exchange(&serde_json::to_vec(&request).unwrap(), &f.head), Err(AuthorityTrustError::Invalid));
    }
    assert_eq!(f.response(/*id*/ 3, None).frontier, Some(original));
    let replay = serde_json::to_vec(&Request::Load { schema_version: 1, request_id: 3 }).unwrap();
    assert_eq!(f.backend.exchange(&replay, &f.head), Err(AuthorityTrustError::Invalid));
    for bytes in [br#"{"operation":"runtime.final_use.frontier.load.v1","schema_version":1,"request_id":4,"owner_id":"other"}"#.as_slice(),
        br#"{"operation":"runtime.final_use.frontier.load.v1","schema_version":1,"request_id":4,"request_id":5}"#.as_slice()] {
        assert_eq!(f.backend.exchange(bytes, &f.head), Err(AuthorityTrustError::Invalid));
    }
    assert_eq!(f.backend.exchange(&vec![b' '; FRAME_LIMIT+1], &f.head), Err(AuthorityTrustError::Invalid));
    assert_eq!(f.response(/*id*/ 4, None).frontier, Some(original));
}

#[test]
#[ignore = "requires explicit root-owned data bind; no production authority"]
fn root_two_real_handles_race_one_durable_cas_and_refuse_the_other() {
    let f = Fixture::new(); let initial = f.initial();
    let gate = Arc::new(Barrier::new(2));
    let handles = [f.reopen(), f.reopen()].into_iter().enumerate().map(|(index, backend)| {
        let gate = gate.clone(); let head = f.head.clone();
        std::thread::spawn(move || { gate.wait(); exchange(&backend, &head, /*id*/ 1, Some((initial, changed(initial, index as u8 + 2)))) })
    }).collect::<Vec<_>>();
    let responses = handles.into_iter().map(|h| h.join().unwrap()).collect::<Vec<_>>();
    assert_eq!(responses.iter().filter(|r| r.status == Status::Ack).count(), 1);
    assert_eq!(responses.iter().filter(|r| r.status == Status::Conflict).count(), 1);
    let winner = responses.iter().find(|r| r.status == Status::Ack).unwrap().frontier;
    assert_eq!(f.response(/*id*/ 1, None).frontier, winner);
}
