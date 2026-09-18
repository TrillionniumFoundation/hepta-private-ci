use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::PolicyRevision;
use codex_hepta_authbus::PolicyRule;
use codex_hepta_authbus::QuotaConfig;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_evidence::AuthBusControlError;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio_rustls::TlsAcceptor;

type TestError = Box<dyn std::error::Error + Send + Sync>;

const SECRET: &str = "fixture-only-consumer-secret";

async fn server<F>(
    status: u16,
    body: String,
    before_response: impl FnOnce() -> F + Send + 'static,
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
        let mut bytes = Vec::new();
        while !bytes.ends_with(b"\r\n\r\n") && bytes.len() < 16 * 1024 {
            bytes.push(stream.read_u8().await?);
        }
        let headers = format!(
            "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        let _ = stream.write_all(headers.as_bytes()).await;
        // Delay/revocation happens after headers, exercising the response-body deadline and
        // the delivery fence rather than only the connection/header timeout.
        before_response().await;
        let _ = stream.write_all(body.as_bytes()).await;
        Ok::<String, TestError>(String::from_utf8(bytes)?)
    });
    Ok((endpoint, pem, task))
}

fn read_request() -> BaoReadRequest {
    BaoReadRequest {
        subject_id: "agent-one".into(),
        consumer_id: "model-provider".into(),
        namespace: "team/one".into(),
        mount: "secret".into(),
        path: "provider/token".into(),
        field: "value".into(),
        version: 2,
        expected_secret_sha256: Digest32::of_bytes(SECRET.as_bytes()).into_array(),
    }
}

fn grant(
    client: &BaoClient,
    request: &BaoReadRequest,
) -> Result<(FinalUseAuthority, SignedFinalUseGrant, tempfile::TempDir), TestError> {
    let issuer = SigningKey::from_bytes(&[71; 32]);
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "owner".into(),
        authority_epoch: 3,
        grant_id: "secret-read".into(),
        nonce: [11; 32],
        binding: client.binding(request)?,
        not_before_unix_ms: now - 1000,
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
            authority_epoch: 3,
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

fn body() -> String {
    body_for(2, SECRET)
}

fn body_for(version: u64, secret: &str) -> String {
    serde_json::json!({"data":{"data":{"value":secret},"metadata":{"version":version}}}).to_string()
}

#[tokio::test]
async fn real_tls_read_uses_headers_exact_version_and_secret_only_consumer() {
    let (endpoint, ca, task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-provider-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, grant, _directory) = grant(&client, &request).unwrap();
    let mut consumed = false;
    let receipt = client
        .consume_kv_v2(&authority, &grant, &request, |bytes| {
            assert_eq!(bytes, SECRET.as_bytes());
            consumed = true;
            Ok(())
        })
        .await
        .unwrap();
    assert!(consumed);
    assert!(!serde_json::to_string(&receipt).unwrap().contains(SECRET));
    let observed = task.await.unwrap().unwrap().to_ascii_lowercase();
    assert!(observed.starts_with("get /v1/secret/data/provider/token?version=2 http/1.1\r\n"));
    assert!(observed.contains("x-vault-token: fixture-provider-token\r\n"));
    assert!(observed.contains("x-vault-namespace: team/one\r\n"));
    assert_eq!(
        client
            .consume_kv_v2(&authority, &grant, &request, |_| Ok(()))
            .await,
        Err(BaoClientError::Authority(FinalUseError::AlreadyClaimed))
    );
}

#[tokio::test]
async fn invalid_signature_and_provider_denial_do_not_release_secret() {
    let (endpoint, ca, task) = server(403, "{}".into(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, mut signed, _directory) = grant(&client, &request).unwrap();
    signed.signature[0] ^= 1;
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!(
                "unauthorized consumer"
            ))
            .await,
        Err(BaoClientError::Authority(FinalUseError::InvalidSignature))
    );
    signed.signature[0] ^= 1;
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!("denied consumer"))
            .await,
        Err(BaoClientError::ProviderDenied)
    );
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn revocation_during_network_wait_prevents_consumer_delivery() {
    let authority_slot = Arc::new(std::sync::Mutex::new(None::<FinalUseAuthority>));
    let update = Arc::clone(&authority_slot);
    let (endpoint, ca, task) = server(200, body(), move || async move {
        update
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .update_revocations(FinalUseRevocations {
                authority_epoch: 3,
                revision: 2,
                revoked_grant_ids: std::collections::BTreeSet::from(["secret-read".into()]),
            })
            .unwrap();
    })
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    *authority_slot.lock().unwrap() = Some(authority.clone());
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!(
                "revoked consumer"
            ))
            .await,
        Err(BaoClientError::Authority(FinalUseError::Revoked))
    );
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn untrusted_tls_certificate_fails_before_secret_delivery() {
    let (endpoint, _, task) = server(200, body(), || async {}).await.unwrap();
    let wrong_ca = rcgen::generate_simple_self_signed(vec!["localhost".into()])
        .unwrap()
        .cert
        .pem();
    let client = BaoClient::new(
        &endpoint,
        wrong_ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!(
                "untrusted server"
            ))
            .await,
        Err(BaoClientError::TransportUnavailable)
    );
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn oversized_reply_fails_without_consumer_delivery() {
    let (endpoint, ca, task) = server(200, "x".repeat(MAX_RESPONSE_BYTES + 1), || async {})
        .await
        .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!("oversized reply"))
            .await,
        Err(BaoClientError::ResponseTooLarge)
    );
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn timeout_does_not_retry_or_release_a_secret() {
    let (endpoint, ca, task) = server(200, body(), || async {
        tokio::time::sleep(Duration::from_millis(150)).await;
    })
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_millis(50),
    )
    .unwrap();
    let request = read_request();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!(
                "timed-out consumer"
            ))
            .await,
        Err(BaoClientError::TimedOut)
    );
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| Ok(()))
            .await,
        Err(BaoClientError::Authority(FinalUseError::AlreadyClaimed))
    );
    // Cancellation can precede TCP accept under load. Stop the fixture as
    // part of timeout cleanup instead of waiting for a connection forever.
    task.abort();
    let _ = task.await;
}

