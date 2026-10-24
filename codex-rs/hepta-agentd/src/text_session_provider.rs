//! Operator entry into the original App Server provider-account APIs. Provider
//! login does not create a Hepta principal, Root permission, key or writer lease.
use super::*;
use codex_app_server_client::AppServerEvent;
use codex_app_server_protocol::Account;
use codex_app_server_protocol::GetAccountParams;
use codex_app_server_protocol::GetAccountResponse;
use codex_app_server_protocol::LoginAccountParams;
use codex_app_server_protocol::LoginAccountResponse;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

#[derive(Debug, Serialize)]
pub struct ProviderAccountDiagnostic {
    pub existing_route_verified: bool,
    pub provider_account_kind: Option<&'static str>,
    pub provider_requires_openai_auth: bool,
    /// Configuration observation, not proof that a model request will succeed.
    pub provider_account_configured: bool,
    pub hepta_human_authority: &'static str,
}

#[derive(Debug, Serialize)]
pub struct ProviderLoginChallenge {
    pub login_id: String,
    pub verification_url: String,
    pub user_code: String,
}

fn read_route(path: &Path) -> Result<AgentdTextSessionConfig, TextSessionError> {
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)
        .map_err(unavailable)?;
    let meta = file.metadata().map_err(unavailable)?;
    // SAFETY: geteuid has no pointer arguments and observes only this process.
    if !meta.is_file()
        || meta.uid() != unsafe { libc::geteuid() }
        || meta.nlink() != 1
        || meta.mode() & 0o777 != 0o600
    {
        return Err(unavailable(
            "route must be a current-user0600 regular single-link file",
        ));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(16 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.is_empty() || bytes.len() > 16 * 1024 {
        return Err(TextSessionError::Capacity);
    }
    serde_json::from_slice(&bytes).map_err(unavailable)
}

async fn connect(route_file: &Path) -> Result<RemoteAppServerClient, TextSessionError> {
    let route = read_route(route_file)?;
    let control = AgentdClient::new(
        route.control_socket.clone(),
        route.agent_id,
        route.spawn_generation,
    )
    .map_err(unavailable)?;
    let ingress = control.session_ingress().await.map_err(unavailable)?;
    let client = RemoteAppServerClient::connect_with_bounded_events(
        RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::UnixSocket {
                socket_path: ingress
                    .socket_path
                    .as_path()
                    .try_into()
                    .map_err(unavailable)?,
            },
            client_name: "hepta-original-provider-login".into(),
            client_version: env!("CARGO_PKG_VERSION").into(),
            experimental_api: true,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: Vec::new(),
            channel_capacity: 4,
        },
        32,
    )
    .await
    .map_err(unavailable)?;
    if client.codex_home() != route.codex_home.to_str() {
        return Err(TextSessionError::Identity);
    }
    let view: ThreadReadResponse = client
        .request_typed(ClientRequest::ThreadRead {
            request_id: RequestId::Integer(1),
            params: ThreadReadParams {
                thread_id: route.thread_id.clone(),
                include_turns: false,
            },
        })
        .await
        .map_err(unavailable)?;
    if view.thread.id != route.thread_id
        || view.thread.session_id != route.app_server_session_id
        || view.thread.ephemeral
    {
        return Err(TextSessionError::Identity);
    }
    Ok(client)
}

async fn account(
    client: &RemoteAppServerClient,
) -> Result<ProviderAccountDiagnostic, TextSessionError> {
    let view: GetAccountResponse = client
        .request_typed(ClientRequest::GetAccount {
            request_id: RequestId::Integer(3),
            params: GetAccountParams {
                refresh_token: false,
            },
        })
        .await
        .map_err(unavailable)?;
    Ok(ProviderAccountDiagnostic {
        existing_route_verified: true,
        provider_account_kind: view.account.as_ref().map(|account| match account {
            Account::ApiKey {} => "api_key",
            Account::Chatgpt { .. } => "chatgpt",
            Account::AmazonBedrock { .. } => "amazon_bedrock",
        }),
        provider_requires_openai_auth: view.requires_openai_auth,
        provider_account_configured: view.account.is_some(),
        hepta_human_authority: "requires_independent_existing_root_human_registration",
    })
}

/// Reads actual account state through the original Agentd-selected App Server.
/// It does not read credential files, refresh tokens, start a thread or turn.
pub async fn diagnose_existing_provider(
    route_file: &Path,
) -> Result<ProviderAccountDiagnostic, TextSessionError> {
    tokio::time::timeout(Duration::from_secs(30), async {
        let client = connect(route_file).await?;
        let result = account(&client).await;
        let _ = client.shutdown().await;
        result
    })
    .await
    .map_err(unavailable)?
}

/// Explicit human-requested device-code login using the original AuthManager.
/// The original server owns credentials and completion. No token is returned.
pub async fn login_existing_provider(
    route_file: &Path,
    show_challenge: impl Fn(ProviderLoginChallenge),
) -> Result<ProviderAccountDiagnostic, TextSessionError> {
    let mut client = tokio::time::timeout(Duration::from_secs(30), connect(route_file))
        .await
        .map_err(unavailable)??;
    let result = async {
        let response: LoginAccountResponse = client
            .request_typed(ClientRequest::LoginAccount {
                request_id: RequestId::Integer(2),
                params: LoginAccountParams::ChatgptDeviceCode,
            })
            .await
            .map_err(unavailable)?;
        let LoginAccountResponse::ChatgptDeviceCode {
            login_id,
            verification_url,
            user_code,
        } = response
        else {
            return Err(TextSessionError::Identity);
        };
        if login_id.is_empty()
            || login_id.len() > 128
            || verification_url.len() > 2048
            || !verification_url.starts_with("https://")
            || user_code.len() > 128
        {
            return Err(TextSessionError::Identity);
        }
        show_challenge(ProviderLoginChallenge {
            login_id: login_id.clone(),
            verification_url,
            user_code,
        });
        loop {
            let event = client
                .next_observed_event()
                .await
                .ok_or_else(|| unavailable("original provider login disconnected"))?;
            if event.connection_id() != client.connection_id() {
                return Err(TextSessionError::Identity);
            }
            match event.event() {
                AppServerEvent::ServerNotification(notification) => {
                    if let ServerNotification::AccountLoginCompleted(completed) =
                        notification.as_ref()
                        && completed.login_id.as_deref() == Some(login_id.as_str())
                    {
                        if !completed.success {
                            return Err(unavailable("original provider login did not complete"));
                        }
                        return account(&client).await;
                    }
                }
                AppServerEvent::Disconnected { .. } | AppServerEvent::Lagged { .. } => {
                    return Err(unavailable(
                        "original provider login result is unknown; inspect account/read",
                    ));
                }
                AppServerEvent::ServerRequest(_) => {
                    return Err(unavailable(
                        "original provider needs its external credential owner",
                    ));
                }
            }
        }
    };
    let result = tokio::time::timeout(Duration::from_secs(300), result)
        .await
        .map_err(unavailable)?;
    let _ = client.shutdown().await;
    result
}
