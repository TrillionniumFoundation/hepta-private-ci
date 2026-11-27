use super::start_echo_websocket_server;
use crate::TcpNodelay;
use crate::WebSocketConnection;
use crate::dialer::connect;
use codex_http_client::BuildCustomCaTransportError;
use codex_http_client::OutboundProxyRoute;
use codex_utils_rustls_provider::ensure_rustls_crypto_provider;
use futures::FutureExt;
use futures::SinkExt;
use futures::StreamExt;
use pretty_assertions::assert_eq;
use rcgen::CertificateParams;
use rcgen::CertifiedKey;
use rcgen::DnType;
use rcgen::KeyPair;
use rcgen::generate_simple_self_signed;
use rustls::ServerConfig;
use rustls::pki_types::PrivateKeyDer;
use rustls::pki_types::PrivatePkcs8KeyDer;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio::task::JoinHandle;
use tokio_rustls::TlsAcceptor;
use tokio_tungstenite::tungstenite::Error as WsError;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::protocol::WebSocketConfig;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error + Send + Sync>>;
const CASE_ENV: &str = "CODEX_WEBSOCKET_LAZY_CA_CASE";
const TARGET_ENV: &str = "CODEX_WEBSOCKET_LAZY_CA_TARGET";
const PROXY_ENV: &str = "CODEX_WEBSOCKET_LAZY_CA_PROXY";
const CHILD_TIMEOUT: Duration = Duration::from_secs(/*secs*/ 10);
const IO_TIMEOUT: Duration = Duration::from_secs(/*secs*/ 5);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Case {
    Trusted,
    Untrusted,
    Invalid,
    Bypass,
}

struct CaFile(PathBuf);

impl Drop for CaFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

#[tokio::test]
async fn plain_target_https_proxy_uses_lazy_trusted_custom_ca() -> TestResult {
    run_proxy_case(Case::Trusted).await
}

#[tokio::test]
async fn plain_target_https_proxy_rejects_untrusted_ca_before_connect() -> TestResult {
    run_proxy_case(Case::Untrusted).await
}

#[tokio::test]
async fn plain_target_https_proxy_rejects_invalid_ca_before_connect() -> TestResult {
    run_proxy_case(Case::Invalid).await
}

#[tokio::test]
async fn plain_target_no_proxy_bypass_does_not_read_unused_invalid_ca() -> TestResult {
    run_proxy_case(Case::Bypass).await
}

async fn run_proxy_case(case: Case) -> TestResult {
    ensure_rustls_crypto_provider();
    let CertifiedKey { cert, signing_key } =
        generate_simple_self_signed(vec!["localhost".to_string()])?;
    let pem = match case {
        Case::Trusted => cert.pem(),
        Case::Untrusted => {
            let signing_key = KeyPair::generate()?;
            let mut params = CertificateParams::new(vec!["unrelated.example".to_string()])?;
            // A distinct anchor subject makes this an unknown issuer, not a bad signature.
            params
                .distinguished_name
                .push(DnType::CommonName, "unrelated proxy test CA");
            params.self_signed(&signing_key)?.pem()
        }
        Case::Invalid | Case::Bypass => "not a PEM certificate".to_string(),
    };
    let config = ServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(
            vec![cert.der().clone()],
            PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(signing_key.serialize_der())),
        )?;
    let acceptor = TlsAcceptor::from(Arc::new(config));
    let proxy_listener = Arc::new(TcpListener::bind("127.0.0.1:0").await?);
    let proxy_address = proxy_listener.local_addr()?;
    let ca_path = std::env::temp_dir().join(format!(
        "codex-lazy-proxy-ca-{}-{}.pem",
        std::process::id(),
        proxy_address.port()
    ));
    let mut ca_output = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&ca_path)?;
    let ca_file = CaFile(ca_path.clone());
    ca_output.write_all(pem.as_bytes())?;
    drop(ca_output);
    let (target_address, target_task) = start_echo_websocket_server(/*acceptor*/ None).await;
    let proxy_task = if case == Case::Bypass {
        None
    } else {
        let listener = Arc::clone(&proxy_listener);
        Some(tokio::spawn(async move {
            let (socket, _) = listener.accept().await?;
            let mut stream = match acceptor.accept(socket).await {
                Ok(stream) => stream,
                Err(_) => return Ok::<_, Box<dyn std::error::Error + Send + Sync>>(Vec::new()),
            };
            let mut request = Vec::new();
            let mut byte = [0_u8; 1];
            while !request.ends_with(b"\r\n\r\n") {
                if stream.read(&mut byte).await? == 0 {
                    return Ok(request);
                }
                request.push(byte[0]);
                assert!(
                    request.len() <= 1024,
                    "proxy CONNECT header exceeded fixture bound"
                );
            }
            let mut target = TcpStream::connect(target_address).await?;
            stream
                .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                .await?;
            let _ = tokio::io::copy_bidirectional(&mut stream, &mut target).await;
            Ok(request)
        }))
    };
    let target_url = format!("ws://127.0.0.1:{}/v1/responses", target_address.port());
    let proxy_url = format!("https://localhost:{}", proxy_address.port());
    let child_result =
        tokio::task::spawn_blocking(move || run_child(case, target_url, proxy_url, ca_path)).await;
    let succeeded = matches!(&child_result, Ok(Ok(())));
    let target_result = finish_task(
        target_task,
        succeeded && matches!(case, Case::Trusted | Case::Bypass),
    )
    .await;
    let proxy_result = match proxy_task {
        Some(task) => finish_task(task, succeeded).await,
        None => Ok(None),
    };
    drop(ca_file);
    child_result??;
    target_result?;
    let request = proxy_result?.transpose()?;
    match case {
        Case::Trusted => {
            let request = String::from_utf8(request.ok_or("proxy did not return its request")?)?;
            let expected_request_line =
                format!("CONNECT 127.0.0.1:{} HTTP/1.1", target_address.port());
            assert_eq!(request.lines().next(), Some(expected_request_line.as_str()));
        }
        Case::Untrusted | Case::Invalid => {
            assert_eq!(
                request,
                Some(Vec::new()),
                "CA rejection must precede CONNECT bytes"
            );
        }
        Case::Bypass => {
            assert!(request.is_none());
            assert!(proxy_listener.accept().now_or_never().is_none());
        }
    }
    Ok(())
}

