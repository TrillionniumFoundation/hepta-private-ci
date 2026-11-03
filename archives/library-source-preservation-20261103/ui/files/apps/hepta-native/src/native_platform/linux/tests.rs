use super::*;
use std::io::BufRead as _;
use std::os::unix::fs::MetadataExt as _;
use std::process::Child;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[test]
fn selected_uri_is_exact_local_utf8_and_never_a_remote_or_ambiguous_path() {
    assert_eq!(
        decode_uri("file:///tmp/%20input%20").unwrap(),
        PathBuf::from("/tmp/ input ")
    );
    assert_eq!(
        decode_uri("file://localhost/tmp/a").unwrap(),
        PathBuf::from("/tmp/a")
    );
    for uri in [
        "https://example.test/a",
        "file:relative",
        "file:///tmp/%ZZ",
        "file:///tmp/%",
        "file://remote.test/a",
        "file:///a?secret=x",
        "file:///a#x",
        "file:///a%00",
        "file:///a%0A",
        "file:///a%FF",
    ] {
        assert!(decode_uri(uri).is_err(), "{uri}");
    }
    assert!(decode_uri(&format!("file:///{}", "a".repeat(16 * 1024))).is_err());
    assert_eq!(
        decode_uri("file:///tmp/a/../selected").unwrap().as_os_str(),
        "/tmp/a/../selected"
    );
}

#[test]
fn session_bus_cannot_redirect_native_ui_data_to_tcp() {
    assert!(validate_session_address(None).is_ok());
    assert!(validate_session_address(Some("unix:path=/run/user/1000/bus")).is_ok());
    for address in [
        "",
        "tcp:host=remote.test,port=1234",
        "unix:path=/tmp/bus;tcp:host=remote.test",
    ] {
        assert!(validate_session_address(Some(address)).is_err());
    }
}

