use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::AuthBusAuthorityStore;
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
        consumer_configuration_sha256: None,
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
        Duration::from_secs(10),
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

    fn time_spec(&self) -> Result<IssuerSpec, TestError> {
        Ok(IssuerSpec {
            issuer_id: StableId::new("issuer:bao-time")?,
            key_epoch: Generation::new(1)?,
            verifying_key: self.time_key.verifying_key(),
        })
    }

    fn settlement_spec(&self) -> Result<IssuerSpec, TestError> {
        Ok(IssuerSpec {
            issuer_id: StableId::new("issuer:bao-settlement")?,
            key_epoch: Generation::new(1)?,
            verifying_key: self.settlement_key.verifying_key(),
        })
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
    authbus_host_with_lifetime(60_000, client, request, now).await
}

fn product_grant(
    client: &BaoClient,
    request: &BaoReadRequest,
) -> Result<(FinalUseAuthority, SignedFinalUseGrant, tempfile::TempDir), TestError> {
    let (authority, mut signed, root) = grant(client, request)?;
    signed.grant.expires_at_unix_ms = signed.grant.not_before_unix_ms + 180_000;
    signed.signature = SigningKey::from_bytes(&[71; 32])
        .sign(&signed.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    Ok((authority, signed, root))
}

async fn authbus_host_with_lifetime(
    lifetime_ms: u64,
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

    let raw = AuthBusAuthorityStore::open(&database).await?;
    let frontier = raw.authority_frontier_digest().await?;
    drop(raw);
    let document = serde_json::json!({
        "schema_version": 1,
        "owner_id": "bao-product-owner",
        "generation": 1,
        "digest": frontier.to_string(),
    });
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&checkpoint)?;
    serde_json::to_writer(&mut file, &document)?;
    file.flush()?;
    file.sync_all()?;

    let host = AuthBusAuthorityHost::open(&database, checkpoint, "bao-product-owner").await?;
    let mut evidence = AuthBusEvidence::new(now);
    host.enroll_issuer(IssuerPurpose::TrustedTime, evidence.time_spec()?)
        .await?;
    host.enroll_issuer(IssuerPurpose::Settlement, evidence.settlement_spec()?)
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
                expires_at_ms: now + lifetime_ms,
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
        expires_at_ms: now + lifetime_ms,
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
            BaoAuthorizedReadV1 {
                admission: &admission,
                authority: &authority,
                grant: &grant,
                request: &request,
            },
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
            BaoAuthorizedReadV1 {
                admission: &admission,
                authority: &authority,
                grant: &grant,
                request: &request,
            },
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

fn registered_product_host(
    authority: FinalUseAuthority,
    grant: &SignedFinalUseGrant,
    callback: crate::BaoOperationConsumerCallback,
    observer: crate::BaoConsumerObserverCallback,
    configuration: [u8; 32],
) -> Result<
    (
        crate::BaoFinalUseHost,
        codex_hepta_contracts::SignedFinalUseApproval,
    ),
    TestError,
> {
    use codex_hepta_contracts::{
        FinalUseApproval, FinalUseApprovalVerifier, FinalUseRevocationFeedVerifier,
        FinalUseRevocationUpdate, SignedFinalUseApproval, SignedFinalUseRevocationUpdate,
        SystemAuthorityClock,
    };
    let approver = SigningKey::from_bytes(&[91; 32]);
    let distributor = SigningKey::from_bytes(&[92; 32]);
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let host = crate::BaoFinalUseHost::new(
        authority,
        FinalUseApprovalVerifier::new(
            "bao-test-approver".into(),
            approver.verifying_key().to_bytes(),
        )?,
        FinalUseRevocationFeedVerifier::new(
            "bao-test-distributor".into(),
            distributor.verifying_key().to_bytes(),
        )?,
        Arc::new(SystemAuthorityClock),
        [crate::RegisteredBaoConsumer::for_operations(
            "model-provider".into(),
            configuration,
            callback,
            observer,
        )?],
    )?;
    let update = FinalUseRevocationUpdate::new(
        "bao-test-distributor".into(),
        FinalUseRevocations {
            authority_epoch: 3,
            revision: 2,
            revoked_grant_ids: Default::default(),
        },
        now - 1_000,
        now + 180_000,
    );
    let signature = distributor
        .sign(&update.signing_bytes()?)
        .to_bytes()
        .to_vec();
    host.apply_revocation_update(&SignedFinalUseRevocationUpdate { update, signature })?;
    let approval = FinalUseApproval::for_grant("bao-test-approver".into(), &grant.grant)?;
    let signature = approver
        .sign(&approval.signing_bytes()?)
        .to_bytes()
        .to_vec();
    Ok((
        host,
        SignedFinalUseApproval {
            approval,
            signature,
        },
    ))
}

fn product_registry() -> Result<
    (
        tempfile::TempDir,
        std::sync::Mutex<crate::DurableLeaseRegistryV1>,
    ),
    TestError,
> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let owner = crate::DurableLeaseRegistryV1::open(directory.path().join("owner.json"))?;
    Ok((directory, std::sync::Mutex::new(owner)))
}

