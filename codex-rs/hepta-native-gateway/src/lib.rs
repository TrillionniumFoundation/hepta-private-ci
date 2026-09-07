//! Minimal loopback-only Hepta live shell.
//!
//! The gateway has no outbound, model, Telegram, operator-mutation, Enforce,
//! promotion, or retirement path. Those remain separate gates.

#![forbid(unsafe_code)]

use std::env;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_paths::HeptaStateRoot;
use codex_hepta_runtime::HeptaRuntime;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::net::TcpStream;

pub const DEFAULT_LISTEN_ADDR: &str = "127.0.0.1:7373";
pub const CANARY_LISTEN_ADDR: &str = "127.0.0.1:17373";
pub const LIVE_SHELL_CONTRACT_ARG: &str = "--hepta-vnext-live-shell-contract-v1";
pub const LIVE_SHELL_CONTRACT_JSON: &str = r#"{"schema":"hepta_vnext_live_shell_contract_v1","status":"ready","protocol_version":1,"routes":["GET /","GET /api/hepta/runtime","GET /healthz"],"runtime":{"loopback_only":true,"read_only":true,"open_mode":"immutable-query-only-open-existing","schema_version":5,"requires_empty_wal":true,"keyed_integrity_required":true},"authority":{"telegram":false,"outbound":false,"model_invocation":false,"operator_mutation":false,"enforce":false,"promotion":false,"retirement":false,"automatic_transition":false}}"#;
const MAX_REQUEST_BYTES: usize = 32 * 1024;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);
const RESPONSE_TIMEOUT: Duration = Duration::from_secs(5);

