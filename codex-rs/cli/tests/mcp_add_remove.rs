use std::path::Path;

use anyhow::Result;
use codex_config::types::McpServerTransportConfig;
use codex_core::config::load_global_mcp_servers;
use predicates::str::contains;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

fn codex_command(codex_home: &Path) -> Result<assert_cmd::Command> {
    let mut cmd = assert_cmd::Command::new(codex_utils_cargo_bin::cargo_bin("codex")?);
    cmd.env("CODEX_HOME", codex_home);
    Ok(cmd)
}

#[tokio::test]
async fn add_and_remove_server_updates_global_config() -> Result<()> {
    let codex_home = TempDir::new()?;

    let mut add_cmd = codex_command(codex_home.path())?;
    add_cmd
        .args(["mcp", "add", "docs", "--", "echo", "hello"])
        .assert()
        .success()
        .stdout(contains("Added global MCP server 'docs'."));

    let servers = load_global_mcp_servers(codex_home.path()).await?;
    assert_eq!(servers.len(), 1);
    let docs = servers.get("docs").expect("server should exist");
    match &docs.transport {
        McpServerTransportConfig::Stdio {
            command,
            args,
            env,
            env_vars,
            cwd,
        } => {
            assert_eq!(command, "echo");
            assert_eq!(args, &vec!["hello".to_string()]);
            assert!(env.is_none());
            assert!(env_vars.is_empty());
            assert!(cwd.is_none());
        }
        other => panic!("unexpected transport: {other:?}"),
    }
    assert!(docs.enabled);

    let mut remove_cmd = codex_command(codex_home.path())?;
    remove_cmd
        .args(["mcp", "remove", "docs"])
        .assert()
        .success()
        .stdout(contains("Removed global MCP server 'docs'."));

    let servers = load_global_mcp_servers(codex_home.path()).await?;
    assert!(servers.is_empty());

    let mut remove_again_cmd = codex_command(codex_home.path())?;
    remove_again_cmd
        .args(["mcp", "remove", "docs"])
        .assert()
        .success()
        .stdout(contains("No MCP server named 'docs' found."));

    let servers = load_global_mcp_servers(codex_home.path()).await?;
    assert!(servers.is_empty());

    Ok(())
}

