#[cfg(unix)]
mod unix {
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;
    use std::time::Duration;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_bao_adapter::BaoClient;
    use codex_hepta_bao_adapter::BaoFinalUseHost;
    use codex_hepta_bao_adapter::BaoFinalUseHostError;
    use codex_hepta_bao_adapter::BaoReadRequest;
    use codex_hepta_bao_adapter::BaoToken;
    use codex_hepta_bao_adapter::RegisteredBaoConsumer;
    use codex_hepta_contracts::AuthorityClock;
    use codex_hepta_contracts::AuthorityTrustError;
    use codex_hepta_contracts::FinalUseApproval;
    use codex_hepta_contracts::FinalUseApprovalVerifier;
    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseControlError;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
    use codex_hepta_contracts::FinalUseRevocationUpdate;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseApproval;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
    use codex_hepta_contracts::SystemAuthorityClock;
    use codex_hepta_types::Digest32;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;
    use tokio::net::TcpListener;
    use tokio_rustls::TlsAcceptor;

    type TestError = Box<dyn std::error::Error + Send + Sync>;

    #[derive(Debug)]
    struct ManualClock(AtomicU64);

    impl ManualClock {
        fn new(now_unix_ms: u64) -> Self {
            Self(AtomicU64::new(now_unix_ms))
        }

        fn set(&self, now_unix_ms: u64) {
            self.0.store(now_unix_ms, Ordering::SeqCst);
        }
    }

