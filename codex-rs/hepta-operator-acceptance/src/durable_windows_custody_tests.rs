use super::FileSnapshot;
use super::open_without_following;
use super::verify_unchanged;
use crate::durable::secure_canonical_file_path;
use crate::durable::secure_read;
use crate::test_support::private_tempdir;
use crate::test_support::windows_custody::change_private_dacl;
use crate::test_support::windows_custody::grant;
use crate::test_support::windows_custody::null_dacl;
use crate::test_support::windows_custody::world_sid;
use crate::test_support::windows_custody::write_private_fixture;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::Storage::FileSystem::WRITE_OWNER;

#[test]
fn public_read_execute_write_delete_and_security_control_fail_on_the_read_handle() {
    for mask in [
        FILE_GENERIC_READ,
        FILE_GENERIC_EXECUTE,
        FILE_GENERIC_WRITE,
        DELETE,
        WRITE_DAC,
        WRITE_OWNER,
    ] {
        let temporary = private_tempdir("custody masks");
        let path = temporary.path().join("artifact");
        write_private_fixture(&path, b"sealed");
        let file = open_without_following(&path).unwrap();
        FileSnapshot::capture(&file, "private positive control").unwrap();
        assert_eq!(secure_read(&path, 64).unwrap(), b"sealed");
        grant(&path, world_sid(), mask, /*flags*/ 0);
        let unsafe_security = crate::test_support::windows_custody::security_bytes(&path);
        assert!(FileSnapshot::capture(&file, "unsafe read handle").is_err());
        assert!(secure_read(&path, 64).is_err());
        assert_eq!(
            std::fs::read(&path).unwrap(),
            b"sealed",
            "admission must not rewrite inputs"
        );
        assert_eq!(
            crate::test_support::windows_custody::security_bytes(&path),
            unsafe_security,
            "admission must not rewrite owner or DACL"
        );
    }
}

#[test]
fn a_null_dacl_is_not_private_even_when_the_os_open_succeeds() {
    let temporary = private_tempdir("null DACL");
    let path = temporary.path().join("artifact");
    write_private_fixture(&path, b"sealed");
    assert_eq!(secure_read(&path, 64).unwrap(), b"sealed");
    null_dacl(&path);
    let file = open_without_following(&path).expect("OS permits read, checker must reject");
    assert!(FileSnapshot::capture(&file, "null DACL").is_err());
}

#[test]
fn changed_but_still_private_dacl_rejects_the_retained_snapshot() {
    let temporary = private_tempdir("private ACL drift");
    let path = temporary.path().join("artifact");
    write_private_fixture(&path, b"sealed");
    let file = open_without_following(&path).unwrap();
    let before = FileSnapshot::capture(&file, "before").unwrap();
    change_private_dacl(&path);
    let after = FileSnapshot::capture(&file, "still private").expect("changed ACL remains private");
    assert_ne!(before, after);
    assert!(verify_unchanged(&file, &path, &before, "changed private ACL").is_err());
}

#[test]
fn inherited_untrusted_access_rejects_but_private_input_in_public_parent_admits() {
    let temporary = private_tempdir("input parent parity");
    let root = temporary.path().canonicalize().unwrap();
    let private = root.join("private-input");
    // Creation primitive applies a protected private DACL; no permission repair.
    let directory = codex_utils_path::open_existing_private_state_directory(&root).unwrap();
    let protected =
        codex_utils_path::create_private_recovery_copy(&directory, private.file_name().unwrap())
            .unwrap();
    drop(protected);
    drop(directory);
    grant(
        &root,
        world_sid(),
        FILE_GENERIC_READ | FILE_GENERIC_WRITE,
        OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
    );
    // No invented private-input-parent requirement: this protected child admits.
    assert_eq!(
        secure_canonical_file_path(&private, "private input").unwrap(),
        private
    );
    assert!(secure_read(&private, 64).unwrap().is_empty());
    let inherited = root.join("inherited-input");
    crate::test_support::windows_custody::write_inheriting_fixture(&inherited);
    let file = open_without_following(&inherited).expect("OS opens inherited fixture");
    assert!(FileSnapshot::capture(&file, "inherited public access").is_err());
    assert!(secure_read(&inherited, 64).is_err());
}

