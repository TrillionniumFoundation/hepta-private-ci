use super::*;

use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio_rustls::TlsAcceptor;

type TestError = Box<dyn std::error::Error + Send + Sync>;

const PROVIDER_LEASE_ID: &str = "database/creds/read-only/lease-123";
const USERNAME: &str = "dynamic-user";
const PASSWORD: &str = "dynamic-password";

struct TestResponse {
    status: u16,
    body: String,
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
        let mut observed = Vec::new();
        for response in responses {
            let (socket, _) = listener.accept().await?;
            let mut stream = acceptor.accept(socket).await?;
            let mut headers = Vec::new();
            while !headers.ends_with(b"\r\n\r\n") && headers.len() < 32 * 1024 {
                headers.push(stream.read_u8().await?);
            }
            let header_text = String::from_utf8(headers)?;
            let content_length = header_text
                .lines()
                .find_map(|line| {
                    let (name, value) = line.split_once(':')?;
                    if name.eq_ignore_ascii_case("content-length") {
                        value.trim().parse::<usize>().ok()
                    } else {
                        None
                    }
                })
                .unwrap_or(0);
            let mut body = vec![0; content_length];
            if content_length != 0 {
                stream.read_exact(&mut body).await?;
            }
            observed.push(format!("{header_text}{}", String::from_utf8_lossy(&body)));
            let response_body = response.body.into_bytes();
            let status_text = match response.status {
                200 => "OK",
                204 => "No Content",
                403 => "Forbidden",
                404 => "Not Found",
                500 => "Internal Server Error",
                _ => "Test",
            };
            let wire = format!(
                "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                response.status,
                status_text,
                response_body.len()
            );
            stream.write_all(wire.as_bytes()).await?;
            if !response_body.is_empty() {
                stream.write_all(&response_body).await?;
            }
        }
        Ok::<Vec<String>, TestError>(observed)
    });
    Ok((endpoint, pem, task))
}

fn issue_body() -> String {
    serde_json::json!({
        "lease_id": PROVIDER_LEASE_ID,
        "renewable": true,
        "lease_duration": 120,
        "data": {
            "username": USERNAME,
            "password": PASSWORD,
        }
    })
    .to_string()
}

fn renew_body(ttl: u64) -> String {
    serde_json::json!({
        "lease_id": PROVIDER_LEASE_ID,
        "renewable": true,
        "lease_duration": ttl,
    })
    .to_string()
}

fn lookup_body(ttl: u64) -> String {
    serde_json::json!({
        "data": {
            "id": PROVIDER_LEASE_ID,
            "renewable": true,
            "ttl": ttl,
        }
    })
    .to_string()
}

fn issue_request(operation_id: &str) -> BaoDynamicLeaseRequest {
    BaoDynamicLeaseRequest {
        subject_id: "agent-one".into(),
        consumer_id: "model-provider".into(),
        namespace: "team/one".into(),
        mount: "database".into(),
        path: "creds/read-only".into(),
        operation_id: operation_id.into(),
        required_fields: vec!["username".into(), "password".into()],
    }
}

struct AuthorityFixture {
    issuer: SigningKey,
    authority: FinalUseAuthority,
    _directory: tempfile::TempDir,
}

fn authority_fixture() -> Result<AuthorityFixture, TestError> {
    let issuer = SigningKey::from_bytes(&[83; 32]);
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
    Ok(AuthorityFixture {
        issuer,
        authority,
        _directory: directory,
    })
}

fn sign_grant(
    fixture: &AuthorityFixture,
    binding: FinalUseBinding,
    grant_id: &str,
    nonce_byte: u8,
) -> Result<SignedFinalUseGrant, TestError> {
    let now = now_ms()?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "owner".into(),
        authority_epoch: 9,
        grant_id: grant_id.into(),
        nonce: [nonce_byte; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now.saturating_add(30_000),
    };
    let signature = fixture
        .issuer
        .sign(&grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    Ok(SignedFinalUseGrant { grant, signature })
}

fn registry_fixture() -> Result<(SecretLeaseRegistry, tempfile::TempDir), TestError> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let registry = SecretLeaseRegistry::open_state_dir(directory.path())?;
    Ok((registry, directory))
}

