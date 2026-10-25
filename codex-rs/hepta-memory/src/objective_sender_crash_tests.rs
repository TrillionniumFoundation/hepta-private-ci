//! Real subprocess death at original commit/ACK boundaries. The external cut
//! file and authority below are explicit test-host fixtures, not production
//! provider implementations or a second Objective ledger.

use super::test_support::*;
use super::*;
use crate::CognitiveStore;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicUsize;
use tempfile::TempDir;

const CHILD_TEST: &str =
    "production_writer::objective_sender::crash_tests::objective_sender_subprocess_fixture";
const CRASH_EXIT: i32 = 72;

struct CrashCheckpoint {
    host_root: PathBuf,
    crash_after: usize,
    calls: AtomicUsize,
}

impl ObjectiveSenderCheckpoint for CrashCheckpoint {
    async fn acknowledge_current(
        &self,
        current: &CognitiveRecoveryAnchor,
        writer: &ObjectiveSenderWriterFence,
    ) -> Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        let bytes = serde_json::to_vec(&(current, writer)).unwrap();
        let mut file = File::create(
            self.host_root
                .join(format!("independent-test-cut-{call}.json")),
        )
        .unwrap();
        file.write_all(&bytes).unwrap();
        file.sync_all().unwrap();
        File::open(&self.host_root).unwrap().sync_all().unwrap();
        if call == self.crash_after {
            // No Rust destructors run. SQLite's already-committed request/event
            // survives; the second BEGIN IMMEDIATE snapshot dies with process.
            std::process::exit(CRASH_EXIT);
        }
        Ok(current.clone())
    }
}

#[test]
#[ignore = "subprocess fixture is invoked with a private test root by the parent test"]
fn objective_sender_subprocess_fixture() {
    let root = PathBuf::from(
        std::env::var_os("HEPTA_OBJECTIVE_SENDER_TEST_ROOT").expect("private child root"),
    );
    let phase = std::env::var("HEPTA_OBJECTIVE_SENDER_TEST_PHASE").expect("child phase");
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        std::fs::create_dir_all(root.join("fleet")).unwrap();
        let owner = agent_id(OWNER);
        let layout = HeptaFleetRoot::parse(root.join("fleet"))
            .unwrap()
            .layout()
            .agent(&owner);
        let verifier = Arc::new(TestVerifier::new());
        let store = if phase == "compete" {
            CognitiveStore::open(&layout).await.unwrap()
        } else {
            // Explicit test genesis only. Production startup is the original
            // independently authorized recovery path, whose private generation
            // already exists before SQLite can create its WAL/SHM. Never repair
            // a crashed source's permissions or fall back to legacy open.
            let genesis_store = CognitiveStore::open(&layout).await.unwrap();
            let genesis_cut = genesis_store.recovery_anchor().await.unwrap();
            genesis_store.close().await;
            CognitiveStore::open_with_recovery(
                &layout,
                crate::CognitiveRecoveryRequirement::ExactCurrentCut(&genesis_cut),
                &authority(&owner, 87),
                verifier.as_ref(),
            )
            .await
            .expect("original production recovery bootstrap from explicit test genesis")
        };
        let lease = if phase == "compete" {
            "objective-sender-other-process"
        } else {
            LEASE
        };
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                authority(&owner, 87),
                verifier.clone(),
                lease,
                1,
            )
            .await
            .unwrap(),
        );
        if phase == "compete" {
            let checkpoint = Arc::new(TestCheckpoint::new(verifier));
            let sender = writer
                .objective_sender(checkpoint.clone(), Duration::from_secs(2))
                .unwrap();
            let mut original = request();
            original.origin.request_id += 1;
            original.origin.expected_peer_pid += 1;
            original.origin.endpoint_identity.push_str(".other-process");
            assert!(matches!(
                sender.retain_before_send(original).await,
                Err(ObjectiveSenderError::AlreadyRetained)
            ));
            assert!(checkpoint.seen.lock().unwrap().is_empty());
            return;
        }
        let checkpoint = Arc::new(CrashCheckpoint {
            host_root: root,
            crash_after: if phase == "retain" { 1 } else { 2 },
            calls: AtomicUsize::new(0),
        });
        let sender = writer
            .objective_sender(checkpoint, Duration::from_secs(2))
            .unwrap();
        let ticket = sender.retain_before_send(request()).await.unwrap();
        match phase.as_str() {
            "observation" => {
                sender.mark_send_started(&ticket).await.unwrap();
                sender
                    .retain_observation(
                        &ticket,
                        &observation(
                            ObjectiveSenderObservationKind::Submission,
                            "{\"status\":\"unknown_after_write\"}",
                        ),
                    )
                    .await
                    .unwrap();
            }
            "cancel" => sender.retain_local_cancellation(&ticket).await.unwrap(),
            _ => panic!("child should have exited at the retained request cut"),
        }
        panic!("crash checkpoint did not terminate the child");
    });
}

