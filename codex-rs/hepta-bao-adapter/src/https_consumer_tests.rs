use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_authbus::PolicyEffect;
use codex_hepta_authbus::PolicySpec;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::QuotaSpec;
use codex_hepta_authbus::SettlementEvidenceClaims;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_authbus::SignedSettlementEvidence;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_authbus::TrustedTimeAttestationClaims;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
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

struct AuthBusEvidence {
    time_key: SigningKey,
    settlement_key: SigningKey,
    revision: u64,
    wall_time_ms: u64,
}

impl AuthBusEvidence {
    fn new(wall_time_ms: u64) -> Self {
        Self {
            time_key: SigningKey::from_bytes(&[81; 32]),
            settlement_key: SigningKey::from_bytes(&[82; 32]),
            revision: 0,
            wall_time_ms,
        }
    }

    fn time_spec(&self) -> IssuerSpec {
        IssuerSpec {
            issuer_id: StableId::new("issuer:bao-time").unwrap(),
            key_epoch: Generation::new(1).unwrap(),
            verifying_key: self.time_key.verifying_key(),
        }
    }

    fn settlement_spec(&self) -> IssuerSpec {
        IssuerSpec {
            issuer_id: StableId::new("issuer:bao-settlement").unwrap(),
            key_epoch: Generation::new(1).unwrap(),
            verifying_key: self.settlement_key.verifying_key(),
        }
    }
}

impl BaoAuthBusEvidenceProvider for AuthBusEvidence {
    fn trusted_time(&mut self) -> Result<SignedTrustedTimeAttestation, BaoAuthBusError> {
        self.revision += 1;
        self.wall_time_ms += 1;
        let claims = TrustedTimeAttestationClaims {
            issuer_id: StableId::new("issuer:bao-time")
                .map_err(|_| BaoAuthBusError::Evidence("time issuer id"))?,
            key_epoch: Generation::new(1)
                .map_err(|_| BaoAuthBusError::Evidence("time issuer epoch"))?,
            wall_time_ms: self.wall_time_ms,
            source_revision: self.revision,
            source_digest: Digest32::of_bytes(
                format!("bao-time:{}:{}", self.revision, self.wall_time_ms).as_bytes(),
            ),
        };
        Ok(SignedTrustedTimeAttestation {
            signature: self.time_key.sign(&claims.signing_bytes()).to_bytes(),
            claims,
        })
    }

    fn settlement_evidence(
        &mut self,
        reservation: &QuotaReservation,
        status: SettlementStatus,
        observed_cost: u64,
        terminal_evidence_digest: Digest32,
        observed_at_ms: u64,
    ) -> Result<SignedSettlementEvidence, BaoAuthBusError> {
        let claims = SettlementEvidenceClaims {
            issuer_id: StableId::new("issuer:bao-settlement")
                .map_err(|_| BaoAuthBusError::Evidence("settlement issuer id"))?,
            key_epoch: Generation::new(1)
                .map_err(|_| BaoAuthBusError::Evidence("settlement issuer epoch"))?,
            reservation_id: reservation.reservation_id.clone(),
            operation_id: reservation.operation_id.clone(),
            status,
            observed_cost,
            terminal_evidence_digest,
            observed_at_ms,
            expires_at_ms: observed_at_ms + 30_000,
        };
        Ok(SignedSettlementEvidence {
            signature: self.settlement_key.sign(&claims.signing_bytes()).to_bytes(),
            claims,
        })
    }
}

async fn authbus_host(
    client: &BaoClient,
    request: &BaoReadRequest,
    now: u64,
) -> Result<
    (
        tempfile::TempDir,
        tempfile::TempDir,
        AuthBusAuthorityHost,
        AuthBusEvidence,
        BaoAuthBusAdmission,
    ),
    TestError,
> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;

    let database_root = tempfile::tempdir()?;
    let checkpoint_root = tempfile::tempdir()?;
    std::fs::set_permissions(database_root.path(), std::fs::Permissions::from_mode(0o700))?;
    std::fs::set_permissions(
        checkpoint_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let database = database_root.path().join("authbus-authority.sqlite");
    let checkpoint = checkpoint_root
        .path()
        .join("authbus-authority-checkpoint.json");

    let host = AuthBusAuthorityHost::open(&database, checkpoint, "bao-product-owner").await?;
    let mut evidence = AuthBusEvidence::new(now);
    host.enroll_issuer(IssuerPurpose::TrustedTime, evidence.time_spec())
        .await?;
    host.enroll_issuer(IssuerPurpose::Settlement, evidence.settlement_spec())
        .await?;

    let binding = client.binding(request)?;
    let scope = Digest32::from_array(binding.scope_sha256);
    let time = host
        .observe_trusted_time_attestation(&evidence.trusted_time()?)
        .await?;
    let policy = host
        .create_policy(
            PolicySpec {
                policy_id: StableId::new("policy:bao-read")?,
                principal: StableId::new(request.subject_id.clone())?,
                action: StableId::new("action:bao-read")?,
                scope_digest: scope,
                effect: PolicyEffect::Allow,
                not_before_ms: now.saturating_sub(1_000),
                expires_at_ms: now + 60_000,
            },
            time,
        )
        .await?;
    let time = host
        .observe_trusted_time_attestation(&evidence.trusted_time()?)
        .await?;
    let quota = host
        .create_quota(
            QuotaSpec {
                quota_key: StableId::new("quota:bao-read")?,
                principal: policy.principal,
                scope_digest: scope,
                unit: StableId::new("unit:provider-request")?,
                period_id: StableId::new("period:test")?,
                limit: 1,
            },
            time,
        )
        .await?;
    let admission = BaoAuthBusAdmission {
        policy_revision: 1,
        quota_key: quota.quota_key,
        expected_quota_revision: 1,
        operation_id: StableId::new("operation:bao-product")?,
        amount: 1,
        expires_at_ms: now + 30_000,
    };
    Ok((database_root, checkpoint_root, host, evidence, admission))
}

#[tokio::test]
async fn authbus_product_path_reserves_fences_final_use_and_settles_observed_cost() {
    let (endpoint, ca, task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-authbus-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let request = read_request();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let (_db, _checkpoint, authbus, mut evidence, admission) =
        authbus_host(&client, &request, now).await.unwrap();
    let (authority, grant, _authority_dir) = grant(&client, &request).unwrap();

    let receipt = client
        .consume_kv_v2_with_authbus(
            &authbus,
            &admission,
            &authority,
            &grant,
            &request,
            &mut evidence,
            |bytes| {
                assert_eq!(bytes, SECRET.as_bytes());
                Ok(())
            },
        )
        .await
        .unwrap();
    assert_eq!(receipt.secret_sha256, request.expected_secret_sha256);
    let quota = authbus.quota_snapshot(&admission.quota_key).await.unwrap();
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 0, 1));
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn authbus_timeout_keeps_quota_held_as_indeterminate() {
    let (endpoint, ca, task) = server(200, body(), || async {
        tokio::time::sleep(Duration::from_millis(150)).await;
    })
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-authbus-token".into()).unwrap(),
        Duration::from_millis(50),
    )
    .unwrap();
    let request = read_request();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let (_db, _checkpoint, authbus, mut evidence, admission) =
        authbus_host(&client, &request, now).await.unwrap();
    let (authority, grant, _authority_dir) = grant(&client, &request).unwrap();

    let result = client
        .consume_kv_v2_with_authbus(
            &authbus,
            &admission,
            &authority,
            &grant,
            &request,
            &mut evidence,
            |_| Ok(()),
        )
        .await;
    assert!(matches!(
        result,
        Err(BaoAuthBusError::Indeterminate {
            provider_error: BaoClientError::TimedOut,
            ..
        })
    ));
    let quota = authbus.quota_snapshot(&admission.quota_key).await.unwrap();
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 1, 0));
    task.abort();
    let _ = task.await;
}