    impl AuthorityClock for ManualClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(self.0.load(Ordering::SeqCst))
        }
    }

    async fn delayed_server(
        body: String,
        before_body: impl FnOnce() + Send + 'static,
    ) -> Result<
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
            rustls::pki_types::PrivatePkcs8KeyDer::from(certified.signing_key.serialize_der())
                .into(),
        )?;
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let endpoint = format!("https://localhost:{}/", listener.local_addr()?.port());
        let task = tokio::spawn(async move {
            let (socket, _) = listener.accept().await?;
            let mut stream = TlsAcceptor::from(Arc::new(config)).accept(socket).await?;
            let mut bytes = Vec::new();
            while !bytes.ends_with(b"\r\n\r\n") && bytes.len() < 16 * 1024 {
                bytes.push(stream.read_u8().await?);
            }
            let headers = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            stream.write_all(headers.as_bytes()).await?;
            before_body();
            stream.write_all(body.as_bytes()).await?;
            Ok::<(), TestError>(())
        });
        Ok((endpoint, pem, task))
    }

    struct Fixture {
        client: BaoClient,
        host: BaoFinalUseHost,
        request: BaoReadRequest,
        grant: SignedFinalUseGrant,
        approval: SignedFinalUseApproval,
        approver: SigningKey,
        _state: tempfile::TempDir,
    }

    fn fixture(request_consumer: &str, registered_consumer: &str) -> Result<Fixture, TestError> {
        let cert = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()])?;
        let client = BaoClient::new(
            "https://localhost:9/",
            cert.cert.pem().as_bytes(),
            BaoToken::new("fixture-token".into())?,
            Duration::from_millis(50),
        )?;
        let request = BaoReadRequest {
            subject_id: "agent-one".into(),
            consumer_id: request_consumer.into(),
            namespace: "team/one".into(),
            mount: "secret".into(),
            path: "provider/token".into(),
            field: "value".into(),
            version: 1,
            expected_secret_sha256: Digest32::of_bytes(b"expected-secret").into_array(),
        };

        let issuer = SigningKey::from_bytes(&[71; 32]);
        let approver = SigningKey::from_bytes(&[72; 32]);
        let distributor = SigningKey::from_bytes(&[73; 32]);
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".into(),
            authority_epoch: 5,
            grant_id: "host-read".into(),
            nonce: [21; 32],
            binding: client.binding(&request)?,
            not_before_unix_ms: now - 1_000,
            expires_at_unix_ms: now + 30_000,
        };
        let grant = SignedFinalUseGrant {
            signature: issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec(),
            grant,
        };

        let state = tempfile::tempdir()?;
        std::fs::set_permissions(state.path(), std::fs::Permissions::from_mode(0o700))?;
        let authority = FinalUseAuthority::open_state_dir(
            state.path(),
            "security-owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 5,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        let approval_verifier = FinalUseApprovalVerifier::new(
            "operator-approver".into(),
            approver.verifying_key().to_bytes(),
        )?;
        let revocation_verifier = FinalUseRevocationFeedVerifier::new(
            "revocation-distributor".into(),
            distributor.verifying_key().to_bytes(),
        )?;
        let consumer =
            RegisteredBaoConsumer::new(registered_consumer.into(), Arc::new(|_| Ok(())))?;
        let host = BaoFinalUseHost::new(
            authority,
            approval_verifier,
            revocation_verifier,
            Arc::new(SystemAuthorityClock),
            [consumer],
        )?;
        let bootstrap = FinalUseRevocationUpdate::new(
            "revocation-distributor".into(),
            FinalUseRevocations {
                authority_epoch: 5,
                revision: 2,
                revoked_grant_ids: BTreeSet::new(),
            },
            now - 1_000,
            now + 30_000,
        );
        let bootstrap = SignedFinalUseRevocationUpdate {
            signature: distributor
                .sign(&bootstrap.signing_bytes()?)
                .to_bytes()
                .to_vec(),
            update: bootstrap,
        };
        host.apply_revocation_update(&bootstrap)?;
        let approval = FinalUseApproval::for_grant("operator-approver".into(), &grant.grant)?;
        let approval = SignedFinalUseApproval {
            signature: approver
                .sign(&approval.signing_bytes()?)
                .to_bytes()
                .to_vec(),
            approval,
        };
        Ok(Fixture {
            client,
            host,
            request,
            grant,
            approval,
            approver,
            _state: state,
        })
    }

    #[tokio::test]
    async fn unregistered_signed_consumer_is_denied_before_network_dispatch() {
        let fixture = fixture("not-enrolled", "model-provider").unwrap();
        assert_eq!(
            fixture
                .host
                .consume_kv_v2(
                    &fixture.client,
                    &fixture.grant,
                    &fixture.approval,
                    &fixture.request,
                )
                .await,
            Err(BaoFinalUseHostError::UnregisteredConsumer)
        );
    }

    #[tokio::test]
    async fn feed_expiry_during_provider_io_denies_final_consumer_entry() {
        const SECRET: &str = "registered-secret";
        let clock = Arc::new(ManualClock::new(10_000));
        let advance_clock = Arc::clone(&clock);
        let body = serde_json::json!({"data":{"data":{"value":SECRET},"metadata":{"version":1}}})
            .to_string();
        let (endpoint, ca, task) = delayed_server(body, move || advance_clock.set(11_000))
            .await
            .unwrap();
        let client = BaoClient::new(
            &endpoint,
            ca.as_bytes(),
            BaoToken::new("fixture-provider-token".into()).unwrap(),
            Duration::from_secs(2),
        )
        .unwrap();
        let request = BaoReadRequest {
            subject_id: "agent-one".into(),
            consumer_id: "model-provider".into(),
            namespace: "team/one".into(),
            mount: "secret".into(),
            path: "provider/token".into(),
            field: "value".into(),
            version: 1,
            expected_secret_sha256: Digest32::of_bytes(SECRET.as_bytes()).into_array(),
        };

        let issuer = SigningKey::from_bytes(&[81; 32]);
        let approver = SigningKey::from_bytes(&[82; 32]);
        let distributor = SigningKey::from_bytes(&[83; 32]);
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".into(),
            authority_epoch: 6,
            grant_id: "host-read-expiring-feed".into(),
            nonce: [31; 32],
            binding: client.binding(&request).unwrap(),
            not_before_unix_ms: 9_000,
            expires_at_unix_ms: 20_000,
        };
        let grant = SignedFinalUseGrant {
            signature: issuer
                .sign(&grant.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            grant,
        };

        let state = tempfile::tempdir().unwrap();
        std::fs::set_permissions(state.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            state.path(),
            "security-owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 6,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            clock.clone(),
        )
        .unwrap();
        let approval_verifier = FinalUseApprovalVerifier::new(
            "operator-approver".into(),
            approver.verifying_key().to_bytes(),
        )
        .unwrap();
        let revocation_verifier = FinalUseRevocationFeedVerifier::new(
            "revocation-distributor".into(),
            distributor.verifying_key().to_bytes(),
        )
        .unwrap();

        let consumed = Arc::new(AtomicBool::new(false));
        let consumed_in_callback = Arc::clone(&consumed);
        let consumer = RegisteredBaoConsumer::new(
            "model-provider".into(),
            Arc::new(move |_| {
                consumed_in_callback.store(true, Ordering::SeqCst);
                Ok(())
            }),
        )
        .unwrap();
        let host = BaoFinalUseHost::new(
            authority,
            approval_verifier,
            revocation_verifier,
            clock,
            [consumer],
        )
        .unwrap();

        let update = FinalUseRevocationUpdate::new(
            "revocation-distributor".into(),
            FinalUseRevocations {
                authority_epoch: 6,
                revision: 2,
                revoked_grant_ids: BTreeSet::new(),
            },
            9_500,
            10_500,
        );
        let update = SignedFinalUseRevocationUpdate {
            signature: distributor
                .sign(&update.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            update,
        };
        host.apply_revocation_update(&update).unwrap();

        let approval =
            FinalUseApproval::for_grant("operator-approver".into(), &grant.grant).unwrap();
        let approval = SignedFinalUseApproval {
            signature: approver
                .sign(&approval.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            approval,
        };

        assert_eq!(
            host.consume_kv_v2(&client, &grant, &approval, &request)
                .await,
            Err(BaoFinalUseHostError::StaleRevocationFeed)
        );
        assert!(!consumed.load(Ordering::SeqCst));
        task.await.unwrap().unwrap();
    }

    #[tokio::test]
    async fn forged_independent_approval_is_denied_before_network_dispatch() {
        let mut fixture = fixture("model-provider", "model-provider").unwrap();
        let attacker = SigningKey::from_bytes(&[99; 32]);
        fixture.approval.signature = attacker
            .sign(&fixture.approval.approval.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        assert_eq!(
            fixture
                .host
                .consume_kv_v2(
                    &fixture.client,
                    &fixture.grant,
                    &fixture.approval,
                    &fixture.request,
                )
                .await,
            Err(BaoFinalUseHostError::Control(
                FinalUseControlError::InvalidSignature
            ))
        );
        let _ = fixture.approver;
    }
}
