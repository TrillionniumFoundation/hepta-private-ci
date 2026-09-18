#[cfg(unix)]
mod unix {
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;
    use std::time::Duration;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_bao_adapter::BaoClient;
    use codex_hepta_bao_adapter::BaoFinalUseHost;
    use codex_hepta_bao_adapter::BaoFinalUseHostError;
    use codex_hepta_bao_adapter::BaoReadRequest;
    use codex_hepta_bao_adapter::BaoToken;
    use codex_hepta_bao_adapter::RegisteredBaoConsumer;
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

    struct Fixture {
        client: BaoClient,
        host: BaoFinalUseHost,
        request: BaoReadRequest,
        grant: SignedFinalUseGrant,
        approval: SignedFinalUseApproval,
        approver: SigningKey,
        _state: tempfile::TempDir,
    }

    fn fixture(request_consumer: &str, registered_consumer: &str) -> Fixture {
        let cert = rcgen::generate_simple_self_signed(vec!["localhost".to_owned()]).unwrap();
        let client = BaoClient::new(
            "https://localhost:9/",
            cert.cert.pem().as_bytes(),
            BaoToken::new("fixture-token".into()).unwrap(),
            Duration::from_millis(50),
        )
        .unwrap();
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
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".into(),
            authority_epoch: 5,
            grant_id: "host-read".into(),
            nonce: [21; 32],
            binding: client.binding(&request).unwrap(),
            not_before_unix_ms: now - 1_000,
            expires_at_unix_ms: now + 30_000,
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
        let authority = FinalUseAuthority::open_state_dir(
            state.path(),
            "security-owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 5,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
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
        let consumer =
            RegisteredBaoConsumer::new(registered_consumer.into(), Arc::new(|_| Ok(()))).unwrap();
        let host = BaoFinalUseHost::new(
            authority,
            approval_verifier,
            revocation_verifier,
            Arc::new(SystemAuthorityClock),
            [consumer],
        )
        .unwrap();
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
                .sign(&bootstrap.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            update: bootstrap,
        };
        host.apply_revocation_update(&bootstrap).unwrap();
        let approval =
            FinalUseApproval::for_grant("operator-approver".into(), &grant.grant).unwrap();
        let approval = SignedFinalUseApproval {
            signature: approver
                .sign(&approval.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            approval,
        };
        Fixture {
            client,
            host,
            request,
            grant,
            approval,
            approver,
            _state: state,
        }
    }

    #[tokio::test]
    async fn unregistered_signed_consumer_is_denied_before_network_dispatch() {
        let fixture = fixture("not-enrolled", "model-provider");
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
    async fn forged_independent_approval_is_denied_before_network_dispatch() {
        let mut fixture = fixture("model-provider", "model-provider");
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
