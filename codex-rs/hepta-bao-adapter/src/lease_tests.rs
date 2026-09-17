use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio_rustls::TlsAcceptor;

type TestError = Box<dyn std::error::Error + Send + Sync>;

const USERNAME: &str = "lease-user";
const PASSWORD: &str = "fixture-only-dynamic-password";
const LEASE_ID: &str = "database/creds/readonly/lease-001";

struct ScriptedResponse {
    status: u16,
    body: String,
    body_delay: Duration,
}

async fn scripted_server(
    scripts: Vec<ScriptedResponse>,
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
        let mut observed = Vec::new();
        for scripted in scripts {
            let (socket, _) = listener.accept().await?;
            let mut stream = acceptor.accept(socket).await?;
            let mut request = Vec::new();
            while !request.ends_with(b"\r\n\r\n") && request.len() < 64 * 1024 {
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
            let mut body = vec![0_u8; content_length];
            if content_length > 0 {
                stream.read_exact(&mut body).await?;
                request.extend_from_slice(&body);
            }
            observed.push(String::from_utf8(request)?);
            let headers = format!(
                "HTTP/1.1 {} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                scripted.status,
                scripted.body.len()
            );
            stream.write_all(headers.as_bytes()).await?;
            if !scripted.body_delay.is_zero() {
                tokio::time::sleep(scripted.body_delay).await;
            }
            let _ = stream.write_all(scripted.body.as_bytes()).await;
            let _ = stream.shutdown().await;
        }
        Ok(observed)
    });
    Ok((endpoint, pem, task))
}

fn dynamic_body(ttl: u64) -> String {
    serde_json::json!({
        "request_id": "provider-request",
        "lease_id": LEASE_ID,
        "renewable": true,
        "lease_duration": ttl,
        "data": {"username": USERNAME, "password": PASSWORD},
        "warnings": null
    })
    .to_string()
}

fn renew_body(ttl: u64) -> String {
    serde_json::json!({
        "lease_id": LEASE_ID,
        "renewable": true,
        "lease_duration": ttl
    })
    .to_string()
}

fn lookup_body(ttl: u64) -> String {
    serde_json::json!({
        "data": {"id": LEASE_ID, "renewable": true, "ttl": ttl}
    })
    .to_string()
}

fn issue_request(operation_id: &str) -> SecretLeaseRequest {
    SecretLeaseRequest {
        subject_id: "agent-one".into(),
        consumer_id: "model-provider".into(),
        operation_id: operation_id.into(),
        namespace: "team/one".into(),
        mount: "database".into(),
        path: "creds/readonly".into(),
        method: BaoDynamicMethod::Post,
        parameters: BTreeMap::from([("ttl".into(), "60s".into())]),
    }
}

fn lease_dir() -> tempfile::TempDir {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    directory
}

fn authority() -> (FinalUseAuthority, SigningKey, tempfile::TempDir) {
    let issuer = SigningKey::from_bytes(&[83; 32]);
    let directory = lease_dir();
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "lease-owner".into(),
        issuer.verifying_key().to_bytes(),
        codex_hepta_contracts::FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )
    .unwrap();
    (authority, issuer, directory)
}

