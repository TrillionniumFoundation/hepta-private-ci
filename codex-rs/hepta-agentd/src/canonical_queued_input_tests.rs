//! Correlation/material tests. Authentication and the actual signed Objective
//! path are covered by objective_native_integration_tests; these records do
//! not claim to be valid authority merely because their correlation hashes fit.

use pretty_assertions::assert_ne;

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::{AgentManifest, FleetRegistry, ResourceBudget, WorkspaceBinding};
use codex_hepta_learning_ledger::{RunStartAdmissionBindingV1, RunStartAuthenticationV1,
    RunStartObjectiveDispositionV1, RunStartSnapshotV1};
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;
use pretty_assertions::assert_eq;

use crate::{AgentRunCoordinator, ContextAttachment, ObjectiveQueuedInputV1, RunPhase, RuntimeComposition};
use crate::intelligence_product::tests::native_context_binding_tests::prepare_native_context;

fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
fn id(value: &str) -> Result<StableId> { Ok(StableId::new(value)?) }

fn fixture() -> Result<(tempfile::TempDir, AgentdIdentity, RunStartRecordV1)> {
    let root = tempfile::tempdir()?;
    let directory = root.path().canonicalize()?;
    let fleet_path = directory.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = directory.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let registered = registry.register(AgentManifest::new(agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet)?, ResourceBudget::local_default())?)?;
    let identity = AgentdIdentity {
        agent_id, layout: registered.layout.clone(), spawn_generation: 1, fleet_root: fleet_path,
        workspace, resources: registered.manifest.resources,
        home_root: registered.layout.home_root().to_path_buf(), run_root: registered.layout.run_root().to_path_buf(),
        control_socket: registered.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: registered.layout.app_server_socket().to_path_buf(),
    };
    let now = u64::try_from(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_millis())?;
    let body = AuthBusObjectiveBody {
        spawn_generation: identity.spawn_generation, run_id: "run:canonical-queued".to_owned(),
        objective_revision: 1, source_envelope_json: "{\"fixture\":true}".to_owned(),
        runtime_body_digest: digest("runtime-body").to_string(),
        preference_state_digest: digest("preferences").to_string(), model_tuple_digest: digest("model").to_string(),
        prompt_registry_digest: digest("prompts").to_string(), artifact_set_digest: digest("artifacts").to_string(),
        authority_epoch: 11, queued_input: Some(ObjectiveQueuedInputV1 {
            thread_id: ThreadId::new().to_string(), text: "Original signed text with a quoted \"instruction\".".to_owned(),
        }),
    };
    let bytes = serde_json::to_vec(&body)?;
    let semantic = b"fixture compiled objective".to_vec();
    let record = RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: id("issuer.fixture")?, key_epoch: 3, message_id: id("message.fixture")?, sequence: 4,
            expires_at_ms: now + 30_000, scope_digest: digest("scope"), signed_body_digest: Digest32::of_bytes(&bytes),
            signature: [7; 64],
        },
        authenticated_payload: Some(bytes),
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.fixture")?, profile_revision: 1, profile_digest: digest("profile"),
            supplied_source_digest: digest("source"), intent_digest: digest("intent"), admitted_source_digest: digest("admitted"),
            observed_at_unix_micros: now * 1_000, deadline_unix_micros: (now + 60_000) * 1_000,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: id(&body.run_id)?, objective_digest: Digest32::of_bytes(&semantic), hard_constraint_digest: digest("hard"),
            preference_state_digest: digest("preferences"), model_tuple_digest: digest("model"),
            prompt_registry_digest: digest("prompts"), artifact_set_digest: digest("artifacts"),
            authority_epoch: 11, generation: 1, fence_digest: crate::state::objective_run_fence(&identity, 1).parse()?,
        },
        runtime_body_digest: digest("runtime-body"), objective_semantic_bytes: semantic,
        objective_function_v1_digest: digest("protocol"), objective_function_v1_bytes: b"protocol".to_vec(),
    };
    Ok((root, identity, record))
}

#[test]
fn exact_signed_input_derives_original_queue_payload_and_authenticated_client_identity() -> Result<()> {
    let (_root, identity, record) = fixture()?;
    let input = queued_input(&identity, &record)?;
    let body: AuthBusObjectiveBody = serde_json::from_slice(record.authenticated_payload.as_deref().unwrap())?;
    let queued = body.queued_input.unwrap();
    assert_eq!((input.thread_id.as_str(), input.text.as_str(), input.run_id.as_str()),
        (queued.thread_id.as_str(), queued.text.as_str(), record.snapshot.run_id.as_str()));
    assert_eq!(input.input_payload_sha256, user_input_payload_sha256(&[UserInput::Text {
        text: queued.text, text_elements: Vec::new(),
    }])?);
    assert_eq!(queued_input(&identity, &record)?, input);
    let mut later_message = record.clone();
    later_message.authentication.sequence += 1;
    assert_ne!(queued_input(&identity, &later_message)?.client_user_message_id, input.client_user_message_id);
    assert!(!format!("{input:?}").contains("Original signed text"));
    let mut other_spawn = identity;
    other_spawn.spawn_generation += 1;
    assert!(queued_input(&other_spawn, &record).is_err());
    Ok(())
}

