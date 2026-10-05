use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use super::*;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdState;
#[cfg(unix)]
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_paths::HeptaFleetRoot;

async fn running_state() -> anyhow::Result<(tempfile::TempDir, FleetRegistry, AgentdState)> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))?;
    }
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let workspace = workspace.canonicalize()?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let record = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;
    let starting = registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let state = AgentdState::new(
        AgentdIdentity {
            agent_id: agent_id.clone(),
            spawn_generation: starting.generation,
            fleet_root: root.join("fleet"),
            workspace,
            resources: record.manifest.resources,
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            app_server_socket: record.layout.app_server_socket().to_path_buf(),
            layout: record.layout,
        },
        registry.clone(),
        /*event_capacity*/ 16,
    )?;
    registry.compare_and_transition(&agent_id, starting.generation, AgentLifecycle::Running)?;
    state.refresh_generation()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(
            &state.identity().home_root,
            std::fs::Permissions::from_mode(0o700),
        )?;
    }
    let cognitive =
        codex_hepta_cognitive_store::DurableCognitiveStore::open(&state.identity().layout).await?;
    state.attach_cognitive_store(Arc::new(cognitive))?;
    state.mark_runtime_prerequisites_ready()?;
    state.mark_app_server_ready()?;
    assert!(state.automation_admission_ready()?);
    Ok((directory, registry, state))
}

fn invocation(body_generation: u64) -> AgentdIntelligenceInvocationV1 {
    let mut value = fixture();
    let snapshot = &value.request.snapshot;
    value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: snapshot.objective_digest(),
        authority_epoch: snapshot.authority_epoch(),
        body_generation: generation(body_generation),
        configuration_digest: snapshot.configuration_digest(),
        revocation_frontier_digest: snapshot.revocation_frontier_digest(),
        owner_bindings: value.owners,
    })
    .expect("current process body snapshot");
    value.inputs.context_request.run_snapshot_digest = value.request.snapshot.digest();
    AgentdIntelligenceInvocationV1 {
        request: value.request,
        inputs: value.inputs,
    }
}

fn run_start(
    state: &AgentdState,
    invocation: &AgentdIntelligenceInvocationV1,
) -> anyhow::Result<RunStartRecordV1> {
    let now_ms = crate::authbus_ingress::now_ms()?;
    // Binding-only tests need no trust owner. The authenticated control below
    // installs owner trust and signs this record before entering the provider.
    Ok(RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: id("issuer.intelligence"),
            key_epoch: 1,
            message_id: id("message.intelligence"),
            sequence: 1,
            expires_at_ms: now_ms + 60_000,
            scope_digest: digest("scope"),
            signed_body_digest: digest("signed-body"),
            signature: [0; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.intelligence"),
            profile_revision: 1,
            profile_digest: digest("profile"),
            supplied_source_digest: digest("source"),
            intent_digest: digest("intent"),
            admitted_source_digest: digest("admitted-source"),
            observed_at_unix_micros: now_ms * 1_000,
            deadline_unix_micros: (now_ms + 60_000) * 1_000,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: invocation.request.run_id.clone(),
            objective_digest: invocation.request.snapshot.objective_digest(),
            hard_constraint_digest: digest("hard-constraints"),
            preference_state_digest: digest("preferences"),
            model_tuple_digest: digest("model"),
            prompt_registry_digest: digest("prompt-registry"),
            artifact_set_digest: digest("artifacts"),
            authority_epoch: invocation.request.snapshot.authority_epoch(),
            generation: 2,
            fence_digest: crate::state::objective_run_fence(state.identity(), 2).parse()?,
        },
        runtime_body_digest: digest("body"),
        objective_semantic_bytes: b"objective".to_vec(),
        objective_function_v1_digest: digest("objective-function"),
        objective_function_v1_bytes: b"objective-function".to_vec(),
    })
}

#[tokio::test]
async fn running_lifecycle_generation_can_differ_from_the_process_body_generation()
-> anyhow::Result<()> {
    let (_directory, registry, state) = running_state().await?;
    let invocation = invocation(1);
    let record = run_start(&state, &invocation)?;
    let lifecycle = registry
        .load()?
        .agent(&state.identity().agent_id)
        .expect("agent")
        .lifecycle
        .clone();
    assert_eq!(lifecycle.lifecycle, AgentLifecycle::Running);
    assert_eq!(lifecycle.generation, record.snapshot.generation);
    assert_eq!(state.identity().spawn_generation, 1);
    assert_eq!(record.snapshot.generation, 2);
    invocation.validate(state.identity(), &record)?;
    assert_eq!(state.active_run_count()?, 0);
    Ok(())
}

#[tokio::test]
async fn lifecycle_generation_cannot_substitute_for_the_process_body_generation()
-> anyhow::Result<()> {
    let (_directory, _registry, state) = running_state().await?;
    let invocation = invocation(2);
    let record = run_start(&state, &invocation)?;
    assert!(matches!(
        invocation.validate(state.identity(), &record),
        Err(AgentdError::Invalid(_))
    ));
    assert_eq!(state.active_run_count()?, 0);
    Ok(())
}

