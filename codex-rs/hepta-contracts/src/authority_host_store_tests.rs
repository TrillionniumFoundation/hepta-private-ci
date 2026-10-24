use super::*;
use crate::FinalUseAuthority;
use crate::FinalUseBinding;
use crate::FinalUseError;
use crate::FinalUseFrontier;
use crate::FinalUseGrant;
use crate::FinalUseIssuerTrustKey;
use crate::FinalUseRevocations;
use crate::SignedFinalUseGrant;
use crate::SystemAuthorityClock;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::ExitStatusExt;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[cfg(target_os = "linux")]
#[path = "authority_host_issuer_tests.rs"]
mod issuer_tests;

#[path = "authority_host_store_durable_tests.rs"]
mod durable_tests;

#[path = "authority_host_store_cache_tests.rs"]
mod cache_tests;

#[path = "authority_host_observation_tests.rs"]
mod observation_tests;

const OWNER: &str = "local-host-authority";

// Tests exercise real filesystem persistence as their ordinary test UID. This
// helper is private to this test module and cannot construct a production root
// directory or bypass the public root/ancestor checks in a deployed broker.
fn test_directory(path: &Path) -> Arc<RootAuthorityDirectory> {
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
    let directory = open_directory(None, path).unwrap();
    let owner_uid = rustix::process::geteuid().as_raw();
    check_directory(&directory, owner_uid, DirectoryAccess::Private).unwrap();
    Arc::new(RootAuthorityDirectory {
        directory,
        owner_uid,
        before_directory_sync: std::sync::Mutex::new(None),
    })
}

fn wait_for(path: &Path) {
    let deadline = Instant::now() + Duration::from_secs(15);
    while !path.exists() {
        assert!(
            Instant::now() < deadline,
            "child did not reach its bounded barrier"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[test]
fn public_directory_rejects_unprotected_test_path() {
    let directory = tempfile::tempdir().unwrap();
    // Even a root test run must reject /tmp or another unprotected ancestor.
    assert!(RootAuthorityDirectory::open(directory.path()).is_err());
}

#[test]
fn register_cas_reopen_and_identity_checks() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap();
    assert_eq!(store.load(OWNER), Ok(1));
    assert_eq!(
        store.load("another-owner"),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(store.compare_and_set(OWNER, &1, &2), Ok(()));
    assert_eq!(
        store.compare_and_set(OWNER, &1, &3),
        Err(AuthorityTrustError::Conflict)
    );
    assert!(HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 0_u64).is_err());
    drop(store);
    let reopened = HostAuthorityFrontierStore::<u64>::open(root, OWNER.into()).unwrap();
    assert_eq!(reopened.load(OWNER), Ok(2));
}

#[cfg(target_os = "linux")]
#[test]
fn actual_host_clock_reopens_and_refuses_a_retained_future_highwater() {
    use crate::AuthorityClock;
    use crate::HostAuthorityClock;
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let clock = HostAuthorityClock::initialize(root.clone(), "host-clock".into()).unwrap();
    let first = clock.now_unix_ms().unwrap();
    drop(clock);
    let clock = HostAuthorityClock::open(root.clone(), "host-clock".into()).unwrap();
    assert!(clock.now_unix_ms().unwrap() >= first);
    assert!(HostAuthorityClock::initialize(root.clone(), "host-clock".into()).is_err());

    // Simulate an independently committed forward mapping, then reopen under
    // the real OS time, which is still above the original old anchor but below
    // that committed wall highwater. Reopening may not forget the advance.
    let retained =
        HostAuthorityFrontierStore::<serde_json::Value>::open(root.clone(), "host-clock".into())
            .unwrap();
    let expected = retained.load("host-clock").unwrap();
    let mut advanced = expected.clone();
    let future_ns = expected["unix_ns"].as_u64().unwrap() + 60_000_000_000;
    advanced["unix_ns"] = future_ns.into();
    advanced["wall_ns"] = future_ns.into();
    advanced["ceiling_ns"] = (future_ns + 1_000_000_000).into();
    retained
        .compare_and_set("host-clock", &expected, &advanced)
        .unwrap();
    drop(clock);
    assert!(HostAuthorityClock::open(root.clone(), "host-clock".into()).is_err());
    assert_eq!(retained.load("host-clock"), Ok(advanced));

    let future = serde_json::json!({ "boot_id": "previous-boot", "boottime_ns": 0,
        "unix_ns": u64::MAX - 1_000_000_000, "wall_ns": u64::MAX - 1_000_000_000, "ceiling_ns": u64::MAX });
    let store =
        HostAuthorityFrontierStore::initialize(root.clone(), "future-clock".into(), future.clone())
            .unwrap();
    assert!(HostAuthorityClock::open(root, "future-clock".into()).is_err());
    assert_eq!(store.load("future-clock"), Ok(future));
}

#[test]
fn stale_temporary_write_is_replaced_but_symlink_is_not_followed() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root, OWNER.into(), 1_u64).unwrap();
    let temporary = directory.path().join(format!("{}.next", store.name));
    std::fs::write(&temporary, b"incomplete prior process write").unwrap();
    std::fs::set_permissions(&temporary, std::fs::Permissions::from_mode(0o600)).unwrap();
    assert_eq!(store.compare_and_set(OWNER, &1, &2), Ok(()));
    let outside = directory.path().join("untouched");
    std::fs::write(&outside, b"retained input").unwrap();
    std::os::unix::fs::symlink(&outside, &temporary).unwrap();
    assert_eq!(
        store.compare_and_set(OWNER, &2, &3),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(std::fs::read(&outside).unwrap(), b"retained input");
    assert_eq!(store.load(OWNER), Ok(2));
}

#[test]
fn malformed_or_aliased_frontier_is_not_repaired() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap();
    let path = directory.path().join(&store.name);
    std::fs::write(&path, b"{").unwrap();
    assert_eq!(store.load(OWNER), Err(AuthorityTrustError::Invalid));
    assert_eq!(
        store.compare_and_set(OWNER, &1, &2),
        Err(AuthorityTrustError::Invalid)
    );
    std::fs::hard_link(&path, directory.path().join("alias")).unwrap();
    assert!(HostAuthorityFrontierStore::<u64>::open(root, OWNER.into()).is_err());
}

