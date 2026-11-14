use super::TargetCheckedTcpConnector;
use crate::config::NetworkProxyConfig;
use crate::dns::AbsoluteDnsResolver;
use crate::state::network_proxy_state_for_policy;
use pretty_assertions::assert_eq;
use rama_core::Service;
use rama_core::error::BoxError;
use rama_dns::client::HickoryDnsResolver;
use rama_dns::client::hickory::resolver::config::NameServerConfig;
use rama_dns::client::hickory::resolver::config::ResolverConfig;
use rama_dns::client::hickory::resolver::config::ResolverOpts;
use rama_dns::client::hickory::resolver::proto::op::Message;
use rama_dns::client::hickory::resolver::proto::op::ResponseCode;
use rama_dns::client::hickory::resolver::proto::rr::RData;
use rama_dns::client::hickory::resolver::proto::rr::Record;
use rama_dns::client::hickory::resolver::proto::rr::RecordType;
use rama_dns::client::hickory::resolver::proto::rr::rdata::A;
use rama_dns::client::hickory::resolver::proto::rr::rdata::AAAA;
use rama_dns::client::resolver::DnsAddressResolver;
use rama_net::address::HostWithPort;
use rama_net::client::Request;
use std::net::Ipv4Addr;
use std::net::Ipv6Addr;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::AsyncReadExt as _;
use tokio::io::AsyncWriteExt as _;
use tokio::net::TcpListener;
use tokio::net::UdpSocket;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;

enum FixtureResponse {
    LoopbackAddresses,
    NoSuchName,
}

struct DnsFixture {
    resolver: AbsoluteDnsResolver<HickoryDnsResolver>,
    queries: mpsc::UnboundedReceiver<String>,
    task: JoinHandle<()>,
}

impl DnsFixture {
    async fn new(answer: FixtureResponse) -> Result<Self, BoxError> {
        let socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let address = socket.local_addr()?;
        let (query_sender, queries) = mpsc::unbounded_channel();
        let task = tokio::spawn(async move {
            let mut buffer = [0; 4096];
            loop {
                let (length, peer) = socket.recv_from(&mut buffer).await.unwrap();
                let query = Message::from_vec(&buffer[..length]).unwrap();
                for question in &query.queries {
                    let _ = query_sender.send(question.name().to_utf8().to_ascii_lowercase());
                }
                let mut response = Message::response(query.metadata.id, query.metadata.op_code);
                response.metadata.authoritative = true;
                response.metadata.recursion_available = true;
                response.metadata.recursion_desired = query.metadata.recursion_desired;
                response.queries = query.queries.clone();
                response.edns = query.edns;
                match answer {
                    FixtureResponse::LoopbackAddresses => {
                        for question in query.queries {
                            let data = match question.query_type() {
                                RecordType::A => Some(RData::A(A(Ipv4Addr::LOCALHOST))),
                                RecordType::AAAA => Some(RData::AAAA(AAAA(Ipv6Addr::LOCALHOST))),
                                _ => None,
                            };
                            if let Some(data) = data {
                                response.add_answer(Record::from_rdata(
                                    question.name().clone(),
                                    /*ttl*/ 60,
                                    data,
                                ));
                            }
                        }
                    }
                    FixtureResponse::NoSuchName => {
                        response.metadata.response_code = ResponseCode::NXDomain
                    }
                }
                socket
                    .send_to(&response.to_vec().unwrap(), peer)
                    .await
                    .unwrap();
            }
        });
        let mut nameserver = NameServerConfig::udp(address.ip());
        nameserver.connections[0].port = address.port();
        let mut options = ResolverOpts::default();
        options.timeout = Duration::from_secs(1);
        options.attempts = 1;
        options.cache_size = 0;
        options.ndots = 5;
        let mut config = ResolverConfig::from_name_servers(vec![nameserver]);
        config.add_search("search-fixture.example.".parse()?);
        let resolver = HickoryDnsResolver::builder()
            .with_config(config)
            .with_options(options)
            .try_build()?;
        Ok(Self {
            resolver: AbsoluteDnsResolver(resolver),
            queries,
            task,
        })
    }
}

impl Drop for DnsFixture {
    fn drop(&mut self) {
        self.task.abort();
    }
}

#[tokio::test]
async fn hickory_resolver_preserves_normal_ipv4_and_ipv6_answers() -> Result<(), BoxError> {
    let mut fixture = DnsFixture::new(FixtureResponse::LoopbackAddresses).await?;
    let domain = "proxy-fixture.example".parse()?;
    let ipv4 = fixture
        .resolver
        .lookup_ipv4_first(domain)
        .await
        .transpose()?;
    let ipv6 = fixture
        .resolver
        .lookup_ipv6_first("proxy-fixture.example".parse()?)
        .await
        .transpose()?;

    assert_eq!(
        (ipv4, ipv6),
        (Some(Ipv4Addr::LOCALHOST), Some(Ipv6Addr::LOCALHOST))
    );
    let mut queries = Vec::new();
    while let Ok(query) = fixture.queries.try_recv() {
        queries.push(query);
    }
    assert_eq!(queries, vec!["proxy-fixture.example.".to_string(); 2]);
    Ok(())
}

#[tokio::test]
async fn resolved_domain_connects_when_local_binding_is_allowed() -> Result<(), BoxError> {
    let fixture = DnsFixture::new(FixtureResponse::LoopbackAddresses).await?;
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
    let target = HostWithPort::new(
        "proxy-fixture.example".parse()?,
        listener.local_addr()?.port(),
    );
    let connector = TargetCheckedTcpConnector {
        state: Arc::new(network_proxy_state_for_policy(NetworkProxyConfig {
            allow_local_binding: true,
            ..NetworkProxyConfig::default()
        })),
        resolver: fixture.resolver.clone(),
    };
    let mut connection = connector.serve(Request::new(target)).await?.conn;
    let (mut accepted, _) = listener.accept().await?;
    connection.write_all(b"dns-connected").await?;
    let mut received = [0; 13];
    accepted.read_exact(&mut received).await?;

    assert_eq!(&received, b"dns-connected");
    Ok(())
}

#[tokio::test]
async fn allowed_domain_does_not_allow_resolved_private_address() -> Result<(), BoxError> {
    let fixture = DnsFixture::new(FixtureResponse::LoopbackAddresses).await?;
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
    let target = HostWithPort::new(
        "proxy-fixture.example".parse()?,
        listener.local_addr()?.port(),
    );
    let mut config = NetworkProxyConfig::default();
    config.set_allowed_domains(vec!["proxy-fixture.example".to_string()]);
    let connector = TargetCheckedTcpConnector {
        state: Arc::new(network_proxy_state_for_policy(config)),
        resolver: fixture.resolver.clone(),
    };
    let error = connector
        .serve(Request::new(target))
        .await
        .expect_err("resolved private address must be checked");

    assert!(format!("{error:?}").contains("network target rejected by policy"));
    Ok(())
}

#[tokio::test]
async fn nonexistent_domain_returns_resolution_error() -> Result<(), BoxError> {
    let fixture = DnsFixture::new(FixtureResponse::NoSuchName).await?;
    let connector = TargetCheckedTcpConnector {
        state: Arc::new(network_proxy_state_for_policy(NetworkProxyConfig::default())),
        resolver: fixture.resolver.clone(),
    };
    let result = connector
        .serve(Request::new("missing-fixture.example:443".parse()?))
        .await;

    assert!(
        result.is_err(),
        "NXDOMAIN must not become an established connection"
    );
    Ok(())
}