#[tokio::test]
async fn registered_product_persists_result_and_never_redispatches_after_restart() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let (endpoint, ca, server_task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("synthetic-product-token".into()).unwrap(),
        Duration::from_secs(3),
    )
    .unwrap();
    let mut request = read_request();
    request.consumer_configuration_sha256 = Some([93; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let (_db, _checkpoint, authbus, mut evidence, admission) =
        authbus_host_with_lifetime(180_000, &client, &request, now)
            .await
            .unwrap();
    let (authority, grant, _authority_root) = product_grant(&client, &request).unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&calls);
    let (host, approval) = registered_product_host(
        authority,
        &grant,
        Arc::new(move |operation, digest, bytes| {
            assert_eq!(operation, "operation:bao-product");
            assert_ne!(digest, [0; 32]);
            assert_eq!(bytes, SECRET.as_bytes());
            counter.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }),
        Arc::new(|_, _| Ok(crate::BaoConsumerObservationV1::Unknown)),
        [93; 32],
    )
    .unwrap();
    let (owner_root, registry) = product_registry().unwrap();
    let receipt = host
        .consume_kv_v2_with_authbus(
            &client,
            &authbus,
            &registry,
            crate::BaoApprovedReadV1 {
                admission: &admission,
                grant: &grant,
                approval: &approval,
                request: &request,
            },
            &mut evidence,
        )
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_secs(10), server_task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    drop(registry);
    let registry = std::sync::Mutex::new(
        crate::DurableLeaseRegistryV1::open(owner_root.path().join("owner.json")).unwrap(),
    );
    let replayed = host
        .consume_kv_v2_with_authbus(
            &client,
            &authbus,
            &registry,
            crate::BaoApprovedReadV1 {
                admission: &admission,
                grant: &grant,
                approval: &approval,
                request: &request,
            },
            &mut evidence,
        )
        .await
        .unwrap();
    assert_eq!(receipt, replayed);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let quota = authbus.quota_snapshot(&admission.quota_key).await.unwrap();
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 0, 1));
    let mut drift = admission.clone();
    drift.expires_at_ms += 1;
    assert!(matches!(
        host.consume_kv_v2_with_authbus(
            &client,
            &authbus,
            &registry,
            crate::BaoApprovedReadV1 {
                admission: &drift,
                grant: &grant,
                approval: &approval,
                request: &request
            },
            &mut evidence
        )
        .await,
        Err(crate::BaoProductHostError::Store(
            crate::LeaseRegistryErrorV1::OperationConflict
        ))
    ));
    let stored = std::fs::read_to_string(owner_root.path().join("owner.json")).unwrap();
    assert!(!stored.contains(SECRET));
    assert!(!stored.contains("synthetic-product-token"));
}