const CLOSED_EFFECT_ENV_VARS: &[&str] = &[
    "HEPTA_GATEWAY_ENABLE_TELEGRAM_PLUGIN",
    "HEPTA_NATIVE_POST_REAL_HANDLER_APPROVED",
    "HEPTA_NATIVE_POST_REAL_HANDLERS",
    "HEPTA_NATIVE_TELEGRAM_CODEX_CORE_RUNNER",
    "HEPTA_NATIVE_TELEGRAM_DELIVERY_APPROVED",
    "HEPTA_NATIVE_TELEGRAM_HEPTA_KERNEL_RUNNER",
    "HEPTA_NATIVE_TELEGRAM_IN_PROCESS_MODEL_RUNNER",
    "HEPTA_NATIVE_TELEGRAM_LIVE_READ",
    "HEPTA_NATIVE_TELEGRAM_MODEL_TURN",
    "HEPTA_NATIVE_TELEGRAM_POLL_LOOP",
    "HEPTA_NATIVE_TELEGRAM_SEND",
    "HEPTA_OPERATOR_MUTATION_ENABLED",
    "HEPTA_RUNTIME_MUTATION_CANARY",
    "HEPTA_TELEGRAM_AUTHORITY_ENABLED",
    "HEPTA_ENFORCE_ENABLED",
    "HEPTA_PROMOTION_ENABLED",
    "HEPTA_OUTBOUND_ENABLED",
    "HEPTA_RETIREMENT_ENABLED",
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeGatewayOptions {
    pub listen_addr: SocketAddr,
    pub state_root: HeptaStateRoot,
}

impl NativeGatewayOptions {
    fn from_args(raw_args: &[String], default_root: HeptaStateRoot) -> Result<Self> {
        let mut listen_addr = DEFAULT_LISTEN_ADDR.to_string();
        let mut state_root = default_root;
        let mut positional_listen_seen = false;
        let mut index = 0;
        while index < raw_args.len() {
            match raw_args[index].as_str() {
                "--listen" => {
                    index += 1;
                    listen_addr = raw_args
                        .get(index)
                        .context("--listen requires HOST:PORT")?
                        .clone();
                }
                "--state-root" => {
                    index += 1;
                    let value = raw_args.get(index).context("--state-root requires PATH")?;
                    state_root = HeptaStateRoot::parse(value)?;
                }
                value if !value.starts_with('-') && !positional_listen_seen => {
                    listen_addr = value.to_string();
                    positional_listen_seen = true;
                }
                value => anyhow::bail!("unexpected --serve-ui argument: {value}"),
            }
            index += 1;
        }

        let listen_addr = listen_addr
            .parse::<SocketAddr>()
            .with_context(|| format!("parse loopback listen address {listen_addr}"))?;
        validate_loopback(listen_addr)?;
        Ok(Self {
            listen_addr,
            state_root,
        })
    }
}

pub fn parse_serve_ui_args(raw_args: &[String]) -> Result<Option<NativeGatewayOptions>> {
    if raw_args.first().map(String::as_str) != Some("--serve-ui") {
        return Ok(None);
    }
    let state_root = HeptaStateRoot::from_env()?;
    NativeGatewayOptions::from_args(&raw_args[1..], state_root).map(Some)
}

/// Prints the exact, machine-verifiable contract of the vNext live shell.
///
/// Release tooling uses this narrow handshake to reject an unrelated or
/// legacy broad-capability `hepta` executable before assigning closed runtime
/// claims to its immutable manifest.
pub fn print_live_shell_contract_if_requested(raw_args: &[String]) -> Result<bool> {
    if raw_args.first().map(String::as_str) != Some(LIVE_SHELL_CONTRACT_ARG) {
        return Ok(false);
    }
    if raw_args.len() != 1 {
        anyhow::bail!("{LIVE_SHELL_CONTRACT_ARG} accepts no additional arguments");
    }
    println!("{LIVE_SHELL_CONTRACT_JSON}");
    Ok(true)
}

/// Runs the live shell when the Hepta binary was invoked with `--serve-ui`.
/// Returns `false` without constructing a runtime for every other CLI mode.
pub fn run_serve_ui_if_requested(raw_args: &[String]) -> Result<bool> {
    let Some(options) = parse_serve_ui_args(raw_args)? else {
        return Ok(false);
    };
    validate_closed_effect_environment()?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("build Hepta gateway runtime")?;
    runtime.block_on(run_native_gateway(options))?;
    Ok(true)
}

pub async fn run_native_gateway(options: NativeGatewayOptions) -> Result<()> {
    validate_closed_effect_environment()?;
    let runtime = Arc::new(HeptaRuntime::open_existing(options.state_root).await?);
    let listener = TcpListener::bind(options.listen_addr)
        .await
        .with_context(|| format!("bind Hepta gateway at {}", options.listen_addr))?;
    let actual_addr = listener
        .local_addr()
        .context("inspect gateway listen address")?;
    validate_loopback(actual_addr)?;
    eprintln!("hepta live shell listening on http://{actual_addr}");

    loop {
        tokio::select! {
            accepted = listener.accept() => {
                let (stream, peer) = accepted.context("accept loopback gateway connection")?;
                if !peer.ip().is_loopback() {
                    continue;
                }
                let runtime = Arc::clone(&runtime);
                tokio::spawn(async move {
                    if let Err(error) = serve_connection(stream, runtime).await {
                        eprintln!("hepta loopback request failed: {error:#}");
                    }
                });
            }
            signal = tokio::signal::ctrl_c() => {
                signal.context("wait for gateway shutdown signal")?;
                return Ok(());
            }
        }
    }
}

fn validate_loopback(address: SocketAddr) -> Result<()> {
    if !address.ip().is_loopback() || address.port() == 0 {
        anyhow::bail!("Hepta live shell requires an explicit non-zero loopback HOST:PORT");
    }
    Ok(())
}

fn validate_closed_effect_environment() -> Result<()> {
    for name in CLOSED_EFFECT_ENV_VARS {
        if env::var(name).is_ok_and(|value| truthy(&value)) {
            anyhow::bail!("{name}=true is not admitted by the vNext live shell");
        }
    }
    Ok(())
}

fn truthy(value: &str) -> bool {
    matches!(
        value.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on"
    )
}

async fn serve_connection(mut stream: TcpStream, runtime: Arc<HeptaRuntime>) -> Result<()> {
    let request = tokio::time::timeout(REQUEST_TIMEOUT, read_request(&mut stream))
        .await
        .context("loopback request timed out")??;
    let response = route_request(&request, &runtime)?;
    tokio::time::timeout(RESPONSE_TIMEOUT, stream.write_all(&response))
        .await
        .context("loopback response timed out")?
        .context("write loopback response")?;
    tokio::time::timeout(RESPONSE_TIMEOUT, stream.shutdown())
        .await
        .context("loopback shutdown timed out")?
        .context("close loopback response")
}

async fn read_request(stream: &mut TcpStream) -> Result<Vec<u8>> {
    let mut bytes = Vec::with_capacity(2048);
    let mut buffer = [0_u8; 2048];
    loop {
        if bytes.windows(4).any(|window| window == b"\r\n\r\n") {
            return Ok(bytes);
        }
        let read = stream
            .read(&mut buffer)
            .await
            .context("read loopback request")?;
        if read == 0 {
            anyhow::bail!("loopback request ended before complete headers");
        }
        bytes.extend_from_slice(&buffer[..read]);
        if bytes.len() > MAX_REQUEST_BYTES {
            anyhow::bail!("HTTP request headers exceed {MAX_REQUEST_BYTES} bytes");
        }
    }
}

fn route_request(request: &[u8], runtime: &HeptaRuntime) -> Result<Vec<u8>> {
    let request = std::str::from_utf8(request).context("HTTP request is not UTF-8")?;
    let first_line = request
        .lines()
        .next()
        .context("HTTP request line is missing")?;
    let mut fields = first_line.split_whitespace();
    let method = fields.next().context("HTTP method is missing")?;
    let target = fields.next().context("HTTP target is missing")?;
    let version = fields.next().context("HTTP version is missing")?;
    if fields.next().is_some() || !matches!(version, "HTTP/1.0" | "HTTP/1.1") {
        return Ok(response(
            "400 Bad Request",
            "application/json; charset=utf-8",
            br#"{"error":"bad request"}"#,
        ));
    }
    if method != "GET" {
        return Ok(response(
            "405 Method Not Allowed",
            "application/json; charset=utf-8",
            br#"{"error":"live shell is read-only"}"#,
        ));
    }
    let path = target.split('?').next().unwrap_or(target);
    match path {
        "/healthz" => Ok(response(
            "200 OK",
            "application/json; charset=utf-8",
            br#"{"product":"hepta","status":"ok"}"#,
        )),
        "/api/hepta/runtime" => match runtime.status_json() {
            Ok(body) => Ok(response("200 OK", "application/json; charset=utf-8", &body)),
            Err(error) => {
                eprintln!("Hepta status organ unavailable: {error:#}");
                Ok(response(
                    "503 Service Unavailable",
                    "application/json; charset=utf-8",
                    br#"{"error":"runtime status unavailable"}"#,
                ))
            }
        },
        "/" => Ok(response(
            "200 OK",
            "text/html; charset=utf-8",
            CONTROL_SHELL.as_bytes(),
        )),
        _ => Ok(response(
            "404 Not Found",
            "application/json; charset=utf-8",
            br#"{"error":"not found"}"#,
        )),
    }
}

fn response(status: &str, content_type: &str, body: &[u8]) -> Vec<u8> {
    let header = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\n\r\n",
        body.len()
    );
    let mut response = Vec::with_capacity(header.len() + body.len());
    response.extend_from_slice(header.as_bytes());
    response.extend_from_slice(body);
    response
}