#[test]
fn separate_processes_have_one_cas_winner() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root, OWNER.into(), 1_u64).unwrap();
    let mut children = Vec::new();
    for id in [2_u64, 3] {
        children.push(
            Command::new(std::env::current_exe().unwrap())
                .arg("--exact")
                .arg("authority_host_store::tests::cas_process_child")
                .arg("--ignored")
                .arg("--nocapture")
                .env("HEPTA_HOST_CAS_CHILD_ROOT", directory.path())
                .env("HEPTA_HOST_CAS_CHILD_ID", id.to_string())
                .spawn()
                .unwrap(),
        );
    }
    wait_for(&directory.path().join("ready-2"));
    wait_for(&directory.path().join("ready-3"));
    std::fs::write(directory.path().join("go"), []).unwrap();
    for child in &mut children {
        assert!(child.wait().unwrap().success());
    }
    let results: Vec<_> = [2, 3]
        .into_iter()
        .map(|id| std::fs::read_to_string(directory.path().join(format!("result-{id}"))).unwrap())
        .collect();
    assert_eq!(
        results
            .iter()
            .filter(|value| value.as_str() == "committed")
            .count(),
        1
    );
    assert!(matches!(store.load(OWNER), Ok(2 | 3)));
}

#[test]
#[ignore = "subprocess entry, exercised by separate_processes_have_one_cas_winner"]
fn cas_process_child() {
    let Ok(path) = std::env::var("HEPTA_HOST_CAS_CHILD_ROOT") else {
        return;
    };
    let id: u64 = std::env::var("HEPTA_HOST_CAS_CHILD_ID")
        .unwrap()
        .parse()
        .unwrap();
    let path = Path::new(&path);
    let root = test_directory(path);
    // Opening and independently observing a durable record now take the same
    // nonblocking publication lock. Only this pre-mutation fixture setup may
    // retry contention; the actual competing CAS below is attempted once.
    let deadline = Instant::now() + Duration::from_secs(10);
    let store = loop {
        let result = HostAuthorityFrontierStore::<u64>::open(root.clone(), OWNER.into())
            .and_then(|store| store.load(OWNER).map(|value| (store, value)));
        match result {
            Ok((store, value)) => {
                assert_eq!(value, 1);
                break store;
            }
            Err(AuthorityTrustError::Conflict) if Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(5));
            }
            other => panic!("pre-mutation fixture open failed: {:?}", other.err()),
        }
    };
    std::fs::write(path.join(format!("ready-{id}")), []).unwrap();
    wait_for(&path.join("go"));
    let result = store.compare_and_set(OWNER, &1, &id);
    let result = match result {
        Ok(()) => "committed",
        Err(AuthorityTrustError::Conflict) => "refused",
        other => panic!("unexpected CAS result: {other:?}"),
    };
    std::fs::write(path.join(format!("result-{id}")), result).unwrap();
}

