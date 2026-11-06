//! Durable synthetic authority fixture for the explicitly invoked real-worker test.

use std::collections::BTreeSet;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::HcsnTaskFlowActionV1;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
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
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

pub const SCOPE: &str = "provider:hcsn:qualification";
const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c18";

pub struct Fixture {
    pub layout: HeptaAgentLayout,
    pub owner: TaskFlowFence,
    pub authority: FinalUseAuthority,
    issuer: SigningKey,
}

impl Fixture {
    pub fn initialize(root: &Path) -> Self {
        fs::DirBuilder::new().mode(0o700).create(root).expect("fresh signed fixture root; never retry an existing attempt");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
        let workspace = root.join("workspace");
        fs::create_dir(&workspace).expect("workspace");
        registry.register(AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        ).expect("manifest")).expect("register agent");
        fs::DirBuilder::new().mode(0o700).create(root.join("authority")).expect("authority directory");
        Self::reopen(root)
    }

    pub fn reopen(root: &Path) -> Self {
        let agent = AgentId::parse(AGENT_ID).expect("agent");
        let registry = FleetRegistry::open_existing(
            HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root"),
        ).expect("existing fleet");
        // This fixed key exists only in this test. It is not host deployment trust.
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &root.join("authority"), "synthetic-security-owner".to_string(),
            issuer.verifying_key().to_bytes(), FinalUseRevocations {
                authority_epoch: 9, revision: 1, revoked_grant_ids: BTreeSet::new(),
            },
        ).expect("durable synthetic authority");
        Self {
            layout: registry.load_agent(&agent).expect("existing agent").layout,
            owner: TaskFlowFence::new(agent, "hcsn-owner", 1, 1, "hcsn-fence").expect("fence"),
            authority,
            issuer,
        }
    }

    pub fn sign(&self, effect: &AuthorizedEffectIntent) -> SignedFinalUseGrant {
        let now = now_ms();
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "synthetic-security-owner".to_string(),
            authority_epoch: 9,
            grant_id: "synthetic-real-worker-grant".to_string(),
            nonce: Sha256::digest(b"synthetic-real-worker-grant").into(),
            binding: effect.final_use_binding().expect("binding"),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 120_000,
        };
        let signature = self.issuer.sign(&grant.signing_bytes().expect("signing bytes")).to_bytes().to_vec();
        SignedFinalUseGrant { grant, signature }
    }

    pub async fn prepare(&self, store: &AutomationStore, payload: &[u8]) -> AuthorizedEffectIntent {
        let now = now_ms();
        let run_id = "hcsn-signed-worker-run";
        let operation = HcsnTaskFlowActionV1::Start.operation_id();
        let definition = TaskFlowDefinition::new(
            run_id, 1, "effect", vec![
                TaskFlowNodeSpec::effect("effect", operation, "hcsn-supervisor-v1"),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ], vec![
                TaskFlowEdgeSpec::new("effect", "success"),
                TaskFlowEdgeSpec::new("effect", "failure"),
            ], vec![operation.to_string()], Sha256Digest::for_bytes(b"hcsn-policy"),
        ).expect("definition");
        store.register_taskflow_definition(&definition, &self.owner, now).await.expect("definition");
        store.create_taskflow_run(run_id, &definition.workflow_id, definition.version,
            definition.definition_digest(), "hcsn-thread", now).await.expect("run");
        let claimed = store.claim_taskflow_run(run_id, &self.owner, now, 300_000).await.expect("claim run");
        store.apply_taskflow_command(&TaskFlowCommand::new(
            run_id, "training-start", self.owner.clone(), claimed.revision, TaskFlowTransition::Start, now,
        ).expect("start command")).await.expect("start run");
        let effect = AuthorizedEffectIntent {
            run_id: run_id.to_string(), step_id: "effect".to_string(), attempt: 1,
            operation_id: operation.to_string(), subject_id: AGENT_ID.to_string(),
            destination_id: SCOPE.to_string(), payload_digest: Sha256Digest::for_bytes(payload),
            final_use_scope_digest: Sha256Digest::for_bytes(b"synthetic-hcsn-training-scope"),
            policy_generation: 7, expected_predecessor_digest: None,
            dependencies: Vec::new(), compensation_for: None,
        };
        let digest = effect.digest().expect("intent digest");
        store.prepare_taskflow_step(run_id, "effect", 1, &self.owner, &digest,
            &effect.payload_digest, "training-prepare", now).await.expect("prepare step");
        store.claim_taskflow_step(run_id, "effect", 1, &self.owner, &digest,
            &effect.payload_digest, "training-claim", now).await.expect("claim step");
        effect
    }
}

pub fn now_ms() -> u64 {
    u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH).expect("clock").as_millis()).expect("milliseconds")
}

pub fn write_new(path: &Path, value: &impl Serialize) {
    let bytes = serde_json::to_vec(value).expect("evidence JSON");
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(path).expect("new evidence file");
    file.write_all(&bytes).expect("write evidence");
    file.sync_all().expect("sync evidence");
    fs::File::open(path.parent().expect("evidence parent")).expect("parent").sync_all().expect("sync directory");
}
