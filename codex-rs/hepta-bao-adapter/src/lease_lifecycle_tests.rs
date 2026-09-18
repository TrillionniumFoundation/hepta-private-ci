use super::*;

use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SecretLeaseCreateDisposition;
use codex_hepta_contracts::SecretLeaseFuture;
use codex_hepta_contracts::SecretLeaseStoreError;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::sync::Notify;
use tokio_rustls::TlsAcceptor;

type TestError = Box<dyn std::error::Error + Send + Sync>;

#[derive(Default)]
struct MemoryStore {
    rows: Mutex<BTreeMap<String, SecretLeaseRecord>>,
}

impl SecretLeaseStore for MemoryStore {
    fn load<'a>(
        &'a self,
        lease_key: &'a str,
    ) -> SecretLeaseFuture<'a, Option<SecretLeaseRecord>> {
        Box::pin(async move {
            Ok(self.rows.lock().unwrap().get(lease_key).cloned())
        })
    }

    fn create<'a>(
        &'a self,
        record: &'a SecretLeaseRecord,
    ) -> SecretLeaseFuture<'a, SecretLeaseCreateDisposition> {
        Box::pin(async move {
            record
                .validate()
                .map_err(SecretLeaseStoreError::InvalidRecord)?;
            let mut rows = self.rows.lock().unwrap();
            match rows.get(&record.lease_key) {
                Some(existing) if existing == record => {
                    Ok(SecretLeaseCreateDisposition::AlreadyPresent)
                }
                Some(_) => Err(SecretLeaseStoreError::Conflict),
                None => {
                    rows.insert(record.lease_key.clone(), record.clone());
                    Ok(SecretLeaseCreateDisposition::Inserted)
                }
            }
        })
    }

    fn compare_and_swap<'a>(
        &'a self,
        expected_revision: u64,
        next: &'a SecretLeaseRecord,
    ) -> SecretLeaseFuture<'a, ()> {
        Box::pin(async move {
            let mut rows = self.rows.lock().unwrap();
            let current = rows
                .get(&next.lease_key)
                .cloned()
                .ok_or(SecretLeaseStoreError::NotFound)?;
            if current.revision != expected_revision {
                return Err(SecretLeaseStoreError::StaleRevision);
            }
            next.validate_transition_from(&current)
                .map_err(SecretLeaseStoreError::InvalidRecord)?;
            rows.insert(next.lease_key.clone(), next.clone());
            Ok(())
        })
    }
}

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
        before_response().await;
        let _ = stream.write_all(body.as_bytes()).await;
        Ok::<String, TestError>(String::from_utf8(bytes)?)
    });
    Ok((endpoint, pem, task))
}

fn issue_request() -> BaoLeaseIssueRequest {
    BaoLeaseIssueRequest {
        lease_key: "lease:database:reader:one".into(),
        operation_id: "operation:issue:one".into(),
        subject_id: "agent-one".into(),
        consumer_id: "database-client".into(),
        namespace: "team/one".into(),
        path: "database/creds/reader".into(),
        method: BaoLeaseIssueMethod::Get,
        request_body: BTreeMap::new(),
        secret_fields: vec!["username".into(), "password".into()],
    }
}

fn issue_body() -> String {
    serde_json::json!({
        "lease_id": "database/creds/reader/provider-lease-one",
        "lease_duration": 60,
        "renewable": true,
        "data": {
            "username": "dynamic-user",
            "password": "dynamic-password"
        }
    })
    .to_string()
}

struct AuthorityFixture {
    authority: FinalUseAuthority,
    signer: SigningKey,
    _directory: tempfile::TempDir,
}

fn authority_fixture() -> Result<AuthorityFixture, TestError> {
    let signer = SigningKey::from_bytes(&[81; 32]);
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "owner".into(),
        signer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    Ok(AuthorityFixture {
        authority,
        signer,
        _directory: directory,
    })
}

fn signed_grant(
    signer: &SigningKey,
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
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
    Ok(SignedFinalUseGrant { grant, signature })
}

