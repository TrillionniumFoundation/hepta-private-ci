use super::*;
use crate::FinalUseAuthority;
use crate::FinalUseBinding;
use crate::FinalUseFrontier;
use crate::FinalUseGrant;
use crate::FinalUseIssuerTrustKey;
use crate::FinalUseRevocations;
use crate::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::mpsc;
use std::time::Duration;

type Pause = (mpsc::SyncSender<ClockRecord>, mpsc::Receiver<()>);

// The real filesystem CAS (including fsync/rename/dirsync) runs first. The
// wrapper then delays its acknowledgement to reproduce a blocking durability
// call without a fake OS clock or changing an original authority owner.
struct DelayedStore {
    inner: HostAuthorityFrontierStore<ClockRecord>,
    pause: Mutex<Option<Pause>>,
}

impl AuthorityFrontierStore<ClockRecord> for DelayedStore {
    fn load(&self, owner: &str) -> Result<ClockRecord, AuthorityTrustError> {
        self.inner.load(owner)
    }

    fn compare_and_set(
        &self,
        owner: &str,
        expected: &ClockRecord,
        next: &ClockRecord,
    ) -> Result<(), AuthorityTrustError> {
        self.inner.compare_and_set(owner, expected, next)?;
        let pause = self
            .pause
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?
            .take();
        if let Some((arrived, resume)) = pause {
            arrived
                .send(next.clone())
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            resume
                .recv_timeout(Duration::from_secs(15))
                .map_err(|_| AuthorityTrustError::Unavailable)?;
        }
        Ok(())
    }
}

struct Fixture {
    _directory: tempfile::TempDir,
    root: Arc<RootAuthorityDirectory>,
    store: Arc<DelayedStore>,
    clock: Arc<HostAuthorityClock>,
}

impl Fixture {
    fn new() -> Self {
        assert_eq!(rustix::process::geteuid().as_raw(), 0);
        // A root-owned /run fixture makes scheduling/delay deterministic. It
        // qualifies the clock/owner boundary, not persistence across power loss.
        let directory = tempfile::Builder::new()
            .prefix("hepta-clock-delay-")
            .tempdir_in("/run")
            .unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let root = RootAuthorityDirectory::open(directory.path()).unwrap();
        let record = initial_record(sample_os_clock().unwrap()).unwrap();
        let store = Arc::new(DelayedStore {
            inner: HostAuthorityFrontierStore::initialize(
                root.clone(),
                "slow-clock".into(),
                record,
            )
            .unwrap(),
            pause: Mutex::new(None),
        });
        let clock = Arc::new(HostAuthorityClock {
            store: store.clone(),
            owner_id: "slow-clock".into(),
            serial: Mutex::new(()),
        });
        Self {
            _directory: directory,
            root,
            store,
            clock,
        }
    }

    fn pause(&self) -> (mpsc::Receiver<ClockRecord>, mpsc::Sender<()>) {
        let (arrived_tx, arrived_rx) = mpsc::sync_channel(1);
        let (resume_tx, resume_rx) = mpsc::channel();
        *self.store.pause.lock().unwrap() = Some((arrived_tx, resume_rx));
        (arrived_rx, resume_tx)
    }
}

fn wait_past(unix_ns: u64) {
    while sample_os_clock().unwrap().realtime_ns <= unix_ns {
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
#[ignore = "explicit root-only controlled durability-acknowledgement delay"]
fn root_slow_durability_refuses_a_pre_io_timestamp_after_its_window() {
    let fixture = Fixture::new();
    let (arrived, resume) = fixture.pause();
    let clock = fixture.clock.clone();
    let worker = std::thread::spawn(move || clock.now_unix_ms());
    let durable = arrived.recv_timeout(Duration::from_secs(15)).unwrap();
    wait_past(durable.ceiling_ns + 10_000_000);
    resume.send(()).unwrap();
    assert_eq!(
        worker.join().unwrap(),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(fixture.store.load("slow-clock"), Ok(durable));
}

#[test]
#[ignore = "explicit root-only original FinalUse expiry negative with delayed durable I/O"]
fn root_slow_clock_cannot_enter_an_expired_original_final_use_token() {
    let fixture = Fixture::new();
    let mut seed = [0; 32];
    File::open("/dev/urandom")
        .unwrap()
        .read_exact(&mut seed)
        .unwrap();
    let key = SigningKey::from_bytes(&seed);
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let frontier = Arc::new(
        HostAuthorityFrontierStore::initialize(
            fixture.root.clone(),
            "clock-entry-owner".into(),
            FinalUseFrontier::for_initial_head(&head).unwrap(),
        )
        .unwrap(),
    );
    let local = fixture._directory.path().join("final-use");
    std::fs::create_dir(&local).unwrap();
    std::fs::set_permissions(&local, std::fs::Permissions::from_mode(0o700)).unwrap();
    let authority = FinalUseAuthority::open_state_dir_with_issuer_keys(
        &local,
        "clock-entry-owner".into(),
        vec![FinalUseIssuerTrustKey {
            key_id: "new-clock-test-key".into(),
            verifying_key: key.verifying_key().to_bytes(),
            not_before_authority_epoch: 1,
            not_after_authority_epoch: 1,
        }],
        head,
        fixture.clock.clone(),
        frontier,
    )
    .unwrap();
    let now = fixture.clock.now_unix_ms().unwrap();
    let binding = FinalUseBinding {
        subject_id: "clock-test".into(),
        destination_id: "no-effect".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "clock-entry-owner".into(),
        authority_epoch: 1,
        grant_id: "expires-during-clock-io".into(),
        nonce: [4; 32],
        binding: binding.clone(),
        not_before_unix_ms: now,
        expires_at_unix_ms: now + 5_000,
    };
    let signature = key
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    let expires = grant.expires_at_unix_ms * 1_000_000;
    let token = authority
        .claim(&SignedFinalUseGrant { grant, signature }, &binding)
        .unwrap();
    let (arrived, resume) = fixture.pause();
    let worker = std::thread::spawn(move || token.enter(&binding));
    let durable = arrived.recv_timeout(Duration::from_secs(15)).unwrap();
    assert!(
        durable.unix_ns < expires,
        "pre-I/O sample must still be before expiry"
    );
    wait_past(expires.max(durable.ceiling_ns) + 10_000_000);
    resume.send(()).unwrap();
    assert!(
        worker.join().unwrap().is_err(),
        "expired authority must not cross original FinalUse entry"
    );
}