struct FailSettlementOnce {
    inner: AuthBusEvidence,
    fail: bool,
}
impl BaoAuthBusEvidenceProvider for FailSettlementOnce {
    fn trusted_time(&mut self) -> Result<SignedTrustedTimeAttestation, BaoAuthBusError> {
        self.inner.trusted_time()
    }
    fn settlement_evidence(
        &mut self,
        reservation: &QuotaReservation,
        status: SettlementStatus,
        observed_cost: u64,
        terminal: Digest32,
        at: u64,
    ) -> Result<SignedSettlementEvidence, BaoAuthBusError> {
        if std::mem::take(&mut self.fail) {
            return Err(BaoAuthBusError::Evidence("synthetic settlement outage"));
        }
        self.inner
            .settlement_evidence(reservation, status, observed_cost, terminal, at)
    }
}

#[tokio::test]
async fn registered_product_recovers_settlement_without_reentering_consumer() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let (endpoint, ca, server_task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("synthetic-token".into()).unwrap(),
        Duration::from_secs(3),
    )
    .unwrap();
    let mut request = read_request();
    request.consumer_configuration_sha256 = Some([94; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let (_db, _checkpoint, authbus, evidence, admission) =
        authbus_host_with_lifetime(180_000, &client, &request, now)
            .await
            .unwrap();
    let mut evidence = FailSettlementOnce {
        inner: evidence,
        fail: true,
    };
    let (authority, grant, _authority_root) = product_grant(&client, &request).unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&calls);
    let (host, approval) = registered_product_host(
        authority,
        &grant,
        Arc::new(move |_, _, _| {
            counter.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }),
        Arc::new(|_, _| Ok(crate::BaoConsumerObservationV1::Unknown)),
        [94; 32],
    )
    .unwrap();
    let (owner_root, registry) = product_registry().unwrap();
    assert!(
        host.consume_kv_v2_with_authbus(
            &client,
            &authbus,
            &registry,
            crate::BaoApprovedReadV1 {
                admission: &admission,
                grant: &grant,
                approval: &approval,
                request: &request
            },
            &mut evidence
        )
        .await
        .is_err()
    );
    tokio::time::timeout(Duration::from_secs(10), server_task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    let row = registry
        .lock()
        .unwrap()
        .consumption_result(admission.operation_id.as_str())
        .unwrap();
    assert_eq!(row.state, crate::BaoConsumptionStateV1::ConsumerSucceeded);
    drop(registry);
    let registry = std::sync::Mutex::new(
        crate::DurableLeaseRegistryV1::open(owner_root.path().join("owner.json")).unwrap(),
    );
    let recovered = host
        .reconcile_consumption(
            &authbus,
            &registry,
            admission.operation_id.as_str(),
            &mut evidence,
        )
        .await
        .unwrap();
    assert_eq!(Some(recovered), row.receipt);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let quota = authbus.quota_snapshot(&admission.quota_key).await.unwrap();
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 0, 1));
}

