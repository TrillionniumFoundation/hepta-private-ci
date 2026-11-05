use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::FileTypeExt;
use std::process::Command;
use tempfile::TempDir;

const ROLE_GID: u32 = 60001;

fn root_directory() -> TempDir {
    // SAFETY: geteuid only observes this fixture process's actual identity.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_SOCKET_TEST_ROOT")
        .expect("explicit Root-owned, non-shared traversable test parent");
    let directory = tempfile::Builder::new()
        .prefix("hepta-g2-socket-")
        .tempdir_in(parent)
        .expect("fresh Root-controlled test directory");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o755)).unwrap();
    directory
}

fn pending(directory: &Path) -> (UnixListener, SocketName) {
    let path = directory.join(".control.sock.pending");
    let listener = UnixListener::bind(&path).unwrap();
    owner_socket(&path, ROLE_GID).unwrap();
    let directory = File::open(directory).unwrap();
    let name = CString::new(".control.sock.pending").unwrap();
    let metadata = metadata_at(&directory, &name).unwrap();
    let name = SocketName {
        directory,
        name,
        device: metadata.st_dev,
        inode: metadata.st_ino,
    };
    (listener, name)
}

#[test]
#[ignore = "requires Root to exercise the actual native socket owner"]
fn configured_inode_is_published_and_accepts_the_dedicated_role() {
    let directory = root_directory();
    let path = directory.path().join("control.sock");
    let listener = listener(&path, ROLE_GID).unwrap();
    let metadata = std::fs::symlink_metadata(&path).unwrap();
    assert_eq!(
        (
            metadata.dev(),
            metadata.ino(),
            metadata.uid(),
            metadata.gid(),
            metadata.mode() & 0o7777,
            metadata.file_type().is_socket()
        ),
        (
            listener._name.device,
            listener._name.inode,
            0,
            ROLE_GID,
            0o660,
            true
        )
    );
    assert_eq!(
        std::fs::symlink_metadata(directory.path().join(".control.sock.pending"))
            .unwrap_err()
            .kind(),
        io::ErrorKind::NotFound
    );
    let status = Command::new("/usr/bin/setpriv")
        .args([
            "--reuid=60001",
            "--regid=60001",
            "--clear-groups",
            "--no-new-privs",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--bounding-set=-all",
            "/usr/bin/python3",
            "-I",
            "-c",
            "import os,socket,sys; assert os.getresuid()==(60001,60001,60001) and os.getresgid()==(60001,60001,60001) and os.getgroups()==[]; s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.settimeout(2); s.connect(sys.argv[1])",
        ])
        .arg(&path)
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .current_dir("/")
        .status()
        .unwrap();
    assert!(status.success());
    let (_stream, _) = listener.accept().unwrap();
    drop(listener);
    assert_eq!(
        std::fs::symlink_metadata(path).unwrap_err().kind(),
        io::ErrorKind::NotFound
    );
}

#[test]
#[ignore = "requires Root to exercise the actual native socket owner"]
fn pending_collision_is_preserved_without_publishing() {
    let directory = root_directory();
    let path = directory.path().join("control.sock");
    let pending = directory.path().join(".control.sock.pending");
    std::fs::write(&pending, b"foreign pending").unwrap();
    let before = std::fs::symlink_metadata(&pending).unwrap();
    let error = listener(&path, ROLE_GID).err().unwrap();
    assert_eq!(error.raw_os_error(), Some(libc::EADDRINUSE));
    let after = std::fs::symlink_metadata(&pending).unwrap();
    assert_eq!((after.dev(), after.ino()), (before.dev(), before.ino()));
    assert_eq!(std::fs::read(pending).unwrap(), b"foreign pending");
    assert_eq!(
        std::fs::symlink_metadata(path).unwrap_err().kind(),
        io::ErrorKind::NotFound
    );
}

#[test]
#[ignore = "requires Root to exercise the actual native socket owner"]
fn existing_final_is_not_replaced_and_own_pending_is_removed() {
    let directory = root_directory();
    let path = directory.path().join("control.sock");
    std::fs::write(&path, b"foreign final").unwrap();
    let before = std::fs::symlink_metadata(&path).unwrap();
    let error = listener(&path, ROLE_GID).err().unwrap();
    assert_eq!(error.raw_os_error(), Some(libc::EEXIST));
    let after = std::fs::symlink_metadata(&path).unwrap();
    assert_eq!((after.dev(), after.ino()), (before.dev(), before.ino()));
    assert_eq!(std::fs::read(path).unwrap(), b"foreign final");
    assert_eq!(
        std::fs::symlink_metadata(directory.path().join(".control.sock.pending"))
            .unwrap_err()
            .kind(),
        io::ErrorKind::NotFound
    );
}

#[test]
#[ignore = "requires Root to exercise the actual native socket owner"]
fn final_replacement_inode_survives_listener_drop() {
    let directory = root_directory();
    let path = directory.path().join("control.sock");
    let listener = listener(&path, ROLE_GID).unwrap();
    std::fs::remove_file(&path).unwrap();
    std::fs::write(&path, b"replacement final").unwrap();
    let replacement = std::fs::symlink_metadata(&path).unwrap();
    assert_ne!(replacement.ino(), listener._name.inode);
    drop(listener);
    let retained = std::fs::symlink_metadata(&path).unwrap();
    assert_eq!(
        (retained.dev(), retained.ino()),
        (replacement.dev(), replacement.ino())
    );
    assert_eq!(std::fs::read(path).unwrap(), b"replacement final");
}

#[test]
#[ignore = "requires Root to exercise the actual native socket owner"]
fn pending_replacement_inode_survives_failed_publication_cleanup() {
    let directory = root_directory();
    let (_listener, name) = pending(directory.path());
    let path = directory.path().join(".control.sock.pending");
    std::fs::remove_file(&path).unwrap();
    std::fs::write(&path, b"replacement pending").unwrap();
    assert_ne!(std::fs::symlink_metadata(&path).unwrap().ino(), name.inode);
    assert!(
        name.publish(CString::new("control.sock").unwrap(), ROLE_GID)
            .is_err()
    );
    assert_eq!(std::fs::read(path).unwrap(), b"replacement pending");
    assert_eq!(
        std::fs::symlink_metadata(directory.path().join("control.sock"))
            .unwrap_err()
            .kind(),
        io::ErrorKind::NotFound
    );
}

#[test]
#[ignore = "requires Root to exercise the actual native socket owner"]
fn preexisting_same_inode_alias_is_rejected_without_removing_final() {
    let directory = root_directory();
    let (_listener, name) = pending(directory.path());
    let source = directory.path().join(".control.sock.pending");
    let final_path = directory.path().join("control.sock");
    std::fs::hard_link(&source, &final_path).unwrap();
    let identity = (name.device, name.inode);
    assert!(
        name.publish(CString::new("control.sock").unwrap(), ROLE_GID)
            .is_err()
    );
    let final_metadata = std::fs::symlink_metadata(final_path).unwrap();
    assert_eq!((final_metadata.dev(), final_metadata.ino()), identity);
    assert_eq!(
        std::fs::symlink_metadata(source).unwrap_err().kind(),
        io::ErrorKind::NotFound
    );
}
