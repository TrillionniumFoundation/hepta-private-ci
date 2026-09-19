use super::*;

use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio_rustls::TlsAcceptor;

type TestError = Box<dyn std::error::Error + Send + Sync>;

#[derive(Clone)]
struct TestResponse {
    status: u16,
    body: String,
    delay_before_body: Duration,
}

impl TestResponse {
    fn json(status: u16, body: serde_json::Value) -> Self {
        Self {
            status,
            body: body.to_string(),
            delay_before_body: Duration::ZERO,
        }
    }

    fn delayed(status: u16, body: serde_json::Value, delay_before_body: Duration) -> Self {
        Self {
            status,
            body: body.to_string(),
            delay_before_body,
        }
    }

    fn empty(status: u16) -> Self {
        Self {
            status,
            body: String::new(),
            delay_before_body: Duration::ZERO,
        }
    }
}

async fn server(
    responses: Vec<TestResponse>,
) -> Result<
    (
        String,
        String,
        tokio::task::JoinHandle<Result<Vec<String>, TestError>>,
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
        let acceptor = TlsAcceptor::from(Arc::new(config));
        let mut requests = Vec::new();
        for response in responses {
            let (socket, _) = listener.accept().await?;
            let mut stream = acceptor.accept(socket).await?;
            requests.push(read_request(&mut stream).await?);
            let reason = match response.status {
                200 => "OK",
                204 => "No Content",
                400 => "Bad Request",
                403 => "Forbidden",
                404 => "Not Found",
                500 => "Internal Server Error",
                _ => "Test",
            };
            let headers = format!(
                "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                response.status,
                reason,
                response.body.len()
            );
            stream.write_all(headers.as_bytes()).await?;
            if !response.delay_before_body.is_zero() {
                tokio::time::sleep(response.delay_before_body).await;
            }
            if !response.body.is_empty() {
                let _ = stream.write_all(response.body.as_bytes()).await;
            }
        }
        Ok::<Vec<String>, TestError>(requests)
    });
    Ok((endpoint, pem, task))
}

async fn read_request<S>(stream: &mut S) -> Result<String, TestError>
where
    S: AsyncRead + Unpin,
{
    let mut bytes = Vec::new();
    while !bytes.ends_with(b"\r\n\r\n") && bytes.len() < 32 * 1024 {
        bytes.push(stream.read_u8().await?);
    }
    let headers = String::from_utf8(bytes.clone())?;
    let content_length = headers
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("content-length")
                .then(|| value.trim().parse::<usize>().ok())
                .flatten()
        })
        .unwrap_or(0);
    for _ in 0..content_length {
        bytes.push(stream.read_u8().await?);
    }
    Ok(String::from_utf8(bytes)?)
}

fn issue_request(operation_id: &str) -> DynamicSecretLeaseRequest {
    DynamicSecretLeaseRequest {
        subject_id: "agent-one".into(),
        consumer_id: "model-provider".into(),
        operation_id: operation_id.into(),
        namespace: "team/one".into(),
        mount: "database".into(),
        path: "creds/readonly".into(),
        secret_fields: vec!["password".into(), "username".into()],
        max_lease_duration_seconds: 120,
    }
}

fn dynamic_response(ttl: u64) -> serde_json::Value {
    serde_json::json!({
        "lease_id": "database/creds/readonly/lease-123",
        "renewable": true,
        "lease_duration": ttl,
        "data": {
            "username": "db-user",
            "password": "db-password-super-secret",
            "ignored": "must-never-cross-callback"
        }
    })
}

fn private_tempdir() -> Result<tempfile::TempDir, TestError> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    Ok(directory)
}

fn authority() -> Result<(FinalUseAuthority, SigningKey, tempfile::TempDir), TestError> {
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let directory = private_tempdir()?;
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "owner".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )?;
    Ok((authority, issuer, directory))
}

