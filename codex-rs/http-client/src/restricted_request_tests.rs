use std::time::Duration;

use pretty_assertions::assert_eq;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;

use super::ClientRouteClass;
use super::HttpClientFactory;
use super::OutboundProxyPolicy;
use super::SystemProxyDecision;
use super::cache_system_proxy_decision;
use crate::HttpAddressPolicy;
use crate::HttpAddressPolicyError;
use crate::RouteAwareClientPool;
use crate::RouteAwareRequestError;

#[tokio::test]
async fn configured_local_redirect_keeps_exact_authority_and_rejects_a_new_private_port() {
    let original = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let denied = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    denied.set_nonblocking(true).unwrap();
    let original_url = format!("http://{}/start", original.local_addr().unwrap());
    let same_origin_url = format!("http://{}/same", original.local_addr().unwrap());
    let denied_url = format!("http://{}/private", denied.local_addr().unwrap());
    cache_system_proxy_decision(&original_url, SystemProxyDecision::Direct);
    cache_system_proxy_decision(&same_origin_url, SystemProxyDecision::Direct);
    let denied_for_server = denied_url.clone();
    let server = async move {
        let mut lines = Vec::new();
        for location in ["/same".to_string(), denied_for_server] {
            let (mut stream, _) = original.accept().await.unwrap();
            let mut headers = Vec::new();
            while !headers.ends_with(b"\r\n\r\n") {
                assert!(headers.len() < 8192);
                headers.push(stream.read_u8().await.unwrap());
            }
            let headers = String::from_utf8(headers).unwrap();
            let authorization = headers
                .lines()
                .filter_map(|line| line.split_once(':'))
                .find(|(name, _)| name.eq_ignore_ascii_case("authorization"))
                .map(|(_, value)| value.trim());
            assert_eq!(authorization, Some("Bearer configured-secret"));
            let gateway = headers
                .lines()
                .filter_map(|line| line.split_once(':'))
                .find(|(name, _)| name.eq_ignore_ascii_case("proxy-authorization"))
                .map(|(_, value)| value.trim());
            assert_eq!(gateway, Some("Basic configured-gateway"));
            lines.push(headers.lines().next().unwrap().to_string());
            stream.write_all(format!("HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes()).await.unwrap();
        }
        lines
    };
    let client = async {
        let pool = RouteAwareClientPool::new_without_request_logging(
            HttpClientFactory::new(OutboundProxyPolicy::RespectSystemProxy),
            ClientRouteClass::Other,
        );
        let policy = HttpAddressPolicy::from_configured_resource(&original_url).unwrap();
        pool.get(&original_url)
            .header("Authorization", "Bearer configured-secret")
            .header("Proxy-Authorization", "Basic configured-gateway")
            .timeout(Duration::from_secs(2))
            .send_restricted(&policy)
            .await
    };
    let (lines, response) = tokio::time::timeout(Duration::from_secs(3), async {
        tokio::join!(server, client)
    })
    .await
    .unwrap();
    assert_eq!(lines, ["GET /start HTTP/1.1", "GET /same HTTP/1.1"]);
    assert!(matches!(
        response,
        Err(RouteAwareRequestError::AddressPolicy(
            HttpAddressPolicyError::DestinationDenied
        ))
    ));
    assert!(
        matches!(denied.accept(), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock)
    );
}

#[tokio::test]
async fn configured_proxy_refusal_never_falls_back_to_direct_http() {
    let direct = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    direct.set_nonblocking(true).unwrap();
    let proxy = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    proxy.set_nonblocking(true).unwrap();
    let url = format!("http://{}/metadata", direct.local_addr().unwrap());
    cache_system_proxy_decision(
        &url,
        SystemProxyDecision::Proxy {
            url: format!("http://{}", proxy.local_addr().unwrap()),
        },
    );
    let pool = RouteAwareClientPool::new(
        HttpClientFactory::new(OutboundProxyPolicy::RespectSystemProxy),
        ClientRouteClass::Other,
    );
    let policy = HttpAddressPolicy::from_configured_resource(&url).unwrap();
    let result = pool
        .get(&url)
        .timeout(Duration::from_secs(1))
        .send_restricted(&policy)
        .await;
    assert!(matches!(
        result,
        Err(RouteAwareRequestError::AddressPolicy(
            HttpAddressPolicyError::ProxyUnsupported
        ))
    ));
    for listener in [direct, proxy] {
        assert!(
            matches!(listener.accept(), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock)
        );
    }
}