fn client(endpoint: &str, pem: &str) -> Result<BaoClient, TestError> {
    Ok(BaoClient::new(
        endpoint,
        pem.as_bytes(),
        crate::BaoToken::new("fixture-provider-token".into())?,
        Duration::from_secs(2),
    )?)
}

#[tokio::test]
async fn dynamic_issue_delivers_only_to_callback_and_replay_does_not_reissue() {
    let (endpoint, pem, task) = server(vec![TestResponse {
        status: 200,
        body: issue_body(),
    }])
    .await
    .unwrap();
    let client = client(&endpoint, &pem).unwrap();
    let (registry, directory) = registry_fixture().unwrap();
    let authority = authority_fixture().unwrap();
    let request = issue_request("issue-one");
    let grant = sign_grant(
        &authority,
        client.dynamic_lease_binding(&request).unwrap(),
        "grant-issue-one",
        1,
    )
    .unwrap();

    let mut delivered = false;
    let receipt = client
        .request_secret_lease(
            &registry,
            &authority.authority,
            &grant,
            &request,
            |secret| {
                assert_eq!(secret.get("username"), Some(USERNAME.as_bytes()));
                assert_eq!(secret.get("password"), Some(PASSWORD.as_bytes()));
                assert_eq!(secret.get("not-requested"), None);
                delivered = true;
                Ok(())
            },
        )
        .await
        .unwrap();
    assert!(delivered);
    assert_eq!(receipt.lease.state, SecretLeaseState::Active);
    assert_eq!(receipt.delivery, LeaseDelivery::Delivered);

    let encoded = serde_json::to_string(&receipt).unwrap();
    assert!(!encoded.contains(USERNAME));
    assert!(!encoded.contains(PASSWORD));
    assert!(!encoded.contains(PROVIDER_LEASE_ID));
    let journal = std::fs::read_to_string(directory.path().join("leases.journal")).unwrap();
    assert!(!journal.contains(USERNAME));
    assert!(!journal.contains(PASSWORD));

    let replay = client
        .request_secret_lease(&registry, &authority.authority, &grant, &request, |_| {
            panic!("completed issue must never redeliver secret bytes")
        })
        .await
        .unwrap();
    assert_eq!(replay.delivery, LeaseDelivery::AlreadyIssuedNoRedelivery);
    assert_eq!(
        replay.lease.lease_handle_sha256,
        receipt.lease.lease_handle_sha256
    );

    let requests = task.await.unwrap().unwrap();
    assert_eq!(requests.len(), 1);
    assert!(requests[0].starts_with("GET /v1/database/creds/read-only HTTP/1.1\r\n"));
    assert!(
        requests[0]
            .to_ascii_lowercase()
            .contains("x-vault-namespace: team/one\r\n")
    );
}