async fn finish_task<T>(mut task: JoinHandle<T>, expect_finish: bool) -> TestResult<Option<T>> {
    if !expect_finish {
        task.abort();
        let _ = task.await;
        return Ok(None);
    }
    match tokio::time::timeout(IO_TIMEOUT, &mut task).await {
        Ok(result) => Ok(Some(result?)),
        Err(error) => {
            task.abort();
            let _ = task.await;
            Err(error.into())
        }
    }
}

fn run_child(case: Case, target: String, proxy: String, ca_path: PathBuf) -> TestResult {
    let mut command = Command::new(std::env::current_exe()?);
    command.args([
        "--exact",
        "dialer::tests::lazy_ca_tests::isolated_lazy_ca_probe",
        "--nocapture",
    ]);
    for key in [
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
        "SSL_CERT_FILE",
    ] {
        command.env_remove(key);
    }
    command
        .env(CASE_ENV, format!("{case:?}"))
        .env(TARGET_ENV, target)
        .env(PROXY_ENV, &proxy)
        .env("HTTP_PROXY", proxy)
        .env(
            "NO_PROXY",
            if case == Case::Bypass {
                "127.0.0.1"
            } else {
                "unrelated.example"
            },
        )
        .env("CODEX_CA_CERTIFICATE", ca_path)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    let mut child = command.spawn()?;
    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                assert!(status.success(), "lazy CA {case:?} child failed: {status}");
                return Ok(());
            }
            Ok(None) if started.elapsed() < CHILD_TIMEOUT => {
                std::thread::sleep(Duration::from_millis(/*millis*/ 10));
            }
            result => {
                let kill = child.kill();
                let wait = child.wait();
                return Err(std::io::Error::other(format!("lazy CA {case:?} child did not complete: {result:?}; cleanup kill={kill:?}; wait={wait:?}")).into());
            }
        }
    }
}

#[tokio::test]
async fn isolated_lazy_ca_probe() -> TestResult {
    let Ok(case) = std::env::var(CASE_ENV) else {
        return Ok(());
    };
    let request = std::env::var(TARGET_ENV)?.into_client_request()?;
    let route = OutboundProxyRoute::Proxy {
        url: std::env::var(PROXY_ENV)?,
        no_proxy: Some(std::env::var("NO_PROXY")?),
    };
    let result = tokio::time::timeout(
        IO_TIMEOUT,
        connect(
            request,
            WebSocketConfig::default(),
            /*tls_config*/ None,
            route,
            TcpNodelay::Enabled,
        ),
    )
    .await?;
    match case.as_str() {
        "Trusted" | "Bypass" => {
            let (inner, _) = result?;
            let mut websocket = WebSocketConnection { inner };
            let expected = Message::Text("lazy CA proxy probe".into());
            websocket.send(expected.clone()).await?;
            assert_eq!(websocket.next().await.ok_or("echo missing")??, expected);
        }
        "Invalid" => match result {
            Err(WsError::Io(error)) => assert!(matches!(
                error
                    .get_ref()
                    .and_then(|cause| cause.downcast_ref::<BuildCustomCaTransportError>()),
                Some(BuildCustomCaTransportError::InvalidCaFile { .. })
            )),
            Err(error) => panic!("expected typed custom CA rejection, got {error}"),
            Ok(_) => panic!("invalid custom CA unexpectedly established a tunnel"),
        },
        "Untrusted" => match result {
            Err(WsError::Io(error)) => assert!(
                matches!(
                    error
                        .get_ref()
                        .and_then(|cause| cause.downcast_ref::<rustls::Error>()),
                    Some(rustls::Error::InvalidCertificate(
                        rustls::CertificateError::UnknownIssuer
                    ))
                ),
                "untrusted custom CA must fail certificate verification: {error}"
            ),
            Err(error) => panic!("expected an untrusted proxy certificate, got {error}"),
            Ok(_) => panic!("untrusted custom CA unexpectedly established a tunnel"),
        },
        _ => panic!("unknown lazy CA case: {case}"),
    }
    Ok(())
}
