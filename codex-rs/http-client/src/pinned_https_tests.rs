use super::HttpClientBuilder;
use opentelemetry::Context;
use opentelemetry::global;
use opentelemetry::propagation::Extractor;
use opentelemetry::propagation::Injector;
use opentelemetry::propagation::TextMapPropagator;
use opentelemetry::propagation::text_map_propagator::FieldIter;
use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

type TestError = Box<dyn std::error::Error + Send + Sync>;
type TlsFixture = (
    String,
    String,
    std::thread::JoinHandle<Result<String, TestError>>,
);

struct Capture(Arc<Mutex<Vec<u8>>>);

impl Write for Capture {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0
            .lock()
            .map_err(|_| std::io::Error::other("capture lock poisoned"))?
            .extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

/// Deliberately attempts to override enrolled fields as well as injecting tracing metadata.
#[derive(Debug)]
struct PollutedPropagator;

impl TextMapPropagator for PollutedPropagator {
    fn inject_context(&self, _: &Context, injector: &mut dyn Injector) {
        injector.set("x-vault-token", "ambient-token".into());
        injector.set("x-vault-namespace", "ambient-namespace".into());
        injector.set("traceparent", "ambient-trace".into());
        injector.set("baggage", "ambient-secret".into());
    }

    fn extract_with_context(&self, context: &Context, _: &dyn Extractor) -> Context {
        context.clone()
    }

    fn fields(&self) -> FieldIter<'_> {
        FieldIter::new(&[])
    }
}

fn tls_fixture(response: String) -> Result<TlsFixture, TestError> {
    codex_utils_rustls_provider::ensure_rustls_crypto_provider();
    let certified = rcgen::generate_simple_self_signed(vec!["localhost".into()])?;
    let pem = certified.cert.pem();
    let config = rustls::ServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(
            vec![certified.cert.der().clone()],
            rustls_pki_types::PrivatePkcs8KeyDer::from(certified.signing_key.serialize_der())
                .into(),
        )?;
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    listener.set_nonblocking(/*nonblocking*/ true)?;
    let url = format!(
        "https://localhost:{}/enrolled-secret-path",
        listener.local_addr()?.port()
    );
    let task = std::thread::spawn(move || {
        let started = Instant::now();
        let socket = loop {
            match listener.accept() {
                Ok((socket, _)) => break socket,
                Err(error)
                    if error.kind() == std::io::ErrorKind::WouldBlock
                        && started.elapsed() < Duration::from_secs(/*secs*/ 8) =>
                {
                    std::thread::sleep(Duration::from_millis(/*millis*/ 10));
                }
                Err(error) => return Err(error.into()),
            }
        };
        socket.set_nonblocking(/*nonblocking*/ false)?;
        socket.set_read_timeout(Some(Duration::from_secs(/*secs*/ 5)))?;
        socket.set_write_timeout(Some(Duration::from_secs(/*secs*/ 5)))?;
        let connection = rustls::ServerConnection::new(Arc::new(config))?;
        let mut stream = rustls::StreamOwned::new(connection, socket);
        let mut request = Vec::new();
        while !request.ends_with(b"\r\n\r\n") && request.len() < 16 * 1024 {
            let mut byte = [0];
            // The wrong-CA case must terminate in the handshake, before an HTTP request.
            if stream.read_exact(&mut byte).is_err() {
                return Ok(String::new());
            }
            request.push(byte[0]);
        }
        stream.write_all(response.as_bytes())?;
        Ok(String::from_utf8(request)?)
    });
    Ok((url, pem, task))
}