#[tokio::test]
async fn add_and_login_discover_oauth_for_configured_local_origin() -> Result<()> {
    let codex_home = TempDir::new()?;
    let resource = MockServer::start().await;
    let proxy = UnexpectedOAuthProxy::start()?;
    let resource_url = resource.uri();
    let server_url = format!("{resource_url}/mcp");
    let challenge = format!("Bearer resource_metadata=\"{resource_url}/oauth-resource\"");
    Mock::given(method("GET"))
        .and(path("/mcp"))
        .respond_with(
            ResponseTemplate::new(401).insert_header("WWW-Authenticate", challenge.as_str()),
        )
        .mount(&resource)
        .await;
    Mock::given(method("GET"))
        .and(path("/oauth-resource"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "resource": format!("{resource_url}/mcp"),
            "authorization_servers": [resource_url],
        })))
        .mount(&resource)
        .await;
    Mock::given(method("GET"))
        .and(path("/.well-known/oauth-authorization-server"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "issuer": resource_url,
            "authorization_endpoint": format!("{resource_url}/oauth/authorize"),
            "token_endpoint": format!("{resource_url}/oauth/token"),
            "registration_endpoint": format!("{resource_url}/oauth/register"),
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
        })))
        .mount(&resource)
        .await;
    Mock::given(method("POST"))
        .and(path("/oauth/register"))
        .respond_with(ResponseTemplate::new(400))
        .mount(&resource)
        .await;

    let mut add = codex_command(codex_home.path())?;
    add.env("HTTP_PROXY", proxy.uri())
        .env("http_proxy", proxy.uri())
        .env_remove("HTTPS_PROXY")
        .env_remove("https_proxy")
        .env_remove("ALL_PROXY")
        .env_remove("all_proxy")
        .env("NO_PROXY", "localhost,127.0.0.1,::1")
        .env("no_proxy", "localhost,127.0.0.1,::1")
        .args([
            "-c",
            "mcp_oauth_credentials_store=\"file\"",
            "mcp",
            "add",
            "oauth",
            "--url",
            server_url.as_str(),
        ]);
    let add_output = tokio::task::spawn_blocking(move || add.output()).await??;
    assert!(
        !add_output.status.success(),
        "mock OAuth registration should terminate the automatic login"
    );
    assert!(
        load_global_mcp_servers(codex_home.path())
            .await?
            .contains_key("oauth")
    );
    let helper_command = if cfg!(windows) {
        r#"echo {"X-Gateway":"gateway-token"}"#
    } else {
        r#"printf '{"X-Gateway":"gateway-token"}'"#
    };
    let config_path = codex_home.path().join("config.toml");
    let mut config = std::fs::read_to_string(&config_path)?;
    config.push_str(&format!(
        "http_headers_helper = {}\n",
        toml::Value::String(helper_command.to_string())
    ));
    std::fs::write(config_path, config)?;

    // Local OAuth login does not require the execution-environment registry.
    std::fs::write(codex_home.path().join("environments.toml"), "invalid = [")?;

    let mut login = codex_command(codex_home.path())?;
    login
        .env("HTTP_PROXY", proxy.uri())
        .env("http_proxy", proxy.uri())
        .env_remove("HTTPS_PROXY")
        .env_remove("https_proxy")
        .env_remove("ALL_PROXY")
        .env_remove("all_proxy")
        .env("NO_PROXY", "localhost,127.0.0.1,::1")
        .env("no_proxy", "localhost,127.0.0.1,::1")
        .args([
            "-c",
            "mcp_oauth_credentials_store=\"file\"",
            "mcp",
            "login",
            "oauth",
        ]);
    let login_output = tokio::task::spawn_blocking(move || login.output()).await??;
    assert!(
        !login_output.status.success(),
        "mock OAuth registration should terminate the explicit login"
    );

    let requests = resource
        .received_requests()
        .await
        .expect("configured resource should record OAuth requests");
    let registrations: Vec<_> = requests
        .iter()
        .filter(|request| request.method == "POST" && request.url.path() == "/oauth/register")
        .collect();
    assert_eq!(registrations.len(), 2);
    assert_eq!(
        registrations
            .iter()
            .filter(|request| request.headers.get("x-gateway").is_some())
            .count(),
        1
    );
    proxy.assert_unused()?;
    Ok(())
}

#[tokio::test]
async fn profile_mcp_reports_legacy_profile_migration() -> Result<()> {
    let codex_home = TempDir::new()?;
    std::fs::write(
        codex_home.path().join("config.toml"),
        r#"[profiles.work]
model = "gpt-5"
"#,
    )?;

    let mut list_cmd = codex_command(codex_home.path())?;
    list_cmd
        .args(["--profile", "work", "mcp", "list"])
        .assert()
        .failure()
        .stderr(contains("--profile `work` cannot be used"))
        .stderr(contains("[profiles.work]"))
        .stderr(contains("work.config.toml"));

    Ok(())
}

#[tokio::test]
async fn add_with_env_preserves_key_order_and_values() -> Result<()> {
    let codex_home = TempDir::new()?;

    let mut add_cmd = codex_command(codex_home.path())?;
    add_cmd
        .args([
            "mcp",
            "add",
            "envy",
            "--env",
            "FOO=bar",
            "--env",
            "ALPHA=beta",
            "--",
            "python",
            "server.py",
        ])
        .assert()
        .success();

    let servers = load_global_mcp_servers(codex_home.path()).await?;
    let envy = servers.get("envy").expect("server should exist");
    let env = match &envy.transport {
        McpServerTransportConfig::Stdio { env: Some(env), .. } => env,
        other => panic!("unexpected transport: {other:?}"),
    };

    assert_eq!(env.len(), 2);
    assert_eq!(env.get("FOO"), Some(&"bar".to_string()));
    assert_eq!(env.get("ALPHA"), Some(&"beta".to_string()));
    assert!(envy.enabled);

    Ok(())
}

