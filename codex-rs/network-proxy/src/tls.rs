use codex_utils_rustls_provider::ensure_rustls_crypto_provider;
use rama_tls::client::TlsClientConfig;
use rama_tls_rustls::client::RustlsClientConfigExt;
use rama_tls_rustls::dep::rustls;
use rama_tls_rustls::dep::webpki_roots;
use std::sync::Arc;
use std::sync::LazyLock;

pub(crate) fn default_root_store() -> Arc<rustls::RootCertStore> {
    // Rama now defaults to the system store. Keep the proxy's existing Mozilla roots;
    // MITM forwarding supplies its explicitly assembled platform/startup trust store.
    static ROOTS: LazyLock<Arc<rustls::RootCertStore>> = LazyLock::new(|| {
        let mut roots = rustls::RootCertStore::empty();
        roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
        Arc::new(roots)
    });
    Arc::clone(&ROOTS)
}

pub(crate) fn client_config(roots: Arc<rustls::RootCertStore>) -> TlsClientConfig {
    ensure_rustls_crypto_provider();
    let client_config = rustls::ClientConfig::builder_with_protocol_versions(rustls::ALL_VERSIONS)
        .with_root_certificates(roots)
        .with_no_client_auth();
    TlsClientConfig::new()
        .with_alpn_http_auto()
        .with_modify_rustls_config(move |resolved| {
            let mut config = client_config.clone();
            // Keep Rama's request-specific ALPN selection, including HTTP/1-only upgrades.
            config.alpn_protocols = resolved.alpn_protocols;
            Ok(config)
        })
}