#[test]
fn missing_changed_noncanonical_and_mismatched_record_material_are_held() -> Result<()> {
    let (_root, identity, record) = fixture()?;
    let expected = signed_objective_queued_text_item(&record, 16)?;
    assert_eq!((expected.role, expected.source_digest, expected.contains_secret),
        (ContextRole::UntrustedEvidence, record.authentication.signed_body_digest, false));
    let mut missing = record.clone();
    missing.authenticated_payload = None;
    assert!(queued_input(&identity, &missing).is_err());
    let mut changed = record.clone();
    changed.authenticated_payload.as_mut().unwrap().push(b' ');
    assert!(queued_input(&identity, &changed).is_err());
    changed.authentication.signed_body_digest = Digest32::of_bytes(changed.authenticated_payload.as_deref().unwrap());
    assert!(queued_input(&identity, &changed).is_err(), "a matching hash cannot make noncanonical bytes the signed typed body");
    let mut other_record = record.clone();
    other_record.snapshot.run_id = id("run:another")?;
    assert!(signed_objective_queued_text_item(&other_record, 16).is_err());
    assert!(signed_objective_queued_text_item(&record, 0).is_err());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_owner_selection_is_retained_only_until_original_coordinator_dispatch() -> Result<()> {
    let (_root, identity, record) = fixture()?;
    let input = queued_input(&identity, &record)?;
    let composition = RuntimeComposition {
        agent_id: identity.agent_id.to_string(), supervisor_generation: 1, agentd_generation: 1,
        configuration_digest: digest("runtime-config").to_string(), ports_digest: digest("runtime-ports").to_string(),
        max_active_runs: 8,
    };
    let item = signed_objective_queued_text_item(&record, 16)?;
    let prepared = prepare_native_context(&composition, &input.run_id, vec![item], 16).await?;
    let context = bind_selected_text(&record, &prepared)?;
    let mut runs = AgentRunCoordinator::compose_runtime(composition.clone())
        .map_err(|error| anyhow::anyhow!("composition: {error:?}"))?;
    let now = u64::try_from(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_millis())?;
    let admitted = runs.start_run(now, context.original_run_snapshot().clone())
        .map_err(|error| anyhow::anyhow!("admission: {error:?}"))?;
    let attachment = prepared.context_attachment();
    let attached = runs.attach_context(now, admitted.revision, ContextAttachment {
        run_id: attachment.run_id, request_digest: attachment.request_digest, objective_digest: attachment.objective_digest,
        body_digest: attachment.body_digest, artifact_set_digest: attachment.artifact_set_digest,
        authority_epoch: attachment.authority_epoch, generation: attachment.generation,
        fence_digest: attachment.fence_digest, deadline_ms: attachment.deadline_ms,
        context_digest: attachment.context_digest, compilation_receipt_digest: attachment.compilation_receipt_digest,
    }).map_err(|error| anyhow::anyhow!("attachment: {error:?}"))?;
    let queued = CanonicalQueuedRunV1 { input: input.clone(), context };
    runs.retain_canonical_queued_input(now, queued.clone()).map_err(|error| anyhow::anyhow!("retain: {error:?}"))?;
    let resolved = runs.resolve_canonical_queued_input(now, &input.thread_id, &input.client_user_message_id, &input.input_payload_sha256)
        .map_err(|error| anyhow::anyhow!("resolve: {error:?}"))?;
    assert_eq!(resolved, (attached.clone(), queued));
    assert!(runs.resolve_canonical_queued_input(now, &input.thread_id, &input.client_user_message_id, &digest("changed input").to_string()).is_err());
    let dispatched = runs.mark_dispatched(now, &input.run_id, attached.revision)
        .map_err(|error| anyhow::anyhow!("dispatch: {error:?}"))?;
    assert_eq!(dispatched.phase, RunPhase::Dispatched);
    assert!(runs.resolve_canonical_queued_input(now, &input.thread_id, &input.client_user_message_id, &input.input_payload_sha256).is_err());
    let original_recovery = runs.recovery_record(&input.run_id).map_err(|error| anyhow::anyhow!("recovery: {error:?}"))?;
    let mut recovered = AgentRunCoordinator::compose_runtime(composition).map_err(|error| anyhow::anyhow!("recovered composition: {error:?}"))?;
    recovered.recover_indeterminate(original_recovery).map_err(|error| anyhow::anyhow!("original restore: {error:?}"))?;
    assert!(recovered.resolve_canonical_queued_input(now, &input.thread_id, &input.client_user_message_id, &input.input_payload_sha256).is_err());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unavailable_selected_source_is_held_instead_of_reconstructed_from_a_digest() -> Result<()> {
    let (_root, identity, record) = fixture()?;
    let composition = RuntimeComposition {
        agent_id: identity.agent_id.to_string(), supervisor_generation: 1, agentd_generation: 1,
        configuration_digest: digest("runtime-config").to_string(), ports_digest: digest("runtime-ports").to_string(),
        max_active_runs: 8,
    };
    let original = signed_objective_queued_text_item(&record, 1)?;
    let mut unavailable = original.clone();
    unavailable.item_id = id("source.unavailable")?;
    unavailable.source_digest = digest("another-source");
    let prepared = prepare_native_context(&composition, record.snapshot.run_id.as_str(), vec![original, unavailable], 2).await?;
    assert_eq!(prepared.selected_native_context_items().len(), 2);
    assert!(bind_selected_text(&record, &prepared).is_err());
    Ok(())
}
