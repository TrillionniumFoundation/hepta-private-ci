use std::fs::File;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::PrivateStateDirectory;

static FIXTURE_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sequence = FIXTURE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-private-acl-{}-{nonce}-{sequence}",
            std::process::id()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.0).unwrap();
    }
}

fn grant_everyone_read(path: &Path) {
    let executable =
        PathBuf::from(std::env::var_os("SystemRoot").unwrap()).join("System32/icacls.exe");
    let output = Command::new(executable)
        .arg(path)
        .args(["/grant", "*S-1-1-0:(R)", "/Q"])
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");
}

#[test]
fn borrowed_file_validation_detects_child_acl_drift_under_a_private_root() {
    let fixture = Fixture::new();
    let path = fixture.0.join("state");
    let directory = PrivateStateDirectory::open(&path).unwrap();
    let file = directory
        .open_file("authority.json", /*create*/ true)
        .unwrap();
    directory.verify_file(&file).unwrap();
    directory.verify_mutable_file(&file).unwrap();

    grant_everyone_read(&path.join("authority.json"));

    directory.verify_trust().unwrap();
    assert_eq!(
        directory.verify_file(&file).unwrap_err().kind(),
        std::io::ErrorKind::PermissionDenied
    );
    assert!(
        directory
            .open_file("authority.json", /*create*/ false)
            .is_err()
    );
}

#[test]
fn immutable_hardlinks_remain_readable_but_mutable_handles_are_rejected() {
    let fixture = Fixture::new();
    let path = fixture.0.join("state");
    let directory = PrivateStateDirectory::open(&path).unwrap();
    let mut file = directory
        .open_file("authority.json", /*create*/ true)
        .unwrap();
    let committed = b"committed authority evidence";
    file.write_all(committed).unwrap();
    file.sync_all().unwrap();
    drop(file);
    let alias = fixture.0.join("alias.json");
    std::fs::hard_link(path.join("authority.json"), &alias).unwrap();
    let file = File::open(path.join("authority.json")).unwrap();

    directory.verify_file(&file).unwrap();
    assert_eq!(
        directory.verify_mutable_file(&file).unwrap_err().kind(),
        std::io::ErrorKind::PermissionDenied
    );
    for create in [false, true] {
        assert_eq!(
            directory
                .open_file("authority.json", create)
                .unwrap_err()
                .kind(),
            std::io::ErrorKind::PermissionDenied
        );
        assert_eq!(
            std::fs::read(path.join("authority.json")).unwrap(),
            committed
        );
        assert_eq!(std::fs::read(&alias).unwrap(), committed);
    }
}
