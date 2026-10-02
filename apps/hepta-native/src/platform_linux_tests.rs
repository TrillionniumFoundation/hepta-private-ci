use super::*;
use std::io::BufRead as _;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use zbus::zvariant::OwnedValue;

struct Bus(Child);
impl Drop for Bus {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[derive(Debug, PartialEq, Eq)]
struct ObservedNotification {
    application: String,
    replaces: u32,
    icon: String,
    title: String,
    body: String,
    actions: Vec<String>,
    desktop_entry: String,
    expiry: i32,
}

struct Notifications(Arc<Mutex<Option<ObservedNotification>>>);
#[zbus::interface(name = "org.freedesktop.Notifications")]
impl Notifications {
    fn get_capabilities(&self) -> Vec<String> {
        vec!["body".into(), "body-markup".into()]
    }

    #[allow(clippy::too_many_arguments)]
    fn notify(
        &self,
        application: String,
        replaces: u32,
        icon: String,
        title: String,
        body: String,
        actions: Vec<String>,
        mut hints: HashMap<String, OwnedValue>,
        expiry: i32,
    ) -> u32 {
        *self.0.lock().unwrap() = Some(ObservedNotification {
            application,
            replaces,
            icon,
            title,
            body,
            actions,
            desktop_entry: String::try_from(hints.remove("desktop-entry").unwrap()).unwrap(),
            expiry,
        });
        17
    }
}

#[test]
fn native_notification_dispatch_preserves_literal_text_and_identity() {
    let root = tempfile::tempdir().unwrap();
    let config = root.path().join("bus.conf");
    // Test-only loopback transport for runners that prohibit AF_UNIX. It carries
    // no product data; product session authentication remains unchanged.
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
    let mut daemon = Bus(Command::new("/usr/bin/dbus-daemon")
        .arg("--config-file")
        .arg(&config)
        .args(["--nofork", "--print-address=1", "--nopidfile"])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap());
    let mut address = String::new();
    std::io::BufReader::new(daemon.0.stdout.take().unwrap())
        .read_line(&mut address)
        .unwrap();
    let received = Arc::new(Mutex::new(None));
    future::block_on(async {
        let _server = zbus::connection::Builder::address(address.trim())
            .unwrap()
            .auth_mechanism(zbus::AuthMechanism::Anonymous)
            .name(DESTINATION)
            .unwrap()
            .serve_at(OBJECT_PATH, Notifications(Arc::clone(&received)))
            .unwrap()
            .build()
            .await
            .unwrap();
        send_on(
            zbus::connection::Builder::address(address.trim())
                .unwrap()
                .auth_mechanism(zbus::AuthMechanism::Anonymous)
                .build(),
            "标题 <title>",
            "literal <b> & café\nline two",
        )
        .await
        .unwrap();
    });
    assert_eq!(
        *received.lock().unwrap(),
        Some(ObservedNotification {
            application: "Hepta Native".into(),
            replaces: 0,
            icon: String::new(),
            title: "标题 <title>".into(),
            body: "literal &lt;b&gt; &amp; café\nline two".into(),
            actions: Vec::new(),
            desktop_entry: "hepta-native".into(),
            expiry: -1,
        })
    );
}
