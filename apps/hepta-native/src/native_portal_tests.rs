use super::*;
use std::io::BufRead as _;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use zbus::message::Header;
use zbus::zvariant::Value;

const CHOOSER_INTERFACE: &str = "org.freedesktop.portal.FileChooser";

struct Bus {
    child: Child,
    address: String,
    _root: tempfile::TempDir,
}

impl Bus {
    fn new() -> Self {
        // The isolated test bus owns no product identity or sensitive data.
        // Loopback TCP also works on runners that prohibit Unix-domain sockets.
        // Anonymous SASL is confined to this mock; product session auth is unchanged.
        let root = tempfile::tempdir().unwrap();
        let config = root.path().join("bus.conf");
        std::fs::write(
            &config,
            r#"<busconfig>
<type>session</type><listen>tcp:host=127.0.0.1,port=0,family=ipv4</listen>
<auth>ANONYMOUS</auth><allow_anonymous/>
<policy context="default"><allow send_destination="*"/>
<allow receive_sender="*"/><allow own="*"/></policy>
</busconfig>"#,
        )
        .unwrap();
        let mut child = Command::new("/usr/bin/dbus-daemon")
            .arg("--config-file")
            .arg(&config)
            .args(["--nofork", "--print-address=1"])
            .stdout(Stdio::piped())
            .spawn()
            .expect("Linux portal tests require dbus-daemon");
        let mut address = String::new();
        std::io::BufReader::new(child.stdout.take().unwrap())
            .read_line(&mut address)
            .unwrap();
        Self {
            child,
            address: address.trim().to_owned(),
            _root: root,
        }
    }

    async fn connect(&self) -> zbus::Result<Connection> {
        zbus::connection::Builder::address(self.address.as_str())?
            .auth_mechanism(zbus::AuthMechanism::Anonymous)
            .build()
            .await
    }
}

