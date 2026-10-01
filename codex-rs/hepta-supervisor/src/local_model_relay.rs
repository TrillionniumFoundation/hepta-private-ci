//! Actual model I/O owned by the existing ordinary model authority.
//! The issuer's immutable peer enrollment, lease, revocations and nonce store
//! also fence this route. No workload receives the operator's login token.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::claim_final_use;
use codex_http_client::ClientRouteClass;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use reqwest::header::AUTHORIZATION;
use reqwest::header::HeaderMap;
use reqwest::header::HeaderName;
use reqwest::header::HeaderValue;
use sha2::Digest;
use sha2::Sha256;
use tokio::net::UnixListener;
use tokio::net::UnixStream;
use tokio::sync::Semaphore;
use tokio::task::JoinHandle;
use tokio::task::JoinSet;

use super::Issuer;
use super::capture_peer;
use super::credentials;
use super::relay_policy::ModelRelayPolicy;
use super::store;

#[path = "local_model_relay_http.rs"]
mod http;

pub(super) async fn start(issuer: Arc<Issuer>) -> anyhow::Result<Option<JoinHandle<()>>> {
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    let Some(policy) = &issuer.config.model_relay else {
        return Ok(None);
    };
    let parent = policy
        .socket
        .parent()
        .context("model relay socket parent")?;
    store::protected_directory(parent)?;
    if let Ok(metadata) = std::fs::symlink_metadata(&policy.socket) {
        anyhow::ensure!(
            metadata.file_type().is_socket() && metadata.uid() == 0,
            "unexpected model relay socket identity"
        );
        anyhow::ensure!(
            std::os::unix::net::UnixStream::connect(&policy.socket).is_err(),
            "model relay already active"
        );
        std::fs::remove_file(&policy.socket)?;
    }
    let listener = UnixListener::bind(&policy.socket)?;
    std::os::unix::fs::chown(&policy.socket, Some(0), Some(issuer.config.socket_gid))?;
    std::fs::set_permissions(&policy.socket, std::fs::Permissions::from_mode(0o660))?;
    let slots = Arc::new(Semaphore::new(policy.max_concurrent_calls));
    Ok(Some(tokio::spawn(async move {
        let mut calls = JoinSet::new();
        loop {
            tokio::select! {
                result = listener.accept() => {
                    let Ok((mut stream, _)) = result else { break; };
                    let Ok(slot) = slots.clone().try_acquire_owned() else {
                        // The rejection is itself bounded; a stalled untrusted
                        // client cannot block the listener or create a task.
                        let _ = tokio::time::timeout(
                            Duration::from_millis(100), http::error(&mut stream, 429)
                        ).await;
                        continue;
                    };
                    let issuer = issuer.clone();
                    calls.spawn(async move {
                        let _slot = slot;
                        let Some(policy) = &issuer.config.model_relay else { return; };
                        let limit = Duration::from_millis(policy.call_timeout_ms);
                        // No retries after dispatch. Disconnect, timeout and
                        // process loss leave the caller's original native
                        // provider attempt unresolved, never known no-effect.
                        let _ = tokio::time::timeout(limit, exchange(&issuer, &mut stream)).await;
                    });
                }
                _ = calls.join_next(), if !calls.is_empty() => {}
            }
        }
        // Dropping JoinSet cancels only this service's admitted calls; it
        // does not rewrite their existing Agentd/App Server effect journals.
    })))
}

async fn exchange(issuer: &Issuer, stream: &mut UnixStream) -> anyhow::Result<()> {
    let policy = issuer
        .config
        .model_relay
        .as_ref()
        .context("model relay disabled")?;
    let prepared = prepare(issuer, policy, stream).await;
    let (request, binding, token) = match prepared {
        Ok(prepared) => prepared,
        Err(_) => {
            http::error(stream, 503).await?;
            return Ok(());
        }
    };
    // No await separates the live admission from polling actual HTTP I/O.
    // The entered witness stays alive through physical streaming completion.
    issuer.synchronize_head()?;
    let _entered = issuer.authority.enter_verified_use(token, &binding)?;
    let mut response = request.send().await?;
    let status = response.status().as_u16();
    if !response.status().is_success() {
        http::error(stream, status).await?;
        return Ok(());
    }
    http::start_response(stream, status, response.headers()).await?;
    let mut delivered = 0_usize;
    while let Some(bytes) = response.chunk().await? {
        delivered = delivered
            .checked_add(bytes.len())
            .context("model response size overflow")?;
        anyhow::ensure!(
            delivered <= http::MAX_RESPONSE_BYTES,
            "model response byte bound"
        );
        http::chunk(stream, &bytes).await?;
    }
    http::finish(stream).await
}

