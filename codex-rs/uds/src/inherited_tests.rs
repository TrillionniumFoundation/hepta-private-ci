use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

use crate::UnixListener;
use crate::UnixStream;

#[tokio::test]
async fn adopted_listener_uses_original_socket_and_leaves_owner_paths_intact() {
    let directory = tempfile::tempdir().expect("fixture directory");
    let path = directory.path().join("original.sock");
    let socket = std::os::unix::net::UnixListener::bind(&path).expect("fixture listener");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).expect("private socket");
    let before = std::fs::metadata(&path).expect("socket metadata");
    let parent_mode = std::fs::metadata(directory.path()).expect("directory metadata").mode();
    let mut listener = UnixListener::from_inherited(OwnedFd::from(socket), &path).expect("adopt");
    let mut client = UnixStream::connect(&path).await.expect("connect");
    let mut accepted = listener.accept().await.expect("accept");
    accepted.ensure_current_user_peer().expect("actual owner peer");
    client.write_all(b"original").await.expect("write");
    let mut bytes = [0; 8];
    accepted.read_exact(&mut bytes).await.expect("read");
    assert_eq!(&bytes, b"original");
    drop(listener);
    let after = std::fs::metadata(&path).expect("owner still has socket path");
    assert_eq!((before.dev(), before.ino(), before.mode()), (after.dev(), after.ino(), after.mode()));
    assert_eq!(std::fs::metadata(directory.path()).expect("directory intact").mode(), parent_mode);
}

#[tokio::test]
async fn adoption_rejects_other_path_and_nonprivate_node_without_changing_either() {
    let directory = tempfile::tempdir().expect("fixture directory");
    let path = directory.path().join("original.sock");
    let other = directory.path().join("other.sock");
    let socket = std::os::unix::net::UnixListener::bind(&path).expect("fixture listener");
    let other_socket = std::os::unix::net::UnixListener::bind(&other).expect("other listener");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).expect("private socket");
    std::fs::set_permissions(&other, std::fs::Permissions::from_mode(0o600)).expect("private other");
    assert!(UnixListener::from_inherited(OwnedFd::from(socket), &other).is_err());
    std::fs::set_permissions(&other, std::fs::Permissions::from_mode(0o660)).expect("shared fixture");
    assert!(UnixListener::from_inherited(OwnedFd::from(other_socket), &other).is_err());
    assert!(path.exists());
    assert_eq!(std::fs::metadata(&other).expect("node retained").mode() & 0o7777, 0o660);
}

#[tokio::test]
async fn adoption_rejects_connected_socket_before_using_a_path() {
    let (socket, _peer) = std::os::unix::net::UnixStream::pair().expect("socket pair");
    assert!(UnixListener::from_inherited(OwnedFd::from(socket), std::path::Path::new("/unused")).is_err());
}
