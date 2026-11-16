//! A single real recovered store is shared by the configured writer, Agentd
//! state and factory. Issuers/clock are controlled; no decoder is executed.

use std::sync::atomic::AtomicBool;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use std::assert_eq;

use super::*;
use crate::AgentdConfig;
use crate::NativeMemoryShadowStartV1;
use crate::native_memory_current_test_support::CurrentMemoryFixture;
use crate::native_memory_shadow_namespace::tests::files;
use crate::native_memory_shadow_namespace::tests::profile;
use crate::native_memory_test_support::Fixture;
use crate::native_memory_test_support::Verifier;
use crate::state::objective_current_tests::ClockCase;

pub(super) struct FactoryFixture {
    pub(super) current: CurrentMemoryFixture,
    pub(super) source: Fixture,
    pub(super) writer: Arc<AgentdProductionWriterHost>,
    pub(super) registration: Arc<AgentdNativeMemoryRegistrationV1>,
    _config: AgentdConfig,
}

async fn factory_fixture() -> anyhow::Result<FactoryFixture> {
    factory_fixture_with_document(crate::native_memory_test_support::controlled_document_bytes())
        .await
}

pub(super) async fn factory_fixture_with_document(
    document_bytes: Vec<u8>,
) -> anyhow::Result<FactoryFixture> {
    let f = starting_factory_fixture(document_bytes).await?;
    let state = &f.current.objective.state;
    f.current.objective.registry.compare_and_transition(
        &state.identity().agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    state.refresh_generation()?;
    state.mark_app_server_ready()?;
    state.start_current_run_start_record(&f.current.objective.record)?;
    Ok(f)
}

pub(super) async fn starting_factory_fixture(
    document_bytes: Vec<u8>,
) -> anyhow::Result<FactoryFixture> {
    let owner_root = tempfile::tempdir()?;
    let root = owner_root.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let manifest = AgentManifest::new(
        owner.clone(),
        WorkspaceBinding::new(&workspace, &fleet)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(
        &owner,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let config = AgentdConfig::load(
        fleet_path,
        owner.clone(),
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?;
    let store = CognitiveStore::open(&config.identity().layout).await?;
    let anchor = store.recovery_anchor().await?;
    store.close().await;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner,
        Sha256Digest::for_bytes(b"registered-source-test"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        crate::authbus_ingress::now_ms()? / 1000 + 3600,
        ProductionAuthorityToken::from_verified_bytes(b"registered-source-test".to_vec())?,
    )?;
    let verifier = Arc::new(Verifier(AtomicBool::default()));
    let writer = Arc::new(
        AgentdProductionWriterHost::open(
            &config,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            authority,
            verifier.clone(),
            "registered-source-test",
            /*lease_generation*/ 1,
        )
        .await?,
    );
    let config = config.with_production_writer_host(Arc::clone(&writer))?;
    let state = Arc::new(AgentdState::new(
        config.identity().clone(),
        registry.clone(),
        /*event_capacity*/ 16,
    )?);
    let cognitive = writer.cognitive_runtime();
    state.attach_cognitive_store(Arc::clone(
        cognitive
            .available_store()
            .ok_or_else(|| anyhow::anyhow!("fixture cognitive store unavailable"))?,
    ))?;
    state.refresh_generation()?;
    state.mark_runtime_prerequisites_ready()?;
    let objective = crate::state::objective_current_tests::unadmitted_fixture_with_state(
        ClockCase::Current,
        owner_root,
        registry,
        state,
    )
    .await?;
    let current = crate::native_memory_current_test_support::fixture_with_objective(objective)?;
    let mut source = crate::native_memory_test_support::fixture_with_document_bytes(
        tempfile::tempdir()?,
        writer.writer(),
        verifier,
        document_bytes,
    )
    .await;
    source.config.output_width = 5;
    std::fs::create_dir_all(&source.config.checkpoint)?;
    let manifest = serde_json::to_vec(&serde_json::json!({
        "roots": [source.claim.production.source_content_sha256.as_str()], "scope": source.config.scope,
    }))?;
    std::fs::write(source.config.checkpoint.join("lineage.json"), &manifest)?;
    source.config.pins.manifest_sha256 = Digest32::of_bytes(&manifest).to_string();
    let registration = Arc::new(AgentdNativeMemoryRegistrationV1::new(
        Arc::clone(&current.ndu),
        current.tick.clone(),
    ));
    let config = config.with_native_memory_registration(Arc::clone(&registration))?;
    Ok(FactoryFixture {
        current,
        source,
        writer,
        registration,
        _config: config,
    })
}

pub(super) fn registered_source(f: &FactoryFixture) -> NativeMemorySourceConfigV1 {
    NativeMemorySourceConfigV1 {
        access: f.source.access.clone(),
        key: f.source.admission.query().key.clone(),
        claim: f.source.claim.clone(),
        model: f.source.config.clone(),
    }
}

#[tokio::test]
async fn installation_requires_no_admitted_run_and_runtime_drop_closes_live_factory_children()
-> anyhow::Result<()> {
    let f = factory_fixture().await?;
    let state = &f.current.objective.state;
    let cancelled = state
        .response(
            /*request_id*/ 101,
            /*spawn_generation*/ 1,
            crate::AgentdMethod::RunCancel {
                run_id: "run.current".into(),
                expected_revision: 1,
                reason: "registration-test".into(),
            },
        )
        .await
        .unwrap();
    let crate::AgentdPayload::RunCancellation(cancelled) = cancelled.payload else {
        panic!("expected actual run cancellation")
    };
    state
        .response(
            /*request_id*/ 102,
            /*spawn_generation*/ 1,
            crate::AgentdMethod::RunReleaseClosed {
                run_id: "run.current".into(),
                expected_revision: cancelled.receipt.revision,
            },
        )
        .await
        .unwrap();
    assert!(f.registration.host().is_err());
    let runtime = CancellationToken::new();
    let lifetime = f
        .registration
        .attach(state, Arc::clone(&f.writer), &runtime)
        .unwrap();
    let host = f.registration.host().unwrap();
    let mut query = f.current.query("factory-later-run")?;
    query.key = f.source.admission.query().key.clone();
    assert!(host.prepare_read("run.current", query.clone()).is_err());
    assert!(
        f.registration
            .attach(state, Arc::clone(&f.writer), &runtime)
            .is_err()
    );
    state
        .start_current_run_start_record(&f.current.objective.record)
        .unwrap();
    let prepared = host.prepare_read("run.current", query.clone()).unwrap();
    let signed = f
        .current
        .sign(prepared.binding().clone(), "factory-later-run")?;
    let owner = host
        .open_shadow(
            prepared,
            &signed,
            registered_source(&f),
            files(f.source.temp.path(), NativeMemoryShadowStartV1::Bootstrap),
            profile(&f.source.config),
        )
        .await
        .unwrap();
    drop(lifetime);
    assert!(f.registration.host().is_err());
    assert!(host.prepare_read("run.current", query.clone()).is_err());
    assert!(owner.read(query).await.is_err());
    assert!(state.checked_current_objective("run.current").is_ok());
    assert!(!runtime.is_cancelled());
    Ok(())
}

#[tokio::test]
async fn factory_rejects_foreign_preparation_and_key_before_spending_grant() -> anyhow::Result<()> {
    let f = factory_fixture().await?;
    let state = &f.current.objective.state;
    let runtime = CancellationToken::new();
    let _lifetime = f
        .registration
        .attach(state, Arc::clone(&f.writer), &runtime)
        .unwrap();
    let host = f.registration.host().unwrap();
    let mut query = f.current.query("factory-exact-query")?;
    query.key = f.source.admission.query().key.clone();
    // Same real owners, different enrolled host: equality of owner IDs alone
    // does not permit an opaque preparation to cross runtime handles.
    let prepared = f
        .current
        .host
        .prepare_read("run.current", query.clone())
        .unwrap();
    let signed = f
        .current
        .sign(prepared.binding().clone(), "foreign-preparation")?;
    let before = f.current.authority.frontier().unwrap();
    assert!(
        host.open_shadow(
            prepared,
            &signed,
            registered_source(&f),
            files(f.source.temp.path(), NativeMemoryShadowStartV1::Bootstrap),
            profile(&f.source.config)
        )
        .await
        .is_err()
    );
    assert_eq!(f.current.authority.frontier().unwrap(), before);
    let prepared = host.prepare_read("run.current", query.clone()).unwrap();
    let signed = f
        .current
        .sign(prepared.binding().clone(), "wrong-source-key")?;
    let mut source = registered_source(&f);
    source.key.relation = "another-repair".to_string();
    assert!(
        host.open_shadow(
            prepared,
            &signed,
            source,
            files(f.source.temp.path(), NativeMemoryShadowStartV1::Bootstrap),
            profile(&f.source.config)
        )
        .await
        .is_err()
    );
    assert_eq!(f.current.authority.frontier().unwrap(), before);
    let prepared = host.prepare_read("run.current", query.clone()).unwrap();
    let signed = f
        .current
        .sign(prepared.binding().clone(), "correct-source-key")?;
    let owner = host
        .open_shadow(
            prepared,
            &signed,
            registered_source(&f),
            files(f.source.temp.path(), NativeMemoryShadowStartV1::Bootstrap),
            profile(&f.source.config),
        )
        .await
        .unwrap();
    let mut substitute = query.clone();
    substitute.request_id = crate::native_memory_current_test_support::id("different-read")?;
    assert!(owner.read(substitute).await.is_err());
    runtime.cancel();
    assert!(f.registration.host().is_err());
    assert!(host.prepare_read("run.current", query.clone()).is_err());
    assert!(owner.read(query).await.is_err());
    assert!(state.checked_current_objective("run.current").is_ok());
    Ok(())
}
