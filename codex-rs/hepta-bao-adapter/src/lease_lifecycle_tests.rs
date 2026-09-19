use super::*;

use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use crate::TrustedConsumerRegistry;
use crate::TrustedSecretConsumer;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio_rustls::TlsAcceptor;

type TestError = Box<dyn std::error::Error + Send + Sync>;

#[derive(Clone)]
struct ResponseFixture {
    status: u16,
    body: String,
    delay_body: Duration,
}

async fn server_sequence(
    responses: Vec<ResponseFixture>,
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
        for fixture in responses {
            let (socket, _) = listener.accept().await?;
            let mut stream = acceptor.accept(socket).await?;
            let mut bytes = Vec::new();
            while !bytes.ends_with(b"\r\n\r\n") && bytes.len() < 32 * 1024 {
                bytes.push(stream.read_u8().await?);
            }
            requests.push(String::from_utf8(bytes)?);
            let reason = if fixture.status == 204 { "No Content" } else { "Test" };
            let headers = format!(
                "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                fixture.status,
                reason,
                fixture.body.len()
            );
            stream.write_all(headers.as_bytes()).await?;
            if !fixture.delay_body.is_zero() {
                tokio::time::sleep(fixture.delay_body).await;
            }
            let _ = stream.write_all(fixture.body.as_bytes()).await;
        }
        Ok::<Vec<String>, TestError>(requests)
    });
    Ok((endpoint, pem, task))
}

fn private_tempdir() -> tempfile::TempDir {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    directory
}

fn authority(directory: &std::path::Path) -> FinalUseAuthority {
    let issuer = SigningKey::from_bytes(&[81; 32]);
    FinalUseAuthority::open_state_dir(
        directory,
        "lease-owner".to_owned(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 4,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )
    .unwrap()
}

fn signed(binding: FinalUseBinding, nonce: u8, grant_id: &str) -> SignedFinalUseGrant {
    let issuer = SigningKey::from_bytes(&[81; 32]);
    let now = now_ms().unwrap();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "lease-owner".to_owned(),
        authority_epoch: 4,
        grant_id: grant_id.to_owned(),
        nonce: [nonce; 32],
        binding,
        not_before_unix_ms: now - 1000,
        expires_at_unix_ms: now + 30_000,
    };
    SignedFinalUseGrant {
        signature: issuer.sign(&grant.signing_bytes().unwrap()).to_bytes().to_vec(),
        grant,
    }
}

fn client(
    endpoint: &str,
    ca: &str,
    timeout: Duration,
    observed: Arc<Mutex<Vec<Vec<u8>>>>,
) -> BaoClient {
    let consumer: Arc<dyn TrustedSecretConsumer> = Arc::new(move |secret: &[u8]| {
        observed.lock().unwrap().push(secret.to_vec());
        Ok(())
    });
    let consumers =
        TrustedConsumerRegistry::new([("database-client".to_owned(), consumer)]).unwrap();
    BaoClient::new_with_consumers(
        endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-provider-token".to_owned()).unwrap(),
        timeout,
        consumers,
    )
    .unwrap()
}

fn issue_request() -> BaoDynamicLeaseRequest {
    BaoDynamicLeaseRequest {
        subject_id: "agent-one".to_owned(),
        consumer_id: "database-client".to_owned(),
        operation_id: "issue-one".to_owned(),
        namespace: "team/one".to_owned(),
        mount: "database".to_owned(),
        issue_path: "creds/readonly".to_owned(),
    }
}