fn signed(
    issuer: &SigningKey,
    binding: FinalUseBinding,
    nonce_byte: u8,
    grant_id: &str,
) -> SignedFinalUseGrant {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let grant = codex_hepta_contracts::FinalUseGrant {
        schema_version: 1,
        signer_id: "lease-owner".into(),
        authority_epoch: 7,
        grant_id: grant_id.into(),
        nonce: [nonce_byte; 32],
        binding,
        not_before_unix_ms: now - 1000,
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

#[tokio::test]
async fn dynamic_issue_delivers_only_through_enrolled_borrowed_view_and_persists_metadata() {
    let (endpoint, ca, server) = scripted_server(vec![ScriptedResponse {
        status: 200,
        body: dynamic_body(60),
        body_delay: Duration::ZERO,
    }])
    .await
    .unwrap();
    let client = BaoClient::new_for_destination(
        &endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture-provider-token".into()).unwrap(),
        Duration::from_secs(2),
        "provider:heptabao:node-a".into(),
    )
    .unwrap();
    let state = lease_dir();
    let manager = BaoLeaseManager::open(client, state.path()).unwrap();
    let (authority, issuer, _authority_state) = authority();
    let request = issue_request("issue-001");
    let grant = signed(&issuer, manager.issue_binding(&request).unwrap(), 1, "issue-001");
    let mut callback_seen = false;
    let consumer = manager
        .enroll_consumer("model-provider".into(), |view: &SecretLeaseView<'_>| {
            assert_eq!(view.get("username"), Some(USERNAME));
            assert_eq!(view.get("password"), Some(PASSWORD));
            assert_eq!(view.field_count(), 2);
            callback_seen = true;
            Ok(())
        })
        .unwrap();
    let receipt = manager
        .request_secret_lease(&authority, &grant, &request, consumer)
        .await
        .unwrap();
    assert!(callback_seen);
    assert_eq!(receipt.metadata.state, SecretLeaseState::Active);
    assert_eq!(receipt.metadata.lease_id.as_deref(), Some(LEASE_ID));
    assert_eq!(receipt.metadata.generation, 1);
    assert!(!receipt.contains_raw_secret);
    let serialized = serde_json::to_string(&receipt).unwrap();
    assert!(!serialized.contains(PASSWORD));
    assert!(!serialized.contains(USERNAME));
    let observed = server.await.unwrap().unwrap();
    assert_eq!(observed.len(), 1);
    let wire = observed[0].to_ascii_lowercase();
    assert!(wire.starts_with("post /v1/database/creds/readonly http/1.1\r\n"));
    assert!(wire.contains("x-vault-token: fixture-provider-token\r\n"));
    assert!(wire.contains("x-vault-namespace: team/one\r\n"));

    drop(manager);
    let reopened_client = BaoClient::new_for_destination(
        &endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture-provider-token".into()).unwrap(),
        Duration::from_secs(2),
        "provider:heptabao:node-a".into(),
    )
    .unwrap();
    let reopened = BaoLeaseManager::open(reopened_client, state.path()).unwrap();
    assert_eq!(
        reopened.metadata_by_lease(LEASE_ID).unwrap().state,
        SecretLeaseState::Active
    );
}

#[tokio::test]
async fn lost_issue_ack_is_indeterminate_and_same_operation_never_blindly_reissues() {
    let (endpoint, ca, server) = scripted_server(vec![ScriptedResponse {
        status: 200,
        body: dynamic_body(60),
        body_delay: Duration::from_millis(120),
    }])
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture".into()).unwrap(),
        Duration::from_millis(40),
    )
    .unwrap();
    let state = lease_dir();
    let manager = BaoLeaseManager::open(client, state.path()).unwrap();
    let (authority, issuer, _authority_state) = authority();
    let request = issue_request("issue-timeout");
    let binding = manager.issue_binding(&request).unwrap();
    let grant = signed(&issuer, binding.clone(), 2, "issue-timeout");
    let consumer = manager
        .enroll_consumer("model-provider".into(), |_view: &SecretLeaseView<'_>| {
            panic!("timed-out issue must not deliver")
        })
        .unwrap();
    assert!(matches!(
        manager
            .request_secret_lease(&authority, &grant, &request, consumer)
            .await,
        Err(SecretLeaseError::ProviderEffectIndeterminate {
            lease_id: None,
            ..
        })
    ));
    assert_eq!(
        manager
            .metadata_by_operation("issue-timeout")
            .unwrap()
            .state,
        SecretLeaseState::IndeterminateIssue
    );
    let retry_grant = signed(&issuer, binding, 3, "issue-timeout-retry");
    let retry_consumer = manager
        .enroll_consumer("model-provider".into(), |_view: &SecretLeaseView<'_>| Ok(()))
        .unwrap();
    assert_eq!(
        manager
            .request_secret_lease(&authority, &retry_grant, &request, retry_consumer)
            .await,
        Err(SecretLeaseError::ReconciliationRequired)
    );
    server.await.unwrap().unwrap();
}

