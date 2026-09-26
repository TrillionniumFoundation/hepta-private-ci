//! Invocation-seam tests, not default-daemon or physical-effect qualification.
use super::*;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct OwnerFixture {
    provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    values: Arc<Mutex<Fixture>>,
    reads: Arc<[AtomicUsize; 8]>,
    fail_at: Arc<AtomicUsize>,
}

fn identity(directory: &std::path::Path, composition: &RuntimeComposition) -> AgentdIdentity {
    let fleet_path = directory.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone()).unwrap();
    let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
    let workspace = directory.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let agent_id = AgentId::parse(&composition.agent_id).unwrap();
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet).unwrap(),
        ResourceBudget::local_default(),
    )
    .unwrap();
    let registered = registry.register(manifest).unwrap();
    AgentdIdentity {
        agent_id,
        layout: registered.layout.clone(),
        spawn_generation: composition.agentd_generation,
        fleet_root: fleet_path,
        workspace,
        resources: registered.manifest.resources,
        home_root: registered.layout.home_root().to_path_buf(),
        run_root: registered.layout.run_root().to_path_buf(),
        control_socket: registered.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: registered.layout.app_server_socket().to_path_buf(),
    }
}

fn reader<T>(
    values: &Arc<Mutex<Fixture>>,
    reads: &Arc<[AtomicUsize; 8]>,
    fail_at: &Arc<AtomicUsize>,
    index: usize,
    extract: fn(&Fixture) -> T,
) -> impl Fn(&AgentdIdentity, &RunStartRecordV1) -> Result<T, AgentdError> + Send + Sync + 'static
where
    T: 'static,
{
    let values = Arc::clone(values);
    let reads = Arc::clone(reads);
    let fail_at = Arc::clone(fail_at);
    move |_, _| {
        reads[index].fetch_add(1, Ordering::SeqCst);
        if fail_at.load(Ordering::SeqCst) == index {
            return Err(AgentdError::Invalid(format!("owner {index} unavailable")));
        }
        let value = values.lock().unwrap();
        Ok(extract(&value))
    }
}

fn owners(value: Fixture) -> OwnerFixture {
    let values = Arc::new(Mutex::new(value));
    let reads = Arc::new(std::array::from_fn(|_| AtomicUsize::new(0)));
    let fail_at = Arc::new(AtomicUsize::new(usize::MAX));
    let provider = AgentdIntelligenceInvocationV1::authoritative_provider(
        reader(
            &values,
            &reads,
            &fail_at,
            /*index*/ 0,
            |v| v.request.clone(),
        ),
        reader(&values, &reads, &fail_at, /*index*/ 1, |v| {
            (
                v.inputs.objective_envelope.clone(),
                v.inputs.objective_profile.clone(),
                v.inputs.objective_context.clone(),
            )
        }),
        reader(&values, &reads, &fail_at, /*index*/ 2, |v| {
            (
                v.inputs.utility_contributions.clone(),
                v.inputs.utility_profile.clone(),
                v.inputs.utility_scalarization.clone(),
                v.inputs.utility_policy.clone(),
            )
        }),
        reader(&values, &reads, &fail_at, /*index*/ 3, |v| {
            (
                v.inputs.neural_config.clone(),
                v.inputs.neural_tick.clone(),
                v.inputs.neural_previous.clone(),
            )
        }),
        reader(&values, &reads, &fail_at, /*index*/ 4, |v| {
            v.inputs.prompt_request.clone()
        }),
        reader(
            &values,
            &reads,
            &fail_at,
            /*index*/ 5,
            |v| v.inputs.intuition.clone(),
        ),
        reader(&values, &reads, &fail_at, /*index*/ 6, |v| {
            v.inputs.context_request.clone()
        }),
        reader(&values, &reads, &fail_at, /*index*/ 7, |v| {
            (
                v.inputs.evaluation_request.clone(),
                v.inputs.signed_evaluation.clone(),
            )
        }),
    );
    OwnerFixture {
        provider,
        values,
        reads,
        fail_at,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn separated_owner_inputs_enter_existing_canonical_preparation() {
    let (value, record, composition, directory, runner) = durable_inputs();
    let identity = identity(directory.path(), &composition);
    let owners = owners(value);
    let invocation = owners.provider.build(&identity, &record).unwrap();
    assert_eq!(invocation.request.run_id, record.snapshot.run_id);
    assert_eq!(
        owners.reads.each_ref().map(|v| v.load(Ordering::SeqCst)),
        [1; 8]
    );
    let result = runner
        .prepare_for_composition(&composition, invocation.request, invocation.inputs)
        .await
        .unwrap();
    let AgentdIntelligenceProductOutcomeV1::Ready(mut prepared) = result else {
        panic!("all seven owner stages must prepare the same durable run");
    };
    prepared
        .bind_revalidated_run_start(&record, NOW_MICROS / 1000)
        .unwrap();
    assert_eq!(
        crate::RunSnapshot::from(prepared.run_snapshot()),
        crate::RunSnapshot::from_revalidated_run_start(&record).unwrap()
    );
    assert!(!prepared.envelope.authority.grants_any());
}

#[test]
fn every_owner_failure_stops_without_reading_later_owners() {
    let (value, record, composition, directory, _runner) = durable_inputs();
    let identity = identity(directory.path(), &composition);
    let owners = owners(value);
    for failed in 0..8 {
        owners.fail_at.store(failed, Ordering::SeqCst);
        for reads in owners.reads.iter() {
            reads.store(0, Ordering::SeqCst);
        }
        let error = match owners.provider.build(&identity, &record) {
            Ok(_) => panic!("unavailable owner must fail closed"),
            Err(error) => error,
        };
        assert!(
            error
                .to_string()
                .contains(&format!("owner {failed} unavailable"))
        );
        let expected = std::array::from_fn(|index| usize::from(index <= failed));
        assert_eq!(
            owners.reads.each_ref().map(|v| v.load(Ordering::SeqCst)),
            expected
        );
    }
}

#[test]
fn current_owner_inputs_are_reread_and_mixed_registry_is_rejected() {
    let (value, record, composition, directory, _runner) = durable_inputs();
    let identity = identity(directory.path(), &composition);
    let owners = owners(value);
    assert!(owners.provider.build(&identity, &record).is_ok());
    owners
        .values
        .lock()
        .unwrap()
        .inputs
        .prompt_request
        .registry_snapshot_digest = digest("changed-owner-registry");
    assert!(owners.provider.build(&identity, &record).is_err());
    assert_eq!(
        owners.reads.each_ref().map(|v| v.load(Ordering::SeqCst)),
        [2; 8]
    );
}

#[test]
fn cross_agent_and_stale_generation_are_rejected_before_owner_reads() {
    let (value, record, composition, directory, _runner) = durable_inputs();
    let identity = identity(directory.path(), &composition);
    let owners = owners(value);
    let mut changed = identity.clone();
    changed.agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3").unwrap();
    assert!(owners.provider.build(&changed, &record).is_err());
    let mut changed = identity.clone();
    changed.spawn_generation += 1;
    assert!(owners.provider.build(&changed, &record).is_err());
    let mut changed = record;
    changed.snapshot.fence_digest = digest("foreign-run-fence");
    assert!(owners.provider.build(&identity, &changed).is_err());
    assert_eq!(
        owners.reads.each_ref().map(|v| v.load(Ordering::SeqCst)),
        [0; 8]
    );
}