#[tokio::test]
async fn only_durable_issue_winner_crosses_provider_boundary() {
    let started = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let started_server = Arc::clone(&started);
    let release_server = Arc::clone(&release);
    let (endpoint, ca, task) = server(200, issue_body(), move || async move {
        started_server.notify_one();
        release_server.notified().await;
    })
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-provider-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let store = MemoryStore::default();
    let request = issue_request();
    let fixture = authority_fixture().unwrap();
    let binding = client.request_secret_lease_binding(&request).unwrap();
    let first_grant = signed_grant(&fixture.signer, binding.clone(), "issue-one", 21).unwrap();
    let second_grant = signed_grant(&fixture.signer, binding, "issue-two", 22).unwrap();
    let consumed = AtomicBool::new(false);

    let first = client.request_secret_lease(
        &store,
        &fixture.authority,
        &first_grant,
        &request,
        |fields| {
            assert_eq!(fields.get("username"), Some(b"dynamic-user".as_slice()));
            assert_eq!(fields.get("password"), Some(b"dynamic-password".as_slice()));
            consumed.store(true, Ordering::Relaxed);
            Ok(())
        },
    );
    let second = async {
        started.notified().await;
        let result = client
            .request_secret_lease(
                &store,
                &fixture.authority,
                &second_grant,
                &request,
                |_| panic!("duplicate issuance reached consumer"),
            )
            .await;
        release.notify_one();
        result
    };
    let (first, second) = tokio::join!(first, second);

    let active = first.unwrap();
    assert_eq!(active.state, SecretLeaseState::Active);
    assert!(consumed.load(Ordering::Relaxed));
    assert_eq!(second, Err(BaoClientError::LeaseOperationAlreadyStarted));
    assert_eq!(
        store.load(&request.lease_key).await.unwrap().unwrap().state,
        SecretLeaseState::Active
    );

    let observed = task.await.unwrap().unwrap().to_ascii_lowercase();
    assert!(observed.starts_with("get /v1/database/creds/reader http/1.1\r\n"));
    assert!(observed.contains("x-vault-token: fixture-provider-token\r\n"));
    assert!(observed.contains("x-vault-namespace: team/one\r\n"));
}

#[tokio::test]
async fn lost_issue_response_enters_unknown_and_reconcile_never_reissues() {
    let (endpoint, ca, task) = server(200, issue_body(), || async {
        tokio::time::sleep(Duration::from_millis(250)).await;
    })
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-provider-token".into()).unwrap(),
        Duration::from_millis(80),
    )
    .unwrap();
    let store = MemoryStore::default();
    let request = issue_request();
    let fixture = authority_fixture().unwrap();
    let binding = client.request_secret_lease_binding(&request).unwrap();
    let grant = signed_grant(&fixture.signer, binding, "issue-timeout", 31).unwrap();

    assert_eq!(
        client
            .request_secret_lease(&store, &fixture.authority, &grant, &request, |_| {
                panic!("timed out response reached consumer")
            })
            .await,
        Err(BaoClientError::TimedOut)
    );
    let unknown = store.load(&request.lease_key).await.unwrap().unwrap();
    assert_eq!(unknown.state, SecretLeaseState::Unknown);
    assert_eq!(unknown.pending_operation, Some(SecretLeaseOperation::Issue));
    assert!(unknown.provider_lease_id.is_none());

    let reconcile = BaoLeaseReconcileRequest {
        lease_key: request.lease_key.clone(),
        operation_id: "operation:reconcile:one".into(),
        subject_id: request.subject_id.clone(),
        consumer_id: request.consumer_id.clone(),
    };
    let binding = client
        .reconcile_secret_lease_binding(&store, &reconcile)
        .await
        .unwrap();
    let grant = signed_grant(&fixture.signer, binding, "reconcile-one", 32).unwrap();
    assert_eq!(
        client
            .reconcile_secret_lease(&store, &fixture.authority, &grant, &reconcile)
            .await,
        Err(BaoClientError::ReconciliationRequired)
    );
    assert_eq!(
        store.load(&request.lease_key).await.unwrap().unwrap().state,
        SecretLeaseState::Unknown
    );
    task.await.unwrap().unwrap();
}

#[test]
fn lifecycle_binding_changes_when_secret_field_or_request_body_changes() {
    let certified = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()]).unwrap();
    let client = BaoClient::new(
        "https://localhost:8443/",
        certified.cert.pem().as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(1),
    )
    .unwrap();
    let request = issue_request();
    let original = client.request_secret_lease_binding(&request).unwrap();

    let mut changed = request.clone();
    changed.secret_fields.push("extra".into());
    let changed_fields = client.request_secret_lease_binding(&changed).unwrap();
    assert_ne!(original.request_sha256, changed_fields.request_sha256);

    let mut post = request;
    post.method = BaoLeaseIssueMethod::Post;
    post.request_body
        .insert("ttl".into(), Zeroizing::new("30s".into()));
    let changed_body = client.request_secret_lease_binding(&post).unwrap();
    assert_ne!(original.request_sha256, changed_body.request_sha256);
}

#[test]
fn invalid_final_use_signature_is_rejected_before_durable_issue() {
    let certified = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()]).unwrap();
    let client = BaoClient::new(
        "https://localhost:8443/",
        certified.cert.pem().as_bytes(),
        BaoToken::new("fixture".into()).unwrap(),
        Duration::from_secs(1),
    )
    .unwrap();
    let request = issue_request();
    let store = MemoryStore::default();
    let fixture = authority_fixture().unwrap();
    let binding = client.request_secret_lease_binding(&request).unwrap();
    let mut grant = signed_grant(&fixture.signer, binding, "bad-signature", 41).unwrap();
    grant.signature[0] ^= 1;

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    assert_eq!(
        runtime.block_on(client.request_secret_lease(
            &store,
            &fixture.authority,
            &grant,
            &request,
            |_| Ok(()),
        )),
        Err(BaoClientError::Authority(FinalUseError::InvalidSignature))
    );
    assert!(runtime.block_on(store.load(&request.lease_key)).unwrap().is_none());
}
