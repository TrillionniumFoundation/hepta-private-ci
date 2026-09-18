use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use codex_hepta_contracts::{FinalUseGrant, FinalUseRevocations};
use ed25519_dalek::{Signer, SigningKey};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio_rustls::TlsAcceptor;

type TestError = Box<dyn std::error::Error + Send + Sync>;

async fn server<F>(
    status: u16,
    body: String,
    before_body: impl FnOnce() -> F + Send + 'static,
) -> Result<
    (
        String,
        String,
        tokio::task::JoinHandle<Result<String, TestError>>,
    ),
    TestError,
>
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    let certified = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()])?;
    let pem = certified.cert.pem();
    let config = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::aws_lc_rs::default_provider(),
    ))
    .with_safe_default_protocol_versions()?
    .with_no_client_auth()
    .with_single_cert(
        vec![certified.cert.der().clone()],
        rustls::pki_types::PrivatePkcs8KeyDer::from(certified.signing_key.serialize_der()).into(),
    )?;
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let endpoint = format!("https://localhost:{}/", listener.local_addr()?.port());
    let task = tokio::spawn(async move {
        let (socket, _) = listener.accept().await?;
        let Ok(mut stream) = TlsAcceptor::from(Arc::new(config)).accept(socket).await else {
            return Ok(String::new());
        };
        let mut request = Vec::new();
        while !request.ends_with(b"\r\n\r\n") && request.len() < 32 * 1024 {
            request.push(stream.read_u8().await?);
        }
        let header_text = String::from_utf8(request.clone())?;
        let content_length = header_text
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().ok())
                    .flatten()
            })
            .unwrap_or(0);
        if content_length > 0 {
            let mut body_bytes = vec![0_u8; content_length];
            stream.read_exact(&mut body_bytes).await?;
            request.extend_from_slice(&body_bytes);
        }

        let headers = format!(
            "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        stream.write_all(headers.as_bytes()).await?;
        before_body().await;
        stream.write_all(body.as_bytes()).await?;
        Ok::<String, TestError>(String::from_utf8(request)?)
    });
    Ok((endpoint, pem, task))
}

async fn drop_after_request_server() -> Result<
    (
        String,
        String,
        tokio::task::JoinHandle<Result<(), TestError>>,
    ),
    TestError,
> {
    let certified = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()])?;
    let pem = certified.cert.pem();
    let config = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::aws_lc_rs::default_provider(),
    ))
    .with_safe_default_protocol_versions()?
    .with_no_client_auth()
    .with_single_cert(
        vec![certified.cert.der().clone()],
        rustls::pki_types::PrivatePkcs8KeyDer::from(certified.signing_key.serialize_der()).into(),
    )?;
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let endpoint = format!("https://localhost:{}/", listener.local_addr()?.port());
    let task = tokio::spawn(async move {
        let (socket, _) = listener.accept().await?;
        let mut stream = TlsAcceptor::from(Arc::new(config)).accept(socket).await?;
        let mut headers = Vec::new();
        while !headers.ends_with(b"\r\n\r\n") && headers.len() < 32 * 1024 {
            headers.push(stream.read_u8().await?);
        }
        // The provider boundary may already have been entered. Deliberately
        // close without an HTTP response: the client must report Unknown and
        // must not create a retry inside the method.
        drop(stream);
        Ok::<(), TestError>(())
    });
    Ok((endpoint, pem, task))
}