#[tokio::test]
async fn consumer_failure_after_delivery_is_indeterminate() {
    let (endpoint, ca, task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| Err(()))
            .await,
        Err(BaoClientError::ConsumerIndeterminate)
    );
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| Ok(()))
            .await,
        Err(BaoClientError::Authority(FinalUseError::AlreadyClaimed))
    );
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn version_and_digest_mismatches_never_deliver() {
    let (endpoint, ca, task) = server(200, body_for(1, SECRET), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!(
                "version-mismatched consumer"
            ))
            .await,
        Err(BaoClientError::VersionMismatch)
    );
    task.await.unwrap().unwrap();

    let (endpoint, ca, task) = server(200, body_for(2, "wrong-secret"), || async {})
        .await
        .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!(
                "digest-mismatched consumer"
            ))
            .await,
        Err(BaoClientError::SecretDigestMismatch)
    );
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn provider_not_found_and_malformed_success_are_denied() {
    let (endpoint, ca, task) = server(404, "{}".into(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!(
                "missing consumer"
            ))
            .await,
        Err(BaoClientError::NotFound)
    );
    task.await.unwrap().unwrap();

    let (endpoint, ca, task) = server(200, "{\"data\":{}}".into(), || async {})
        .await
        .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    assert_eq!(
        client
            .consume_kv_v2(&authority, &signed, &request, |_| panic!(
                "malformed consumer"
            ))
            .await,
        Err(BaoClientError::InvalidResponse)
    );
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn root_namespace_omits_namespace_header() {
    let (endpoint, ca, task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let mut request = read_request();
    request.namespace.clear();
    let (authority, signed, _directory) = grant(&client, &request).unwrap();
    client
        .consume_kv_v2(&authority, &signed, &request, |bytes| {
            assert_eq!(bytes, SECRET.as_bytes());
            Ok(())
        })
        .await
        .unwrap();
    let observed = task.await.unwrap().unwrap().to_ascii_lowercase();
    assert!(!observed.contains("x-vault-namespace:"));
}

#[tokio::test]
async fn authbus_wrapper_cancels_reservation_when_request_fails_before_effect() {
    let certified = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()]).unwrap();
    let client = BaoClient::new(
        "https://localhost:443/",
        certified.cert.pem().as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let valid_request = read_request();
    let (authority, grant, _authority_dir) = grant(&client, &valid_request).unwrap();

    let evidence_dir = tempfile::tempdir().unwrap();
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(evidence_dir.path().to_path_buf()).unwrap(),
    );
    let evidence = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let policy_id = StableId::new("policy:bao").unwrap();
    let principal = StableId::new("principal:bao").unwrap();
    let action = StableId::new("action:bao-read").unwrap();
    let quota = StableId::new("quota:bao-read").unwrap();
    let reservation_id = StableId::new("reservation:bao-read").unwrap();
    let operation_id = StableId::new("operation:bao-read").unwrap();
    let scope = Digest32::of_bytes(b"bao-read-scope");
    evidence
        .install_authbus_policy(
            &PolicyRevision {
                policy_id: policy_id.clone(),
                revision: 1,
                rules: vec![PolicyRule {
                    principal_id: principal.clone(),
                    action_id: action.clone(),
                    scope_digest: scope,
                    allow: true,
                }],
            },
            false,
        )
        .await
        .unwrap();
    evidence
        .configure_authbus_quota(&QuotaConfig {
            quota_key: quota.clone(),
            revision: 1,
            endowment: 1,
        })
        .await
        .unwrap();
    evidence
        .authorize_and_reserve_authbus(
            &policy_id,
            1,
            &principal,
            &action,
            scope,
            &quota,
            1,
            &reservation_id,
            &operation_id,
            1,
            u64::MAX,
        )
        .await
        .unwrap();

    let mut invalid_request = valid_request;
    invalid_request.field.clear();
    assert_eq!(
        client
            .consume_kv_v2_with_authbus(
                &evidence,
                &reservation_id,
                &authority,
                &grant,
                &invalid_request,
                |_| panic!("pre-effect invalid request reached consumer"),
            )
            .await,
        Err(BaoClientError::InvalidRequest)
    );
    assert!(matches!(
        evidence
            .validate_authbus_reservation_for_effect(&reservation_id, 1)
            .await,
        Err(AuthBusControlError::InvalidTransition)
    ));
}
