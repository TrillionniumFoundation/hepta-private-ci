use super::ConnectMitmMode;
use super::upgrade_response;
use crate::config::NetworkMode;
use crate::rama_ext::TunnelTarget;
use pretty_assertions::assert_eq;
use rama_core::extensions::Extensions;
use rama_core::extensions::ExtensionsRef;
use rama_core::extensions::Ingress;
use rama_http::Body;
use rama_http::Request;
use rama_http::Response;
use rama_net::Protocol;

#[test]
fn upgrade_copies_tunnel_policy_without_copying_the_connection_wrapper() {
    let connection = Extensions::new();
    let request = Request::new(Body::empty());
    request.extensions().insert(Ingress(connection.clone()));
    request
        .extensions()
        .insert(TunnelTarget("example.com:443".parse().unwrap()));
    request.extensions().insert(NetworkMode::Limited);
    request.extensions().insert(ConnectMitmMode::DetectTls);

    let upgraded = upgrade_response((Response::new(Body::empty()), request));
    assert!(!upgraded.extensions.contains::<Ingress<Extensions>>());
    connection.extend(&upgraded.extensions);

    assert_eq!(connection.get_ref::<Protocol>(), None);
    assert_eq!(
        connection.get_ref::<NetworkMode>(),
        Some(&NetworkMode::Limited)
    );
    assert_eq!(
        connection.get_ref::<ConnectMitmMode>(),
        Some(&ConnectMitmMode::DetectTls)
    );
    assert_eq!(
        connection.get_ref::<TunnelTarget>().unwrap().0.to_string(),
        "example.com:443"
    );
}
