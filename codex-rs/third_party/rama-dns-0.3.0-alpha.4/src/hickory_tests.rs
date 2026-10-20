use super::*;
use hickory_resolver::config::NameServerConfig;
use hickory_resolver::config::ResolveHosts;
use hickory_resolver::config::ResolverOpts;
use hickory_resolver::proto::op::Message;
use hickory_resolver::proto::op::ResponseCode;
use hickory_resolver::proto::rr::Record;
use hickory_resolver::proto::rr::RecordType;
use hickory_resolver::proto::rr::rdata::CNAME;
use hickory_resolver::proto::rr::rdata::TXT;
use pretty_assertions::assert_eq;
use std::time::Duration;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::net::UdpSocket;
use tokio::time::timeout;

const DEADLINE: Duration = Duration::from_secs(5);

fn response(query: &[u8]) -> (Vec<u8>, RecordType) {
    let query = Message::from_vec(query).unwrap();
    assert_eq!(query.queries.len(), 1);
    let question = &query.queries[0];
    let name = question.name();
    assert!(name.is_fqdn());
    let kind = question.query_type();
    let mut reply = Message::response(query.metadata.id, query.metadata.op_code);
    reply.metadata.authoritative = true;
    reply.metadata.recursion_available = true;
    reply.metadata.recursion_desired = query.metadata.recursion_desired;
    reply.queries = query.queries.clone();
    if name.to_ascii().to_ascii_lowercase() == "missing.hepta.test." {
        reply.metadata.response_code = ResponseCode::NXDomain;
    } else {
        assert_eq!(name.to_ascii().to_ascii_lowercase(), "resolver.hepta.test.");
        let data = match kind {
            RecordType::A => RData::A(A("192.0.2.44".parse().unwrap())),
            RecordType::AAAA => RData::AAAA(AAAA("2001:db8::44".parse().unwrap())),
            RecordType::TXT => RData::TXT(TXT::from_bytes(vec![b"first", b"\0binary\xff"])),
            unexpected => panic!("unexpected resolver question: {unexpected:?}"),
        };
        let answer_name = if kind == RecordType::A {
            let alias = Name::from_utf8("alias.hepta.test.").unwrap();
            reply.add_answer(Record::from_rdata(
                name.clone(),
                /*ttl*/ 60,
                RData::CNAME(CNAME(alias.clone())),
            ));
            alias
        } else {
            name.clone()
        };
        reply.add_answer(Record::from_rdata(answer_name, /*ttl*/ 60, data));
    }
    (reply.to_vec().unwrap(), kind)
}

fn builder(server: NameServerConfig) -> HickoryDnsBuilder {
    let mut options = ResolverOpts::default();
    options.timeout = Duration::from_millis(500);
    options.attempts = 1;
    options.cache_size = 0;
    options.use_hosts_file = ResolveHosts::Never;
    HickoryDns::builder()
        .with_config(ResolverConfig::from_name_servers(vec![server]))
        .with_options(options)
}

async fn query_all(resolver: HickoryDns) {
    let domain = Domain::from_static("resolver.hepta.test");
    let boxed = resolver.clone().boxed();
    let v4 = timeout(DEADLINE, resolver.ipv4_lookup(domain.clone()))
        .await
        .unwrap()
        .unwrap();
    let v6 = timeout(DEADLINE, boxed.ipv6_lookup(domain.clone()))
        .await
        .unwrap()
        .unwrap();
    let txt = timeout(DEADLINE, resolver.txt_lookup(domain))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        (v4, v6, txt),
        (
            vec!["192.0.2.44".parse::<Ipv4Addr>().unwrap()],
            vec!["2001:db8::44".parse::<Ipv6Addr>().unwrap()],
            vec![b"first".to_vec(), b"\0binary\xff".to_vec()],
        )
    );
    let missing = timeout(
        DEADLINE,
        resolver.ipv4_lookup(Domain::from_static("missing.hepta.test")),
    )
    .await
    .unwrap();
    assert!(missing.is_err());
}

#[tokio::test]
async fn original_builder_and_boxed_api_resolve_real_udp_answers_and_errors() {
    let socket = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let address = socket.local_addr().unwrap();
    let mut server = NameServerConfig::udp(address.ip());
    server.connections[0].port = address.port();
    // Join the listener and caller inside the same timeout. A failed lookup
    // cannot leave a spawned listener behind, and no external DNS is used.
    let serve = async move {
        let mut seen = Vec::new();
        for _ in 0..4 {
            let mut packet = [0; 4096];
            let (size, peer) = socket.recv_from(&mut packet).await.unwrap();
            let (answer, kind) = response(&packet[..size]);
            socket.send_to(&answer, peer).await.unwrap();
            seen.push(kind);
        }
        seen
    };
    let (seen, ()) = timeout(DEADLINE, async {
        tokio::join!(serve, query_all(builder(server).build()))
    })
    .await
    .unwrap();
    assert_eq!(
        seen,
        vec![
            RecordType::A,
            RecordType::AAAA,
            RecordType::TXT,
            RecordType::A
        ]
    );
}

#[tokio::test]
async fn fallible_builder_uses_real_tcp_framing_and_preserves_txt_segments() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let mut server = NameServerConfig::tcp(address.ip());
    server.connections[0].port = address.port();
    let serve = async move {
        let (mut stream, peer) = listener.accept().await.unwrap();
        assert!(peer.ip().is_loopback());
        let mut seen = Vec::new();
        for _ in 0..4 {
            let length = stream.read_u16().await.unwrap() as usize;
            assert!((12..=4096).contains(&length));
            let mut packet = vec![0; length];
            stream.read_exact(&mut packet).await.unwrap();
            let (answer, kind) = response(&packet);
            stream
                .write_u16(answer.len().try_into().unwrap())
                .await
                .unwrap();
            stream.write_all(&answer).await.unwrap();
            seen.push(kind);
        }
        seen
    };
    let (seen, ()) = timeout(DEADLINE, async {
        tokio::join!(serve, query_all(builder(server).try_build().unwrap()))
    })
    .await
    .unwrap();
    assert_eq!(
        seen,
        vec![
            RecordType::A,
            RecordType::AAAA,
            RecordType::TXT,
            RecordType::A
        ]
    );
}

#[tokio::test]
async fn retained_initialization_failure_reaches_every_cloned_and_boxed_lookup() {
    let resolver = HickoryDns(Arc::new(Err(OpaqueError::from_display(
        "initialization failed",
    ))));
    let domain = Domain::from_static("resolver.hepta.test");
    let boxed = resolver.clone().boxed();
    let outcomes = timeout(DEADLINE, async {
        (
            resolver
                .ipv4_lookup(domain.clone())
                .await
                .unwrap_err()
                .to_string(),
            boxed
                .ipv6_lookup(domain.clone())
                .await
                .unwrap_err()
                .to_string(),
            resolver.txt_lookup(domain).await.unwrap_err().to_string(),
        )
    })
    .await
    .unwrap();
    let message = "DNS resolver initialization failed: initialization failed".to_owned();
    assert_eq!(outcomes, (message.clone(), message.clone(), message));
}