fn grant(
    issuer: &SigningKey,
    binding: FinalUseBinding,
    grant_id: &str,
    nonce_byte: u8,
) -> Result<SignedFinalUseGrant, TestError> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "owner".into(),
        authority_epoch: 7,
        grant_id: grant_id.into(),
        nonce: [nonce_byte; 32],
        binding,
        not_before_unix_ms: now - 1000,
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
    Ok(SignedFinalUseGrant { grant, signature })
}

#[tokio::test]
async fn dynamic_issue_delivers_only_selected_fields_and_persists_metadata() {
    let (endpoint, ca, task) = server(vec![TestResponse::json(200, dynamic_response(60))])
        .await
        .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-provider-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let lease_dir = private_tempdir().unwrap();
    let registry = SecretLeaseRegistry::open_state_dir(lease_dir.path()).unwrap();
    let (authority, issuer, _authority_dir) = authority().unwrap();
    let request = issue_request("issue-1");
    let signed = grant(
        &issuer,
        client.dynamic_secret_lease_binding(&request).unwrap(),
        "issue-grant",
        1,
    )
    .unwrap();

    let mut delivered = false;
    let metadata = client
        .request_secret_lease(&registry, &authority, &signed, &request, |values| {
            assert_eq!(values.field_count(), 2);
            assert!(values.contains_field("username"));
            assert!(values.contains_field("password"));
            assert!(!values.contains_field("ignored"));
            assert_eq!(
                values.with_field("username", |value| value.to_vec()),
                Some(b"db-user".to_vec())
            );
            assert_eq!(
                values.with_field("password", |value| value.to_vec()),
                Some(b"db-password-super-secret".to_vec())
            );
            delivered = true;
            Ok(())
        })
        .await
        .unwrap();
    assert!(delivered);
    assert_eq!(metadata.state, SecretLeaseState::Active);
    assert_eq!(metadata.lease_duration_seconds, 60);
    assert_eq!(metadata.rotation_generation, 1);

    let request_text = task.await.unwrap().unwrap().pop().unwrap();
    let lower = request_text.to_ascii_lowercase();
    assert!(lower.starts_with("get /v1/database/creds/readonly http/1.1\r\n"));
    assert!(lower.contains("x-vault-token: fixture-provider-token\r\n"));
    assert!(lower.contains("x-vault-namespace: team/one\r\n"));

    let persisted = std::fs::read_to_string(lease_dir.path().join("lease-registry.json")).unwrap();
    assert!(!persisted.contains("db-password-super-secret"));
    assert!(!persisted.contains("db-user"));
    assert!(!persisted.contains("must-never-cross-callback"));
    assert!(persisted.contains("database/creds/readonly/lease-123"));

    drop(registry);
    let reopened = SecretLeaseRegistry::open_state_dir(lease_dir.path()).unwrap();
    assert_eq!(
        reopened
            .lease("database/creds/readonly/lease-123")
            .unwrap()
            .unwrap()
            .state,
        SecretLeaseState::Active
    );
}

#[tokio::test]
async fn issue_timeout_is_durable_unknown_and_duplicate_operation_is_blocked() {
    let (endpoint, ca, task) = server(vec![TestResponse::delayed(
        200,
        dynamic_response(60),
        Duration::from_millis(150),
    )])
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_millis(50),
    )
    .unwrap();
    let lease_dir = private_tempdir().unwrap();
    let registry = SecretLeaseRegistry::open_state_dir(lease_dir.path()).unwrap();
    let (authority, issuer, _authority_dir) = authority().unwrap();
    let request = issue_request("issue-timeout");
    let first = grant(
        &issuer,
        client.dynamic_secret_lease_binding(&request).unwrap(),
        "issue-timeout-1",
        2,
    )
    .unwrap();

    assert_eq!(
        client
            .request_secret_lease(&registry, &authority, &first, &request, |_| {
                panic!("timed-out issuance must not deliver")
            })
            .await,
        Err(SecretLeaseError::OutcomeIndeterminate)
    );
    assert_eq!(
        registry.operation("issue-timeout").unwrap().unwrap().state,
        LeaseOperationState::OutcomeUnknown
    );

    let second = grant(
        &issuer,
        client.dynamic_secret_lease_binding(&request).unwrap(),
        "issue-timeout-2",
        3,
    )
    .unwrap();
    assert_eq!(
        client
            .request_secret_lease(&registry, &authority, &second, &request, |_| Ok(()))
            .await,
        Err(SecretLeaseError::ReconciliationRequired)
    );
    task.await.unwrap().unwrap();

    drop(registry);
    let reopened = SecretLeaseRegistry::open_state_dir(lease_dir.path()).unwrap();
    assert_eq!(
        reopened
            .operation("issue-timeout")
            .unwrap()
            .unwrap()
            .state,
        LeaseOperationState::OutcomeUnknown
    );
}