#[test]
fn committed_frontier_survives_controlled_sigkill() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap();
    let mut child = Command::new(std::env::current_exe().unwrap())
        .arg("--exact")
        .arg("authority_host_store::tests::committed_frontier_child")
        .arg("--ignored")
        .env("HEPTA_HOST_CAS_KILL_ROOT", directory.path())
        .spawn()
        .unwrap();
    wait_for(&directory.path().join("committed"));
    child.kill().unwrap();
    assert_eq!(child.wait().unwrap().signal(), Some(9));
    let reopened = HostAuthorityFrontierStore::<u64>::open(root, OWNER.into()).unwrap();
    assert_eq!(reopened.load(OWNER), Ok(2));
}

#[test]
#[ignore = "subprocess entry, exercised by committed_frontier_survives_controlled_sigkill"]
fn committed_frontier_child() {
    let Ok(path) = std::env::var("HEPTA_HOST_CAS_KILL_ROOT") else {
        return;
    };
    let path = Path::new(&path);
    let root = test_directory(path);
    let store = HostAuthorityFrontierStore::<u64>::open(root, OWNER.into()).unwrap();
    store.compare_and_set(OWNER, &1, &2).unwrap();
    std::fs::write(path.join("committed"), []).unwrap();
    loop {
        std::thread::park();
    }
}

struct AuthorityFixture {
    local: tempfile::TempDir,
    root: Arc<RootAuthorityDirectory>,
    key: SigningKey,
    head: FinalUseRevocations,
}

impl AuthorityFixture {
    fn new(path: &Path) -> Self {
        let mut seed = [0_u8; 32];
        File::open("/dev/urandom")
            .unwrap()
            .read_exact(&mut seed)
            .unwrap();
        let local = tempfile::tempdir().unwrap();
        std::fs::set_permissions(local.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        Self {
            local,
            root: test_directory(path),
            key: SigningKey::from_bytes(&seed),
            head: FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        }
    }

    fn open(&self) -> Result<FinalUseAuthority, FinalUseError> {
        FinalUseAuthority::open_state_dir_with_issuer_keys(
            self.local.path(),
            OWNER.into(),
            vec![FinalUseIssuerTrustKey {
                key_id: "new-host-key".into(),
                verifying_key: self.key.verifying_key().to_bytes(),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: 1,
            }],
            self.head.clone(),
            Arc::new(SystemAuthorityClock),
            Arc::new(
                HostAuthorityFrontierStore::<FinalUseFrontier>::open(
                    self.root.clone(),
                    OWNER.into(),
                )
                .unwrap(),
            ),
        )
    }

    fn grant(&self, grant_id: &str) -> SignedFinalUseGrant {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        let mut nonce = [0_u8; 32];
        File::open("/dev/urandom")
            .unwrap()
            .read_exact(&mut nonce)
            .unwrap();
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: OWNER.into(),
            authority_epoch: 1,
            grant_id: grant_id.into(),
            nonce,
            binding: FinalUseBinding {
                subject_id: "host-authority-test".into(),
                destination_id: "no-effect".into(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            not_before_unix_ms: now.saturating_sub(1),
            expires_at_unix_ms: now + 60_000,
        };
        let signature = self
            .key
            .sign(&grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }
}

#[test]
fn original_final_use_rejects_replay_revocation_and_rolled_back_local_state() {
    let protected = tempfile::tempdir().unwrap();
    let fixture = AuthorityFixture::new(protected.path());
    HostAuthorityFrontierStore::initialize(
        fixture.root.clone(),
        OWNER.into(),
        FinalUseFrontier::for_initial_head(&fixture.head).unwrap(),
    )
    .unwrap();
    let authority = fixture.open().unwrap();
    let retained: Vec<_> = std::fs::read_dir(fixture.local.path())
        .unwrap()
        .map(|entry| {
            let entry = entry.unwrap();
            (entry.file_name(), std::fs::read(entry.path()).unwrap())
        })
        .collect();
    let grant = fixture.grant("first-use");
    authority.claim(&grant, &grant.grant.binding).unwrap();
    assert!(matches!(
        authority.claim(&grant, &grant.grant.binding),
        Err(FinalUseError::AlreadyClaimed)
    ));
    let revoked = fixture.grant("revoked-use");
    let mut head = fixture.head.clone();
    head.revision += 1;
    head.revoked_grant_ids.insert("revoked-use".into());
    authority.update_revocations(head).unwrap();
    assert!(matches!(
        authority.claim(&revoked, &revoked.grant.binding),
        Err(FinalUseError::Revoked)
    ));
    drop(authority);
    for (name, bytes) in retained {
        std::fs::write(fixture.local.path().join(name), bytes).unwrap();
    }
    assert!(matches!(
        fixture.open(),
        Err(FinalUseError::AntiRollbackViolation)
    ));
}
