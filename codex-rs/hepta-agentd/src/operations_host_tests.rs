use std::collections::BTreeSet;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::automation_task_operation_intent;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_operations::DispatchEffect;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::time::Duration;

use super::AgentdOperationsError;
use super::AgentdOperationsHost;
use super::AutomationGrantProvider;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const THREAD_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75ddd";

struct SigningGrantProvider {
    issuer: SigningKey,
    authority_epoch: u64,
}

impl AutomationGrantProvider for SigningGrantProvider {
    fn signed_grant(
        &self,
        intent: &codex_hepta_operations::OperationIntentV1,
    ) -> Result<SignedFinalUseGrant, AgentdOperationsError> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| AgentdOperationsError::Grant(error.to_string()))?
            .as_millis() as u64;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "automation-security-owner".to_string(),
            authority_epoch: self.authority_epoch,
            grant_id: format!("grant:{}", intent.operation_id),
            nonce: intent.semantic_digest().into_array(),
            binding: intent.final_use_binding(),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now.saturating_add(30_000),
        };
        let signature = self
            .issuer
            .sign(
                &grant
                    .signing_bytes()
                    .map_err(|error| AgentdOperationsError::Grant(error.to_string()))?,
            )
            .to_bytes()
            .to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }
}

fn draft() -> AutomationTaskDraft {
    AutomationTaskDraft::new(
        THREAD_ID,
        "create through durable kernel operations",
        AutomationSchedule::FixedInterval { interval_ms: 5_000 },
        20_000,
        10_000,
    )
}

#[tokio::test]
#[cfg(unix)]
async fn configured_host_create_is_terminal_and_reopen_is_idempotent()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = temp.path().canonicalize()?;
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let workspace = workspace.canonicalize()?;
    let agent_id = AgentId::parse(AGENT_ID)?;
    let manifest = AgentManifest::new(
        agent_id,
        WorkspaceBinding::new(workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let layout = registry.register(manifest)?.layout;
    let automation = AutomationStore::open(&layout).await?;
    let operations_path = layout
        .agent_root()
        .join("kernel-operations")
        .join("automation.sqlite3");

    let issuer = SigningKey::from_bytes(&[83; 32]);
    let authority_dir = root.join("final-use");
    std::fs::create_dir(&authority_dir)?;
    std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))?;
    let authority = FinalUseAuthority::open_state_dir(
        &authority_dir,
        "automation-security-owner".to_string(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let grants = Arc::new(SigningGrantProvider {
        issuer: issuer.clone(),
        authority_epoch: 7,
    });
    let generation = Generation::new(1)?;
    let host = AgentdOperationsHost::open(
        &operations_path,
        automation.clone(),
        authority.clone(),
        grants.clone(),
        generation,
    )
    .await?;

    let draft = draft();
    let intent = automation_task_operation_intent(automation.owner_agent_id(), &draft, generation)?;
    let first = host.create_automation_task(draft.clone()).await?;
    let record = host
        .source_store()
        .operation(&intent.scope_id, &intent.operation_id)
        .await?
        .expect("durable source operation");
    assert!(record.state.is_terminal());
    assert_eq!(automation.list_tasks(10).await?.len(), 1);

    drop(host);
    let reopened = AgentdOperationsHost::open(
        &operations_path,
        automation.clone(),
        authority,
        grants,
        generation,
    )
    .await?;
    let replay = reopened.create_automation_task(draft).await?;
    assert_eq!(replay, first);
    assert_eq!(automation.list_tasks(10).await?.len(), 1);
    Ok(())
}

#[tokio::test]
#[cfg(unix)]
async fn newer_generation_reopen_reconciles_applied_destination_without_redispatch()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = temp.path().canonicalize()?;
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let workspace = workspace.canonicalize()?;
    let agent_id = AgentId::parse(AGENT_ID)?;
    let manifest = AgentManifest::new(
        agent_id,
        WorkspaceBinding::new(workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let layout = registry.register(manifest)?.layout;
    let automation = AutomationStore::open(&layout).await?;
    let operations_path = layout
        .agent_root()
        .join("kernel-operations")
        .join("automation.sqlite3");

    let issuer = SigningKey::from_bytes(&[91; 32]);
    let authority_dir = root.join("final-use-handoff");
    std::fs::create_dir(&authority_dir)?;
    std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))?;
    let authority = FinalUseAuthority::open_state_dir(
        &authority_dir,
        "automation-security-owner".to_string(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 11,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let grants = Arc::new(SigningGrantProvider {
        issuer,
        authority_epoch: 11,
    });

    let generation_one = Generation::new(1)?;
    let host = AgentdOperationsHost::open(
        &operations_path,
        automation.clone(),
        authority.clone(),
        grants.clone(),
        generation_one,
    )
    .await?;
    let draft = draft();
    let intent =
        automation_task_operation_intent(automation.owner_agent_id(), &draft, generation_one)?;
    host.source_store().prepare_intent(&intent).await?;
    let claim = host
        .source_store()
        .claim_operation(
            &intent.scope_id,
            &intent.operation_id,
            &StableId::new("agentd:test-handoff-worker")?,
            generation_one,
            Duration::from_secs(30),
        )
        .await?
        .expect("generation-one claim");
    let signed = grants.signed_grant(&intent)?;
    let authorized = host
        .source_store()
        .authorize_dispatch(&authority, &signed, &claim)
        .await?;
    host.source_store()
        .execute_authorized(authorized, |_| DispatchEffect::Dispatched {
            value: (),
            dispatch_digest: Digest32::of_bytes(b"handoff-transport-dispatched"),
            acknowledgement_digest: Some(Digest32::of_bytes(b"handoff-transport-ack")),
        })
        .await?;

    automation
        .create_task_from_operation(&intent, &draft)
        .await?;
    let before = host
        .source_store()
        .operation(&intent.scope_id, &intent.operation_id)
        .await?
        .expect("source operation before restart");
    assert_eq!(
        before.state,
        codex_hepta_operations::DurableOperationState::Dispatched
    );
    assert_eq!(before.intent.owner_generation, generation_one);
    drop(host);

    let generation_two = Generation::new(2)?;
    let reopened = AgentdOperationsHost::open(
        &operations_path,
        automation.clone(),
        authority,
        grants,
        generation_two,
    )
    .await?;
    let terminal = reopened
        .source_store()
        .operation(&intent.scope_id, &intent.operation_id)
        .await?
        .expect("source operation after generation handoff");
    assert_eq!(
        terminal.state,
        codex_hepta_operations::DurableOperationState::Applied
    );
    assert_eq!(terminal.intent.owner_generation, generation_two);
    assert_eq!(automation.list_tasks(10).await?.len(), 1);
    Ok(())
}
