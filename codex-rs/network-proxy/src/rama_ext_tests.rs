use super::RequestTarget;
use super::TunnelTarget;
use super::request_path;
use pretty_assertions::assert_eq;
use rama_core::extensions::ExtensionsRef;
use rama_http::Body;
use rama_http::Request;
use rama_net::Protocol;
use rama_net::uri::Uri;

#[test]
fn authorization_path_preserves_literal_and_encoded_bytes() {
    for (uri, expected) in [
        ("/repos/[draft]/issues?state=op*", "/repos/[draft]/issues"),
        (
            "https://example.com/repos/[draft]/issues?state=op*",
            "/repos/[draft]/issues",
        ),
        ("/repos/%5Bdraft%5D/issues", "/repos/%5Bdraft%5D/issues"),
        ("https://example.com?next=/repos/", "/"),
        ("/repos/?", "/repos/"),
        ("*", "*"),
    ] {
        assert_eq!(request_path(&Uri::parse(uri).unwrap()), expected);
    }
}

#[test]
fn absolute_request_keeps_uri_authority_over_tunnel_target() {
    let request = Request::builder()
        .uri("https://absolute.example:8443/path")
        .header("host", "header.example")
        .body(Body::empty())
        .unwrap();
    request
        .extensions()
        .insert(TunnelTarget("tunnel.example:443".parse().unwrap()));
    let target = RequestTarget::try_from(&request).unwrap();

    assert_eq!(
        (
            target.host_with_port().to_string(),
            target.protocol.is_secure(),
            target.authority_has_default_port()
        ),
        ("absolute.example:8443".to_string(), true, false),
    );
}

#[test]
fn origin_request_keeps_checked_tunnel_domain_over_host_header() {
    let request = Request::builder()
        .uri("/path")
        .header("host", "header.example")
        .body(Body::empty())
        .unwrap();
    request
        .extensions()
        .insert(TunnelTarget("tunnel.example:443".parse().unwrap()));
    request.extensions().insert(Protocol::HTTPS);
    let target = RequestTarget::try_from(&request).unwrap();

    assert_eq!(
        (
            target.host_with_port().to_string(),
            target.protocol.is_secure(),
            target.authority_has_default_port()
        ),
        ("tunnel.example:443".to_string(), true, true),
    );
}

#[test]
fn origin_request_to_ip_tunnel_keeps_host_header_routing() {
    let request = Request::builder()
        .uri("/path")
        .header("host", "header.example:8443")
        .body(Body::empty())
        .unwrap();
    request
        .extensions()
        .insert(TunnelTarget("192.0.2.1:443".parse().unwrap()));
    request.extensions().insert(Protocol::HTTPS);
    let target = RequestTarget::try_from(&request).unwrap();

    assert_eq!(
        (
            target.host_with_port().to_string(),
            target.protocol.is_secure(),
            target.authority_has_default_port()
        ),
        ("header.example:8443".to_string(), true, false),
    );
}

#[test]
fn origin_request_without_explicit_port_uses_protocol_default() {
    let request = Request::builder()
        .uri("/path")
        .header("host", "header.example")
        .body(Body::empty())
        .unwrap();
    request.extensions().insert(Protocol::HTTPS);
    let target = RequestTarget::try_from(&request).unwrap();

    assert_eq!(target.host_with_port().to_string(), "header.example:443");
}