#[test]
fn admission_does_not_create_missing_files_or_parent_directories() {
    let temporary = private_tempdir("missing inputs");
    let missing = temporary.path().join("missing");
    assert!(secure_read(&missing.join("artifact"), 64).is_err());
    assert!(!missing.exists());
    assert_eq!(std::fs::read_dir(temporary.path()).unwrap().count(), 0);
}

#[cfg(feature = "windows-custody-privileged-tests")]
#[test]
fn wrong_owner_rejects_even_with_a_current_user_only_dacl() {
    let temporary = private_tempdir("wrong owner");
    let path = temporary.path().join("artifact");
    write_private_fixture(&path, b"sealed");
    assert_eq!(secure_read(&path, 64).unwrap(), b"sealed");
    crate::test_support::windows_custody::change_owner_to_enabled_group(&path);
    assert_eq!(
        std::fs::read(&path).unwrap(),
        b"sealed",
        "owner mutation preserves readable fixture bytes"
    );
    let file = open_without_following(&path).expect("current user still has data-read access");
    assert!(FileSnapshot::capture(&file, "wrong owner").is_err());
    assert!(secure_read(&path, 64).is_err());
}

#[cfg(feature = "windows-custody-privileged-tests")]
#[test]
fn owner_change_after_open_rejects_the_same_retained_descriptor() {
    let temporary = private_tempdir("owner drift");
    let path = temporary.path().join("artifact");
    write_private_fixture(&path, b"sealed");
    let file = open_without_following(&path).unwrap();
    let before = FileSnapshot::capture(&file, "before owner change").unwrap();
    crate::test_support::windows_custody::change_owner_to_enabled_group(&path);
    assert_eq!(
        std::fs::read(&path).unwrap(),
        b"sealed",
        "owner mutation preserves readable fixture bytes"
    );
    assert!(verify_unchanged(&file, &path, &before, "owner change").is_err());
}

thread_local! {
    static BEFORE_READ: std::cell::RefCell<Option<Box<dyn FnOnce(&std::path::Path)>>> =
        const { std::cell::RefCell::new(None) };
}

pub(in crate::durable) fn before_read(path: &std::path::Path) {
    BEFORE_READ.with(|hook| {
        let action = hook.borrow_mut().take();
        if let Some(action) = action {
            action(path);
        }
    });
}

#[test]
fn bounded_read_revalidates_security_after_the_same_open_handle_was_bound() {
    let temporary = private_tempdir("read-boundary ACL drift");
    let path = temporary.path().join("artifact");
    write_private_fixture(&path, b"sealed");
    assert_eq!(secure_read(&path, 64).unwrap(), b"sealed");
    BEFORE_READ.with(|hook| *hook.borrow_mut() = Some(Box::new(change_private_dacl)));
    assert!(
        secure_read(&path, 64).is_err(),
        "still-private ACL drift after bind must reject"
    );
    assert!(
        BEFORE_READ.with(|hook| hook.borrow().is_none()),
        "attack hook must have run"
    );
    assert_eq!(
        secure_read(&path, 64).unwrap(),
        b"sealed",
        "new private snapshot admits unchanged bytes"
    );
}

#[cfg(feature = "windows-custody-privileged-tests")]
#[test]
fn final_symlink_rejects_even_when_its_target_is_private_and_valid() {
    let temporary = private_tempdir("final reparse fixture");
    let target = temporary.path().join("target");
    let link = temporary.path().join("link");
    write_private_fixture(&target, b"sealed");
    assert_eq!(secure_read(&target, 64).unwrap(), b"sealed");
    std::os::windows::fs::symlink_file(&target, &link)
        .expect("authorized native symlink fixture must be created, not treated as rejection");
    assert!(secure_read(&link, 64).is_err());
    assert_eq!(secure_read(&target, 64).unwrap(), b"sealed");
}
