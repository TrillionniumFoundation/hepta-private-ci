//! Same-UID/synthetic-key qualification with the original durable owners.
use super::*;
use crate::root_writer_proof::tests::fixture;
use crate::root_writer_proof::tests::observation;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::sync::atomic::AtomicU64;
struct Frontier {
    value: Mutex<FinalUseFrontier>,
    commits: AtomicU64,
    wait: AtomicBool,
    entered: AtomicBool,
    fail: AtomicBool,
}
impl AuthorityFrontierStore<FinalUseFrontier> for Frontier {
    fn load(&self, _: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        Ok(*self.value.lock().unwrap())
    }
    fn compare_and_set(
        &self,
        _: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        self.entered.store(true, Ordering::Release);
        let bound = std::time::Instant::now() + Duration::from_secs(1);
        while self.wait.load(Ordering::Acquire) {
            if std::time::Instant::now() >= bound {
                return Err(AuthorityTrustError::Unavailable);
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        if self.fail.load(Ordering::Acquire) {
            return Err(AuthorityTrustError::Unavailable);
        }
        let mut value = self.value.lock().unwrap();
        if *value != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *value = *next;
        self.commits.fetch_add(1, Ordering::AcqRel);
        Ok(())
    }
}
fn owner(
    session: &AgentdRootAuthoritySession,
    key: [u8; 32],
) -> (FinalUseAuthority, Arc<Frontier>, tempfile::TempDir) {
    let head = session.revocations().unwrap();
    let frontier = Arc::new(Frontier {
        value: Mutex::new(FinalUseFrontier::for_initial_head(&head).unwrap()),
        commits: AtomicU64::new(0),
        wait: AtomicBool::new(false),
        entered: AtomicBool::new(false),
        fail: AtomicBool::new(false),
    });
    let directory = tempfile::tempdir().unwrap();
    let authority = FinalUseAuthority::open_state_dir_with_issuer_keys(
        directory.path(),
        "root-issuer".into(),
        vec![FinalUseIssuerTrustKey {
            key_id: "synthetic-fixture".into(),
            verifying_key: key,
            not_before_authority_epoch: 2,
            not_after_authority_epoch: 2,
        }],
        head,
        session.clock(),
        frontier.clone(),
    )
    .unwrap();
    (authority, frontier, directory)
}
async fn connected() -> (
    AgentdRootAuthoritySession,
    Arc<AtomicU64>,
    std::thread::JoinHandle<()>,
    [u8; 32],
) {
    let (trust, proof) = fixture();
    let key = trust.verifying_key;
    let (client, mut server) = UnixStream::pair().unwrap();
    let pid = std::process::id();
    let boot_id = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
        .unwrap()
        .trim()
        .to_string();
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
    let peer = AgentdRootAuthorityPeer {
        pid,
        boot_id: boot_id.clone(),
        process_start_ticks: stat
            .rsplit_once(") ")
            .unwrap()
            .1
            .split_whitespace()
            .nth(19)
            .unwrap()
            .parse()
            .unwrap(),
    };
    // SAFETY: live test PID; syscall returns exclusively owned descriptor.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(fd >= 0);
    let pidfd = unsafe { OwnedFd::from_raw_fd(fd as i32) };
    let stream = RootObservationStream::from_stream_for_uid(
        client,
        peer,
        pidfd,
        Duration::from_millis(300),
        Duration::from_secs(10),
        unsafe { libc::geteuid() },
    )
    .unwrap();
    let head = Arc::new(AtomicU64::new(1));
    let next_head = Arc::clone(&head);
    let base = boottime_ns().unwrap();
    let peer_boot = boot_id.clone();
    let worker = std::thread::spawn(move || {
        server
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        loop {
            let mut prefix = [0; 4];
            if server.read_exact(&mut prefix).is_err() {
                return;
            }
            let mut request = vec![0; u32::from_be_bytes(prefix) as usize];
            server.read_exact(&mut request).unwrap();
            let value: serde_json::Value = serde_json::from_slice(&request).unwrap();
            let response = if value["operation"] == HOST_WRITER_AUTHORIZATION_V1 {
                serde_json::to_vec(&HostWriterAuthorizationReadResponseV1 {
                    schema_version: 1,
                    operation: HOST_WRITER_AUTHORIZATION_V1.into(),
                    proof: proof.clone(),
                })
                .unwrap()
            } else {
                assert_eq!(value["operation"], HOST_AUTHORITY_OBSERVATION_V2);
                let mut sample = observation(&proof);
                let elapsed = (boottime_ns().unwrap() - base) / 1_000_000;
                sample.clock.boot_id = peer_boot.clone();
                sample.clock.anchor_boottime_ns = base;
                sample.clock.anchor_unix_ms = 2_000;
                sample.clock.ceiling_unix_ms = 3_001 + elapsed;
                sample.observed_unix_ms = 2_000 + elapsed;
                sample.revocations.revision = next_head.load(Ordering::Acquire);
                if sample.revocations.revision > 1 {
                    sample
                        .revocations
                        .revoked_grant_ids
                        .insert("revoked-effect".into());
                }
                sample.writer.store_revision = 7 + sample.revocations.revision;
                serde_json::to_vec(&sample).unwrap()
            };
            if server
                .write_all(&(response.len() as u32).to_be_bytes())
                .is_err()
                || server.write_all(&response).is_err()
            {
                return;
            }
        }
    });
    let session = AgentdRootAuthoritySession::connect_owned_stream(
        stream,
        boot_id,
        base,
        Duration::from_secs(10),
        trust,
    )
    .await
    .unwrap();
    (session, head, worker, key)
}
#[tokio::test]
async fn exact_original_consumers_activate_writer_and_drop_fences_retained_clones() {
    let (session, _, peer, key) = connected().await;
    let authority = session.authority();
    let verifier = session.verifier();
    assert!(verifier.verify(&authority, &authority.agent_id).is_err());
    let (device, _, _device_dir) = owner(&session, key);
    let (notes, _, _notes_dir) = owner(&session, key);
    session
        .activate_final_use_owners(vec![device, notes])
        .await
        .unwrap();
    verifier.verify(&authority, &authority.agent_id).unwrap();
    let mut changed = authority.clone();
    changed.owner_epoch += 1;
    assert!(verifier.verify(&changed, &changed.agent_id).is_err());
    verifier.verify(&authority, &authority.agent_id).unwrap();
    let clock = session.clock();
    drop(session);
    assert!(verifier.verify(&authority, &authority.agent_id).is_err());
    assert!(clock.now_unix_ms().is_err());
    tokio::time::sleep(Duration::from_millis(20)).await;
    peer.join().unwrap();
}
#[tokio::test]
async fn both_original_frontiers_finish_before_new_head_is_published() {
    let (session, head, peer, key) = connected().await;
    let (device, first, _device_dir) = owner(&session, key);
    let (notes, second, _notes_dir) = owner(&session, key);
    session
        .activate_final_use_owners(vec![device.clone(), notes.clone()])
        .await
        .unwrap();
    second.wait.store(true, Ordering::Release);
    head.store(2, Ordering::Release);
    tokio::time::timeout(Duration::from_secs(2), async {
        while !second.entered.load(Ordering::Acquire) {
            tokio::time::sleep(Duration::from_millis(2)).await;
        }
    })
    .await
    .unwrap();
    let before = std::time::Instant::now();
    assert!(
        session
            .verifier()
            .verify(&session.authority(), &session.authority().agent_id)
            .is_err()
    );
    assert!(before.elapsed() < Duration::from_millis(30));
    assert_eq!(first.commits.load(Ordering::Acquire), 1);
    assert_eq!(second.commits.load(Ordering::Acquire), 0);
    second.wait.store(false, Ordering::Release);
    tokio::time::timeout(Duration::from_millis(300), async {
        while session.revocations().is_err() {
            tokio::time::sleep(Duration::from_millis(2)).await;
        }
    })
    .await
    .unwrap();
    let current = session.revocations().unwrap();
    assert_eq!(current.revision, 2);
    assert_eq!(device.revocation_head().unwrap(), current);
    assert_eq!(notes.revocation_head().unwrap(), current);
    assert_eq!(second.commits.load(Ordering::Acquire), 1);
    drop(session);
    tokio::time::sleep(Duration::from_millis(20)).await;
    peer.join().unwrap();
}
#[tokio::test]
async fn uncertain_original_consumer_update_fences_even_with_fresh_root_responses() {
    let (session, head, peer, key) = connected().await;
    let (device, first, _device_dir) = owner(&session, key);
    let (notes, second, _notes_dir) = owner(&session, key);
    session
        .activate_final_use_owners(vec![device, notes])
        .await
        .unwrap();
    second.fail.store(true, Ordering::Release);
    head.store(2, Ordering::Release);
    tokio::time::timeout(Duration::from_secs(2), async {
        while !second.entered.load(Ordering::Acquire) {
            tokio::time::sleep(Duration::from_millis(2)).await;
        }
    })
    .await
    .unwrap();
    tokio::time::sleep(Duration::from_millis(20)).await;
    assert_eq!(first.commits.load(Ordering::Acquire), 1);
    assert!(session.clock().now_unix_ms().is_err());
    assert!(
        session
            .verifier()
            .verify(&session.authority(), &session.authority().agent_id)
            .is_err()
    );
    assert!(session.activate_final_use_owners(Vec::new()).await.is_err());
    drop(session);
    tokio::time::sleep(Duration::from_millis(20)).await;
    peer.join().unwrap();
}
