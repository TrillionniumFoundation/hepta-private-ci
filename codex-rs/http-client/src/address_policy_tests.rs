use std::collections::VecDeque;
use std::net::SocketAddr;
use std::sync::Mutex;
use std::time::Duration;

use pretty_assertions::assert_eq;

use super::*;

struct Lookup(Mutex<VecDeque<Vec<SocketAddr>>>);

impl Resolve for Lookup {
    fn resolve(&self, _name: Name) -> Resolving {
        let addresses = self
            .0
            .lock()
            .expect("lookup lock")
            .pop_front()
            .expect("one lookup per connector attempt");
        Box::pin(async move { Ok(Box::new(addresses.into_iter()) as Addrs) })
    }
}

#[test]
fn configured_local_authority_does_not_authorize_other_ports_hosts_or_schemes() {
    let policy = HttpAddressPolicy::from_configured_resource("http://127.0.0.1:8181/mcp")
        .expect("configured local server");
    assert!(
        policy
            .resolver_for(&Url::parse("http://127.0.0.1:8181/metadata").unwrap())
            .is_ok()
    );
    for destination in [
        "http://127.0.0.1:8182/token",
        "https://127.0.0.1:8181/token",
        "http://127.0.0.2:8181/token",
        "http://localhost:8181/token",
        "http://10.0.0.1:8181/token",
    ] {
        assert!(matches!(
            policy.resolver_for(&Url::parse(destination).unwrap()),
            Err(HttpAddressPolicyError::DestinationDenied)
        ));
    }
    assert!(
        policy
            .resolver_for(&Url::parse("https://login.example.com/token").unwrap())
            .is_ok()
    );
}

#[test]
fn discovered_private_and_translated_literals_cannot_expand_public_capability() {
    let policy = HttpAddressPolicy::from_configured_resource("https://mcp.example.com").unwrap();
    for destination in [
        "http://2130706433/",
        "http://[::ffff:127.0.0.1]/",
        "http://[64:ff9b::7f00:1]/",
        "http://[2002:7f00:1::]/",
        "http://[2001:db8::1]/",
        "http://169.254.169.254/",
        "http://168.63.129.16/",
        "http://localhost./",
        "http://other.localhost/",
        "http://[fd00:ec2::254]/",
        "http://[fd20:ce::254]/",
    ] {
        assert!(
            matches!(
                policy.resolver_for(&Url::parse(destination).unwrap()),
                Err(HttpAddressPolicyError::DestinationDenied)
            ),
            "{destination}"
        );
    }
    for forbidden in [
        "http://169.254.169.254/",
        "http://[fd00:ec2::254]/",
        "http://[fd20:ce::254]/",
        "http://168.63.129.16/",
    ] {
        assert!(matches!(
            HttpAddressPolicy::from_configured_resource(forbidden),
            Err(HttpAddressPolicyError::InvalidConfiguredResource)
        ));
    }
}

#[tokio::test]
async fn actual_resolver_filters_mixed_results_and_rebinding_without_reusing_old_admission() {
    let policy = HttpAddressPolicy::from_configured_resource("https://mcp.example.com").unwrap();
    let mut resolver = policy
        .resolver_for(&Url::parse("https://login.example.com").unwrap())
        .unwrap();
    resolver.lookup = Arc::new(Lookup(Mutex::new(VecDeque::from([
        vec![
            "127.0.0.1:9".parse().unwrap(),
            "8.8.8.8:99".parse().unwrap(),
            "[::ffff:127.0.0.1]:10".parse().unwrap(),
        ],
        vec!["10.0.0.7:443".parse().unwrap()],
    ]))));
    assert_eq!(
        resolver
            .resolve("login.example.com".parse().unwrap())
            .await
            .unwrap()
            .collect::<Vec<_>>(),
        vec!["8.8.8.8:0".parse::<SocketAddr>().unwrap()]
    );
    assert!(
        resolver
            .resolve("login.example.com".parse().unwrap())
            .await
            .is_err()
    );
    assert!(
        resolver
            .resolve("different.example.com".parse().unwrap())
            .await
            .is_err()
    );
}

#[tokio::test]
async fn configured_hostname_does_not_gain_private_dns_and_localhost_accepts_only_loopback() {
    let named = HttpAddressPolicy::from_configured_resource("http://service.example:8181").unwrap();
    let mut resolver = named
        .resolver_for(&Url::parse("http://service.example:8181").unwrap())
        .unwrap();
    resolver.lookup = Arc::new(Lookup(Mutex::new(VecDeque::from([vec![
        "10.0.0.1:0".parse().unwrap(),
    ]]))));
    assert!(
        resolver
            .resolve("service.example".parse().unwrap())
            .await
            .is_err()
    );
    let local = HttpAddressPolicy::from_configured_resource("http://localhost:8181").unwrap();
    let mut resolver = local
        .resolver_for(&Url::parse("http://localhost:8181/metadata").unwrap())
        .unwrap();
    resolver.lookup = Arc::new(Lookup(Mutex::new(VecDeque::from([vec![
        "8.8.8.8:0".parse().unwrap(),
        "127.0.0.1:0".parse().unwrap(),
        "[::1]:0".parse().unwrap(),
    ]]))));
    assert_eq!(
        resolver
            .resolve("localhost".parse().unwrap())
            .await
            .unwrap()
            .collect::<Vec<_>>(),
        vec![
            "127.0.0.1:0".parse::<SocketAddr>().unwrap(),
            "[::1]:0".parse::<SocketAddr>().unwrap()
        ]
    );
}

#[tokio::test]
async fn reqwest_connector_never_receives_rejected_loopback_dns_answer() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("private target listener");
    listener.set_nonblocking(true).unwrap();
    let policy = HttpAddressPolicy::from_configured_resource("https://mcp.example.com").unwrap();
    let target = Url::parse(&format!(
        "http://untrusted.example:{}/",
        listener.local_addr().unwrap().port()
    ))
    .unwrap();
    let mut resolver = policy.resolver_for(&target).unwrap();
    resolver.lookup = Arc::new(Lookup(Mutex::new(VecDeque::from([vec![
        listener.local_addr().unwrap(),
    ]]))));
    // Hermetic connector control: product construction continues to require the factory.
    let client = reqwest::Client::builder()
        .no_proxy()
        .dns_resolver(Arc::new(resolver))
        .timeout(Duration::from_secs(1))
        .build()
        .unwrap();
    assert!(client.get(target).send().await.is_err());
    assert!(
        matches!(listener.accept(), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock)
    );
}
