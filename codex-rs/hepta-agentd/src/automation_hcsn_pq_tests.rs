#![allow(
    clippy::expect_used,
    reason = "local PQ authority and process-contact fixtures"
)]

use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_automation::AuthorizedEffectDispatchRequest;
use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::HcsnJobIdentityV1;
use codex_hepta_automation::HcsnSupervisorCommandV1;
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::VerifiedUseToken;
use serde_json::Value;

use super::super::tests::Fixture as AgentFixture;
use super::*;

#[path = "automation_hcsn_pq_fixture.rs"]
mod fixture;
#[path = "automation_hcsn_pq_real_worker.rs"]
mod real_worker;
#[path = "automation_hcsn_source_host_tests.rs"]
mod source_tests;
#[path = "automation_hcsn_pq_test_support.rs"]
mod support;

use fixture::PqFixture;

const NOW: u64 = 1_800_000_000_000;
const SCOPE: &str = "provider:hcsn:pq-test";
const WIRE: &[u8] = b"{\"bounded_cpu_test_peer\":true}";
const COMMAND: &str = "hcsn-pq-test-dispatch";

#[tokio::test]
async fn explicit_pq_host_binds_deployment_and_rejects_downgrade_before_trust_contact()
-> anyhow::Result<()> {
    let mut fixture = PqFixture::new().await?;
    let original = fixture.config.clone();
    for (pointer, value) in [
        (
            "/authority_profile",
            serde_json::json!("engineering_ed25519_v1"),
        ),
        ("/schema_version", serde_json::json!(2)),
        ("/deployment_key/key_id", serde_json::json!("")),
        (
            "/deployment_key/key_id",
            serde_json::json!("invalid key id"),
        ),
        ("/deployment_key/key_id", serde_json::json!("x".repeat(129))),
        (
            "/deployment_key/not_before_authority_epoch",
            serde_json::json!(0),
        ),
        (
            "/deployment_key/not_after_authority_epoch",
            serde_json::json!(0),
        ),
        (
            "/deployment/contract_id",
            serde_json::json!("substituted-contract"),
        ),
        ("/deployment/authority_epoch", serde_json::json!(10)),
        (
            "/deployment/provider_scope",
            serde_json::json!("provider:substituted"),
        ),
        (
            "/deployment/final_use_scope_sha256",
            serde_json::json!(Sha256Digest::for_bytes(b"substituted")),
        ),
        ("/deployment/timeout_ms", serde_json::json!(1_999)),
        (
            "/deployment/python_executable",
            serde_json::json!("/substituted/python"),
        ),
        (
            "/deployment/python_sha256",
            serde_json::json!(Sha256Digest::for_bytes(b"substituted binary")),
        ),
        (
            "/deployment/repository_root",
            serde_json::json!("/substituted/repository"),
        ),
        (
            "/deployment/supervisor_sha256",
            serde_json::json!(Sha256Digest::for_bytes(b"substituted supervisor")),
        ),
        (
            "/deployment/durable_root",
            serde_json::json!("/substituted/store"),
        ),
        (
            "/deployment_signature/0",
            serde_json::json!(
                original["deployment_signature"][0]
                    .as_u64()
                    .expect("signature byte")
                    ^ 1
            ),
        ),
    ] {
        fixture.config = original.clone();
        *fixture.config.pointer_mut(pointer).expect("existing field") = value;
        fixture.write_config()?;
        assert!(
            AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path)
                .is_err(),
            "accepted {pointer}"
        );
        assert_eq!(
            fixture.trust_requests(),
            0,
            "rejected deployment must not contact trust services"
        );
        assert!(!fixture.marker.exists());
        assert!(
            !fixture
                .agent
                .identity
                .layout
                .automation_root()
                .join("final-use-authority")
                .exists()
        );
    }
    fixture.config = original.clone();
    fixture
        .config
        .as_object_mut()
        .expect("configuration")
        .remove("authority_profile");
    fixture.write_config()?;
    assert!(
        AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path).is_err()
    );
    fixture.config = original;
    fixture.config["final_use"]["issuer_keys"][0] = fixture.config["deployment_key"].clone();
    fixture.write_config()?;
    assert!(
        AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path).is_err()
    );
    assert_eq!(
        fixture.trust_requests(),
        0,
        "shared role key must fail before external IO"
    );
    fixture.agent.store.close().await;
    Ok(())
}