#[tokio::test]
async fn add_streamable_http_without_manual_token() -> Result<()> {
    let codex_home = TempDir::new()?;

    let mut add_cmd = codex_command(codex_home.path())?;
    add_cmd
        .args([
            "mcp",
            "add",
            "github",
            "--url",
            "https://example.com/mcp",
            "--oauth-client-registration",
            "dcr",
        ])
        .assert()
        .success();

    let servers = load_global_mcp_servers(codex_home.path()).await?;
    let github = servers.get("github").expect("github server should exist");
    match &github.transport {
        McpServerTransportConfig::StreamableHttp {
            url,
            bearer_token_env_var,
            http_headers,
            env_http_headers,
            ..
        } => {
            assert_eq!(url, "https://example.com/mcp");
            assert!(bearer_token_env_var.is_none());
            assert!(http_headers.is_none());
            assert!(env_http_headers.is_none());
        }
        other => panic!("unexpected transport: {other:?}"),
    }
    assert!(github.enabled);
    assert_eq!(github.oauth, None);

    assert!(!codex_home.path().join(".credentials.json").exists());
    assert!(!codex_home.path().join(".env").exists());
    let config = std::fs::read_to_string(codex_home.path().join("config.toml"))?;
    assert!(!config.contains("client_registration"));
    assert!(!config.contains("[mcp_servers.github.oauth]"));

    Ok(())
}

#[tokio::test]
async fn add_streamable_http_with_custom_env_var() -> Result<()> {
    let codex_home = TempDir::new()?;

    let mut add_cmd = codex_command(codex_home.path())?;
    add_cmd
        .args([
            "mcp",
            "add",
            "issues",
            "--url",
            "https://example.com/issues",
            "--bearer-token-env-var",
            "GITHUB_TOKEN",
        ])
        .assert()
        .success();

    let servers = load_global_mcp_servers(codex_home.path()).await?;
    let issues = servers.get("issues").expect("issues server should exist");
    match &issues.transport {
        McpServerTransportConfig::StreamableHttp {
            url,
            bearer_token_env_var,
            http_headers,
            env_http_headers,
            ..
        } => {
            assert_eq!(url, "https://example.com/issues");
            assert_eq!(bearer_token_env_var.as_deref(), Some("GITHUB_TOKEN"));
            assert!(http_headers.is_none());
            assert!(env_http_headers.is_none());
        }
        other => panic!("unexpected transport: {other:?}"),
    }
    assert!(issues.enabled);
    Ok(())
}

#[tokio::test]
async fn add_streamable_http_with_oauth_options() -> Result<()> {
    let codex_home = TempDir::new()?;

    let mut add_cmd = codex_command(codex_home.path())?;
    add_cmd
        .args([
            "mcp",
            "add",
            "oauth-server",
            "--url",
            "https://example.com/mcp",
            "--oauth-client-id",
            "eci-prd-pub-codex-123",
            "--oauth-resource",
            "https://resource.example.com",
        ])
        .assert()
        .success();

    let servers = load_global_mcp_servers(codex_home.path()).await?;
    let oauth_server = servers
        .get("oauth-server")
        .expect("oauth server should exist");
    assert_eq!(
        oauth_server.oauth_client_id(),
        Some("eci-prd-pub-codex-123")
    );
    assert_eq!(
        oauth_server.oauth_resource.as_deref(),
        Some("https://resource.example.com")
    );

    Ok(())
}