#[tokio::test]
async fn renew_and_revoke_uncertainty_reconcile_against_provider_truth() {
    let scripts = vec![
        ScriptedResponse {
            status: 200,
            body: dynamic_body(60),
            body_delay: Duration::ZERO,
        },
        ScriptedResponse {
            status: 200,
            body: renew_body(120),
            body_delay: Duration::from_millis(120),
        },
        ScriptedResponse {
            status: 200,
            body: lookup_body(120),
            body_delay: Duration::ZERO,
        },
        ScriptedResponse {
            status: 204,
            body: String::new(),
            body_delay: Duration::from_millis(120),
        },
        ScriptedResponse {
            status: 404,
            body: "{}".into(),
            body_delay: Duration::ZERO,
        },
    ];
    let (endpoint, ca, server) = scripted_server(scripts).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture".into()).unwrap(),
        Duration::from_millis(40),
    )
    .unwrap();
    let state = lease_dir();
    let manager = BaoLeaseManager::open(client, state.path()).unwrap();
    let (authority, issuer, _authority_state) = authority();

    let issue = issue_request("issue-lifecycle");
    let issue_grant = signed(&issuer, manager.issue_binding(&issue).unwrap(), 4, "issue-lifecycle");
    let consumer = manager
        .enroll_consumer("model-provider".into(), |_view: &SecretLeaseView<'_>| Ok(()))
        .unwrap();
    manager
        .request_secret_lease(&authority, &issue_grant, &issue, consumer)
        .await
        .unwrap();

    let renew = RenewSecretLeaseRequest {
        subject_id: "agent-one".into(),
        consumer_id: "model-provider".into(),
        operation_id: "renew-001".into(),
        lease_id: LEASE_ID.into(),
        increment_seconds: 120,
    };
    let renew_grant = signed(&issuer, manager.renew_binding(&renew).unwrap(), 5, "renew-001");
    assert!(matches!(
        manager
            .renew_secret_lease(&authority, &renew_grant, &renew)
            .await,
        Err(SecretLeaseError::ProviderEffectIndeterminate { .. })
    ));
    assert_eq!(
        manager.metadata_by_lease(LEASE_ID).unwrap().state,
        SecretLeaseState::IndeterminateRenew
    );
    tokio::time::sleep(Duration::from_millis(140)).await;
    let reconcile = ReconcileSecretLeaseRequest {
        subject_id: "agent-one".into(),
        consumer_id: "model-provider".into(),
        operation_id: "reconcile-renew".into(),
        lease_id: LEASE_ID.into(),
    };
    let reconcile_grant = signed(
        &issuer,
        manager.reconcile_binding(&reconcile).unwrap(),
        6,
        "reconcile-renew",
    );
    let observation = manager
        .reconcile_secret_lease(&authority, &reconcile_grant, &reconcile)
        .await
        .unwrap();
    assert!(observation.provider_present);
    assert_eq!(observation.metadata.state, SecretLeaseState::Active);
    assert_eq!(observation.metadata.generation, 2);

    let revoke = RevokeSecretLeaseRequest {
        subject_id: "agent-one".into(),
        consumer_id: "model-provider".into(),
        operation_id: "revoke-001".into(),
        lease_id: LEASE_ID.into(),
    };
    let revoke_grant = signed(&issuer, manager.revoke_binding(&revoke).unwrap(), 7, "revoke-001");
    assert!(matches!(
        manager
            .revoke_secret_lease(&authority, &revoke_grant, &revoke)
            .await,
        Err(SecretLeaseError::ProviderEffectIndeterminate { .. })
    ));
    assert_eq!(
        manager.metadata_by_lease(LEASE_ID).unwrap().state,
        SecretLeaseState::IndeterminateRevoke
    );
    tokio::time::sleep(Duration::from_millis(140)).await;
    let reconcile = ReconcileSecretLeaseRequest {
        subject_id: "agent-one".into(),
        consumer_id: "model-provider".into(),
        operation_id: "reconcile-revoke".into(),
        lease_id: LEASE_ID.into(),
    };
    let reconcile_grant = signed(
        &issuer,
        manager.reconcile_binding(&reconcile).unwrap(),
        8,
        "reconcile-revoke",
    );
    let observation = manager
        .reconcile_secret_lease(&authority, &reconcile_grant, &reconcile)
        .await
        .unwrap();
    assert!(!observation.provider_present);
    assert_eq!(observation.metadata.state, SecretLeaseState::Revoked);

    let observed = server.await.unwrap().unwrap();
    assert_eq!(observed.len(), 5);
    assert!(observed[1].starts_with("POST /v1/sys/leases/renew HTTP/1.1\r\n"));
    assert!(observed[2].starts_with("POST /v1/sys/leases/lookup HTTP/1.1\r\n"));
    assert!(observed[3].starts_with("POST /v1/sys/leases/revoke HTTP/1.1\r\n"));
    assert!(observed[4].starts_with("POST /v1/sys/leases/lookup HTTP/1.1\r\n"));
}