impl Drop for Bus {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[derive(Clone, Copy)]
enum Reply {
    Success,
    Cancel,
    Rejected,
    Silent,
    Malformed,
    WrongHandle,
    WrongSender,
    Oversized,
}

struct Chooser {
    reply: Reply,
    closed: Arc<AtomicUsize>,
    rogue: Connection,
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
impl Chooser {
    async fn open_file(
        &self,
        _parent: &str,
        _title: &str,
        options: HashMap<String, OwnedValue>,
        #[zbus(connection)] connection: &Connection,
        #[zbus(header)] header: Header<'_>,
    ) -> zbus::fdo::Result<OwnedObjectPath> {
        let sender = header.sender().unwrap();
        let token: &str = options.get("handle_token").unwrap().try_into().unwrap();
        let path = format!(
            "{DESKTOP_PATH}/request/{}/{token}",
            sender.as_str().trim_start_matches(':').replace('.', "_")
        );
        let owned_path = if matches!(self.reply, Reply::WrongHandle) {
            format!("{path}_different")
        } else {
            path.clone()
        };
        connection
            .object_server()
            .at(
                owned_path.as_str(),
                Request {
                    closed: Arc::clone(&self.closed),
                },
            )
            .await
            .unwrap();
        let success = HashMap::from([("uris", Value::from(vec!["file:///tmp/selected"]))]);
        match self.reply {
            Reply::Silent => {}
            Reply::Malformed => {
                connection
                    .emit_signal(
                        Some(sender.as_str()),
                        path.as_str(),
                        REQUEST_INTERFACE,
                        "Response",
                        &"invalid",
                    )
                    .await
                    .unwrap();
            }
            Reply::WrongHandle => {
                return Ok(OwnedObjectPath::try_from(format!("{path}_different")).unwrap());
            }
            Reply::WrongSender => {
                // The attack precedes the genuine reply with the same member,
                // path and successful wire shape, but a different bus owner.
                let malicious = HashMap::from([("uris", Value::from(vec!["file:///tmp/wrong"]))]);
                self.rogue
                    .emit_signal(
                        Some(sender.as_str()),
                        path.as_str(),
                        REQUEST_INTERFACE,
                        "Response",
                        &(0_u32, malicious),
                    )
                    .await
                    .unwrap();
                connection
                    .emit_signal(
                        Some(sender.as_str()),
                        path.as_str(),
                        REQUEST_INTERFACE,
                        "Response",
                        &(0_u32, success),
                    )
                    .await
                    .unwrap();
            }
            Reply::Oversized => {
                let oversized = "x".repeat(MAX_RESPONSE_BYTES + 1);
                let results = HashMap::from([("uris", Value::from(vec![oversized]))]);
                connection
                    .emit_signal(
                        Some(sender.as_str()),
                        path.as_str(),
                        REQUEST_INTERFACE,
                        "Response",
                        &(0_u32, results),
                    )
                    .await
                    .unwrap();
            }
            Reply::Success | Reply::Cancel | Reply::Rejected => {
                let code = match self.reply {
                    Reply::Cancel => 1_u32,
                    Reply::Rejected => 2,
                    _ => 0,
                };
                // Intentionally signal before returning the method reply.
                connection
                    .emit_signal(
                        Some(sender.as_str()),
                        path.as_str(),
                        REQUEST_INTERFACE,
                        "Response",
                        &(code, success),
                    )
                    .await
                    .unwrap();
            }
        }
        Ok(OwnedObjectPath::try_from(path).unwrap())
    }
}

fn observed(reply: Reply) -> (Result<PortalResponse, ShellError>, usize) {
    let bus = Bus::new();
    futures_lite::future::block_on(async {
        let closed = Arc::new(AtomicUsize::new(0));
        let service = zbus::connection::Builder::address(bus.address.as_str())
            .unwrap()
            .auth_mechanism(zbus::AuthMechanism::Anonymous)
            .name(DESTINATION)
            .unwrap()
            .serve_at(
                DESKTOP_PATH,
                Chooser {
                    reply,
                    closed: Arc::clone(&closed),
                    rogue: bus.connect().await.unwrap(),
                },
            )
            .unwrap()
            .build()
            .await
            .unwrap();
        let token = request_token().unwrap();
        let options = HashMap::from([("handle_token", Value::from(token.as_str()))]);
        let maximum = if matches!(reply, Reply::Silent) {
            Duration::from_millis(500)
        } else {
            Duration::from_secs(3)
        };
        let response = request_on(
            bus.connect(),
            CHOOSER_INTERFACE,
            "OpenFile",
            &("", "test", options),
            &token,
            maximum,
        )
        .await;
        let count = closed.load(Ordering::SeqCst);
        service.close().await.unwrap();
        (response, count)
    })
}

#[test]
fn response_before_method_reply_is_observed_and_wrong_owner_is_ignored() {
    for reply in [Reply::Success, Reply::WrongSender] {
        let (response, closed) = observed(reply);
        let PortalResponse::Completed(mut results) = response.unwrap() else {
            panic!("not completed")
        };
        let uris: Vec<String> = results.remove("uris").unwrap().try_into().unwrap();
        assert_eq!(uris, ["file:///tmp/selected"]);
        assert_eq!(closed, 0);
    }
}

#[test]
fn portal_cancel_is_distinct_from_rejection_and_malformed_results() {
    let (response, closed) = observed(Reply::Cancel);
    assert!(matches!(response, Ok(PortalResponse::Cancelled)));
    assert_eq!(closed, 0);
    for reply in [
        Reply::Rejected,
        Reply::Malformed,
        Reply::WrongHandle,
        Reply::Oversized,
    ] {
        let (response, closed) = observed(reply);
        assert!(response.is_err());
        assert_eq!(closed, 1);
    }
}

#[test]
fn stalled_request_times_out_and_closes_the_owned_request() {
    let (response, closed) = observed(Reply::Silent);
    assert!(response.unwrap_err().to_string().contains("deadline"));
    assert_eq!(closed, 1);
}

#[test]
fn connecting_consumes_the_same_observation_budget() {
    let result = futures_lite::future::block_on(request_on(
        std::future::pending(),
        CHOOSER_INTERFACE,
        "OpenFile",
        &(),
        "test",
        Duration::from_millis(10),
    ));
    assert!(result.unwrap_err().to_string().contains("deadline"));
}

#[test]
fn method_reply_identity_and_size_are_checked_before_deserialization() {
    let call = zbus::Message::method_call(DESKTOP_PATH, "OpenFile")
        .unwrap()
        .build(&())
        .unwrap();
    let reply = |sender: &str, bytes: usize| {
        zbus::Message::method_return(&call.header())
            .unwrap()
            .sender(sender)
            .unwrap()
            .build(&"x".repeat(bytes))
            .unwrap()
    };
    assert!(verified_reply(Ok(reply(":1.2", 1)), ":1.2").is_ok());
    assert!(verified_reply(Ok(reply(":1.3", 1)), ":1.2").is_err());
    assert!(verified_reply(Ok(reply(":1.2", MAX_RESPONSE_BYTES + 1)), ":1.2").is_err());
}
