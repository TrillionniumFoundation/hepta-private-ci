use super::*;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);
fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value { Ok(value) => value, Err(error) => panic!("fixture: {error:?}") }
}
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!("neuron-file-v2-{}-{serial}", std::process::id()));
        checked(std::fs::create_dir(&path));
        Self(path)
    }
    fn file(&self) -> PathBuf { self.0.join("store") }
}
impl Drop for Fixture {
    fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); }
}

#[cfg(unix)]
#[test]
fn final_symlink_and_hard_link_are_not_accepted_as_owned_stores() {
    let fixture = Fixture::new();
    let target = fixture.0.join("target");
    checked(std::fs::write(&target, b"unchanged"));
    checked(std::os::unix::fs::symlink(&target, fixture.file()));
    assert!(open_regular(&fixture.file()).is_err());
    checked(std::fs::remove_file(fixture.file()));
    checked(std::fs::hard_link(&target, fixture.file()));
    assert!(open_regular(&fixture.file()).is_err());
    assert_eq!(checked(std::fs::read(target)), b"unchanged");
}

#[cfg(unix)]
#[test]
fn raced_in_symlink_is_not_followed_after_the_metadata_check() {
    let fixture = Fixture::new();
    checked(std::fs::write(fixture.file(), b"source"));
    let target = fixture.0.join("target");
    checked(std::fs::write(&target, b"target"));
    let result = open_regular_after_metadata(&fixture.file(), || {
        checked(std::fs::remove_file(fixture.file()));
        checked(std::os::unix::fs::symlink(&target, fixture.file()));
    });
    assert!(result.is_err());
    assert_eq!(checked(std::fs::read(target)), b"target");
}

#[cfg(unix)]
#[test]
fn raced_in_fifo_is_rejected_without_a_blocking_open() {
    let fixture = Fixture::new();
    checked(std::fs::write(fixture.file(), b"source"));
    let result = open_regular_after_metadata(&fixture.file(), || {
        checked(std::fs::remove_file(fixture.file()));
        assert!(checked(std::process::Command::new("mkfifo").arg(fixture.file()).status()).success());
    });
    assert!(result.is_err());
}

#[test]
fn sync_statistics_count_actual_successful_file_syncs() {
    let fixture = Fixture::new();
    checked(std::fs::write(fixture.file(), b"source"));
    let file = checked(MeasuredFileV2::new(checked(open_regular(&fixture.file())), &fixture.file()));
    checked(file.sync_data());
    checked(file.sync_all());
    assert_eq!(file.metrics().sync_calls, 2);
    assert_eq!(file.metrics().sync_errors, 0);
}