async fn prepare(
    issuer: &Issuer,
    policy: &ModelRelayPolicy,
    stream: &mut UnixStream,
) -> anyhow::Result<(
    reqwest::RequestBuilder,
    FinalUseBinding,
    codex_hepta_contracts::VerifiedUseToken,
)> {
    let peer = capture_peer(
        &issuer.config,
        &issuer.verifier,
        &issuer.executables,
        stream,
    )
    .await?;
    let request = tokio::time::timeout(
        Duration::from_millis(policy.ingress_timeout_ms),
        http::read_request(stream),
    )
    .await
    .context("model request ingress timed out")??;
    anyhow::ensure!(
        policy.allowed_models.contains(&request.model),
        "model is not enrolled"
    );
    let credential = credentials::load(policy).await?;
    let upstream = if credential.uses_codex_backend {
        "https://chatgpt.com/backend-api/codex/responses"
    } else {
        "https://api.openai.com/v1/responses"
    };
    let client = HttpClientFactory::new(OutboundProxyPolicy::RespectSystemProxy)
        .build_reqwest_client(
            reqwest::Client::builder()
                .redirect(reqwest::redirect::Policy::none())
                .connect_timeout(Duration::from_secs(15))
                .timeout(Duration::from_millis(policy.call_timeout_ms)),
            upstream,
            ClientRouteClass::Api,
        )?;
    let mut headers = HeaderMap::new();
    for name in [
        "content-type",
        "content-encoding",
        "openai-beta",
        "originator",
        "user-agent",
        "x-codex-turn-metadata",
        "session_id",
    ] {
        if let Some(value) = request.headers.get(name) {
            headers.insert(
                HeaderName::from_bytes(name.as_bytes())?,
                HeaderValue::from_str(value)?,
            );
        }
    }
    let mut authorization = HeaderValue::from_str(&format!("Bearer {}", credential.bearer))?;
    authorization.set_sensitive(true);
    headers.insert(AUTHORIZATION, authorization);
    if let Some(account) = &credential.account_id {
        let mut value = HeaderValue::from_str(account)?;
        value.set_sensitive(true);
        headers.insert("chatgpt-account-id", value);
    }
    let body_digest: [u8; 32] = Sha256::digest(&request.body).into();
    let scope = serde_json::to_vec(&serde_json::json!({
        "operation": "runtime.codex.responses.relay.v1",
        "subject": peer.subject,
        "pid": peer.pid,
        "start_ticks": peer.start_ticks,
        "cgroup": peer.cgroup,
        "cgroup_device": peer.cgroup_device,
        "cgroup_inode": peer.cgroup_inode,
        "executable_sha256": peer.executable_sha256,
        "model": request.model,
        "credential_uid": policy.credential_uid,
        "socket": policy.socket,
        "upstream": upstream,
    }))?;
    let binding = FinalUseBinding {
        subject_id: peer.subject.clone(),
        destination_id: format!("model-relay:{:x}", Sha256::digest(upstream)),
        request_sha256: Sha256::digest(
            [
                b"POST\0".as_slice(),
                http::REQUEST_PATH.as_bytes(),
                b"\0",
                &body_digest,
            ]
            .concat(),
        )
        .into(),
        scope_sha256: Sha256::digest(scope).into(),
        payload_sha256: body_digest,
    };
    let outgoing = client.post(upstream).headers(headers).body(request.body);
    let head = issuer.synchronize_head()?;
    anyhow::ensure!(
        capture_peer(
            &issuer.config,
            &issuer.verifier,
            &issuer.executables,
            stream
        )
        .await?
            == peer,
        "model caller identity or execution lease changed"
    );
    let signed = Issuer::sign_binding(
        &issuer.config,
        &issuer.signer,
        issuer.clock.as_ref(),
        binding.clone(),
        &head,
    )?;
    let token = claim_final_use(&issuer.authority, &signed, &binding)?;
    // Claim fsync may wait on disk. Recheck the physical original execution
    // once more and the original revocation head/time at the actual entry.
    anyhow::ensure!(
        capture_peer(
            &issuer.config,
            &issuer.verifier,
            &issuer.executables,
            stream
        )
        .await?
            == peer,
        "model caller changed after durable nonce admission"
    );
    Ok((outgoing, binding, token))
}
