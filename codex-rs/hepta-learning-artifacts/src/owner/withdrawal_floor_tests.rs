use super::*;

use std::process::Command;
use std::process::Stdio;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use pretty_assertions::assert_eq;

use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalScopeV1;
use crate::test_support::FixtureValue;

static NEXT: AtomicU64 = AtomicU64::new(1);

struct TestDir(PathBuf);

impl TestDir {
    fn new() -> Self {
        let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "artifact-withdrawal-floor-{}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&root).fixture("create fresh test root");
        fs::create_dir(root.join("writer")).fixture("create control parent");
        Self(root)
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).fixture("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn frontier(count: usize, branch: &str) -> DatasetWithdrawalRegistry {
    let mut registry = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("withdrawal-authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    });
    for index in 0..count {
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id(&format!("notice-{index}")),
                dataset_digest: digest(&format!("dataset-{branch}-{index}")),
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("withdrawal-authority"),
                credential_chain_digest: digest("test-credential"),
                signing_key_digest: digest("test-key"),
                authority_epoch: 1,
                issued_at: 10,
            })
            .fixture("append fixture notice");
    }
    registry
}

fn floor(root: &Path) -> DurableWithdrawalFloor {
    DurableWithdrawalFloor::new(
        root,
        &id("artifacts"),
        frontier(0, "a").scope_digest().fixture("scoped frontier"),
        digest("binding"),
    )
}

#[test]
fn prefix_extensions_reopen_but_all_shorter_frontiers_and_forks_fail() {
    let directory = TestDir::new();
    for count in 0..6 {
        floor(&directory.0)
            .persist(&frontier(count, "a"))
            .fixture("persist monotonic prefix");
        for stale in 0..count {
            assert!(floor(&directory.0).persist(&frontier(stale, "a")).is_err());
        }
        if count > 0 {
            assert!(floor(&directory.0).persist(&frontier(count, "b")).is_err());
        }
        floor(&directory.0)
            .persist(&frontier(count, "a"))
            .fixture("exact resync");
    }
    assert_eq!(
        fs::read_dir(directory.0.join("writer/withdrawal-floor-v1"))
            .fixture("enumerate bounded floors")
            .count(),
        6
    );
}

#[test]
fn every_truncation_and_byte_mutation_is_rejected_without_repair() {
    let directory = TestDir::new();
    let floor = floor(&directory.0);
    let frontier = frontier(0, "a");
    floor.persist(&frontier).fixture("initial floor");
    let path = floor.directory.join("0000.v1");
    let expected = fs::read(&path).fixture("read original");
    for length in 0..expected.len() {
        let truncated = &expected[..length];
        fs::write(&path, truncated).fixture("inject truncation");
        assert!(floor.persist(&frontier).is_err());
        assert_eq!(fs::read(&path).fixture("not repaired"), truncated);
    }
    for offset in 0..expected.len() {
        let mut altered = expected.clone();
        altered[offset] ^= 1;
        fs::write(&path, &altered).fixture("inject mutation");
        assert!(floor.persist(&frontier).is_err());
        assert_eq!(fs::read(&path).fixture("not overwritten"), altered);
    }
}

#[test]
fn missing_prefix_unknown_entry_and_symlink_are_not_new_stores() {
    let directory = TestDir::new();
    let floor = floor(&directory.0);
    floor.persist(&frontier(2, "a")).fixture("initial chain");
    let first = floor.directory.join("0000.v1");
    let original = fs::read(&first).fixture("original genesis");
    fs::remove_file(&first).fixture("inject missing prefix");
    assert!(floor.persist(&frontier(2, "a")).is_err());
    fs::write(&first, &original).fixture("restore test fixture");
    let unknown = floor.directory.join("unrecognized");
    fs::write(&unknown, b"").fixture("inject unknown entry");
    assert!(floor.persist(&frontier(2, "a")).is_err());
    fs::remove_file(unknown).fixture("remove injected entry");
    let target = directory.0.join("foreign");
    fs::write(&target, &original).fixture("symlink target");
    fs::remove_file(&first).fixture("replace test fixture");
    std::os::unix::fs::symlink(&target, &first).fixture("inject symlink");
    assert!(floor.persist(&frontier(2, "a")).is_err());
    assert_eq!(fs::read(target).fixture("target unchanged"), original);
}

