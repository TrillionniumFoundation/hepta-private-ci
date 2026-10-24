//! Physical attempt naming with real UID60001 processes/files and original
//! store locking. The explicit head fixture is not Root authority qualification.
use super::*;
use crate::CognitiveCheckpointHead;
use crate::CognitiveCheckpointPeerLifetime;
use crate::CognitiveCheckpointPhase;
use crate::CognitiveCheckpointWriterBinding;
use pretty_assertions::assert_eq;

fn publisher() -> (OwnedChild, CognitiveCheckpointPeerLifetime) {
    let mut child = OwnedChild(
        Command::new("setpriv")
            .args([
                "--reuid=60001",
                "--regid=60001",
                "--clear-groups",
                "--no-new-privs",
                "/usr/bin/sleep",
                "120",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        assert!(child.0.try_wait().unwrap().is_none());
        let status = std::fs::read_to_string(format!("/proc/{}/status", child.0.id())).unwrap();
        if status
            .lines()
            .find_map(|line| line.strip_prefix("Uid:"))
            .is_some_and(|ids| ids.split_whitespace().all(|id| id == "60001"))
        {
            let stat = std::fs::read_to_string(format!("/proc/{}/stat", child.0.id())).unwrap();
            let peer = CognitiveCheckpointPeerLifetime {
                uid: 60001,
                pid: child.0.id(),
                boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
                    .unwrap()
                    .trim()
                    .into(),
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
            return (child, peer);
        }
        assert!(
            Instant::now() < deadline,
            "actual UID60001 publisher did not start"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
}

fn naming_head(
    fixture: &Fixture,
    peer: CognitiveCheckpointPeerLifetime,
    generation: u64,
) -> CognitiveCheckpointHead {
    CognitiveCheckpointHead {
        schema_version: 1,
        owner_agent_id: fixture.cut.owner_agent_id.clone(),
        publisher_epoch: generation,
        counter: generation,
        last_mutation_sequence: 0,
        writer_binding: CognitiveCheckpointWriterBinding {
            lease_id: "physical-component-fixture".into(),
            generation,
            authority_epoch: 1,
            owner_epoch: generation,
            authority_grant_digest: Sha256Digest::for_bytes(b"component naming; no authority"),
            fencing_token_digest: Sha256Digest::for_bytes(b"component naming; no fence"),
            expires_at_unix_seconds: 1,
        },
        peer_lifetime: peer,
        phase: CognitiveCheckpointPhase::Current,
        last_current: fixture.cut.clone(),
        proposal: None,
        last_request: None,
    }
}

#[tokio::test]
#[ignore = "requires actual Root0 plus independent Root0/0711 owner-install namespace"]
async fn root_new_physical_attempt_preserves_partial_and_published_predecessor_files() {
    let (fixture, material) = Fixture::new().await;
    let (old, peer) = publisher();
    let head = naming_head(&fixture, peer, 1);
    let installed = material
        .install_for_registered_successor(&fixture.owner_layout, &head)
        .unwrap();
    let old_path = installed.path().to_path_buf();
    let old_bytes = std::fs::read(&old_path).unwrap();
    let old_metadata = std::fs::metadata(&old_path).unwrap();
    installed.verify_unchanged().unwrap();
    // The actual physical publication survives loss of this caller/return.
    drop(installed);
    drop(old); // Actual child is killed and reaped; no peer metadata is reused.
    let material =
        CognitiveStore::verify_retained_root_material(&fixture.source_layout, &fixture.cut)
            .await
            .unwrap();
    assert!(
        material
            .install_for_registered_successor(&fixture.owner_layout, &head)
            .is_err(),
        "the same attempt must never reuse or overwrite its visible candidate"
    );
    assert_eq!(std::fs::read(&old_path).unwrap(), old_bytes);
    let (next, peer) = publisher();
    let next_head = naming_head(&fixture, peer, 2);
    let material =
        CognitiveStore::verify_retained_root_material(&fixture.source_layout, &fixture.cut)
            .await
            .unwrap();
    let installed = material
        .install_for_registered_successor(&fixture.owner_layout, &next_head)
        .unwrap();
    let next_path = installed.path().to_path_buf();
    assert_ne!(old_path, next_path);
    assert_eq!(std::fs::read(&next_path).unwrap(), old_bytes);
    assert_eq!(
        std::fs::metadata(&old_path).unwrap().ino(),
        old_metadata.ino()
    );
    assert_eq!(
        resolve_active_database_path(fixture.owner_layout.cognitive_root()).unwrap(),
        next_path
    );
    complete(fixture.child("locked", &next_path));
    installed.verify_unchanged().unwrap();
    drop(installed);
    drop(next);
    complete(fixture.child("recover", &next_path));
    fixture.assert_old_dirty_unchanged();
    assert_eq!(std::fs::read(&old_path).unwrap(), old_bytes);
}

#[tokio::test]
#[ignore = "requires actual Root0 plus independent Root0/0711 owner-install namespace"]
async fn root_failed_physical_candidate_does_not_block_a_distinct_successor_attempt() {
    let (fixture, material) = Fixture::new().await;
    let (old, peer) = publisher();
    let old_head = naming_head(&fixture, peer, 1);
    let discriminator = Sha256Digest::for_bytes(
        &serde_json::to_vec(&("hepta:cognitive:root-successor-install:v1", &old_head)).unwrap(),
    );
    let partial = fixture
        .owner_layout
        .cognitive_root()
        .join(recovered_database_filename(&fixture.cut, &discriminator));
    owner_file(
        &partial,
        b"actual incomplete candidate retained for reconciliation",
    );
    let partial_inode = std::fs::metadata(&partial).unwrap().ino();
    assert!(
        material
            .install_for_registered_successor(&fixture.owner_layout, &old_head)
            .is_err()
    );
    drop(old);
    let (_next, peer) = publisher();
    let next_head = naming_head(&fixture, peer, 2);
    let material =
        CognitiveStore::verify_retained_root_material(&fixture.source_layout, &fixture.cut)
            .await
            .unwrap();
    let installed = material
        .install_for_registered_successor(&fixture.owner_layout, &next_head)
        .unwrap();
    installed.verify_unchanged().unwrap();
    assert_ne!(installed.path(), partial);
    assert_eq!(
        std::fs::read(&partial).unwrap(),
        b"actual incomplete candidate retained for reconciliation"
    );
    assert_eq!(std::fs::metadata(&partial).unwrap().ino(), partial_inode);
    fixture.assert_old_dirty_unchanged();
}