#[tokio::test]
async fn add_streamable_http_rejects_removed_flag() -> Result<()> {
    let codex_home = TempDir::new()?;

    let mut add_cmd = codex_command(codex_home.path())?;
    add_cmd
        .args([
            "mcp",
            "add",
            "github",
            "--url",
            "https://example.com/mcp",
            "--with-bearer-token",
        ])
        .assert()
        .failure()
        .stderr(contains("--with-bearer-token"));

    let servers = load_global_mcp_servers(codex_home.path()).await?;
    assert!(servers.is_empty());

    Ok(())
}

#[tokio::test]
async fn add_cant_add_command_and_url() -> Result<()> {
    let codex_home = TempDir::new()?;

    let mut add_cmd = codex_command(codex_home.path())?;
    add_cmd
        .args([
            "mcp",
            "add",
            "github",
            "--url",
            "https://example.com/mcp",
            "--command",
            "--",
            "echo",
            "hello",
        ])
        .assert()
        .failure()
        .stderr(contains("unexpected argument '--command' found"));

    let servers = load_global_mcp_servers(codex_home.path()).await?;
    assert!(servers.is_empty());

    Ok(())
}

#[must_use = "finish the proxy observation with assert_unused"]
struct UnexpectedOAuthProxy {
    uri: String,
    stop: std::sync::Arc<std::sync::atomic::AtomicBool>,
    observer: Option<std::thread::JoinHandle<std::io::Result<Vec<String>>>>,
}

impl UnexpectedOAuthProxy {
    fn start() -> Result<Self> {
        let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
        listener.set_nonblocking(true)?;
        let uri = format!("http://{}", listener.local_addr()?);
        let stop = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let observer_stop = std::sync::Arc::clone(&stop);
        let observer = std::thread::spawn(move || -> std::io::Result<Vec<String>> {
            let mut connections = Vec::new();
            loop {
                match listener.accept() {
                    Ok((stream, peer)) => {
                        // Observe at most one immediately available request-line prefix.
                        // Never wait for request bytes or let unexpected traffic hang.
                        stream.set_nonblocking(true)?;
                        let mut bytes = [0_u8; 256];
                        let prefix = match stream.peek(&mut bytes) {
                            Ok(count) => format!(
                                "first request-line prefix {:?}",
                                String::from_utf8_lossy(&bytes[..count])
                                    .lines()
                                    .next()
                                    .map(str::to_owned)
                            ),
                            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                                "no request bytes immediately available".to_string()
                            }
                            Err(error) => format!("request prefix peek failed: {error}"),
                        };
                        drop(stream);
                        connections.push(format!("{peer}: {prefix}"));
                        if connections.len() >= 16 {
                            return Err(std::io::Error::other(format!(
                                "unexpected OAuth proxy connection limit reached: {connections:?}"
                            )));
                        }
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        if observer_stop.load(std::sync::atomic::Ordering::Acquire) {
                            return Ok(connections);
                        }
                        std::thread::sleep(std::time::Duration::from_millis(5));
                    }
                    Err(error) => return Err(error),
                }
            }
        });
        Ok(Self {
            uri,
            stop,
            observer: Some(observer),
        })
    }

    fn uri(&self) -> &str {
        &self.uri
    }

    fn assert_unused(mut self) -> Result<()> {
        self.stop.store(true, std::sync::atomic::Ordering::Release);
        let observer = self
            .observer
            .take()
            .ok_or_else(|| anyhow::anyhow!("proxy observer must be owned"))?;
        let connections = match observer.join() {
            Ok(result) => result?,
            Err(payload) => std::panic::resume_unwind(payload),
        };
        assert!(
            connections.is_empty(),
            "the explicit direct route unexpectedly reached its configured proxy: {connections:?}"
        );
        Ok(())
    }
}

impl Drop for UnexpectedOAuthProxy {
    fn drop(&mut self) {
        // Early test failures still close the listener and join the bounded observer.
        self.stop.store(true, std::sync::atomic::Ordering::Release);
        if let Some(observer) = self.observer.take() {
            let _ = observer.join();
        }
    }
}