#[tokio::test]
async fn renew_and_revoke_use_provider_lease_endpoints_and_persist_terminal_state() {
    let lease_id = "database/creds/readonly/lease-123";
    let (endpoint, ca, task) = server(vec![
        TestResponse::json(200, dynamic_response(60)),
        TestResponse::json(
            200,
            serde_json::json!({
                "lease_id": lease_id,
                "renewable": true,
                "lease_duration": 90
            }),
        ),
        TestResponse::empty(204),
    ])
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let lease_dir = private_tempdir().unwrap();
    let registry = SecretLeaseRegistry::open_state_dir(lease_dir.path()).unwrap();
    let (authority, issuer, _authority_dir) = authority().unwrap();

    let issue = issue_request("issue-lifecycle");
    let issue_grant = grant(
        &issuer,
        client.dynamic_secret_lease_binding(&issue).unwrap(),
        "issue-lifecycle-grant",
        4,
    )
    .unwrap();
    client
        .request_secret_lease(&registry, &authority, &issue_grant, &issue, |_| Ok(()))
        .await
        .unwrap();

    let renew = LeaseRenewRequest {
        subject_id: issue.subject_id.clone(),
        consumer_id: issue.consumer_id.clone(),
        operation_id: "renew-1".into(),
        namespace: issue.namespace.clone(),
        lease_id: lease_id.into(),
        increment_seconds: 90,
    };
    let renew_grant = grant(
        &issuer,
        client.lease_renew_binding(&renew).unwrap(),
        "renew-grant",
        5,
    )
    .unwrap();
    let renewed = client
        .renew_secret_lease(&registry, &authority, &renew_grant, &renew)
        .await
        .unwrap();
    assert_eq!(renewed.state, SecretLeaseState::Active);
    assert_eq!(renewed.lease_duration_seconds, 90);
    assert_eq!(renewed.rotation_generation, 2);

    let revoke = LeaseRevokeRequest {
        subject_id: issue.subject_id,
        consumer_id: issue.consumer_id,
        operation_id: "revoke-1".into(),
        namespace: issue.namespace,
        lease_id: lease_id.into(),
    };
    let revoke_grant = grant(
        &issuer,
        client.lease_revoke_binding(&revoke).unwrap(),
        "revoke-grant",
        6,
    )
    .unwrap();
    let revoked = client
        .revoke_secret_lease(&registry, &authority, &revoke_grant, &revoke)
        .await
        .unwrap();
    assert_eq!(revoked.state, SecretLeaseState::Revoked);
    assert!(!revoked.provider_absent);

    let requests = task.await.unwrap().unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests[0]
        .to_ascii_lowercase()
        .starts_with("get /v1/database/creds/readonly http/1.1\r\n"));
    assert!(requests[1]
        .to_ascii_lowercase()
        .starts_with("post /v1/sys/leases/renew http/1.1\r\n"));
    assert!(requests[1].contains(lease_id));
    assert!(requests[1].contains("\"increment\":90"));
    assert!(requests[2]
        .to_ascii_lowercase()
        .starts_with("post /v1/sys/leases/revoke http/1.1\r\n"));
    assert!(requests[2].contains(lease_id));
    assert!(requests[2].contains("\"sync\":true"));

    drop(registry);
    let reopened = SecretLeaseRegistry::open_state_dir(lease_dir.path()).unwrap();
    let terminal = reopened.lease(lease_id).unwrap().unwrap();
    assert_eq!(terminal.state, SecretLeaseState::Revoked);
    assert_eq!(terminal.rotation_generation, 3);
}

