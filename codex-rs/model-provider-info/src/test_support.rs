//! Explicit, instance-bound support for in-process provider test fixtures.
//!
//! Like core's test_support module, this is a trusted-code helper rather than
//! a configuration feature. A serialized provider cannot acquire this permit.

use std::net::IpAddr;

use crate::ModelProviderInfo;

#[derive(Debug, Clone, PartialEq)]
pub struct MockInternalChatMetadata {
    base_url: String,
}

impl MockInternalChatMetadata {
    pub(crate) fn permits(&self, configured: Option<&str>, resolved: &str) -> bool {
        configured == Some(self.base_url.as_str()) && resolved == self.base_url.as_str()
    }
}

/// Explicitly model a metadata-capable backend at one local mock endpoint.
///
/// The exact URL belongs to this provider instance. No name, environment
/// variable, header or serialized configuration can grant this permission.
pub fn allow_internal_metadata_for_mock(
    provider: &mut ModelProviderInfo,
) -> Result<(), &'static str> {
    provider.mock_internal_chat_metadata = None;
    let base_url = provider.base_url.as_deref().ok_or("mock URL is required")?;
    let uri: http::Uri = base_url.parse().map_err(|_| "invalid mock URL")?;
    if !matches!(uri.scheme_str(), Some("http" | "ws"))
        || base_url.contains('#')
        || provider.query_params.is_some()
    {
        return Err("mock metadata requires one explicit HTTP or WS endpoint");
    }
    let authority = uri.authority().ok_or("mock authority is required")?;
    if authority.as_str().contains('@') || uri.port_u16().is_none_or(|port| port == 0) {
        return Err("mock metadata requires an explicit port and no credentials");
    }
    let host = uri.host().ok_or("mock host is required")?;
    let host = host.trim_matches(['[', ']']);
    if !host
        .parse::<IpAddr>()
        .is_ok_and(|address| address.is_loopback())
    {
        return Err("mock metadata requires a literal loopback address");
    }
    provider.mock_internal_chat_metadata = Some(MockInternalChatMetadata {
        base_url: base_url.to_string(),
    });
    Ok(())
}