#[test]
fn full_uncertain_write_resyncs_but_create_only_orphan_never_succeeds() {
    for phase in ["created", "written", "file_synced", "directory_synced"] {
        let directory = TestDir::new();
        let floor = floor(&directory.0);
        let frontier = frontier(1, "a");
        assert!(
            floor
                .persist_with_hook(&frontier, |sequence, boundary| {
                    if sequence == 1 && boundary == phase {
                        return Err(io::Error::other("injected boundary failure"));
                    }
                    Ok(())
                })
                .is_err()
        );
        assert_eq!(floor.persist(&frontier).is_ok(), phase != "created");
    }
}

#[test]
fn foreign_binding_and_unscoped_frontier_fail_before_creation() {
    let directory = TestDir::new();
    let floor = floor(&directory.0);
    assert!(floor.persist(&DatasetWithdrawalRegistry::new()).is_err());
    assert!(!floor.directory.exists());
    floor.persist(&frontier(1, "a")).fixture("initial scoped floor");
    let foreign = DurableWithdrawalFloor::new(
        &directory.0,
        &id("artifacts"),
        frontier(0, "a").scope_digest().fixture("scope"),
        digest("different-binding"),
    );
    assert!(foreign.persist(&frontier(1, "a")).is_err());
}

#[test]
fn withdrawal_floor_crash_child() {
    let Some(root) = std::env::var_os("HEPTA_WITHDRAWAL_CRASH_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    let phase = std::env::var("HEPTA_WITHDRAWAL_CRASH_PHASE").fixture("phase");
    let sequence: usize = std::env::var("HEPTA_WITHDRAWAL_CRASH_SEQUENCE")
        .fixture("sequence")
        .parse()
        .fixture("numeric sequence");
    floor(&root)
        .persist_with_hook(&frontier(2, "a"), |index, boundary| {
            if index == sequence && boundary == phase {
                fs::write(root.join("ready"), b"at-boundary")?;
                // The parent SIGKILLs this process. A watchdog avoids leaving a
                // child alive if the test runner itself disappears.
                std::thread::sleep(Duration::from_secs(20));
                return Err(io::Error::other("crash parent did not terminate child"));
            }
            Ok(())
        })
        .fixture("child must reach selected boundary");
}

#[test]
fn sigkill_each_floor_boundary_reopens_only_exact_complete_records() {
    for sequence in 0..3 {
        for phase in ["created", "written", "file_synced", "directory_synced"] {
            let directory = TestDir::new();
            let mut child = Command::new(std::env::current_exe().fixture("test executable"))
                .args([
                    "--exact",
                    "owner_service::durable_withdrawals::tests::withdrawal_floor_crash_child",
                    "--nocapture",
                ])
                .env("HEPTA_WITHDRAWAL_CRASH_ROOT", &directory.0)
                .env("HEPTA_WITHDRAWAL_CRASH_PHASE", phase)
                .env("HEPTA_WITHDRAWAL_CRASH_SEQUENCE", sequence.to_string())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .fixture("spawn crash child");
            let started = Instant::now();
            while !directory.0.join("ready").is_file()
                && started.elapsed() < Duration::from_secs(10)
            {
                if child.try_wait().fixture("observe child").is_some() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(10));
            }
            let ready = directory.0.join("ready").is_file();
            let _ = child.kill();
            let status = child.wait().fixture("reap crash child");
            assert!(ready, "child did not reach {sequence}/{phase}");
            assert!(!status.success());
            assert_eq!(
                floor(&directory.0).persist(&frontier(2, "a")).is_ok(),
                phase != "created"
            );
        }
    }
}
