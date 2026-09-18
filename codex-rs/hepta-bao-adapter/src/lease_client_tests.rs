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
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio_rustls::TlsAcceptor;

type TestError = Box<dyn std::error::Error + Send + Sync>;

const DYNAMIC_SECRET: &str = "fixture-dynamic-password";

async fn server(
    status: u16,
    body: String,
    delay: Duration,
) -> Result<
    (
        String,
        String,
        tokio::task::JoinHandle<Result<String, TestError>>,
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
        let Ok(mut stream) = TlsAcceptor::from(Arc::new(config)).accept(socket).await else {
            return Ok(String::new());
        };
        let mut bytes = Vec::new();
        while !bytes.ends_with(b"\r\n\r\n") && bytes.len() < 16 * 1024 {
            bytes.push(stream.read_u8().await?);
        }
        let headers = format!(
            "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        stream.write_all(headers.as_bytes()).await?;
        if !delay.is_zero() {
            tokio::time::sleep(delay).await;
        }
        let _ = stream.write_all(body.as_bytes()).await;
        Ok::<String, TestError>(String::from_utf8(bytes)?)
    });
    Ok((endpoint, pem, task))
}

fn issue_request(operation_id: &str) -> BaoSecretLeaseRequest {
    BaoSecretLeaseRequest {
        operation_id: operation_id.to_owned(),
        subject_id: "agent-one".to_owned(),
        consumer_id: "model-provider".to_owned(),
        namespace: "team/one".to_owned(),
        mount: "database".to_owned(),
        path: "creds/readonly".to_owned(),
    }
}

fn dynamic_body() -> String {
    serde_json::json!({
        "lease_id": "database/creds/readonly/lease-123",
        "renewable": true,
        "lease_duration": 60,
        "data": {
            "username": "dynamic-user",
            "password": DYNAMIC_SECRET
        }
    })
    .to_string()
}

fn grant(
    client: &BaoClient,
    request: &BaoSecretLeaseRequest,
    grant_id: &str,
    nonce_byte: u8,
) -> Result<(FinalUseAuthority, SignedFinalUseGrant, tempfile::TempDir), TestError> {
    let issuer = SigningKey::from_bytes(&[81; 32]);
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "owner".into(),
        authority_epoch: 4,
        grant_id: grant_id.to_owned(),
        nonce: [nonce_byte; 32],
        binding: client.secret_lease_binding(request)?,
        not_before_unix_ms: now - 1_000,
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "owner".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 4,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )?;
    Ok((
        authority,
        SignedFinalUseGrant { grant, signature },
        directory,
    ))
}

#[tokio::test]
async fn dynamic_issue_persists_metadata_and_only_delivers_secret_to_callback() {
    let (endpoint, ca, task) =
        server(200, dynamic_body(), Duration::ZERO).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture-provider-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = issue_request("issue-dynamic-1");
    let (authority, signed, _authority_directory) =
        grant(&client, &request, "dynamic-issue", 41).unwrap();
    let lease_directory = tempfile::tempdir().unwrap();
    let store = SecretLeaseStore::open(lease_directory.path()).await.unwrap();
    let receipt_key = BaoReceiptKey::new("receipt-key-1".into(), [44; 32]).unwrap();

    let mut consumed = false;
    let lease = client
        .request_secret_lease(
            &store,
            &authority,
            &signed,
            &request,
            &receipt_key,
            |bytes| {
                let text = std::str::from_utf8(bytes).unwrap();
                assert!(text.contains(DYNAMIC_SECRET));
                assert!(text.contains("dynamic-user"));
                consumed = true;
                Ok(())
            },
        )
        .await
        .unwrap();
    assert!(consumed);
    assert_eq!(lease.state, SecretLeaseStateV1::Active);
    assert_eq!(lease.rotation_generation, 1);
    assert_eq!(lease.fingerprint_key_id, "receipt-key-1");
    let persisted = store.lease(&lease.lease_id).await.unwrap().unwrap();
    assert_eq!(persisted, lease);
    let encoded = serde_json::to_string(&lease).unwrap();
    assert!(!encoded.contains(DYNAMIC_SECRET));
    assert!(!encoded.contains("dynamic-user"));

    let observed = task.await.unwrap().unwrap().to_ascii_lowercase();
    assert!(observed.starts_with("get /v1/database/creds/readonly http/1.1\r\n"));
    assert!(observed.contains("x-vault-token: fixture-provider-token\r\n"));
    assert!(observed.contains("x-vault-namespace: team/one\r\n"));
}

#[tokio::test]
async fn issue_timeout_is_durable_indeterminate_and_never_blind_retries() {
    let (endpoint, ca, task) =
        server(200, dynamic_body(), Duration::from_millis(150))
            .await
            .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        crate::BaoToken::new("fixture-provider-token".into()).unwrap(),
        Duration::from_millis(50),
    )
    .unwrap();
    let request = issue_request("issue-dynamic-timeout");
    let (authority, signed, _authority_directory) =
        grant(&client, &request, "dynamic-timeout", 42).unwrap();
    let lease_directory = tempfile::tempdir().unwrap();
    let store = SecretLeaseStore::open(lease_directory.path()).await.unwrap();
    let receipt_key = BaoReceiptKey::new("receipt-key-1".into(), [45; 32]).unwrap();

    assert_eq!(
        client
            .request_secret_lease(
                &store,
                &authority,
                &signed,
                &request,
                &receipt_key,
                |_| panic!("timed-out issuance must not deliver"),
            )
            .await,
        Err(BaoLeaseError::TimedOut)
    );
    let operation = store
        .operation(&request.operation_id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        operation.state,
        SecretLeaseOperationStateV1::Indeterminate
    );

    assert_eq!(
        client
            .request_secret_lease(
                &store,
                &authority,
                &signed,
                &request,
                &receipt_key,
                |_| Ok(()),
            )
            .await,
        Err(BaoLeaseError::OperationIndeterminate)
    );
    task.abort();
    let _ = task.await;
}

#[test]
fn receipt_fingerprint_is_keyed_and_debug_redacts_key() {
    let first = BaoReceiptKey::new("key-a".into(), [1; 32]).unwrap();
    let second = BaoReceiptKey::new("key-b".into(), [2; 32]).unwrap();
    let first_digest =
        first.fingerprint(b"hepta.test\0", b"low-entropy-secret");
    let second_digest =
        second.fingerprint(b"hepta.test\0", b"low-entropy-secret");
    assert_ne!(first_digest, second_digest);
    assert!(!format!("{first:?}").contains(&"01".repeat(32)));
    assert!(format!("{first:?}").contains("[REDACTED]"));
}
