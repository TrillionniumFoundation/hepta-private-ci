//! Destination restrictions attached to the actual connector, not a preliminary lookup.

use std::fmt;
use std::net::IpAddr;
use std::net::Ipv4Addr;
use std::sync::Arc;

use reqwest::Url;
use reqwest::dns::Addrs;
use reqwest::dns::Name;
use reqwest::dns::Resolve;
use reqwest::dns::Resolving;

/// A capability derived only from the originally configured resource URL.
///
/// Discovered URLs never extend this capability. Public addresses are allowed;
/// an explicit private/loopback IP or `localhost` permits only that exact origin.
/// Other DNS names must resolve to public addresses, even at the configured origin.
#[derive(Clone)]
pub struct HttpAddressPolicy {
    configured_origin: String,
    local: ConfiguredLocal,
}

impl fmt::Debug for HttpAddressPolicy {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HttpAddressPolicy")
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Copy)]
enum ConfiguredLocal {
    None,
    Literal(IpAddr),
    Localhost,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum HttpAddressPolicyError {
    #[error("restricted HTTP requires a valid configured HTTP resource origin")]
    InvalidConfiguredResource,
    #[error("restricted HTTP requires an HTTP destination without URL credentials")]
    InvalidDestination,
    #[error("HTTP destination is outside the configured address capability")]
    DestinationDenied,
    #[error("the selected proxy does not support restricted HTTP destination enforcement")]
    ProxyUnsupported,
    #[error("HTTP resolver was invoked for a different destination host")]
    ResolverHostMismatch,
    #[error("HTTP destination resolved to no permitted address")]
    NoPermittedAddress,
}

impl HttpAddressPolicy {
    pub fn from_configured_resource(resource: &str) -> Result<Self, HttpAddressPolicyError> {
        if resource.len() > 16 * 1024 {
            return Err(HttpAddressPolicyError::InvalidConfiguredResource);
        }
        let url =
            Url::parse(resource).map_err(|_| HttpAddressPolicyError::InvalidConfiguredResource)?;
        validate_url(&url).map_err(|_| HttpAddressPolicyError::InvalidConfiguredResource)?;
        let local = match literal_ip(&url) {
            Some(ip) => match address_class(ip) {
                AddressClass::Public => ConfiguredLocal::None,
                AddressClass::Private | AddressClass::Loopback => ConfiguredLocal::Literal(ip),
                AddressClass::Forbidden => {
                    return Err(HttpAddressPolicyError::InvalidConfiguredResource);
                }
            },
            None if url.host_str() == Some("localhost") => ConfiguredLocal::Localhost,
            None => ConfiguredLocal::None,
        };
        Ok(Self {
            configured_origin: url.origin().ascii_serialization(),
            local,
        })
    }

    /// Carries the same original origin across an execution boundary; it must not
    /// be replaced by the current metadata, issuer, token or redirect URL.
    pub fn configured_resource_origin(&self) -> &str {
        &self.configured_origin
    }