struct PrivateBus {
    child: Child,
    address: String,
    _root: tempfile::TempDir,
}
impl PrivateBus {
    fn start() -> Self {
        let root = tempfile::tempdir().unwrap();
        let mut child = std::process::Command::new("/usr/bin/dbus-daemon")
            .args([
                "--session",
                "--nofork",
                "--print-address=1",
                &format!("--address=unix:path={}/bus", root.path().display()),
            ])
            .env("XDG_RUNTIME_DIR", root.path())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap();
        let mut address = String::new();
        std::io::BufReader::new(child.stdout.take().unwrap())
            .read_line(&mut address)
            .unwrap();
        if !address.starts_with("unix:") {
            let _ = child.kill();
            let _ = child.wait();
            panic!("private D-Bus fixture could not create its Unix socket");
        }
        Self {
            child,
            address: address.trim().to_owned(),
            _root: root,
        }
    }
}
impl Drop for PrivateBus {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[derive(Clone, Copy)]
enum Reply {
    EarlySuccess,
    Cancel,
    Multiple,
    Timeout,
    ForeignHandle,
}
struct Portal {
    reply: Reply,
    closed: Arc<AtomicUsize>,
}
struct Request {
    closed: Arc<AtomicUsize>,
}
#[zbus::interface(name = "org.freedesktop.portal.Request")]
impl Request {
    fn close(&self) {
        self.closed.fetch_add(1, Ordering::SeqCst);
    }
}

#[zbus::interface(name = "org.freedesktop.portal.FileChooser")]
impl Portal {
    async fn open_file(
        &self,
        _parent: &str,
        _title: &str,
        options: HashMap<String, OwnedValue>,
        #[zbus(connection)] connection: &Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<OwnedObjectPath> {
        let sender = header.sender().unwrap().as_str();
        let token = <&str>::try_from(options.get("handle_token").unwrap()).unwrap();
        let path = format!(
            "/org/freedesktop/portal/desktop/request/{}/{}",
            sender.trim_start_matches(':').replace('.', "_"),
            token
        );
        connection
            .object_server()
            .at(
                path.as_str(),
                Request {
                    closed: Arc::clone(&self.closed),
                },
            )
            .await?;
        if matches!(self.reply, Reply::ForeignHandle) {
            return Ok(OwnedObjectPath::try_from("/foreign/request").unwrap());
        }
        if !matches!(self.reply, Reply::Timeout) {
            let code = if matches!(self.reply, Reply::Cancel) {
                1_u32
            } else {
                0
            };
            let uris = if matches!(self.reply, Reply::Multiple) {
                vec!["file:///tmp/one", "file:///tmp/two"]
            } else {
                vec!["file:///tmp/%20chosen%20"]
            };
            let results = HashMap::from([("uris", Value::new(uris))]);
            // Deliberately emit before the method returns its handle.
            connection
                .emit_signal(
                    Some(sender),
                    path.as_str(),
                    REQUEST_INTERFACE,
                    "Response",
                    &(code, results),
                )
                .await?;
        }
        Ok(OwnedObjectPath::try_from(path).unwrap())
    }
}

#[test]
fn actual_private_bus_handles_early_cancel_invalid_and_timed_out_picker_responses() {
    let bus = PrivateBus::start();
    futures_lite::future::block_on(async {
        for reply in [
            Reply::EarlySuccess,
            Reply::Cancel,
            Reply::Multiple,
            Reply::Timeout,
            Reply::ForeignHandle,
        ] {
            let closed = Arc::new(AtomicUsize::new(0));
            let server = zbus::connection::Builder::address(bus.address.as_str())
                .unwrap()
                .serve_at(
                    DESKTOP_PATH,
                    Portal {
                        reply,
                        closed: Arc::clone(&closed),
                    },
                )
                .unwrap()
                .build()
                .await
                .unwrap();
            let client = zbus::connection::Builder::address(bus.address.as_str())
                .unwrap()
                .build()
                .await
                .unwrap();
            let owner = server.unique_name().unwrap().as_str();
            let duration = if matches!(reply, Reply::Timeout) {
                Duration::from_millis(60)
            } else {
                Duration::from_secs(3)
            };
            let result = request(
                &client,
                owner,
                Action::Picker,
                /*resource*/ None,
                Instant::now() + duration,
            )
            .await;
            match reply {
                Reply::EarlySuccess => {
                    assert_eq!(result.unwrap(), Some(PathBuf::from("/tmp/ chosen ")))
                }
                Reply::Cancel => assert_eq!(result.unwrap(), None),
                Reply::Multiple | Reply::Timeout | Reply::ForeignHandle => {
                    assert!(result.is_err());
                    assert_eq!(closed.load(Ordering::SeqCst), 1);
                }
            }
        }
    });
}

struct ResourcePortal {
    expected_device: u64,
    expected_inode: u64,
    received: Arc<AtomicUsize>,
}
#[zbus::interface(name = "org.freedesktop.portal.OpenURI")]
impl ResourcePortal {
    async fn open_file(
        &self,
        _parent: &str,
        fd: Fd<'_>,
        options: HashMap<String, OwnedValue>,
        #[zbus(connection)] connection: &Connection,
        #[zbus(header)] header: zbus::message::Header<'_>,
    ) -> zbus::fdo::Result<OwnedObjectPath> {
        let file = std::fs::File::from(fd.as_fd().try_clone_to_owned().unwrap());
        let metadata = file.metadata().unwrap();
        assert_eq!(
            (metadata.dev(), metadata.ino()),
            (self.expected_device, self.expected_inode)
        );
        assert!(!bool::try_from(options.get("writable").unwrap()).unwrap());
        self.received.fetch_add(1, Ordering::SeqCst);
        let sender = header.sender().unwrap().as_str();
        let token = <&str>::try_from(options.get("handle_token").unwrap()).unwrap();
        let path = format!(
            "/org/freedesktop/portal/desktop/request/{}/{}",
            sender.trim_start_matches(':').replace('.', "_"),
            token
        );
        connection
            .emit_signal(
                Some(sender),
                path.as_str(),
                REQUEST_INTERFACE,
                "Response",
                &(0_u32, HashMap::<String, Value<'_>>::new()),
            )
            .await?;
        Ok(OwnedObjectPath::try_from(path).unwrap())
    }
}

#[test]
fn resource_handoff_transfers_retained_inode_not_a_replaced_path() {
    let bus = PrivateBus::start();
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("selected");
    std::fs::write(&path, "original").unwrap();
    let retained = std::fs::File::open(&path).unwrap();
    let metadata = retained.metadata().unwrap();
    std::fs::rename(&path, root.path().join("retained")).unwrap();
    std::fs::write(&path, "replacement").unwrap();
    let received = Arc::new(AtomicUsize::new(0));
    futures_lite::future::block_on(async {
        let server = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .serve_at(
                DESKTOP_PATH,
                ResourcePortal {
                    expected_device: metadata.dev(),
                    expected_inode: metadata.ino(),
                    received: Arc::clone(&received),
                },
            )
            .unwrap()
            .build()
            .await
            .unwrap();
        let client = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .build()
            .await
            .unwrap();
        assert_eq!(
            request(
                &client,
                server.unique_name().unwrap().as_str(),
                Action::Open,
                Some(&retained),
                Instant::now() + Duration::from_secs(3)
            )
            .await
            .unwrap(),
            None
        );
    });
    assert_eq!(received.load(Ordering::SeqCst), 1);
}
