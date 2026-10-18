use super::*;
use crate::model::sha256_hex;

fn backup(target: &Path, bytes: &[u8]) -> std::path::PathBuf {
    let path = target.with_extension(format!("{}.predecessor", sha256_hex(bytes)));
    std::fs::write(&path, bytes).unwrap();
    path
}

#[test]
fn retention_ceiling_rejects_new_backup_but_reuses_an_admitted_identity() {
    let root = tempfile::tempdir().unwrap();
    let target = root.path().join("installed");
    std::fs::write(&target, b"new predecessor").unwrap();
    for bytes in [b"one".as_slice(), b"two", b"three", b"four"] {
        backup(&target, bytes);
    }
    let digest = sha256_hex(b"new predecessor");
    let next = target.with_extension(format!("{digest}.predecessor"));
    assert!(admit_predecessor_backup(&target, &next, &digest).is_err());
    assert!(!next.exists());
    assert_eq!(std::fs::read(&target).unwrap(), b"new predecessor");

    let existing = target.with_extension(format!("{}.predecessor", sha256_hex(b"one")));
    admit_predecessor_backup(&target, &existing, &sha256_hex(b"one")).unwrap();
    assert_eq!(std::fs::read(existing).unwrap(), b"one");
}

#[test]
fn unrelated_operator_files_do_not_consume_retention_admission() {
    let root = tempfile::tempdir().unwrap();
    let target = root.path().join("installed.exe");
    let unrelated = [
        root.path().join("operator-data"),
        root.path().join("installed.notes.predecessor"),
        root.path()
            .join(format!("other.{}.predecessor", sha256_hex(b"other"))),
    ];
    for path in &unrelated {
        std::fs::write(path, b"preserve").unwrap();
    }
    let digest = sha256_hex(b"predecessor");
    let next = target.with_extension(format!("{digest}.predecessor"));
    admit_predecessor_backup(&target, &next, &digest).unwrap();
    for path in unrelated {
        assert_eq!(std::fs::read(path).unwrap(), b"preserve");
    }
}

#[test]
fn matching_nonregular_and_oversized_backups_deny_admission() {
    let root = tempfile::tempdir().unwrap();
    let target = root.path().join("installed");
    let digest = sha256_hex(b"predecessor");
    let next = target.with_extension(format!("{digest}.predecessor"));
    let invalid = target.with_extension(format!("{}.predecessor", sha256_hex(b"invalid")));
    std::fs::create_dir(&invalid).unwrap();
    assert!(admit_predecessor_backup(&target, &next, &digest).is_err());
    std::fs::remove_dir(&invalid).unwrap();
    let file = std::fs::File::create(&invalid).unwrap();
    file.set_len(MAX_PACKAGE_BYTES + 1).unwrap();
    assert!(admit_predecessor_backup(&target, &next, &digest).is_err());
    drop(file);
    std::fs::remove_file(&invalid).unwrap();
    #[cfg(unix)]
    {
        let outside = root.path().join("operator-data");
        std::fs::write(&outside, b"preserve").unwrap();
        std::os::unix::fs::symlink(&outside, &invalid).unwrap();
        assert!(admit_predecessor_backup(&target, &next, &digest).is_err());
        assert_eq!(std::fs::read(outside).unwrap(), b"preserve");
    }
}