#[tokio::test]
async fn pq_host_contacts_pinned_peer_and_reads_settled_terminal_without_feed() -> anyhow::Result<()>
{
    let fixture = PqFixture::new().await?;
    let host = AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path)?;
    assert_eq!(
        host.authority.authentication_profile(),
        FinalUseAuthenticationProfile::MlDsa65V2
    );
    let (intent, _) = fixture.prepare().await?;
    let grant = fixture.grant(&intent)?;
    let terminal = host
        .execute(&fixture.agent.store, &intent, WIRE, &grant, COMMAND, NOW)
        .await?;
    assert_eq!(terminal.observation, Some(TaskFlowStepObservation::Failed));
    let contacts = fs::read(&fixture.marker)?;
    assert_eq!(String::from_utf8(contacts.clone())?.lines().count(), 1);
    let contact: HcsnSupervisorCommandV1 = serde_json::from_slice(&contacts)?;
    let expected = HcsnSupervisorCommandV1::start(
        HcsnJobIdentityV1::for_taskflow(
            SCOPE,
            &intent.run_id,
            &intent.step_id,
            intent.payload_digest.clone(),
        )?,
        String::from_utf8(WIRE.to_vec())?,
    )?;
    assert_eq!(contact, expected);
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
    fixture.agent.store.close().await;
    let reopened = AutomationStore::open(&fixture.agent.identity.layout).await?;
    assert_eq!(
        reopened
            .read_authorized_taskflow_effect_receipt(&intent, COMMAND)
            .await?,
        Some(terminal.clone())
    );
    fs::remove_file(&fixture.feed_path)?;
    fixture.now.store(NOW + 120_000, Ordering::SeqCst);
    let trust_before = fixture.trust_requests();
    assert_eq!(
        host.execute(&reopened, &intent, WIRE, &grant, COMMAND, NOW + 120_000)
            .await?,
        terminal
    );
    assert_eq!(fixture.trust_requests(), trust_before);
    assert_eq!(fs::read(&fixture.marker)?, contacts);
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn pq_host_rejects_tampered_feed_and_grant_before_provider_and_nonce_use()
-> anyhow::Result<()> {
    let fixture = PqFixture::new().await?;
    let host = AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path)?;
    let (intent, _) = fixture.prepare().await?;
    let grant = fixture.grant(&intent)?;
    let mut feed: Value = serde_json::from_slice(&fs::read(&fixture.feed_path)?)?;
    feed["signature"][0] =
        serde_json::json!(feed["signature"][0].as_u64().expect("signature byte") ^ 1);
    support::write_private(&fixture.feed_path, &serde_json::to_vec(&feed)?)?;
    assert!(
        host.execute(&fixture.agent.store, &intent, WIRE, &grant, COMMAND, NOW)
            .await
            .is_err()
    );
    fixture.publish_feed(fixture.head.clone(), NOW + 60_000)?;
    let mut invalid = grant.clone();
    invalid.signature[0] ^= 1;
    assert!(
        host.execute(&fixture.agent.store, &intent, WIRE, &invalid, COMMAND, NOW)
            .await
            .is_err()
    );
    assert!(!fixture.marker.exists());
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    assert!(
        fixture
            .agent
            .store
            .pending_authorized_taskflow_effects(8)
            .await?
            .is_empty()
    );
    fixture.agent.store.close().await;
    Ok(())
}

#[tokio::test]
async fn pq_host_rejects_expired_feed_and_changed_supervisor_pins_before_dispatch()
-> anyhow::Result<()> {
    for fault in ["expired-feed", "changed-source"] {
        let fixture = PqFixture::new().await?;
        let host = AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path)?;
        let (intent, _) = fixture.prepare().await?;
        let grant = fixture.grant(&intent)?;
        match fault {
            "expired-feed" => fixture.now.store(NOW + 60_000, Ordering::SeqCst),
            "changed-source" => {
                support::write_private(&fixture.script, b"raise RuntimeError('tampered pin')\n")?
            }
            _ => unreachable!("closed fault set"),
        }
        assert!(
            host.execute(&fixture.agent.store, &intent, WIRE, &grant, COMMAND, NOW)
                .await
                .is_err(),
            "accepted {fault}"
        );
        assert!(!fixture.marker.exists());
        assert_eq!(host.authority.capacity()?.used_nonces, 0);
        fixture.agent.store.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn authenticated_old_head_cannot_bind_a_newer_final_use_claim() -> anyhow::Result<()> {
    let fixture = PqFixture::new().await?;
    let host = AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path)?;
    let (intent, fence) = fixture.prepare().await?;
    let grant = fixture.grant(&intent)?;
    let gate = host.pq_gate.as_ref().expect("PQ host gate");
    let lease = gate.authenticate(&host.authority, &fixture.feed_path, &grant)?;
    let mut newer = fixture.head.clone();
    newer.revision += 1;
    fixture.publish_feed(newer, NOW + 60_000)?;
    host.refresh_revocations()?;
    let EffectProvider::Hcsn(provider) = &host.adapter else {
        panic!("HCSN provider");
    };
    let mut driver = provider.driver_with_lease(
        &intent.operation_id,
        lease,
        Arc::clone(gate),
        host.authority.clone(),
        fixture.feed_path.clone(),
        grant.clone(),
    )?;
    let result = fixture
        .agent
        .store
        .execute_authorized_taskflow_effect(
            &host.authority,
            &mut driver,
            AuthorizedEffectDispatchRequest {
                intent: &intent,
                wire_payload: WIRE,
                fence: &fence,
                signed_grant: &grant,
                expected_binding: &intent.final_use_binding()?,
                command_id: COMMAND,
                now_ms: NOW,
            },
        )
        .await;
    assert!(matches!(
        result,
        Err(AuthorizedEffectError::Driver(
            AuthorizedEffectDriverError::BeforeProviderContact
        ))
    ));
    assert!(!fixture.marker.exists());
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
    assert_eq!(
        fs::read_dir(&provider.requests_root)?.count(),
        0,
        "wrong head must fail before request retention"
    );
    fixture.agent.store.close().await;
    Ok(())
}