#[tokio::test]
async fn issue_renew_revoke_lifecycle_is_durable_and_secret_only_reaches_registry() {
    let issue = serde_json::json!({
        "request_id": "provider-request",
        "lease_id": "database/creds/readonly/lease-one",
        "renewable": true,
        "lease_duration": 60,
        "data": {"username": "fixture-user", "password": "fixture-password"},
        "warnings": null
    })
    .to_string();
    let renew = serde_json::json!({
        "request_id": "provider-renew",
        "lease_id": "database/creds/readonly/lease-one",
        "renewable": true,
        "lease_duration": 120,
        "data": null
    })
    .to_string();
    let (endpoint, ca, task) = server_sequence(vec![
        ResponseFixture {
            status: 200,
            body: issue,
            delay_body: Duration::ZERO,
        },
        ResponseFixture {
            status: 200,
            body: renew,
            delay_body: Duration::ZERO,
        },
        ResponseFixture {
            status: 204,
            body: String::new(),
            delay_body: Duration::ZERO,
        },
    ])
    .await
    .unwrap();
    let observed = Arc::new(Mutex::new(Vec::new()));
    let client = client(&endpoint, &ca, Duration::from_secs(2), Arc::clone(&observed));
    let authority_directory = private_tempdir();
    let authority = authority(authority_directory.path());
    let lease_directory = private_tempdir();
    let leases = BaoLeaseRegistry::open_state_dir(lease_directory.path()).unwrap();

    let issue_request = issue_request();
    let issue_grant = signed(client.issue_binding(&issue_request).unwrap(), 1, "issue-grant");
    let receipt = client
        .request_secret_lease(&leases, &authority, &issue_grant, &issue_request)
        .await
        .unwrap();
    assert_eq!(receipt.metadata.generation, 1);
    assert_eq!(receipt.metadata.state, BaoLeaseState::Active);
    assert!(receipt.metadata.renewable);
    let delivered = observed.lock().unwrap();
    assert_eq!(delivered.len(), 1);
    let delivered_json: serde_json::Value = serde_json::from_slice(&delivered[0]).unwrap();
    assert_eq!(delivered_json["username"], "fixture-user");
    assert_eq!(delivered_json["password"], "fixture-password");
    drop(delivered);

    let renew_request = BaoRenewLeaseRequest {
        subject_id: "agent-one".to_owned(),
        operation_id: "renew-one".to_owned(),
        namespace: "team/one".to_owned(),
        lease_id: receipt.metadata.lease_id.clone(),
        increment_seconds: 120,
    };
    let renew_grant = signed(client.renew_binding(&renew_request).unwrap(), 2, "renew-grant");
    let renewed = client
        .renew_secret_lease(&leases, &authority, &renew_grant, &renew_request)
        .await
        .unwrap();
    assert_eq!(renewed.generation, 2);
    assert_eq!(renewed.state, BaoLeaseState::Active);

    let revoke_request = BaoRevokeLeaseRequest {
        subject_id: "agent-one".to_owned(),
        operation_id: "revoke-one".to_owned(),
        namespace: "team/one".to_owned(),
        lease_id: receipt.metadata.lease_id.clone(),
    };
    let revoke_grant = signed(client.revoke_binding(&revoke_request).unwrap(), 3, "revoke-grant");
    let revoked = client
        .revoke_secret_lease(&leases, &authority, &revoke_grant, &revoke_request)
        .await
        .unwrap();
    assert_eq!(revoked.generation, 3);
    assert_eq!(revoked.state, BaoLeaseState::Revoked);
    assert!(!revoked.renewable);

    let persisted = leases
        .lease("database/creds/readonly/lease-one")
        .unwrap()
        .unwrap();
    assert_eq!(persisted, revoked);

    let requests = task.await.unwrap().unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests[0].starts_with("GET /v1/database/creds/readonly HTTP/1.1\r\n"));
    assert!(requests[1].starts_with("POST /v1/sys/leases/renew HTTP/1.1\r\n"));
    assert!(requests[2].starts_with("POST /v1/sys/leases/revoke HTTP/1.1\r\n"));
}

#[tokio::test]
async fn timeout_after_dispatch_is_indeterminate_and_same_operation_never_blind_retries() {
    let issue = serde_json::json!({
        "lease_id": "database/creds/readonly/uncertain",
        "renewable": true,
        "lease_duration": 60,
        "data": {"username": "u", "password": "p"}
    })
    .to_string();
    let (endpoint, ca, task) = server_sequence(vec![ResponseFixture {
        status: 200,
        body: issue,
        delay_body: Duration::from_millis(150),
    }])
    .await
    .unwrap();
    let client = client(
        &endpoint,
        &ca,
        Duration::from_millis(50),
        Arc::new(Mutex::new(Vec::new())),
    );
    let authority_directory = private_tempdir();
    let authority = authority(authority_directory.path());
    let lease_directory = private_tempdir();
    let leases = BaoLeaseRegistry::open_state_dir(lease_directory.path()).unwrap();
    let request = issue_request();
    let binding = client.issue_binding(&request).unwrap();
    let grant = signed(binding.clone(), 5, "issue-timeout");

    assert_eq!(
        client
            .request_secret_lease(&leases, &authority, &grant, &request)
            .await,
        Err(BaoClientError::LeaseOperationIndeterminate)
    );
    // The same operation is fenced by the durable registry before another
    // authority claim or network request can occur.
    assert_eq!(
        client
            .request_secret_lease(&leases, &authority, &grant, &request)
            .await,
        Err(BaoClientError::LeaseOperationIndeterminate)
    );

    let requests = task.await.unwrap().unwrap();
    assert_eq!(requests.len(), 1);

    let observation = BaoLeaseReconciliationObservation {
        subject_id: "agent-one".to_owned(),
        operation_id: request.operation_id.clone(),
        original_request_sha256: binding.request_sha256,
        outcome: BaoReconciliationOutcome::NotApplied,
        metadata: None,
    };
    let reconciliation_grant = signed(
        client.reconciliation_binding(&observation).unwrap(),
        6,
        "reconcile-not-applied",
    );
    client
        .reconcile_lease_operation(&leases, &authority, &reconciliation_grant, &observation)
        .unwrap();
    assert!(matches!(
        leases
            .store
            .prepare(
                &request.operation_id,
                binding.request_sha256,
                BaoLeaseOperationKind::Issue,
                None,
            )
            .unwrap(),
        PrepareDisposition::Dispatch
    ));
}

#[test]
fn reconciliation_rejects_changed_operation_semantics() {
    let directory = private_tempdir();
    let leases = BaoLeaseRegistry::open_state_dir(directory.path()).unwrap();
    let digest = [7; 32];
    assert!(matches!(
        leases
            .store
            .prepare("operation-one", digest, BaoLeaseOperationKind::Issue, None)
            .unwrap(),
        PrepareDisposition::Dispatch
    ));
    leases
        .store
        .mark_dispatched("operation-one", digest)
        .unwrap();
    leases
        .store
        .mark_indeterminate("operation-one", digest)
        .unwrap();
    let observation = BaoLeaseReconciliationObservation {
        subject_id: "agent-one".to_owned(),
        operation_id: "operation-one".to_owned(),
        original_request_sha256: [8; 32],
        outcome: BaoReconciliationOutcome::NotApplied,
        metadata: None,
    };
    assert_eq!(
        leases.store.resolve_indeterminate(&observation),
        Err(LeaseStoreError::Conflict)
    );
}