    pub(crate) fn resolver_for(
        &self,
        url: &Url,
    ) -> Result<RestrictedResolver, HttpAddressPolicyError> {
        validate_url(url)?;
        let same_origin = url.origin().ascii_serialization() == self.configured_origin;
        let allowance = if let Some(ip) = literal_ip(url) {
            match address_class(ip) {
                AddressClass::Public => AddressAllowance::Public,
                AddressClass::Private | AddressClass::Loopback
                    if same_origin
                        && matches!(self.local, ConfiguredLocal::Literal(original) if original == ip) =>
                {
                    AddressAllowance::Exact(ip)
                }
                AddressClass::Private | AddressClass::Loopback | AddressClass::Forbidden => {
                    return Err(HttpAddressPolicyError::DestinationDenied);
                }
            }
        } else if url.host_str() == Some("localhost")
            && same_origin
            && matches!(self.local, ConfiguredLocal::Localhost)
        {
            AddressAllowance::Loopback
        } else {
            let host = url
                .host_str()
                .ok_or(HttpAddressPolicyError::InvalidDestination)?
                .trim_end_matches('.');
            if host == "localhost" || host.ends_with(".localhost") {
                return Err(HttpAddressPolicyError::DestinationDenied);
            }
            AddressAllowance::Public
        };
        Ok(RestrictedResolver {
            expected_host: url
                .host_str()
                .ok_or(HttpAddressPolicyError::InvalidDestination)?
                .to_string(),
            allowance,
            lookup: Arc::new(SystemResolver),
        })
    }
}

fn validate_url(url: &Url) -> Result<(), HttpAddressPolicyError> {
    if !matches!(url.scheme(), "http" | "https")
        || url.host().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.port_or_known_default() == Some(0)
    {
        return Err(HttpAddressPolicyError::InvalidDestination);
    }
    Ok(())
}

fn literal_ip(url: &Url) -> Option<IpAddr> {
    url.host_str()?
        .trim_start_matches('[')
        .trim_end_matches(']')
        .parse()
        .ok()
}

#[derive(Clone, Copy)]
enum AddressAllowance {
    Public,
    Exact(IpAddr),
    Loopback,
}

/// Every address returned here is the address reqwest's connector receives.
/// No unchecked second lookup, resolver override or shared client cache follows.
pub(crate) struct RestrictedResolver {
    expected_host: String,
    allowance: AddressAllowance,
    lookup: Arc<dyn Resolve>,
}

impl Resolve for RestrictedResolver {
    fn resolve(&self, name: Name) -> Resolving {
        if name.as_str() != self.expected_host {
            return Box::pin(async { Err(HttpAddressPolicyError::ResolverHostMismatch.into()) });
        }
        let resolving = self.lookup.resolve(name);
        let allowance = self.allowance;
        Box::pin(async move {
            let addresses = resolving.await?;
            let allowed = addresses
                .filter(|address| match allowance {
                    AddressAllowance::Public => address_class(address.ip()) == AddressClass::Public,
                    AddressAllowance::Exact(ip) => address.ip() == ip,
                    AddressAllowance::Loopback => {
                        address_class(address.ip()) == AddressClass::Loopback
                    }
                })
                .map(|mut address| {
                    address.set_port(/*port*/ 0);
                    address
                })
                .collect::<Vec<_>>();
            if allowed.is_empty() {
                return Err(HttpAddressPolicyError::NoPermittedAddress.into());
            }
            Ok(Box::new(allowed.into_iter()) as Addrs)
        })
    }
}

struct SystemResolver;

impl Resolve for SystemResolver {
    fn resolve(&self, name: Name) -> Resolving {
        let host = name.as_str().to_owned();
        Box::pin(async move {
            let addresses = tokio::net::lookup_host((host.as_str(), 0)).await?;
            let addresses = addresses.collect::<Vec<_>>();
            Ok(Box::new(addresses.into_iter()) as Addrs)
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AddressClass {
    Public,
    Private,
    Loopback,
    Forbidden,
}

fn address_class(ip: IpAddr) -> AddressClass {
    match ip {
        IpAddr::V4(ip) => ipv4_class(ip),
        IpAddr::V6(ip) => {
            if let Some(ip) = ip.to_ipv4_mapped() {
                return ipv4_class(ip);
            }
            if ip.is_loopback() {
                return AddressClass::Loopback;
            }
            let segments = ip.segments();
            // Known cloud metadata addresses never receive an explicit local exception.
            if segments == [0xfd00, 0x0ec2, 0, 0, 0, 0, 0, 0x0254]
                || segments == [0xfd20, 0x00ce, 0, 0, 0, 0, 0, 0x0254]
            {
                return AddressClass::Forbidden;
            }
            if segments[0] & 0xfe00 == 0xfc00 {
                return AddressClass::Private;
            }
            // Conservative global unicast subset. Translation/tunnel prefixes
            // (including NAT64 and 6to4), special-use and documentation are refused.
            if segments[0] & 0xe000 != 0x2000
                || (segments[0] == 0x2001 && segments[1] & 0xfe00 == 0)
                || (segments[0] == 0x2001 && segments[1] == 0x0db8)
                || segments[0] == 0x2002
                || segments[0] == 0x3ffe
                || (segments[0] == 0x3fff && segments[1] & 0xf000 == 0)
            {
                return AddressClass::Forbidden;
            }
            AddressClass::Public
        }
    }
}

fn ipv4_class(ip: Ipv4Addr) -> AddressClass {
    let [a, b, c, d] = ip.octets();
    if a == 127 {
        return AddressClass::Loopback;
    }
    if a == 10 || (a == 172 && (16..=31).contains(&b)) || (a == 192 && b == 168) {
        return AddressClass::Private;
    }
    if a == 0
        || (a == 100 && (64..=127).contains(&b))
        || (a == 169 && b == 254)
        || (a == 192 && b == 0 && (c == 0 || c == 2))
        || (a == 192 && b == 88 && c == 99)
        || (a == 198 && (b == 18 || b == 19))
        || (a == 198 && b == 51 && c == 100)
        || (a == 203 && b == 0 && c == 113)
        || [a, b, c, d] == [168, 63, 129, 16]
        || a >= 224
    {
        return AddressClass::Forbidden;
    }
    AddressClass::Public
}

#[cfg(test)]
#[path = "address_policy_tests.rs"]
mod tests;