#[tokio::test]
async fn dynamic_lease_renews_and_revokes_with_provider_identity_hidden() {
    let (endpoint, pem, task) = server(vec![
        TestResponse {
            status: 200,
            body: issue_body(),
        },
        TestResponse {
            status: 200,
            body: renew_body(240),
        },
        TestResponse {
            status: 204,
            body: String::new(),
        },
    ])
    .await
    .unwrap();
    let client = client(&endpoint, &pem).unwrap();
    let (registry, _directory) = registry_fixture().unwrap();
    let authority = authority_fixture().unwrap();
    let issue = issue_request("issue-lifecycle");
    let issue_grant = sign_grant(
        &authority,
        client.dynamic_lease_binding(&issue).unwrap(),
        "grant-issue-lifecycle",
        2,
    )
    .unwrap();
    let issued = client
        .request_secret_lease(
            &registry,
            &authority.authority,
            &issue_grant,
            &issue,
            |_| Ok(()),
        )
        .await
        .unwrap();

    let renew = BaoRenewLeaseRequest {
        subject_id: issue.subject_id.clone(),
        consumer_id: issue.consumer_id.clone(),
        namespace: issue.namespace.clone(),
        lease_handle_sha256: issued.lease.lease_handle_sha256,
        operation_id: "renew-one".into(),
        increment_seconds: 60,
    };
    let renew_grant = sign_grant(
        &authority,
        client.renew_lease_binding(&renew).unwrap(),
        "grant-renew-one",
        3,
    )
    .unwrap();
    let renewed = client
        .renew_secret_lease(&registry, &authority.authority, &renew_grant, &renew)
        .await
        .unwrap();
    assert_eq!(renewed.lease.state, SecretLeaseState::Active);
    assert_eq!(renewed.lease.generation, 2);

    let revoke = BaoRevokeLeaseRequest {
        subject_id: issue.subject_id,
        consumer_id: issue.consumer_id,
        namespace: issue.namespace,
        lease_handle_sha256: issued.lease.lease_handle_sha256,
        operation_id: "revoke-one".into(),
    };
    let revoke_grant = sign_grant(
        &authority,
        client.revoke_lease_binding(&revoke).unwrap(),
        "grant-revoke-one",
        4,
    )
    .unwrap();
    let revoked = client
        .revoke_secret_lease(&registry, &authority.authority, &revoke_grant, &revoke)
        .await
        .unwrap();
    assert_eq!(revoked.lease.state, SecretLeaseState::Revoked);

    let replay = client
        .revoke_secret_lease(&registry, &authority.authority, &revoke_grant, &revoke)
        .await
        .unwrap();
    assert!(replay.idempotent_replay);

    let requests = task.await.unwrap().unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests[1].starts_with("POST /v1/sys/leases/renew HTTP/1.1\r\n"));
    assert!(requests[1].contains(PROVIDER_LEASE_ID));
    assert!(requests[1].contains("\"increment\":60"));
    assert!(requests[2].starts_with("POST /v1/sys/leases/revoke HTTP/1.1\r\n"));
    assert!(requests[2].contains("\"sync\":true"));
}

#[tokio::test]
async fn unknown_issue_blocks_new_operation_until_signed_absence_resolution() {
    let (endpoint, pem, task) = server(vec![TestResponse {
        status: 500,
        body: "{}".into(),
    }])
    .await
    .unwrap();
    let client = client(&endpoint, &pem).unwrap();
    let (registry, _directory) = registry_fixture().unwrap();
    let authority = authority_fixture().unwrap();
    let request = issue_request("issue-unknown");
    let grant = sign_grant(
        &authority,
        client.dynamic_lease_binding(&request).unwrap(),
        "grant-issue-unknown",
        5,
    )
    .unwrap();
    assert_eq!(
        client
            .request_secret_lease(
                &registry,
                &authority.authority,
                &grant,
                &request,
                |_| Ok(()),
            )
            .await,
        Err(BaoLeaseError::ProviderUnavailable)
    );
    let unresolved = registry
        .lookup_by_operation_id("issue-unknown")
        .unwrap()
        .unwrap();
    assert_eq!(unresolved.state, SecretLeaseState::ReconciliationRequired);
    assert_eq!(
        unresolved.reconciliation_reason,
        Some(ReconciliationReason::IssueOutcomeUnknown)
    );

    let second = issue_request("issue-second");
    let second_fields = validate_issue_request(&second).unwrap();
    let second_digest = issue_request_digest(&client, &second, &second_fields).unwrap();
    assert!(matches!(
        registry.prepare_issue(&second, second_digest, second_fields),
        Err(LeaseRegistryError::UnresolvedLeaseExists)
    ));

    let resolution = BaoUnknownIssueResolutionRequest {
        subject_id: request.subject_id,
        consumer_id: request.consumer_id,
        namespace: request.namespace,
        lease_handle_sha256: unresolved.lease_handle_sha256,
        operation_id: "resolve-unknown".into(),
        evidence_sha256: Digest32::of_bytes(b"trusted-provider-audit").into_array(),
        resolution: BaoUnknownIssueResolution::ConfirmedAbsent,
    };
    let resolution_grant = sign_grant(
        &authority,
        client
            .unknown_issue_resolution_binding(&resolution)
            .unwrap(),
        "grant-resolve-unknown",
        6,
    )
    .unwrap();
    let resolved = client
        .resolve_unknown_issue(
            &registry,
            &authority.authority,
            &resolution_grant,
            &resolution,
        )
        .unwrap();
    assert_eq!(resolved.lease.state, SecretLeaseState::Failed);

    let second_fields = validate_issue_request(&second).unwrap();
    let second_digest = issue_request_digest(&client, &second, &second_fields).unwrap();
    assert!(matches!(
        registry.prepare_issue(&second, second_digest, second_fields),
        Ok(PrepareIssue::New)
    ));
    assert_eq!(task.await.unwrap().unwrap().len(), 1);
}

