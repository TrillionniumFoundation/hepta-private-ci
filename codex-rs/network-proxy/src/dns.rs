use rama_core::error::BoxError;
use rama_core::error::ErrorExt as _;
use rama_core::error::extra::OpaqueError;
use rama_core::futures::Stream;
use rama_core::futures::StreamExt as _;
use rama_core::futures::stream;
use rama_dns::client::HickoryDnsResolver;
#[cfg(any(target_family = "unix", target_os = "windows"))]
use rama_dns::client::hickory::resolver::TokioResolver;
use rama_dns::client::hickory::resolver::config::ResolverOpts;
use rama_dns::client::resolver::DnsAddressResolver;
use rama_net::address::Domain;
use std::net::Ipv4Addr;
use std::net::Ipv6Addr;
use std::sync::Arc;
use std::sync::OnceLock;

/// Keep the proxy's system-configured Hickory resolver when Rama's global default changes.
#[derive(Clone, Copy, Debug)]
pub(crate) struct ProxyDnsResolver;

static RESOLVER: OnceLock<Result<AbsoluteDnsResolver<HickoryDnsResolver>, Arc<OpaqueError>>> =
    OnceLock::new();

fn resolver() -> Result<&'static AbsoluteDnsResolver<HickoryDnsResolver>, BoxError> {
    RESOLVER
        .get_or_init(|| {
            create_resolver()
                .map(AbsoluteDnsResolver)
                .map_err(|error| Arc::new(error.into_opaque_error()))
        })
        .as_ref()
        .map_err(|error| Box::new(Arc::clone(error)) as BoxError)
}

/// Rama's previous Hickory adapter treated every target as an absolute DNS name.
/// Preserve that behavior even when the system has search domains or high ndots.
#[derive(Clone, Debug)]
pub(crate) struct AbsoluteDnsResolver<Resolver>(pub(crate) Resolver);

fn absolute_domain(domain: Domain) -> Result<Domain, BoxError> {
    if domain.is_fqdn() {
        Ok(domain)
    } else {
        format!("{domain}.").parse().map_err(Into::into)
    }
}

impl<Resolver: DnsAddressResolver> DnsAddressResolver for AbsoluteDnsResolver<Resolver> {
    type Error = BoxError;

    fn lookup_ipv4(
        &self,
        domain: Domain,
    ) -> impl Stream<Item = Result<Ipv4Addr, Self::Error>> + Send + '_ {
        match absolute_domain(domain) {
            Ok(domain) => self
                .0
                .lookup_ipv4(domain)
                .map(|result| result.map_err(Into::into))
                .boxed(),
            Err(error) => stream::once(async move { Err(error) }).boxed(),
        }
    }

    fn lookup_ipv6(
        &self,
        domain: Domain,
    ) -> impl Stream<Item = Result<Ipv6Addr, Self::Error>> + Send + '_ {
        match absolute_domain(domain) {
            Ok(domain) => self
                .0
                .lookup_ipv6(domain)
                .map(|result| result.map_err(Into::into))
                .boxed(),
            Err(error) => stream::once(async move { Err(error) }).boxed(),
        }
    }
}

fn create_resolver() -> Result<HickoryDnsResolver, BoxError> {
    #[cfg(any(target_family = "unix", target_os = "windows"))]
    let system = (|| -> Result<HickoryDnsResolver, BoxError> {
        Ok(TokioResolver::builder_tokio()?.build()?.into())
    })();
    #[cfg(any(target_family = "unix", target_os = "windows"))]
    match system {
        Ok(resolver) => return Ok(resolver),
        Err(error) => {
            tracing::warn!("failed to load system DNS configuration; using Cloudflare: {error}")
        }
    }

    HickoryDnsResolver::builder()
        .with_options(ResolverOpts::default())
        .try_build()
}

impl DnsAddressResolver for ProxyDnsResolver {
    type Error = BoxError;

    fn lookup_ipv4(
        &self,
        domain: Domain,
    ) -> impl Stream<Item = Result<Ipv4Addr, Self::Error>> + Send + '_ {
        match resolver() {
            Ok(resolver) => resolver.lookup_ipv4(domain).boxed(),
            Err(error) => stream::once(async move { Err(error) }).boxed(),
        }
    }

    fn lookup_ipv6(
        &self,
        domain: Domain,
    ) -> impl Stream<Item = Result<Ipv6Addr, Self::Error>> + Send + '_ {
        match resolver() {
            Ok(resolver) => resolver.lookup_ipv6(domain).boxed(),
            Err(error) => stream::once(async move { Err(error) }).boxed(),
        }
    }
}