fn child(root: &std::path::Path, phase: &str) -> std::process::Output {
    Command::new(std::env::current_exe().unwrap())
        .args(["--exact", CHILD_TEST, "--ignored", "--nocapture"])
        .env("HEPTA_OBJECTIVE_SENDER_TEST_ROOT", root)
        .env("HEPTA_OBJECTIVE_SENDER_TEST_PHASE", phase)
        .output()
        .expect("start original package test subprocess")
}

#[tokio::test]
async fn process_death_after_each_committed_cut_recovers_without_new_send_permission() {
    for phase in ["retain", "observation", "cancel"] {
        let temp = TempDir::new().unwrap();
        let output = child(temp.path(), phase);
        assert_eq!(
            output.status.code(),
            Some(CRASH_EXIT),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let index = if phase == "retain" { 1 } else { 2 };
        let (current, fence): (CognitiveRecoveryAnchor, ObjectiveSenderWriterFence) =
            serde_json::from_slice(
                &std::fs::read(
                    temp.path()
                        .join(format!("independent-test-cut-{index}.json")),
                )
                .unwrap(),
            )
            .unwrap();
        let owner = agent_id(OWNER);
        let auth = authority(&owner, 87);
        let verifier = Arc::new(TestVerifier::new());
        assert_eq!(current.owner_agent_id, owner);
        assert_eq!(fence.owner_agent_id, owner);
        if index == 2 {
            let (stale, _): (CognitiveRecoveryAnchor, ObjectiveSenderWriterFence) =
                serde_json::from_slice(
                    &std::fs::read(temp.path().join("independent-test-cut-1.json")).unwrap(),
                )
                .unwrap();
            assert_ne!(stale.state_digest, current.state_digest);
            assert!(
                CognitiveStore::open_with_recovery(
                    &layout(&temp, &owner),
                    crate::CognitiveRecoveryRequirement::ExactCurrentCut(&stale),
                    &auth,
                    verifier.as_ref(),
                )
                .await
                .is_err()
            );
        }
        let store = CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            crate::CognitiveRecoveryRequirement::ExactCurrentCut(&current),
            &auth,
            verifier.as_ref(),
        )
        .await
        .expect("original exact-cut recovery after real process exit");
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store.clone(),
                auth,
                verifier.clone(),
                LEASE,
                1,
            )
            .await
            .unwrap(),
        );
        let checkpoint = Arc::new(TestCheckpoint::new(verifier));
        let sender = writer
            .objective_sender(checkpoint.clone(), Duration::from_secs(2))
            .unwrap();
        assert!(matches!(
            sender.retain_before_send(request()).await,
            Err(ObjectiveSenderError::AlreadyRetained)
        ));
        let mut page = sender
            .retained_page(ObjectiveSenderRetainedPosition::Beginning)
            .await
            .unwrap();
        assert!(page.next.is_none());
        assert_eq!(page.requests.len(), 1);
        let original = page.requests.pop().unwrap();
        assert_eq!(original.exact_original(), request().exact_original());
        let ticket = sender.recover_pending(original).await.unwrap();
        assert!(matches!(
            sender.mark_send_started(&ticket).await,
            Err(ObjectiveSenderError::SendPermissionUnavailable)
        ));
        assert!(matches!(
            sender.retain_local_cancellation(&ticket).await,
            Err(ObjectiveSenderError::LocalCancellationUnavailable)
        ));
        let snapshot = sender.snapshot(&ticket).await.unwrap();
        assert_eq!(snapshot.locally_cancelled, phase == "cancel");
        if phase == "observation" {
            assert!(
                snapshot.observations
                    == vec![observation(
                        ObjectiveSenderObservationKind::Submission,
                        "{\"status\":\"unknown_after_write\"}",
                    )]
            );
        } else {
            assert!(snapshot.observations.is_empty());
        }
        assert!(checkpoint.seen.lock().unwrap().is_empty());
        drop(ticket);
        drop(sender);
        drop(writer);
        store.close().await;
    }
}

#[tokio::test]
async fn a_second_real_process_and_different_lease_still_cannot_send_retained_run() {
    let fixture = Fixture::new().await;
    let ticket = fixture
        .sender()
        .retain_before_send(request())
        .await
        .unwrap();
    let output = child(fixture.temp.path(), "compete");
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let request_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_objective_sender_requests")
            .fetch_one(&fixture.store.pool)
            .await
            .unwrap();
    assert_eq!(request_count, 1);
    fixture.sender().mark_send_started(&ticket).await.unwrap();
}