fn client(endpoint: &str, ca: &str) -> BaoClient {
    BaoClient::new(
        endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture-provider-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap()
}

fn issue_request() -> BaoLeaseIssueRequest {
    BaoLeaseIssueRequest::new(
        "agent-one".into(),
        "model-provider".into(),
        "team/one".into(),
        "operation_1".into(),
        "/database/creds/app".into(),
        60,
        true,
        br#"{"role":"app"}"#.to_vec(),
    )
    .unwrap()
}

fn signed_grant(
    binding: FinalUseBinding,
    grant_id: &str,
    nonce: u8,
) -> Result<(FinalUseAuthority, SignedFinalUseGrant, tempfile::TempDir), TestError> {
    let issuer = SigningKey::from_bytes(&[73; 32]);
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let proposal = FinalUseGrant {
        schema_version: 1,
        signer_id: "owner".into(),
        authority_epoch: 9,
        grant_id: grant_id.into(),
        nonce: [nonce; 32],
        binding,
        not_before_unix_ms: now - 1000,
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer.sign(&proposal.signing_bytes()?).to_bytes().to_vec();
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "owner".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )?;
    Ok((
        authority,
        SignedFinalUseGrant {
            grant: proposal,
            signature,
        },
        directory,
    ))
}

fn lease_value(state: &str, generation: u64, renewable: bool) -> serde_json::Value {
    serde_json::json!({
        "lease_id": "lease_0123456789abcdef0123456789abcdef",
        "scope": "/database/creds/app",
        "state": state,
        "issued_at": 100,
        "expires_at": 1000,
        "renewable": renewable,
        "generation": generation,
    })
}

#[tokio::test]
async fn issue_uses_exact_bound_body_and_releases_secret_only_to_consumer() {
    let generated = b"dynamic-fixture-password";
    let response = serde_json::json!({
        "data": {
            "lease": lease_value("active", 1, true),
            "value_base64": STANDARD.encode(generated),
        }
    })
    .to_string();
    let (endpoint, ca, task) = server(200, response, || async {}).await.unwrap();
    let client = client(&endpoint, &ca);
    let request = issue_request();
    let binding = client.lease_issue_binding(&request).unwrap();
    let (authority, grant, _state) = signed_grant(binding.clone(), "lease-issue", 11).unwrap();

    let mut consumed = false;
    let receipt = client
        .request_secret_lease(&authority, &grant, &request, |secret| {
            assert_eq!(secret, generated);
            consumed = true;
            Ok(())
        })
        .await
        .unwrap();

    assert!(consumed);
    assert_eq!(receipt.request_sha256, binding.request_sha256);
    assert_eq!(receipt.secret_sha256, Digest32::of_bytes(generated).into_array());
    assert!(!serde_json::to_string(&receipt).unwrap().contains("dynamic-fixture-password"));

    let observed = task.await.unwrap().unwrap();
    let lower = observed.to_ascii_lowercase();
    assert!(lower.starts_with("post /v1/sys/dynamic-secrets/issue http/1.1\r\n"));
    assert!(lower.contains("x-vault-token: fixture-provider-token\r\n"));
    assert!(lower.contains("x-vault-namespace: team/one\r\n"));
    let (_, sent_body) = observed.split_once("\r\n\r\n").unwrap();
    let wire: serde_json::Value = serde_json::from_str(sent_body).unwrap();
    assert_eq!(wire["operation_id"], "operation_1");
    assert_eq!(wire["scope"], "/database/creds/app");
    assert_eq!(wire["ttl"], 60);
    assert_eq!(
        STANDARD.decode(wire["provider_request_base64"].as_str().unwrap()).unwrap(),
        br#"{"role":"app"}"#
    );
    assert_eq!(binding.payload_sha256, Digest32::of_bytes(sent_body.as_bytes()).into_array());

    assert_eq!(
        client
            .request_secret_lease(&authority, &grant, &request, |_| Ok(()))
            .await,
        Err(BaoLeaseClientError::Authority(FinalUseError::AlreadyClaimed))
    );
}

#[tokio::test]
async fn issue_revoked_during_response_never_releases_generated_secret() {
    let generated = b"must-not-be-delivered";
    let response = serde_json::json!({
        "data": {
            "lease": lease_value("active", 1, true),
            "value_base64": STANDARD.encode(generated),
        }
    })
    .to_string();
    let authority_slot = Arc::new(std::sync::Mutex::new(None::<FinalUseAuthority>));
    let update = Arc::clone(&authority_slot);
    let (endpoint, ca, task) = server(200, response, move || async move {
        update
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .update_revocations(FinalUseRevocations {
                authority_epoch: 9,
                revision: 2,
                revoked_grant_ids: std::collections::BTreeSet::from(["lease-issue".into()]),
            })
            .unwrap();
    })
    .await
    .unwrap();
    let client = client(&endpoint, &ca);
    let request = issue_request();
    let (authority, grant, _state) =
        signed_grant(client.lease_issue_binding(&request).unwrap(), "lease-issue", 12).unwrap();
    *authority_slot.lock().unwrap() = Some(authority.clone());

    let result = client
        .request_secret_lease(&authority, &grant, &request, |_| {
            panic!("revoked final-use grant released generated secret")
        })
        .await;
    assert_eq!(
        result,
        Err(BaoLeaseClientError::PostDispatchAuthority(FinalUseError::Revoked))
    );
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn renew_and_revoke_are_operation_bound_and_return_metadata_only() {
    let lease_id = "lease_0123456789abcdef0123456789abcdef";

    let renew_response = serde_json::json!({
        "data": lease_value("active", 2, true)
    })
    .to_string();
    let (renew_endpoint, renew_ca, renew_task) =
        server(200, renew_response, || async {}).await.unwrap();
    let renew_client = client(&renew_endpoint, &renew_ca);
    let renew = BaoLeaseRenewRequest::new(
        "agent-one".into(),
        "model-provider".into(),
        "team/one".into(),
        "renew_1".into(),
        lease_id.into(),
        120,
        br#"{"lease":"renew"}"#.to_vec(),
    )
    .unwrap();
    let renew_binding = renew_client.lease_renew_binding(&renew).unwrap();
    let (renew_authority, renew_grant, _renew_state) =
        signed_grant(renew_binding, "lease-renew", 21).unwrap();
    let renewed = renew_client
        .renew_secret_lease(&renew_authority, &renew_grant, &renew)
        .await
        .unwrap();
    assert_eq!(renewed.lease.state, BaoLeaseState::Active);
    assert_eq!(renewed.lease.generation, 2);
    let renew_observed = renew_task.await.unwrap().unwrap();
    assert!(
        renew_observed
            .to_ascii_lowercase()
            .starts_with("post /v1/sys/leases/renew http/1.1\r\n")
    );

    let revoke_response = serde_json::json!({
        "data": lease_value("revoked", 3, true)
    })
    .to_string();
    let (revoke_endpoint, revoke_ca, revoke_task) =
        server(200, revoke_response, || async {}).await.unwrap();
    let revoke_client = client(&revoke_endpoint, &revoke_ca);
    let revoke = BaoLeaseRevokeRequest::new(
        "agent-one".into(),
        "model-provider".into(),
        "team/one".into(),
        "revoke_1".into(),
        lease_id.into(),
        b"provider-revoke-canary".to_vec(),
    )
    .unwrap();
    let revoke_binding = revoke_client.lease_revoke_binding(&revoke).unwrap();
    let (revoke_authority, revoke_grant, _revoke_state) =
        signed_grant(revoke_binding, "lease-revoke", 22).unwrap();
    let revoked = revoke_client
        .revoke_secret_lease(&revoke_authority, &revoke_grant, &revoke)
        .await
        .unwrap();
    assert_eq!(revoked.lease.state, BaoLeaseState::Revoked);
    assert_eq!(revoked.lease.generation, 3);
    assert!(!serde_json::to_string(&revoked).unwrap().contains("provider-revoke-canary"));
    let revoke_observed = revoke_task.await.unwrap().unwrap();
    assert!(
        revoke_observed
            .to_ascii_lowercase()
            .starts_with("post /v1/sys/leases/revoke http/1.1\r\n")
    );
}

#[tokio::test]
async fn lost_mutation_response_is_unknown_and_not_retried() {
    let (endpoint, ca, task) = drop_after_request_server().await.unwrap();
    let client = client(&endpoint, &ca);
    let request = issue_request();
    let (authority, grant, _state) =
        signed_grant(client.lease_issue_binding(&request).unwrap(), "lease-unknown", 31).unwrap();

    assert_eq!(
        client
            .request_secret_lease(&authority, &grant, &request, |_| {
                panic!("lost response cannot release a secret")
            })
            .await,
        Err(BaoLeaseClientError::OutcomeUnknown)
    );
    task.await.unwrap().unwrap();

    // The consumed final-use nonce also prevents a caller from turning the
    // unknown outcome into a second dispatch with the same authority.
    assert_eq!(
        client
            .request_secret_lease(&authority, &grant, &request, |_| Ok(()))
            .await,
        Err(BaoLeaseClientError::Authority(FinalUseError::AlreadyClaimed))
    );
}

#[tokio::test]
async fn reconciliation_required_and_read_only_projections_are_explicit() {
    let pending = serde_json::json!({
        "errors": ["provider outcome is not safe to retry"],
        "reconciliation_required": true,
        "pending": {
            "lease_id": "lease_0123456789abcdef0123456789abcdef",
            "operation": "issue",
            "generation": 1
        }
    })
    .to_string();
    let (endpoint, ca, task) = server(503, pending, || async {}).await.unwrap();
    let client = client(&endpoint, &ca);
    let request = issue_request();
    let (authority, grant, _state) =
        signed_grant(client.lease_issue_binding(&request).unwrap(), "lease-reconcile", 41).unwrap();
    assert_eq!(
        client
            .request_secret_lease(&authority, &grant, &request, |_| Ok(()))
            .await,
        Err(BaoLeaseClientError::ReconciliationRequired)
    );
    task.await.unwrap().unwrap();

    let projection = serde_json::json!({
        "data": {
            "pending": {
                "lease_id": "lease_0123456789abcdef0123456789abcdef",
                "operation": "issue",
                "generation": 1
            }
        }
    })
    .to_string();
    let (endpoint, ca, task) = server(200, projection, || async {}).await.unwrap();
    let client = client(&endpoint, &ca);
    let pending = client
        .pending_secret_lease_operation("team/one")
        .await
        .unwrap()
        .unwrap();
    assert_eq!(pending.operation, "issue");
    let observed = task.await.unwrap().unwrap().to_ascii_lowercase();
    assert!(observed.starts_with("get /v1/sys/dynamic-secrets/pending http/1.1\r\n"));
}
