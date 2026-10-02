use super::*;
use std::collections::HashMap;
use std::io::Read as _;
use std::os::unix::net::UnixStream;
use zbus::zvariant::OwnedFd;
use zbus::zvariant::OwnedValue;

struct OpenUri;
#[zbus::interface(name = "org.freedesktop.portal.OpenURI")]
impl OpenUri {
    fn open_file(
        &self,
        parent: &str,
        descriptor: OwnedFd,
        options: HashMap<String, OwnedValue>,
    ) -> Vec<u8> {
        assert!(parent.is_empty());
        assert_eq!(options.len(), 3);
        assert_eq!(
            <&str>::try_from(&options["handle_token"]).unwrap(),
            "verified_resource"
        );
        assert!(!bool::try_from(&options["writable"]).unwrap());
        assert!(!bool::try_from(&options["ask"]).unwrap());
        let received = File::from(std::os::fd::OwnedFd::from(descriptor));
        let mut bytes = Vec::new();
        received.take(4096).read_to_end(&mut bytes).unwrap();
        bytes
    }
}

#[test]
fn rust_open_uri_transfers_original_verified_descriptor_after_name_replacement() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("resource.txt");
    std::fs::write(&path, b"verified original inode").unwrap();
    let adapter = SystemPlatformAdapter::new(
        PlatformPolicy::new(vec![directory.path().to_owned()], false, false).unwrap(),
    );
    let (file, _identity) = adapter.open_verified_resource(&path).unwrap();
    let replacement = directory.path().join("replacement.txt");
    std::fs::write(&replacement, b"untrusted replacement inode").unwrap();
    std::fs::rename(&replacement, &path).unwrap();
    let (server_socket, client_socket) = UnixStream::pair().unwrap();
    futures_lite::future::block_on(async {
        // Authenticated local socketpair supports real SCM_RIGHTS. This tests
        // the exact production body serializer without a desktop portal or any
        // mutation of process-wide session-bus configuration.
        let server = zbus::connection::Builder::async_io_unix_stream(server_socket)
            .server(zbus::Guid::generate())
            .unwrap()
            .p2p()
            .serve_at("/org/freedesktop/portal/desktop", OpenUri)
            .unwrap()
            .build();
        let client = zbus::connection::Builder::async_io_unix_stream(client_socket)
            .p2p()
            .build();
        let (server, client) = futures_lite::future::zip(server, client).await;
        let _server = server.unwrap();
        let client = client.unwrap();
        let reply = client
            .call_method(
                None::<&str>,
                "/org/freedesktop/portal/desktop",
                Some("org.freedesktop.portal.OpenURI"),
                "OpenFile",
                &portal_resource_body(&file, "verified_resource"),
            )
            .await
            .unwrap();
        assert_eq!(
            reply.body().deserialize::<Vec<u8>>().unwrap(),
            b"verified original inode"
        );
    });
    assert_eq!(
        std::fs::read(&path).unwrap(),
        b"untrusted replacement inode"
    );
}
