use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::ProductEffectPreparationRequestV1;
use codex_hepta_automation::TaskFlowError;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register agent").layout;
        Self {
            _temp: temp,
            layout,
        }
    }
}

fn fence(generation: u64) -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        "agentd.automation-effect",
        generation,
        generation,
        format!("effect-fence-{generation}"),
    )
    .expect("fence")
}

fn request(generation: u64, provider: &str) -> ProductEffectPreparationRequestV1 {
    ProductEffectPreparationRequestV1 {
        operation_id: "deliver:review-result".to_string(),
        subject_id: AGENT_ID.to_string(),
        destination_id: "provider:fixture".to_string(),
        payload_digest: Sha256Digest::for_bytes(b"exact-provider-wire"),
        final_use_scope_digest: Sha256Digest::for_bytes(b"automation-effect-scope"),
        policy_generation: generation,
        expected_predecessor_digest: Some(Sha256Digest::for_bytes(b"prior-effect")),
        compensation_for: None,
        provider_scope: provider.to_string(),
        provider_profile_digest: Sha256Digest::for_bytes(provider.as_bytes()),
    }
}

#[tokio::test]
async fn product_prepare_is_durable_idempotent_and_freezes_the_claimed_step() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let request = request(1, "provider-effect:v1:original");
    let prepared = store
        .prepare_product_effect_v1(&request, &fence(1), 100, 60_000)
        .await
        .expect("prepare product effect");
    let replay = store
        .prepare_product_effect_v1(&request, &fence(1), 101, 60_000)
        .await
        .expect("idempotent prepare");
    assert_eq!(replay, prepared);

    let run = store
        .taskflow_run(&prepared.intent.run_id)
        .await
        .expect("read run")
        .expect("run exists");
    assert_eq!(run.state, TaskFlowRunState::Running);
    let step = store
        .read_taskflow_step(
            &prepared.intent.run_id,
            &prepared.intent.step_id,
            prepared.intent.attempt,
            &fence(1),
        )
        .await
        .expect("read step")
        .expect("step exists");
    assert_eq!(step.state, TaskFlowStepState::Claimed);

    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let durable = reopened
        .product_effect_preparation_by_attempt(
            &prepared.intent.run_id,
            &prepared.intent.step_id,
            prepared.intent.attempt,
        )
        .await
        .expect("read durable preparation")
        .expect("preparation exists");
    assert_eq!(durable, prepared);
}

#[tokio::test]
async fn product_prepare_rejects_semantic_substitution_but_retains_original_profile() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let original = request(1, "provider-effect:v1:original");
    let prepared = store
        .prepare_product_effect_v1(&original, &fence(1), 100, 60_000)
        .await
        .expect("prepare product effect");

    let mut changed_payload = request(2, "provider-effect:v1:rotated");
    changed_payload.payload_digest = Sha256Digest::for_bytes(b"substituted-provider-wire");
    assert!(matches!(
        store
            .prepare_product_effect_v1(&changed_payload, &fence(2), 200, 60_000)
            .await,
        Err(TaskFlowError::Conflict(_))
    ));

    let rotated_host = request(2, "provider-effect:v1:rotated");
    let replay = store
        .prepare_product_effect_v1(&rotated_host, &fence(2), 200, 60_000)
        .await
        .expect("original preparation survives host rotation");
    assert_eq!(replay, prepared);
    assert_ne!(replay.provider_key, "provider-effect:v1:rotated");
    assert_eq!(replay.prepared_generation, 1);
}

#[tokio::test]
async fn interrupted_preparation_keeps_original_semantics_and_resumes_same_claim() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let pool = codex_state::open_durable_sqlite_pool(store.path(), 1)
        .await
        .expect("fixture SQL");
    sqlx::query("CREATE TRIGGER test_pause_product_claim BEFORE INSERT ON taskflow_step_outbox WHEN NEW.event_kind = 'claimed' BEGIN SELECT RAISE(ABORT, 'injected pre-contact crash cut'); END")
        .execute(&pool).await.expect("inject claim failure");
    let original = request(1, "provider:original");
    assert!(
        store
            .prepare_product_effect_v1(&original, &fence(1), 100, 60_000)
            .await
            .is_err()
    );
    let reserved = store
        .product_effect_preparation_by_operation(&original.operation_id)
        .await
        .expect("reservation lookup")
        .expect("intent survives");
    assert_eq!(reserved.intent.payload_digest, original.payload_digest);
    let mut changed = original.clone();
    changed.payload_digest = Sha256Digest::for_bytes(b"replacement after crash");
    assert!(
        store
            .prepare_product_effect_v1(&changed, &fence(1), 101, 60_000)
            .await
            .is_err()
    );
    sqlx::query("DROP TRIGGER test_pause_product_claim")
        .execute(&pool)
        .await
        .expect("remove fault");
    pool.close().await;
    let resumed = store
        .prepare_product_effect_v1(&original, &fence(1), 102, 60_000)
        .await
        .expect("resume original step");
    assert_eq!(resumed, reserved);
    assert!(
        store
            .pending_authorized_taskflow_effects(16)
            .await
            .expect("no provider contact")
            .is_empty()
    );
}

