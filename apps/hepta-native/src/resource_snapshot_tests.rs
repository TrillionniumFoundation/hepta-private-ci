use super::snapshot;

#[test]
fn unchanged_opened_resource_has_a_stable_confirmation() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("resource.txt");
    std::fs::write(&path, b"unchanged").unwrap();
    assert_eq!(
        snapshot(&path).unwrap().digest,
        snapshot(&path).unwrap().digest
    );
}

#[cfg(unix)]
#[test]
fn substitution_between_open_and_identity_check_is_rejected() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("resource.txt");
    std::fs::write(&path, b"same bytes").unwrap();
    assert!(
        super::snapshot_observed(&path, || {
            std::fs::rename(&path, temp.path().join("original.txt")).unwrap();
            std::fs::write(&path, b"same bytes").unwrap();
        })
        .is_err()
    );
}

#[cfg(unix)]
#[test]
fn parent_redirect_during_snapshot_is_rejected_even_for_same_object() {
    use std::os::unix::fs::symlink;
    let temp = tempfile::tempdir().unwrap();
    let first = temp.path().join("first");
    let second = temp.path().join("second");
    std::fs::create_dir(&first).unwrap();
    std::fs::create_dir(&second).unwrap();
    std::fs::write(first.join("file"), b"same inode").unwrap();
    std::fs::hard_link(first.join("file"), second.join("file")).unwrap();
    let link = temp.path().join("current");
    symlink(&first, &link).unwrap();
    assert!(
        super::snapshot_observed(&link.join("file"), || {
            std::fs::remove_file(&link).unwrap();
            symlink(&second, &link).unwrap();
        })
        .is_err()
    );
}