struct ChangeAfterEntry {
    inner: hcsn::RetainedDriver,
    change: Box<dyn FnMut()>,
    entered: bool,
}

impl AuthorizedEffectDriver for ChangeAfterEntry {
    fn prepare_claim(
        &mut self,
        token: &VerifiedUseToken,
    ) -> Result<(), AuthorizedEffectDriverError> {
        self.inner.prepare_claim(token)
    }

    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        self.entered = true;
        (self.change)();
        self.inner.dispatch(request)
    }
}

#[tokio::test]
async fn pq_hcsn_rechecks_clock_frontier_and_signed_feed_after_token_entry_before_spawn()
-> anyhow::Result<()> {
    for fault in ["expiry", "external-frontier", "signed-feed-revocation"] {
        let fixture = PqFixture::new().await?;
        let host = AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path)?;
        let (intent, fence) = fixture.prepare().await?;
        let grant = fixture.grant(&intent)?;
        let gate = host.pq_gate.as_ref().expect("PQ gate");
        let lease = gate.authenticate(&host.authority, &fixture.feed_path, &grant)?;
        let EffectProvider::Hcsn(provider) = &host.adapter else {
            panic!("HCSN provider");
        };
        let inner = provider.driver_with_lease(
            &intent.operation_id,
            lease,
            Arc::clone(gate),
            host.authority.clone(),
            fixture.feed_path.clone(),
            grant.clone(),
        )?;
        let now = Arc::clone(&fixture.now);
        let frontier = fixture.root.path().join("frontier.json");
        let feed = fixture.feed_path.clone();
        let mut revoked = fixture.head.clone();
        revoked.revision += 1;
        revoked
            .revoked_grant_ids
            .insert(grant.grant.grant_id.clone());
        let signed_revocation = fixture.feed_bytes(revoked, NOW + 60_000)?;
        let changed_feed = signed_revocation.clone();
        let change = Box::new(move || match fault {
            "expiry" => now.store(NOW + 30_000, Ordering::SeqCst),
            "external-frontier" => {
                let mut next: FinalUseFrontier =
                    serde_json::from_slice(&fs::read(&frontier).expect("frontier"))
                        .expect("frontier JSON");
                next.state_sha256[0] ^= 1;
                support::write_private(
                    &frontier,
                    &serde_json::to_vec(&next).expect("new frontier"),
                )
                .expect("advance fixture frontier");
            }
            "signed-feed-revocation" => support::write_private(&feed, &signed_revocation)
                .expect("publish revoked feed after entry"),
            _ => unreachable!("closed fault set"),
        });
        let mut driver = ChangeAfterEntry {
            inner,
            change,
            entered: false,
        };
        let result = fixture
            .agent
            .store
            .execute_authorized_taskflow_effect(
                &host.authority,
                &mut driver,
                AuthorizedEffectDispatchRequest {
                    intent: &intent,
                    wire_payload: WIRE,
                    fence: &fence,
                    signed_grant: &grant,
                    expected_binding: &intent.final_use_binding()?,
                    command_id: COMMAND,
                    now_ms: NOW,
                },
            )
            .await;
        assert!(
            driver.entered,
            "fault must occur inside the original token callback"
        );
        assert!(
            matches!(
                result,
                Err(AuthorizedEffectError::Driver(
                    AuthorizedEffectDriverError::BeforeProviderContact
                ))
            ),
            "accepted {fault}"
        );
        assert!(!fixture.marker.exists());
        assert_eq!(host.authority.capacity()?.used_nonces, 1);
        assert_eq!(
            fs::read_dir(&provider.requests_root)?.count(),
            1,
            "reach retained dispatch before the final transport guard"
        );
        if fault == "signed-feed-revocation" {
            assert_eq!(fs::read(&fixture.feed_path)?, changed_feed);
            assert_eq!(
                host.authority.revocation_head()?,
                fixture.head,
                "active effect blocks the successor feed instead of dispatching under stale trust"
            );
        }
        fixture.agent.store.close().await;
    }
    Ok(())
}