#[tokio::test]
async fn renew_timeout_requires_lookup_reconciliation_before_further_mutation() {
    let lease_id = "database/creds/readonly/lease-123";
    let (endpoint, ca, task) = server(vec![
        TestResponse::json(200, dynamic_response(60)),
        TestResponse::delayed(
            200,
            serde_json::json!({
                "lease_id": lease_id,
                "renewable": true,
                "lease_duration": 90
            }),
            Duration::from_millis(150),
        ),
        TestResponse::json(
            200,
            serde_json::json!({
                "data": {
                    "id": lease_id,
                    "renewable": true,
                    "ttl": 45
                }
            }),
        ),
    ])
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_millis(50),
    )
    .unwrap();
    let lease_dir = private_tempdir().unwrap();
    let registry = SecretLeaseRegistry::open_state_dir(lease_dir.path()).unwrap();
    let (authority, issuer, _authority_dir) = authority().unwrap();

    let issue = issue_request("issue-reconcile");
    let issue_grant = grant(
        &issuer,
        client.dynamic_secret_lease_binding(&issue).unwrap(),
        "issue-reconcile-grant",
        7,
    )
    .unwrap();
    client
        .request_secret_lease(&registry, &authority, &issue_grant, &issue, |_| Ok(()))
        .await
        .unwrap();

    let renew = LeaseRenewRequest {
        subject_id: issue.subject_id.clone(),
        consumer_id: issue.consumer_id.clone(),
        operation_id: "renew-timeout".into(),
        namespace: issue.namespace.clone(),
        lease_id: lease_id.into(),
        increment_seconds: 90,
    };
    let renew_grant = grant(
        &issuer,
        client.lease_renew_binding(&renew).unwrap(),
        "renew-timeout-grant",
        8,
    )
    .unwrap();
    assert_eq!(
        client
            .renew_secret_lease(&registry, &authority, &renew_grant, &renew)
            .await,
        Err(SecretLeaseError::OutcomeIndeterminate)
    );
    assert_eq!(
        registry.lease(lease_id).unwrap().unwrap().state,
        SecretLeaseState::RenewOutcomeUnknown
    );

    let repeat_grant = grant(
        &issuer,
        client.lease_renew_binding(&renew).unwrap(),
        "renew-repeat-grant",
        9,
    )
    .unwrap();
    assert_eq!(
        client
            .renew_secret_lease(&registry, &authority, &repeat_grant, &renew)
            .await,
        Err(SecretLeaseError::LeaseNotActive)
    );

    let reconcile = LeaseReconcileRequest {
        subject_id: issue.subject_id,
        consumer_id: issue.consumer_id,
        operation_id: "lookup-1".into(),
        target_operation_id: "renew-timeout".into(),
        namespace: issue.namespace,
        lease_id: lease_id.into(),
    };
    let reconcile_grant = grant(
        &issuer,
        client.lease_reconcile_binding(&reconcile).unwrap(),
        "lookup-grant",
        10,
    )
    .unwrap();
    let reconciled = client
        .reconcile_secret_lease(&registry, &authority, &reconcile_grant, &reconcile)
        .await
        .unwrap();
    assert_eq!(reconciled.state, SecretLeaseState::Active);
    assert_eq!(reconciled.lease_duration_seconds, 45);
    assert_eq!(reconciled.last_operation_id, "lookup-1");
    assert_eq!(
        registry
            .operation("renew-timeout")
            .unwrap()
            .unwrap()
            .state,
        LeaseOperationState::Reconciled
    );
    assert_eq!(
        registry.operation("lookup-1").unwrap().unwrap().state,
        LeaseOperationState::Completed
    );

    let requests = task.await.unwrap().unwrap();
    assert_eq!(requests.len(), 3, "renew was never retried automatically");
    assert!(requests[2]
        .to_ascii_lowercase()
        .starts_with("post /v1/sys/leases/lookup http/1.1\r\n"));
}

