//! Fleet, FinalUse and durable TaskFlow fixtures, following authorized_effect.rs.

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AsyncAuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDispatchRequest;
use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sha2::Digest;
use sha2::Sha256;

pub const DESTINATION: &str = "provider:act1";
const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
static NONCE: AtomicU64 = AtomicU64::new(1);

pub struct Harness {
    pub store: AutomationStore,
    pub effect: AuthorizedEffectIntent,
    pub wire: Vec<u8>,
    pub fence: TaskFlowFence,
    pub binding: FinalUseBinding,
    pub authority: FinalUseAuthority,
    pub grant: SignedFinalUseGrant,
}

pub fn layout(root: &Path) -> HeptaAgentLayout {
    HeptaFleetRoot::parse(root.join("fleet"))
        .expect("fleet root")
        .layout()
        .agent(&AgentId::parse(AGENT_ID).expect("agent id"))
}

pub fn key() -> ProviderEffectKey {
    ProviderEffectKey::for_logical_effect(DESTINATION, "taskflow:act1-run:effect")
        .expect("stable original operation key")
}

impl Harness {
    pub async fn create(root: &Path, wire: Vec<u8>) -> Self {
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("initialize fleet");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        registry
            .register(
                AgentManifest::new(
                    AgentId::parse(AGENT_ID).expect("agent id"),
                    WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
                    ResourceBudget::local_default(),
                )
                .expect("manifest"),
            )
            .expect("register agent");
        let harness = Self::reopen(root, wire).await;
        let definition = TaskFlowDefinition::new(
            "act1",
            1,
            "effect",
            vec![
                TaskFlowNodeSpec::effect("effect", "act1.write", "act1-write-v1"),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new("effect", "success"),
                TaskFlowEdgeSpec::new("effect", "failure"),
            ],
            vec!["act1.write".to_string()],
            Sha256Digest::for_bytes(b"act1-policy"),
        )
        .expect("definition");
        harness
            .store
            .register_taskflow_definition(&definition, &harness.fence, 10)
            .await
            .expect("register definition");
        harness
            .store
            .create_taskflow_run(
                &harness.effect.run_id,
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "thread-act1",
                10,
            )
            .await
            .expect("create run");
        let claimed = harness
            .store
            .claim_taskflow_run(&harness.effect.run_id, &harness.fence, 20, 1_000)
            .await
            .expect("claim run");
        harness
            .store
            .apply_taskflow_command(
                &TaskFlowCommand::new(
                    &harness.effect.run_id,
                    "act1-start",
                    harness.fence.clone(),
                    claimed.revision,
                    TaskFlowTransition::Start,
                    21,
                )
                .expect("start command"),
            )
            .await
            .expect("start run");
        let digest = harness.effect.digest().expect("effect digest");
        harness
            .store
            .prepare_taskflow_step(
                &harness.effect.run_id,
                &harness.effect.step_id,
                harness.effect.attempt,
                &harness.fence,
                &digest,
                &harness.effect.payload_digest,
                "act1-prepare",
                22,
            )
            .await
            .expect("durably prepare step");
        harness
            .store
            .claim_taskflow_step(
                &harness.effect.run_id,
                &harness.effect.step_id,
                harness.effect.attempt,
                &harness.fence,
                &digest,
                &harness.effect.payload_digest,
                "act1-claim",
                23,
            )
            .await
            .expect("durably claim step");
        harness
    }

    pub async fn reopen(root: &Path, wire: Vec<u8>) -> Self {
        let store = AutomationStore::open(&layout(root))
            .await
            .expect("open owner ledger");
        let fence = TaskFlowFence::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            "act1-owner",
            1,
            1,
            "act1-fence",
        )
        .expect("owner fence");
        let effect = AuthorizedEffectIntent {
            run_id: "act1-run".to_string(),
            step_id: "effect".to_string(),
            attempt: 1,
            operation_id: "act1.write".to_string(),
            subject_id: "agent-one".to_string(),
            destination_id: DESTINATION.to_string(),
            payload_digest: Sha256Digest::for_bytes(&wire),
            final_use_scope_digest: Sha256Digest::for_bytes(b"act1-target-scope"),
            policy_generation: 7,
            expected_predecessor_digest: None,
            dependencies: Vec::new(),
            compensation_for: None,
        };
        let binding = effect.final_use_binding().expect("exact FinalUse binding");
        let (authority, grant) = authority(root, binding.clone());
        Self {
            store,
            effect,
            wire,
            fence,
            binding,
            authority,
            grant,
        }
    }

    pub async fn dispatch<D: AsyncAuthorizedEffectDriver>(
        &self,
        driver: &mut D,
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        self.dispatch_bytes(driver, &self.wire).await
    }

    pub async fn dispatch_bytes<D: AsyncAuthorizedEffectDriver>(
        &self,
        driver: &mut D,
        wire: &[u8],
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        self.store
            .execute_authorized_taskflow_effect_async(
                &self.authority,
                driver,
                AuthorizedEffectDispatchRequest {
                    intent: &self.effect,
                    wire_payload: wire,
                    fence: &self.fence,
                    signed_grant: &self.grant,
                    expected_binding: &self.binding,
                    command_id: "act1-dispatch",
                    now_ms: 30,
                },
            )
            .await
    }

    pub async fn pending(&self) -> AuthorizedEffectPending {
        let pending = self
            .store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("scan original operation");
        assert_eq!(pending.len(), 1);
        pending.into_iter().next().expect("pending operation")
    }

    pub async fn recover(
        &self,
        lookup: AuthorizedProviderEffectLookup,
    ) -> Option<TaskFlowStepReceipt> {
        let AuthorizedProviderEffectLookup::Observed(receipt) = lookup else {
            return None;
        };
        let result = self
            .store
            .recover_authorized_taskflow_effect(
                &self.effect.run_id,
                &self.effect.step_id,
                self.effect.attempt,
                &self.fence,
                AuthorizedEffectRecovery::Observed(receipt),
                40,
            )
            .await
            .expect("recover using owner evidence");
        let AuthorizedEffectRecoveryResult::Observed(receipt) = result else {
            panic!("observed recovery must retain receipt");
        };
        Some(*receipt)
    }
}

fn authority(root: &Path, binding: FinalUseBinding) -> (FinalUseAuthority, SignedFinalUseGrant) {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("wall clock")
            .as_millis(),
    )
    .expect("milliseconds");
    let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".to_string(),
        authority_epoch: 9,
        grant_id: format!("act1-{}-{nonce}", std::process::id()),
        nonce: Sha256::digest(format!("{}:{now}:{nonce}:{root:?}", std::process::id()).as_bytes())
            .into(),
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("grant bytes"))
        .to_bytes()
        .to_vec();
    let state = root.join("final-use");
    std::fs::create_dir_all(&state).expect("authority directory");
    std::fs::set_permissions(&state, std::fs::Permissions::from_mode(0o700))
        .expect("private authority permissions");
    let authority = FinalUseAuthority::open_state_dir(
        &state,
        "security-owner".to_string(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("FinalUse authority");
    (authority, SignedFinalUseGrant { grant, signature })
}