#[tokio::test]
async fn unknown_renew_is_reconciled_by_provider_lookup_without_blind_retry() {
    let (endpoint, pem, task) = server(vec![
        TestResponse {
            status: 200,
            body: issue_body(),
        },
        TestResponse {
            status: 500,
            body: "{}".into(),
        },
        TestResponse {
            status: 200,
            body: lookup_body(300),
        },
    ])
    .await
    .unwrap();
    let client = client(&endpoint, &pem).unwrap();
    let (registry, _directory) = registry_fixture().unwrap();
    let authority = authority_fixture().unwrap();
    let issue = issue_request("issue-before-renew");
    let issue_grant = sign_grant(
        &authority,
        client.dynamic_lease_binding(&issue).unwrap(),
        "grant-issue-before-renew",
        7,
    )
    .unwrap();
    let issued = client
        .request_secret_lease(
            &registry,
            &authority.authority,
            &issue_grant,
            &issue,
            |_| Ok(()),
        )
        .await
        .unwrap();
    let renew = BaoRenewLeaseRequest {
        subject_id: issue.subject_id.clone(),
        consumer_id: issue.consumer_id.clone(),
        namespace: issue.namespace.clone(),
        lease_handle_sha256: issued.lease.lease_handle_sha256,
        operation_id: "renew-unknown".into(),
        increment_seconds: 60,
    };
    let renew_grant = sign_grant(
        &authority,
        client.renew_lease_binding(&renew).unwrap(),
        "grant-renew-unknown",
        8,
    )
    .unwrap();
    assert_eq!(
        client
            .renew_secret_lease(&registry, &authority.authority, &renew_grant, &renew)
            .await,
        Err(BaoLeaseError::ProviderUnavailable)
    );
    let unknown = registry
        .lookup(issued.lease.lease_handle_sha256)
        .unwrap()
        .unwrap();
    assert_eq!(
        unknown.reconciliation_reason,
        Some(ReconciliationReason::RenewOutcomeUnknown)
    );

    let reconcile = BaoReconcileLeaseRequest {
        subject_id: issue.subject_id,
        consumer_id: issue.consumer_id,
        namespace: issue.namespace,
        lease_handle_sha256: issued.lease.lease_handle_sha256,
        operation_id: "reconcile-renew".into(),
    };
    let reconcile_grant = sign_grant(
        &authority,
        client.reconcile_lease_binding(&reconcile).unwrap(),
        "grant-reconcile-renew",
        9,
    )
    .unwrap();
    let reconciled = client
        .reconcile_secret_lease(
            &registry,
            &authority.authority,
            &reconcile_grant,
            &reconcile,
        )
        .await
        .unwrap();
    assert_eq!(reconciled.lease.state, SecretLeaseState::Active);
    assert_eq!(reconciled.lease.generation, 2);
    let requests = task.await.unwrap().unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests[2].starts_with("POST /v1/sys/leases/lookup HTTP/1.1\r\n"));
}

