use std::fs;
use std::fs::File;
use std::io;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

use super::FsProjectionPersistenceV1;
use super::NduProjectionStoreError;
use super::NduProjectionStoreV1;
use super::ProjectionPersistenceV1;
use crate::NduProjectionKindV1;

const CHILD_ROOT_ENV: &str = "HEPTA_NDU_PROCESS_KILL_ROOT";
const CHILD_STAGE_ENV: &str = "HEPTA_NDU_PROCESS_KILL_STAGE";
const MARKER_FILE: &str = ".process-kill-cut-ready";
static NONCE: AtomicU64 = AtomicU64::new(1);

struct TempRoot(PathBuf);

impl TempRoot {
    fn new(label: &str) -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-ndu-process-kill-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&path).expect("create process-kill root");
        Self(path)
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct KillAtPersistenceCut {
    root: PathBuf,
    stage: String,
    real: FsProjectionPersistenceV1,
}

impl KillAtPersistenceCut {
    fn pause_if(&self, stage: &str) -> io::Result<()> {
        if self.stage != stage {
            return Ok(());
        }
        let marker = self.root.join(MARKER_FILE);
        let mut file = File::create(&marker)?;
        writeln!(file, "{stage}")?;
        file.sync_all()?;
        File::open(&self.root)?.sync_all()?;
        loop {
            thread::sleep(Duration::from_secs(60));
        }
    }
}

impl ProjectionPersistenceV1 for KillAtPersistenceCut {
    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        self.real.write_temp(path, bytes)?;
        self.pause_if("after_temp_write")
    }

    fn sync_temp(&self, path: &Path) -> io::Result<()> {
        self.real.sync_temp(path)?;
        self.pause_if("after_file_sync")
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        self.pause_if("before_rename")?;
        self.real.rename(from, to)?;
        self.pause_if("after_rename")
    }

    fn sync_parent(&self, root: &Path) -> io::Result<()> {
        self.pause_if("before_directory_sync")?;
        self.real.sync_parent(root)?;
        self.pause_if("after_directory_sync")
    }
}

struct ErrnoPersistence {
    errno: i32,
    real: FsProjectionPersistenceV1,
}

impl ProjectionPersistenceV1 for ErrnoPersistence {
    fn write_temp(&self, _path: &Path, _bytes: &[u8]) -> io::Result<()> {
        Err(io::Error::from_raw_os_error(self.errno))
    }

    fn sync_temp(&self, path: &Path) -> io::Result<()> {
        self.real.sync_temp(path)
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        self.real.rename(from, to)
    }

    fn sync_parent(&self, root: &Path) -> io::Result<()> {
        self.real.sync_parent(root)
    }
}

#[test]
fn process_kill_cut_child() {
    let Ok(root) = std::env::var(CHILD_ROOT_ENV) else {
        return;
    };
    let stage = std::env::var(CHILD_STAGE_ENV).expect("process-kill stage");
    let persistence = Arc::new(KillAtPersistenceCut {
        root: PathBuf::from(&root),
        stage,
        real: FsProjectionPersistenceV1,
    });
    let mut store = NduProjectionStoreV1::open_with_persistence(&root, persistence)
        .expect("child opens initialized store");
    store
        .append_projection(
            NduProjectionKindV1::Preference,
            digest("process-kill-identity"),
            digest("process-kill-objective"),
            digest("process-kill-subject"),
            digest("process-kill-projection"),
        )
        .expect("configured cut must pause before append returns");
    panic!("configured process-kill cut was not reached");
}

#[test]
fn process_kill_matrix_reopens_at_every_persistence_cut() {
    let cuts = [
        ("after_temp_write", 0_usize),
        ("after_file_sync", 0),
        ("before_rename", 0),
        ("after_rename", 1),
        ("before_directory_sync", 1),
        ("after_directory_sync", 1),
    ];
    for (stage, expected_records) in cuts {
        let root = TempRoot::new(stage);
        drop(NduProjectionStoreV1::open(&root.0).expect("initialize kill root"));
        let marker = root.0.join(MARKER_FILE);
        let mut child = Command::new(std::env::current_exe().expect("current test executable"))
            .arg("process_kill_cut_child")
            .arg("--nocapture")
            .arg("--test-threads=1")
            .env(CHILD_ROOT_ENV, &root.0)
            .env(CHILD_STAGE_ENV, stage)
            .spawn()
            .expect("spawn process-kill child");

        let deadline = Instant::now() + Duration::from_secs(20);
        loop {
            if marker.is_file() {
                break;
            }
            if let Some(status) = child.try_wait().expect("poll process-kill child") {
                panic!("child exited before cut {stage}: {status}");
            }
            assert!(Instant::now() < deadline, "child did not reach cut {stage}");
            thread::sleep(Duration::from_millis(10));
        }
        child.kill().expect("SIGKILL process at persistence cut");
        let status = child.wait().expect("reap killed process");
        assert!(!status.success(), "killed child unexpectedly succeeded");

        let reopened = NduProjectionStoreV1::open(&root.0).expect("reopen after process kill");
        assert_eq!(
            reopened.entries().expect("authoritative reopened journal").len(),
            expected_records,
            "unexpected journal state after cut {stage}"
        );
    }
}

#[test]
fn disk_full_and_read_only_filesystem_fail_before_commit() {
    // Unix ENOSPC and EROFS are injected at the actual temp-create boundary;
    // the store must retain the old authoritative state and remain reopenable.
    for (label, errno) in [("disk-full", 28), ("read-only", 30)] {
        let root = TempRoot::new(label);
        drop(NduProjectionStoreV1::open(&root.0).expect("initialize errno root"));
        let persistence = Arc::new(ErrnoPersistence {
            errno,
            real: FsProjectionPersistenceV1,
        });
        let mut store =
            NduProjectionStoreV1::open_with_persistence(&root.0, persistence)
                .expect("open errno-injected store");
        let error = store
            .append_projection(
                NduProjectionKindV1::Preference,
                digest(&format!("{label}-identity")),
                digest("errno-objective"),
                digest("errno-subject"),
                digest(&format!("{label}-projection")),
            )
            .expect_err("capacity/filesystem error must reject");
        assert_eq!(
            error,
            NduProjectionStoreError::Io(io::Error::from_raw_os_error(errno).kind())
        );
        assert!(!store.is_indeterminate());
        assert!(store.entries().expect("old state remains authoritative").is_empty());
        drop(store);
        assert!(
            NduProjectionStoreV1::open(&root.0)
                .expect("reopen after errno")
                .entries()
                .expect("reopened state")
                .is_empty()
        );
    }
}
