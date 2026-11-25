use super::*;

#[test]
fn canonical_proxy_matching_never_turns_a_parse_failure_into_direct_egress() {
    let destination = Url::parse("https://login.example.com/token").unwrap();
    for proxy in [
        "http://proxy.example:8080",
        "http://bücher.example:8080",
        "proxy.example:8080",
        "socks5://proxy.example:1080",
    ] {
        let route = OutboundProxyRoute::Proxy {
            url: proxy.to_string(),
            no_proxy: None,
        };
        assert!(require_direct_route(&route, &destination, ClientRouteClass::Other).is_err());
    }
    let bypass = OutboundProxyRoute::Proxy {
        url: "http://bücher.example:8080".to_string(),
        no_proxy: Some("login.example.com".to_string()),
    };
    assert!(require_direct_route(&bypass, &destination, ClientRouteClass::Other).is_ok());
    let different_destination = Url::parse("https://other.example.com/token").unwrap();
    assert!(
        require_direct_route(&bypass, &different_destination, ClientRouteClass::Other).is_err()
    );
}

#[test]
fn unsupported_proxy_normalization_and_invalid_destinations_stay_refusals() {
    let destination = Url::parse("https://login.example.com/").unwrap();
    for proxy in [
        "proxy.example:8080",
        "socks5://proxy.example:1080",
        "http://[invalid",
    ] {
        let route = OutboundProxyRoute::Proxy {
            url: proxy.to_string(),
            no_proxy: Some("*".to_string()),
        };
        assert!(require_direct_route(&route, &destination, ClientRouteClass::Other).is_err());
    }
    assert!(
        require_direct_route(
            &OutboundProxyRoute::Direct,
            &Url::parse("file:///etc/passwd").unwrap(),
            ClientRouteClass::Other
        )
        .is_err()
    );
}