#[cfg(unix)]
#[tokio::test]
async fn mutable_preparation_cannot_change_provider_key_or_burn_the_valid_grant() {
    use codex_hepta_automation::AsyncAuthorizedEffectDriver;
    use codex_hepta_automation::AuthorizedEffectFuture;
    use codex_hepta_automation::AuthorizedEffectOutcome;
    use codex_hepta_automation::AuthorizedEffectProviderReceipt;
    use codex_hepta_automation::AuthorizedProviderEffectRequest;
    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::ProviderEffectKey;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;
    struct Driver {
        calls: usize,
        expected_key: String,
    }
    impl AsyncAuthorizedEffectDriver for Driver {
        fn dispatch<'a>(
            &'a mut self,
            request: AuthorizedProviderEffectRequest<'a>,
        ) -> AuthorizedEffectFuture<'a> {
            Box::pin(async move {
                assert_eq!(request.provider_intent.key.as_str(), self.expected_key);
                self.calls += 1;
                Ok(AuthorizedEffectProviderReceipt {
                    outcome: AuthorizedEffectOutcome::Succeeded,
                    receipt_digest: Sha256Digest::for_bytes(b"fixture terminal"),
                })
            })
        }
    }
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time")
            .as_millis(),
    )
    .expect("millis");
    let prepared = store
        .prepare_product_effect_v1(&request(1, "provider:original"), &fence(1), now, 60_000)
        .await
        .expect("prepare");
    let binding = prepared.intent.final_use_binding().expect("binding");
    let issuer = SigningKey::from_bytes(&[47; 32]);

    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch: 9,
        grant_id: "preparation-integrity-fixture".into(),
        nonce: [71; 32],
        binding: binding.clone(),
        not_before_unix_ms: now - 1_000,
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("bytes"))
        .to_bytes()
        .to_vec();
    let signed = SignedFinalUseGrant { grant, signature };
    let directory = tempfile::tempdir().expect("authority");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private authority");
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "security-owner".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let mut driver = Driver {
        calls: 0,
        expected_key: prepared.provider_key.clone(),
    };
    let mut forged = prepared.clone();
    forged.provider_key =
        ProviderEffectKey::for_operation("different-provider", "different-run", "effect")
            .expect("key")
            .as_str()
            .to_string();
    assert!(
        store
            .execute_prepared_product_effect_async(
                &mut driver,
                &forged,
                codex_hepta_automation::AuthorizedEffectDispatch {
                    authority: &authority,
                    intent: &forged.intent,
                    wire_payload: b"exact-provider-wire",
                    fence: &fence(1),
                    signed_grant: &signed,
                    expected_binding: &binding,
                    command_id: "effect-command",
                    now_ms: 104
                }
            )
            .await
            .is_err()
    );
    assert_eq!(driver.calls, 0);
    store
        .execute_prepared_product_effect_async(
            &mut driver,
            &prepared,
            codex_hepta_automation::AuthorizedEffectDispatch {
                authority: &authority,
                intent: &prepared.intent,
                wire_payload: b"exact-provider-wire",
                fence: &fence(1),
                signed_grant: &signed,
                expected_binding: &binding,
                command_id: "effect-command",
                now_ms: now + 5,
            },
        )
        .await
        .expect("unchanged preparation retains grant");
    assert_eq!(driver.calls, 1);
}

#[tokio::test]
async fn expired_uncontacted_preparation_reclaims_with_same_key_and_new_attempt() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let original = store
        .prepare_product_effect_v1(&request(1, "provider:original"), &fence(1), 100, 10)
        .await
        .expect("prepare");
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let next = reopened
        .prepare_product_effect_v1(&request(2, "provider:original"), &fence(2), 200, 60_000)
        .await
        .expect("reclaim uncontacted preparation");
    assert_eq!(next.intent.attempt, 2);
    assert_eq!(next.provider_key, original.provider_key);
    assert_eq!(next.intent.operation_id, original.intent.operation_id);
    assert_eq!(next.intent.payload_digest, original.intent.payload_digest);
    assert_eq!(
        reopened
            .product_effect_preparation_by_attempt(
                &original.intent.run_id,
                &original.intent.step_id,
                1
            )
            .await
            .expect("original lookup")
            .expect("original retained"),
        original
    );
    let run = reopened
        .taskflow_run(&next.intent.run_id)
        .await
        .expect("run")
        .expect("run exists");
    assert_eq!(run.generation, Some(2));
    assert!(
        reopened
            .pending_authorized_taskflow_effects(32)
            .await
            .expect("no contact")
            .is_empty()
    );
}