const CONTROL_SHELL: &str = r#"<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hepta vNext</title>
<style>body{font:16px system-ui;margin:3rem;max-width:58rem}pre{padding:1rem;background:#111;color:#eee;overflow:auto}</style>
<h1>Hepta vNext live shell</h1>
<p>Loopback-only, read-only internal canary surface.</p>
<pre id="status">loading…</pre>
<script>fetch('/api/hepta/runtime').then(r=>r.json()).then(v=>status.textContent=JSON.stringify(v,null,2)).catch(e=>status.textContent=String(e))</script>
</html>
"#;

#[cfg(test)]
#[path = "organ_request_tests.rs"]
mod organ_request_tests;

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_runtime::RuntimeAuthorityStatus;
    use codex_hepta_runtime::RuntimeStateAdapter;
    use codex_hepta_runtime::RuntimeStateStatus;
    use pretty_assertions::assert_eq;

    #[derive(Debug)]
    struct FixtureAdapter;

    impl RuntimeStateAdapter for FixtureAdapter {
        fn status(&self) -> RuntimeStateStatus {
            RuntimeStateStatus {
                adapter: "fixture",
                schema_version: 5,
                outcome_generation: 0,
                preference_generation: 0,
                runtime_snapshot_version: 1,
                runtime_snapshot_generation: 0,
                integrity_binding_present: true,
                integrity_verification: "hmac-sha256-v1-key-id-and-row-macs-verified",
                open_mode: "immutable-query-only-open-existing",
            }
        }
    }

    fn fixture_root(name: &str) -> Result<HeptaStateRoot> {
        HeptaStateRoot::parse(std::env::temp_dir().join(name))
    }

    fn fixture_runtime() -> Result<HeptaRuntime> {
        Ok(HeptaRuntime::from_adapter(
            fixture_root("hepta-vnext-gateway-test")?,
            Arc::new(FixtureAdapter),
        ))
    }

    #[test]
    fn parses_production_default_and_isolated_canary_addresses() -> Result<()> {
        let root = fixture_root("hepta-state")?;
        let canary_root = std::env::temp_dir().join("hepta-canary");
        let production = NativeGatewayOptions::from_args(&[], root.clone())?;
        assert_eq!(production.listen_addr.to_string(), DEFAULT_LISTEN_ADDR);
        let canary = NativeGatewayOptions::from_args(
            &[
                CANARY_LISTEN_ADDR.to_string(),
                "--state-root".to_string(),
                canary_root.to_string_lossy().into_owned(),
            ],
            root,
        )?;
        assert_eq!(canary.listen_addr.to_string(), CANARY_LISTEN_ADDR);
        assert_eq!(canary.state_root.as_path(), canary_root);
        Ok(())
    }

    #[test]
    fn rejects_non_loopback_or_ephemeral_address() -> Result<()> {
        let root = fixture_root("hepta-state")?;
        assert!(
            NativeGatewayOptions::from_args(&["0.0.0.0:7373".to_string()], root.clone()).is_err()
        );
        assert!(NativeGatewayOptions::from_args(&["127.0.0.1:0".to_string()], root).is_err());
        Ok(())
    }

    #[test]
    fn exposes_only_health_shell_and_closed_runtime_status() -> Result<()> {
        let runtime = fixture_runtime()?;
        let health = route_request(
            b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n",
            &runtime,
        )?;
        assert!(health.starts_with(b"HTTP/1.1 200 OK"));
        let status = route_request(
            b"GET /api/hepta/runtime HTTP/1.1\r\nHost: localhost\r\n\r\n",
            &runtime,
        )?;
        let body_start = status
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .context("runtime response headers")?
            + 4;
        let body = &status[body_start..];
        let value: serde_json::Value = serde_json::from_slice(body)?;
        assert_eq!(value["authority"]["outbound"], false);
        assert_eq!(value["authority"]["operator_mutation"], false);
        assert_eq!(value["authority"]["enforce"], false);
        assert_eq!(value["authority"]["promotion"], false);
        assert_eq!(value["authority"]["retirement"], false);
        Ok(())
    }

    #[test]
    fn rejects_all_post_requests() -> Result<()> {
        let response = route_request(
            b"POST /api/hepta/runtime HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n",
            &fixture_runtime()?,
        )?;
        assert!(response.starts_with(b"HTTP/1.1 405 Method Not Allowed"));
        Ok(())
    }

    #[tokio::test]
    async fn rejects_headers_larger_than_the_limit_even_with_a_terminator() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream).await
        });

        let mut client = TcpStream::connect(address).await.unwrap();
        let mut request = b"GET / HTTP/1.1\r\nX-Large: ".to_vec();
        request.resize(MAX_REQUEST_BYTES + 1, b'a');
        request.extend_from_slice(b"\r\n\r\n");
        client.write_all(&request).await.unwrap();

        let error = server.await.unwrap().unwrap_err();
        assert!(error.to_string().contains("headers exceed"));
    }

    #[test]
    fn truthy_values_are_explicit() {
        for value in ["1", "true", "TRUE", "yes", "on"] {
            assert!(truthy(value));
        }
        for value in ["", "0", "false", "off", "disabled"] {
            assert!(!truthy(value));
        }
    }

    #[test]
    fn ip_loopback_classification_matches_socket_policy() {
        assert!(std::net::IpAddr::from([127, 0, 0, 1]).is_loopback());
        assert!(!std::net::IpAddr::from([0, 0, 0, 0]).is_loopback());
        assert_eq!(
            RuntimeAuthorityStatus::default().automatic_transition,
            false
        );
    }

    #[test]
    fn live_shell_contract_is_exact_and_all_authority_is_closed() -> Result<()> {
        let value: serde_json::Value = serde_json::from_str(LIVE_SHELL_CONTRACT_JSON)?;
        assert_eq!(value["schema"], "hepta_vnext_live_shell_contract_v1");
        assert_eq!(value["routes"].as_array().map(Vec::len), Some(3));
        assert_eq!(value["runtime"]["loopback_only"], true);
        assert_eq!(value["runtime"]["read_only"], true);
        assert_eq!(value["runtime"]["schema_version"], 5);
        let authority = value["authority"]
            .as_object()
            .context("live shell contract authority object")?;
        assert_eq!(authority.len(), 8);
        assert!(authority.values().all(|gate| gate == false));
        Ok(())
    }
}