struct CountingProvider {
    calls: Arc<AtomicUsize>,
}

const PROVIDER_REACHED: &str = "current RunStart reached the invocation provider";

impl AgentdIntelligenceInvocationProviderV1 for CountingProvider {
    fn build(
        &self,
        _identity: &AgentdIdentity,
        _record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Err(AgentdError::Invalid(PROVIDER_REACHED.into()))
    }
}

#[tokio::test]
async fn stale_run_start_is_rejected_before_the_invocation_provider_runs() -> anyhow::Result<()> {
    let (directory, _registry, state) = running_state().await?;
    let calls = Arc::new(AtomicUsize::new(0));
    let runner = AgentdIntelligenceProductRunnerV1::new(
        directory.path().join("authority.json"),
        authority_verifier(),
    )?;
    assert!(state.intelligence_product.set(Arc::new(runner)).is_ok());
    assert!(
        state
            .intelligence_invocation
            .set(Arc::new(CountingProvider {
                calls: calls.clone()
            }))
            .is_ok()
    );
    let invocation = invocation(1);
    for (generation, fence) in [
        (1, crate::state::objective_run_fence(state.identity(), 1)),
        (2, digest("stale-fence").to_string()),
    ] {
        let mut record = run_start(&state, &invocation)?;
        record.snapshot.generation = generation;
        record.snapshot.fence_digest = fence.parse()?;
        assert!(matches!(
            state.start_canonical_intelligence(&record).await,
            Err(AgentdError::GenerationFenced(_))
        ));
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert_eq!(state.active_run_count()?, 0);
    }
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn authenticated_current_run_start_reaches_the_invocation_provider_once() -> anyhow::Result<()>
{
    use std::os::unix::fs::PermissionsExt;

    let (directory, _registry, state) = running_state().await?;
    let key = SigningKey::from_bytes(&[77; 32]);
    let trust_file = state.identity().home_root.join("run-start-trust.json");
    let public_key_hex = key
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let trust = serde_json::json!({
        "schema_version": 1,
        "agent_id": state.identity().agent_id.as_str(),
        "issuer_id": "issuer.intelligence",
        "key_epoch": 1,
        "public_key_hex": public_key_hex,
        "revoked": false,
        "thread_ids": [],
    });
    std::fs::write(&trust_file, serde_json::to_vec(&trust)?)?;
    std::fs::set_permissions(&trust_file, std::fs::Permissions::from_mode(0o600))?;

    // Capture the actual empty replay owner's frontier before opening ingress.
    let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
        &codex_state::SqliteConfig::from_sqlite_home(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
                &state.identity().home_root,
            )?,
        ),
    )
    .await?;
    let frontier = evidence.authbus_replay_frontier_digest().await?;
    drop(evidence);
    let checkpoint_file = directory.path().join("run-start-replay-checkpoint.json");
    let checkpoint = serde_json::json!({
        "schema_version": 1,
        "agent_id": state.identity().agent_id.as_str(),
        "generation": 1,
        "digest": frontier.to_string(),
    });
    std::fs::write(&checkpoint_file, serde_json::to_vec(&checkpoint)?)?;
    std::fs::set_permissions(&checkpoint_file, std::fs::Permissions::from_mode(0o600))?;
    let ingress =
        crate::authbus_ingress::TextIngress::open(state.identity(), trust_file, checkpoint_file)
            .await?;
    assert!(state.authbus.set(Arc::new(ingress)).is_ok());

    let calls = Arc::new(AtomicUsize::new(0));
    let runner = AgentdIntelligenceProductRunnerV1::new(
        directory.path().join("authority.json"),
        authority_verifier(),
    )?;
    assert!(state.intelligence_product.set(Arc::new(runner)).is_ok());
    assert!(
        state
            .intelligence_invocation
            .set(Arc::new(CountingProvider {
                calls: calls.clone()
            }))
            .is_ok()
    );

    let mut record = run_start(&state, &invocation(1))?;
    let mut scope_bytes = b"hepta:agentd:signed-objective:v1\0".to_vec();
    scope_bytes.extend_from_slice(state.identity().agent_id.as_str().as_bytes());
    record.authentication.scope_digest = Digest32::of_bytes(&scope_bytes);
    let authentication = &record.authentication;
    let claims = SignedMessageClaims {
        issuer_id: authentication.issuer_id.clone(),
        key_epoch: generation(authentication.key_epoch),
        message_id: authentication.message_id.clone(),
        subject_id: id(state.identity().agent_id.as_str()),
        scope_digest: authentication.scope_digest,
        payload_digest: authentication.signed_body_digest,
        sequence: authentication.sequence,
        expires_at_ms: authentication.expires_at_ms,
    };
    record.authentication.signature = key.sign(&claims.signing_bytes()).to_bytes();
    assert!(matches!(
        state.start_canonical_intelligence(&record).await,
        Err(AgentdError::Invalid(message)) if message == PROVIDER_REACHED
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(state.active_run_count()?, 0);
    Ok(())
}