#[tokio::test]
async fn unknown_revoke_becomes_revoked_when_lookup_reports_absent() {
    let (endpoint, pem, task) = server(vec![
        TestResponse {
            status: 200,
            body: issue_body(),
        },
        TestResponse {
            status: 500,
            body: "{}".into(),
        },
        TestResponse {
            status: 404,
            body: "{}".into(),
        },
    ])
    .await
    .unwrap();
    let client = client(&endpoint, &pem).unwrap();
    let (registry, _directory) = registry_fixture().unwrap();
    let authority = authority_fixture().unwrap();
    let issue = issue_request("issue-before-revoke");
    let issue_grant = sign_grant(
        &authority,
        client.dynamic_lease_binding(&issue).unwrap(),
        "grant-issue-before-revoke",
        10,
    )
    .unwrap();
    let issued = client
        .request_secret_lease(
            &registry,
            &authority.authority,
            &issue_grant,
            &issue,
            |_| Ok(()),
        )
        .await
        .unwrap();

    let revoke = BaoRevokeLeaseRequest {
        subject_id: issue.subject_id.clone(),
        consumer_id: issue.consumer_id.clone(),
        namespace: issue.namespace.clone(),
        lease_handle_sha256: issued.lease.lease_handle_sha256,
        operation_id: "revoke-unknown".into(),
    };
    let revoke_grant = sign_grant(
        &authority,
        client.revoke_lease_binding(&revoke).unwrap(),
        "grant-revoke-unknown",
        11,
    )
    .unwrap();
    assert_eq!(
        client
            .revoke_secret_lease(&registry, &authority.authority, &revoke_grant, &revoke)
            .await,
        Err(BaoLeaseError::ProviderUnavailable)
    );

    let reconcile = BaoReconcileLeaseRequest {
        subject_id: issue.subject_id,
        consumer_id: issue.consumer_id,
        namespace: issue.namespace,
        lease_handle_sha256: issued.lease.lease_handle_sha256,
        operation_id: "reconcile-revoke".into(),
    };
    let reconcile_grant = sign_grant(
        &authority,
        client.reconcile_lease_binding(&reconcile).unwrap(),
        "grant-reconcile-revoke",
        12,
    )
    .unwrap();
    let reconciled = client
        .reconcile_secret_lease(
            &registry,
            &authority.authority,
            &reconcile_grant,
            &reconcile,
        )
        .await
        .unwrap();
    assert_eq!(reconciled.lease.state, SecretLeaseState::Revoked);
    assert_eq!(task.await.unwrap().unwrap().len(), 3);
}

#[test]
fn restart_converts_dispatching_issue_to_reconciliation_required() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let registry = SecretLeaseRegistry::open_state_dir(directory.path()).unwrap();
    let request = issue_request("crash-window");
    let request_sha256 = [31; 32];
    assert!(matches!(
        registry.prepare_issue(
            &request,
            request_sha256,
            vec!["password".into(), "username".into()]
        ),
        Ok(PrepareIssue::New)
    ));
    registry
        .mark_dispatching(
            &request.operation_id,
            request_sha256,
            LeaseOperationKind::Issue,
        )
        .unwrap();
    drop(registry);

    let reopened = SecretLeaseRegistry::open_state_dir(directory.path()).unwrap();
    let recovered = reopened
        .lookup_by_operation_id(&request.operation_id)
        .unwrap()
        .unwrap();
    assert_eq!(recovered.state, SecretLeaseState::ReconciliationRequired);
    assert_eq!(
        recovered.reconciliation_reason,
        Some(ReconciliationReason::IssueOutcomeUnknown)
    );
}

#[test]
fn restart_during_callback_recovers_consumer_outcome_unknown() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(
        directory.path(),
        std::fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    let registry = SecretLeaseRegistry::open_state_dir(directory.path()).unwrap();
    let request = issue_request("callback-crash-window");
    let request_sha256 = [41; 32];
    assert!(matches!(
        registry.prepare_issue(
            &request,
            request_sha256,
            vec!["password".into(), "username".into()]
        ),
        Ok(PrepareIssue::New)
    ));
    registry
        .mark_dispatching(
            &request.operation_id,
            request_sha256,
            LeaseOperationKind::Issue,
        )
        .unwrap();
    registry
        .observe_issue_identity(
            &request.operation_id,
            request_sha256,
            Zeroizing::new(PROVIDER_LEASE_ID.to_owned()),
            true,
        )
        .unwrap();
    registry
        .observe_issue_ready(
            &request.operation_id,
            request_sha256,
            true,
            1_000,
            121_000,
            2,
            USERNAME.len() + PASSWORD.len(),
        )
        .unwrap();
    registry
        .mark_delivering(&request.operation_id, request_sha256)
        .unwrap();
    drop(registry);

    let reopened = SecretLeaseRegistry::open_state_dir(directory.path()).unwrap();
    let recovered = reopened
        .lookup_by_operation_id(&request.operation_id)
        .unwrap()
        .unwrap();
    assert_eq!(recovered.state, SecretLeaseState::ReconciliationRequired);
    assert_eq!(
        recovered.reconciliation_reason,
        Some(ReconciliationReason::ConsumerOutcomeUnknown)
    );
}
