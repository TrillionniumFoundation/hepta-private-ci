use super::bounded_read::read_control_bytes;
use super::*;
use pretty_assertions::assert_eq;
use std::io;
use std::io::Read;

struct SnapshotDirectory(PathBuf);

impl SnapshotDirectory {
    fn new() -> Self {
        let tick = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = super::control_test_directory_at("hepta-control-snapshot-bound", tick);
        Self(path)
    }
}

impl Drop for SnapshotDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn extend_snapshot(path: &Path) -> u64 {
    let file = fs::OpenOptions::new()
        .write(true)
        .open(path)
        .expect("open snapshot for growth");
    let oversized_length = DURABLE_CONTROL_MAX_FILE_BYTES_V1 as u64 + 1;
    file.set_len(oversized_length).expect("extend");
    file.sync_all().expect("sync");
    oversized_length
}

fn unchanged_snapshot_prefix(path: &Path, expected: &[u8], expected_len: u64) {
    let mut file = File::open(path).expect("read snapshot");
    assert_eq!(file.metadata().expect("metadata").len(), expected_len);
    let mut prefix = vec![0; expected.len()];
    file.read_exact(&mut prefix).expect("read prefix");
    assert_eq!(prefix, expected);
}

#[test]
fn oversized_snapshot_open_preserves_the_file_and_releases_the_writer_lock() {
    let directory = SnapshotDirectory::new();
    let path = directory.0.join("control");
    let owner = DurableControlRoleOwnerV1::open(&path).expect("create");
    drop(owner);
    let original = fs::read(&path).expect("original snapshot");
    let oversized_len = extend_snapshot(&path);

    assert_eq!(
        DurableControlRoleOwnerV1::open(&path),
        Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
    );

    let _lock = lock_durable_control_writer(&path).expect("failed open released lock");
    unchanged_snapshot_prefix(&path, &original, oversized_len);
}

#[test]
fn oversized_snapshot_during_mutation_preserves_memory_and_disk() {
    let directory = SnapshotDirectory::new();
    let path = directory.0.join("control");
    let mut owner = DurableControlRoleOwnerV1::open(&path).expect("create");
    let before = owner.inner().clone();
    let original = fs::read(&path).expect("original snapshot");
    let oversized_len = extend_snapshot(&path);

    assert_eq!(
        owner.set_now_ms(1),
        Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
    );
    assert_eq!(owner.inner(), &before);

    let _lock = lock_durable_control_writer(&path).expect("failed mutation released lock");
    unchanged_snapshot_prefix(&path, &original, oversized_len);
}

#[test]
fn snapshot_limit_is_inclusive_but_a_growing_reader_is_bounded() {
    let mut exact = io::repeat(/*byte*/ 0x5a).take(DURABLE_CONTROL_MAX_FILE_BYTES_V1 as u64);
    let bytes = read_control_bytes::<DURABLE_CONTROL_MAX_FILE_BYTES_V1>(
        &mut exact,
        DURABLE_CONTROL_MAX_FILE_BYTES_V1 as u64,
    )
    .expect("exact snapshot byte limit");
    assert_eq!(bytes, vec![0x5a; DURABLE_CONTROL_MAX_FILE_BYTES_V1]);
    drop(bytes);

    let overflow = 4096;
    let mut growing =
        io::repeat(/*byte*/ 0xa5).take(DURABLE_CONTROL_MAX_FILE_BYTES_V1 as u64 + overflow);
    assert_eq!(
        read_control_bytes::<DURABLE_CONTROL_MAX_FILE_BYTES_V1>(
            &mut growing,
            /*observed_len*/ 0,
        ),
        Err(ControlOwnerErrorV1::InvalidDurableSnapshot)
    );
    assert_eq!(growing.limit(), overflow - 1);
}
