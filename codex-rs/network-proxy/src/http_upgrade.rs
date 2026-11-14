use crate::config::NetworkMode;
use crate::mitm::MitmState;
use crate::rama_ext::TunnelTarget;
use crate::state::NetworkProxyState;
use rama_core::extensions::Extension;
use rama_core::extensions::Extensions;
use rama_core::extensions::ExtensionsRef;
use rama_http::Request;
use rama_http::Response;
use rama_http::layer::upgrade::UpgradeResponse;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ConnectMitmMode {
    Disabled,
    Enabled,
    DetectTls,
}

impl Extension for ConnectMitmMode {}

pub(crate) fn upgrade_response(
    (response, request): (Response, Request),
) -> UpgradeResponse<Request, Response> {
    let extensions = Extensions::new();
    // The upgraded IO already owns the connection's extensions. Copy only the
    // policy values consumed by the tunnel: copying the request's Ingress wrapper
    // back into that same connection would create a recursive extension chain.
    copy_extension::<NetworkProxyState>(request.extensions(), &extensions);
    copy_extension::<MitmState>(request.extensions(), &extensions);
    copy_extension::<TunnelTarget>(request.extensions(), &extensions);
    copy_extension::<NetworkMode>(request.extensions(), &extensions);
    copy_extension::<ConnectMitmMode>(request.extensions(), &extensions);
    UpgradeResponse {
        response,
        request,
        extensions,
    }
}

fn copy_extension<T: Extension>(source: &Extensions, target: &Extensions) {
    if let Some(value) = source.get_arc::<T>() {
        target.insert_arc(value);
    }
}

#[cfg(test)]
#[path = "http_upgrade_tests.rs"]
mod tests;