#[tokio::test]
async fn lost_issue_response_can_only_be_adopted_as_orphaned_after_explicit_provider_lookup() {
    let scripts = vec![
        ScriptedResponse {
            status: 200,
            body: dynamic_body(60),
            body_delay: Duration::from_millis(120),
        },
        ScriptedResponse {
            status: 200,
            body: lookup_body(55),
            body_delay: Duration::ZERO,
        },
    ];
    let (endpoint, ca, server) = scripted_server(scripts).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture".into()).unwrap(),
        Duration::from_millis(40),
    )
    .unwrap();
    let state = lease_dir();
    let manager = BaoLeaseManager::open(client, state.path()).unwrap();
    let (authority, issuer, _authority_state) = authority();
    let request = issue_request("issue-orphan");
    let issue_grant = signed(&issuer, manager.issue_binding(&request).unwrap(), 9, "issue-orphan");
    let consumer = manager
        .enroll_consumer("model-provider".into(), |_view: &SecretLeaseView<'_>| {
            panic!("lost response must not expose secret")
        })
        .unwrap();
    assert!(matches!(
        manager
            .request_secret_lease(&authority, &issue_grant, &request, consumer)
            .await,
        Err(SecretLeaseError::ProviderEffectIndeterminate { .. })
    ));
    tokio::time::sleep(Duration::from_millis(140)).await;
    let reconcile = ReconcileIndeterminateIssueRequest {
        subject_id: "agent-one".into(),
        consumer_id: "model-provider".into(),
        operation_id: "adopt-orphan".into(),
        issue_operation_id: "issue-orphan".into(),
        observed_provider_lease_id: LEASE_ID.into(),
    };
    let grant = signed(
        &issuer,
        manager.reconcile_issue_binding(&reconcile).unwrap(),
        10,
        "adopt-orphan",
    );
    let observation = manager
        .reconcile_indeterminate_issue(&authority, &grant, &reconcile)
        .await
        .unwrap();
    assert!(observation.provider_present);
    assert_eq!(observation.metadata.state, SecretLeaseState::Orphaned);
    assert_eq!(observation.metadata.lease_id.as_deref(), Some(LEASE_ID));
    server.await.unwrap().unwrap();
}

#[test]
fn destination_sharding_makes_final_use_grants_non_portable_between_active_replicas() {
    let certified = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()]).unwrap();
    let ca = certified.cert.pem();
    let endpoint = "https://localhost:65530/";
    let client_a = BaoClient::new_for_destination(
        endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(1),
        "provider:heptabao:node-a".into(),
    )
    .unwrap();
    let client_b = BaoClient::new_for_destination(
        endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(1),
        "provider:heptabao:node-b".into(),
    )
    .unwrap();
    let state_a = lease_dir();
    let state_b = lease_dir();
    let manager_a = BaoLeaseManager::open(client_a, state_a.path()).unwrap();
    let manager_b = BaoLeaseManager::open(client_b, state_b.path()).unwrap();
    let request = issue_request("sharded-issue");
    let binding_a = manager_a.issue_binding(&request).unwrap();
    let binding_b = manager_b.issue_binding(&request).unwrap();
    assert_ne!(binding_a, binding_b);
    let (authority, issuer, _authority_state) = authority();
    let grant_a = signed(&issuer, binding_a, 11, "sharded-issue");
    assert_eq!(
        authority.claim(&grant_a, &binding_b).unwrap_err(),
        FinalUseError::BindingMismatch
    );
}

#[test]
fn lease_store_is_destination_bound_and_reserved_control_mounts_are_rejected() {
    let certified = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()]).unwrap();
    let ca = certified.cert.pem();
    let endpoint = "https://localhost:65530/";
    let state = lease_dir();
    let client_a = BaoClient::new_for_destination(
        endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(1),
        "provider:heptabao:node-a".into(),
    )
    .unwrap();
    let manager_a = BaoLeaseManager::open(client_a, state.path()).unwrap();
    let mut reserved = issue_request("reserved");
    reserved.mount = "sys".into();
    assert_eq!(
        manager_a.issue_binding(&reserved),
        Err(SecretLeaseError::InvalidRequest)
    );
    drop(manager_a);
    let client_b = BaoClient::new_for_destination(
        endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(1),
        "provider:heptabao:node-b".into(),
    )
    .unwrap();
    assert_eq!(
        BaoLeaseManager::open(client_b, state.path()).unwrap_err(),
        SecretLeaseError::InvalidState
    );
}