#[test]
fn pinned_https_isolates_ambient_authority_and_redirects() -> Result<(), TestError> {
    // Environment and the global OTel propagator are changed only in an isolated subprocess,
    // including when a developer runs this under the ordinary parallel Rust test harness.
    if let Ok(url) = std::env::var("HEPTA_PINNED_HTTPS_TEST_URL") {
        let captured = Arc::new(Mutex::new(Vec::new()));
        let writer = Arc::clone(&captured);
        let subscriber = tracing_subscriber::fmt()
            .with_max_level(tracing::Level::DEBUG)
            .with_writer(move || Capture(Arc::clone(&writer)))
            .finish();
        let _subscriber = tracing::subscriber::set_default(subscriber);
        global::set_text_map_propagator(PollutedPropagator);
        let ambient = crate::client::trace_headers();
        assert_eq!(ambient["x-vault-token"], "ambient-token");
        assert!(ambient.contains_key("baggage"));
        let ca = std::fs::read(std::env::var("HEPTA_PINNED_HTTPS_TEST_CA")?)?;
        let client =
            HttpClientBuilder::build_pinned_https_direct(&ca, Duration::from_secs(/*secs*/ 2))?;
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        runtime.block_on(async {
            let response = client
                .get(&url)
                .header("X-Vault-Token", "explicit-token")
                .header("X-Vault-Namespace", "explicit-namespace")
                .send()
                .await?;
            assert_eq!(response.status(), http::StatusCode::TEMPORARY_REDIRECT);
            // A plaintext endpoint must be rejected before any request reaches the socket.
            assert!(
                client
                    .get(std::env::var("HEPTA_PINNED_HTTPS_TEST_TRAP")?)
                    .send()
                    .await
                    .is_err()
            );
            let wrong_ca = rcgen::generate_simple_self_signed(vec!["localhost".into()])?
                .cert
                .pem();
            let wrong = HttpClientBuilder::build_pinned_https_direct(
                wrong_ca.as_bytes(),
                Duration::from_secs(/*secs*/ 2),
            )?;
            // The server CA is explicitly present in both ambient CA environment variables.
            // It must still be rejected when a different CA is enrolled.
            assert!(
                wrong
                    .get(std::env::var("HEPTA_PINNED_HTTPS_TEST_WRONG_URL")?)
                    .send()
                    .await
                    .is_err()
            );
            Ok::<(), TestError>(())
        })?;
        let diagnostics = String::from_utf8(
            captured
                .lock()
                .map_err(|_| "capture lock poisoned")?
                .clone(),
        )?;
        for value in [
            "explicit-token",
            "explicit-namespace",
            "ambient-secret",
            "/enrolled-secret-path",
        ] {
            assert!(
                !diagnostics.contains(value),
                "transport diagnostics exposed enrolled data"
            );
        }
        return Ok(());
    }

    let trap = TcpListener::bind(("127.0.0.1", 0))?;
    trap.set_nonblocking(/*nonblocking*/ true)?;
    let proxy_url = format!("http://{}", trap.local_addr()?);
    let trap_url = format!("http://{}/must-not-receive-token", trap.local_addr()?);
    let response = format!(
        "HTTP/1.1 307 Temporary Redirect\r\nLocation: {trap_url}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );
    let (url, ca, task) = tls_fixture(response)?;
    let (wrong_url, ambient_ca, wrong_task) = tls_fixture(String::new())?;
    let directory = tempfile::tempdir()?;
    let ca_file = directory.path().join("enrolled.pem");
    let ambient_file = directory.path().join("ambient.pem");
    std::fs::write(&ca_file, ca)?;
    std::fs::write(&ambient_file, ambient_ca)?;
    let mut command = Command::new(std::env::current_exe()?);
    command
        .arg("pinned_https_isolates_ambient_authority_and_redirects")
        .arg("--nocapture");
    command
        .env("HEPTA_PINNED_HTTPS_TEST_URL", url)
        .env("HEPTA_PINNED_HTTPS_TEST_CA", ca_file)
        .env("HEPTA_PINNED_HTTPS_TEST_TRAP", &trap_url)
        .env("HEPTA_PINNED_HTTPS_TEST_WRONG_URL", wrong_url)
        .env("CODEX_CA_CERTIFICATE", &ambient_file)
        .env("SSL_CERT_FILE", &ambient_file);
    for name in [
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ] {
        command.env(name, &proxy_url);
    }
    command.env("NO_PROXY", "").env("no_proxy", "");
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let started = Instant::now();
    while child.try_wait()?.is_none() {
        if started.elapsed() > Duration::from_secs(/*secs*/ 15) {
            child.kill()?;
            child.wait()?;
            return Err("isolated transport probe exceeded its deadline".into());
        }
        std::thread::sleep(Duration::from_millis(/*millis*/ 10));
    }
    let output = child.wait_with_output()?;
    assert!(
        output.status.success(),
        "isolated transport probe failed: {} {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let observed = task
        .join()
        .map_err(|_| "TLS fixture panicked")??
        .to_ascii_lowercase();
    assert!(observed.contains("x-vault-token: explicit-token\r\n"));
    assert!(observed.contains("x-vault-namespace: explicit-namespace\r\n"));
    assert!(!observed.contains("ambient-"));
    assert!(!observed.contains("traceparent:"));
    assert!(!observed.contains("baggage:"));
    assert!(
        wrong_task
            .join()
            .map_err(|_| "wrong-CA fixture panicked")??
            .is_empty()
    );
    assert_eq!(
        trap.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
    Ok(())
}
