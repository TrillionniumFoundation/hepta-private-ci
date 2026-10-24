use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

use codex_app_server_protocol::JSONRPCMessage;
use codex_app_server_protocol::JSONRPCNotification;
use codex_uds::UnixStream;
use codex_utils_absolute_path::AbsolutePathBuf;
use futures::SinkExt;
use pretty_assertions::assert_eq;
use tokio::sync::mpsc;
use tokio::time::Duration;
use tokio::time::timeout;
use tokio_tungstenite::client_async;
use tokio_tungstenite::tungstenite::Message;
use tokio_util::sync::CancellationToken;

use super::InheritedControlSocket;
use super::TransportEvent;
use super::start_inherited_control_socket_acceptor;

#[tokio::test]
async fn inherited_acceptor_preserves_original_rpc_and_external_path_ownership() {
    let directory = tempfile::tempdir().expect("fixture directory");
    let path = directory.path().join("original.sock");
    let listener = std::os::unix::net::UnixListener::bind(&path).expect("fixture listener");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).expect("private socket");
    let before = std::fs::metadata(&path).expect("original node");
    let parent = std::fs::metadata(directory.path()).expect("original parent");
    let inherited = InheritedControlSocket::from_inherited(
        OwnedFd::from(listener), AbsolutePathBuf::from_absolute_path(&path).expect("absolute path"),
    ).expect("adopt original listener");
    let (sender, mut receiver) = mpsc::channel(8);
    let shutdown = CancellationToken::new();
    let acceptor = start_inherited_control_socket_acceptor(inherited, sender, shutdown.clone());
    let stream = UnixStream::connect(&path).await.expect("original path connect");
    let (mut websocket, response) = client_async("ws://localhost/rpc", stream).await.expect("original handshake");
    assert_eq!(response.status().as_u16(), 101);
    let connection_id = match timeout(Duration::from_secs(2), receiver.recv()).await.expect("open timeout").expect("open event") {
        TransportEvent::ConnectionOpened { connection_id, .. } => connection_id,
        event => panic!("expected open event, received {event:?}"),
    };
    let message = JSONRPCMessage::Notification(JSONRPCNotification { method: "initialized".into(), params: None });
    websocket.send(Message::Text(serde_json::to_string(&message).expect("serialize").into())).await.expect("send original wire");
    let incoming = timeout(Duration::from_secs(2), receiver.recv()).await.expect("message timeout").expect("message event");
    assert_eq!(match incoming {
        TransportEvent::IncomingMessage { connection_id, message } => (connection_id, message),
        event => panic!("expected original message, received {event:?}"),
    }, (connection_id, message));
    websocket.close(None).await.expect("close client");
    shutdown.cancel();
    timeout(Duration::from_secs(2), acceptor).await.expect("acceptor shutdown").expect("acceptor task");
    let after = std::fs::metadata(&path).expect("external owner retains node");
    assert_eq!((after.dev(), after.ino(), after.mode()), (before.dev(), before.ino(), before.mode()));
    let parent_after = std::fs::metadata(directory.path()).expect("parent retained");
    assert_eq!((parent_after.uid(), parent_after.gid(), parent_after.mode()), (parent.uid(), parent.gid(), parent.mode()));
}