#[tokio::test]
async fn independently_observed_unknown_issue_is_revoke_required_and_not_lookup_activatable() {
    let lease_id = "database/creds/readonly/lost-ack";
    let (endpoint, ca, task) = server(vec![TestResponse::delayed(
        200,
        serde_json::json!({
            "lease_id": lease_id,
            "renewable": true,
            "lease_duration": 60,
            "data": {"username":"lost-user","password":"lost-password"}
        }),
        Duration::from_millis(150),
    )])
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_millis(50),
    )
    .unwrap();
    let lease_dir = private_tempdir().unwrap();
    let registry = SecretLeaseRegistry::open_state_dir(lease_dir.path()).unwrap();
    let (authority, issuer, _authority_dir) = authority().unwrap();

    let issue = issue_request("issue-lost-ack");
    let issue_grant = grant(
        &issuer,
        client.dynamic_secret_lease_binding(&issue).unwrap(),
        "lost-ack-grant",
        11,
    )
    .unwrap();
    assert_eq!(
        client
            .request_secret_lease(&registry, &authority, &issue_grant, &issue, |_| {
                panic!("unknown issue must not deliver")
            })
            .await,
        Err(SecretLeaseError::OutcomeIndeterminate)
    );
    task.await.unwrap().unwrap();

    let resolution = UnknownIssueResolutionRequest {
        subject_id: issue.subject_id.clone(),
        consumer_id: issue.consumer_id.clone(),
        issue_operation_id: issue.operation_id.clone(),
        resolution_operation_id: "resolve-lost-ack".into(),
        resolution: UnknownIssueResolution::LeaseObserved {
            lease_id: lease_id.into(),
            lease_duration_seconds: 45,
            renewable: true,
        },
    };
    let resolution_grant = grant(
        &issuer,
        client
            .unknown_issue_resolution_binding(&resolution)
            .unwrap(),
        "resolve-lost-ack-grant",
        12,
    )
    .unwrap();
    let adopted = client
        .resolve_unknown_secret_issue(&registry, &authority, &resolution_grant, &resolution)
        .unwrap()
        .unwrap();
    assert_eq!(adopted.state, SecretLeaseState::RevokeRequired);
    assert_ne!(adopted.state, SecretLeaseState::Active);
    assert_eq!(
        registry
            .operation("issue-lost-ack")
            .unwrap()
            .unwrap()
            .state,
        LeaseOperationState::Completed
    );

    let illegal_lookup = LeaseReconcileRequest {
        subject_id: issue.subject_id,
        consumer_id: issue.consumer_id,
        operation_id: "illegal-orphan-lookup".into(),
        target_operation_id: "issue-lost-ack".into(),
        namespace: issue.namespace,
        lease_id: lease_id.into(),
    };
    let illegal_grant = grant(
        &issuer,
        client.lease_reconcile_binding(&illegal_lookup).unwrap(),
        "illegal-orphan-lookup-grant",
        13,
    )
    .unwrap();
    assert_eq!(
        client
            .reconcile_secret_lease(&registry, &authority, &illegal_grant, &illegal_lookup)
            .await,
        Err(SecretLeaseError::ReconciliationRequired)
    );
    assert_eq!(
        registry.lease(lease_id).unwrap().unwrap().state,
        SecretLeaseState::RevokeRequired
    );
}