#[tokio::test]
async fn registered_product_queries_durable_consumer_after_lost_ack() {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    use std::sync::atomic::{AtomicUsize, Ordering};
    let (endpoint, ca, server_task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("synthetic-token".into()).unwrap(),
        Duration::from_secs(3),
    )
    .unwrap();
    let mut request = read_request();
    request.consumer_configuration_sha256 = Some([95; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let (_db, _checkpoint, authbus, mut evidence, admission) =
        authbus_host_with_lifetime(180_000, &client, &request, now)
            .await
            .unwrap();
    let (authority, grant, _authority_root) = product_grant(&client, &request).unwrap();
    let (owner_root, registry) = product_registry().unwrap();
    let output = owner_root.path().join("consumer-outcome.json");
    let observed = output.clone();
    let calls = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&calls);
    let (host, approval) = registered_product_host(
        authority,
        &grant,
        Arc::new(move |operation, digest, bytes| {
            assert_eq!(bytes, SECRET.as_bytes());
            counter.fetch_add(1, Ordering::SeqCst);
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&output)
                .map_err(|_| ())?;
            file.write_all(&serde_json::to_vec(&(operation, digest)).map_err(|_| ())?)
                .map_err(|_| ())?;
            file.sync_all().map_err(|_| ())?;
            std::fs::File::open(output.parent().unwrap())
                .and_then(|parent| parent.sync_all())
                .map_err(|_| ())?;
            Err(()) // The consumer completed its effect, but its acknowledgement was lost.
        }),
        Arc::new(move |operation, digest| {
            let recorded: (String, [u8; 32]) =
                serde_json::from_slice(&std::fs::read(&observed).map_err(|_| ())?)
                    .map_err(|_| ())?;
            if recorded == (operation.to_owned(), digest) {
                Ok(crate::BaoConsumerObservationV1::Succeeded)
            } else {
                Err(())
            }
        }),
        [95; 32],
    )
    .unwrap();
    assert!(matches!(
        host.consume_kv_v2_with_authbus(
            &client,
            &authbus,
            &registry,
            crate::BaoApprovedReadV1 {
                admission: &admission,
                grant: &grant,
                approval: &approval,
                request: &request
            },
            &mut evidence
        )
        .await,
        Err(crate::BaoProductHostError::AuthBus(
            BaoAuthBusError::Indeterminate { .. }
        ))
    ));
    tokio::time::timeout(Duration::from_secs(10), server_task)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    drop(registry);
    let registry = std::sync::Mutex::new(
        crate::DurableLeaseRegistryV1::open(owner_root.path().join("owner.json")).unwrap(),
    );
    let result = host
        .reconcile_consumption(
            &authbus,
            &registry,
            admission.operation_id.as_str(),
            &mut evidence,
        )
        .await
        .unwrap();
    assert_eq!(result.secret_sha256, request.expected_secret_sha256);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn durable_preparation_precedes_final_revocation_check() {
    let (endpoint, ca, task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("synthetic-token".into()).unwrap(),
        Duration::from_secs(3),
    )
    .unwrap();
    let request = read_request();
    let (authority, grant, _root) = product_grant(&client, &request).unwrap();
    let called = std::sync::atomic::AtomicBool::new(false);
    let result = client
        .consume_kv_v2_guarded(
            &authority,
            &grant,
            &request,
            |_receipt| {
                authority
                    .update_revocations(FinalUseRevocations {
                        authority_epoch: 3,
                        revision: 2,
                        revoked_grant_ids: [grant.grant.grant_id.clone()].into_iter().collect(),
                    })
                    .unwrap();
                Ok::<(), ()>(())
            },
            |_, _| {
                called.store(true, std::sync::atomic::Ordering::SeqCst);
                Ok(())
            },
        )
        .await;
    assert!(matches!(result, Err(BaoClientError::Authority(_))));
    assert!(!called.load(std::sync::atomic::Ordering::SeqCst));
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn consumer_configuration_is_inside_the_independently_signed_request() {
    let (endpoint, ca, task) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("synthetic-token".into()).unwrap(),
        Duration::from_secs(3),
    )
    .unwrap();
    let mut request = read_request();
    let legacy = client.binding(&request).unwrap();
    assert!(
        !serde_json::to_string(&request)
            .unwrap()
            .contains("consumer_configuration_sha256")
    );
    request.consumer_configuration_sha256 = Some([93; 32]);
    let first = client.binding(&request).unwrap();
    request.consumer_configuration_sha256 = Some([94; 32]);
    let second = client.binding(&request).unwrap();
    assert_ne!(legacy.request_sha256, first.request_sha256);
    assert_ne!(first.request_sha256, second.request_sha256);
    request.consumer_configuration_sha256 = Some([0; 32]);
    assert!(matches!(
        client.binding(&request),
        Err(BaoClientError::InvalidRequest)
    ));
    task.abort();
}
