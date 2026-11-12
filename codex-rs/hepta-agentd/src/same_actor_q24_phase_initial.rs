//! Actual Initial publication and ordinary A owners for the explicit phase.
//! The original Root prepare/issuer/publish path is consumed once. Nothing in
//! this module marks a daemon or a task Ready or synthesizes a receipt.

use super::*;
use crate::circuit_task::SameActorTaskRoute;

pub(crate) fn install_original_initial_task(
    config: AgentdConfig,
    context: Arc<OriginalSameActorRootContext>,
    initial: OriginalRootGenerationInitialV1,
    inputs: OriginalSameActorBusinessInputsV1,
    scoped: UnixDatagram,
) -> Result<AgentdConfig, AgentdError> {
    let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
    OriginalSameActorRootContext::require_current(&context)?;
    if config.identity() != context.identity()
        || inputs.ledger.open_mode != CircuitQ24TaskOpenModeV1::Create
    {
        return Err(phase_refused("original phase A requires its fresh exact Starting owner"));
    }
    let OriginalSameActorBusinessInputsV1 {
        artifacts, selected, initial: target, task, ledger,
        authbus_trust_file, authbus_checkpoint_file, objective_profile_file,
        plasticity, host,
    } = inputs;
    let config = config
        .with_authbus_trust_file(authbus_trust_file)
        .with_authbus_checkpoint_file(authbus_checkpoint_file)
        .with_objective_profile_file(objective_profile_file)
        .with_plasticity_runtime_bootstrap(plasticity)?;
    let model = Arc::clone(&target.model);
    let bundle = target.bundle.clone();
    let authorities = AgentdGenerationUpdateAuthoritiesV1::new(
        artifacts, Arc::new(context.device()), context.clock(),
    )?;
    let prepared: PreparedRootInitialFeatureV1 =
        OriginalRootGenerationInitialV1::prepare_feature(
            initial, authorities.clone(), selected, target,
        )?;
    OriginalSameActorRootContext::require_current(&context)?;
    let grants: Arc<AgentdUnixFinalUseGrantProvider> = context.grants();
    let signed = AgentdUnixFinalUseGrantProvider::request_grant(
        grants.as_ref(), prepared.final_use_binding(),
    ).map_err(phase_owner_error)?;
    OriginalSameActorRootContext::require_current(&context)?;
    let published: PublishedCircuitFeatureTaskV1 = prepared.publish(&signed)?;
    OriginalSameActorRootContext::require_current(&context)?;
    let OriginalSameActorATaskInputsV1 {
        files, fence, circuit, routes, worker_generation, maximum_cell_records,
        queue_capacity, clock,
    } = task;
    let runtime: CircuitQ24TaskRuntimeV1<FileAnchorWitnessStore, FileAnchorWitnessStore> =
        circuit_q24_task_channel_v1(
            context.identity(),
            CircuitQ24TaskProfileV1 {
                files,
                source_mode: CircuitQ24TaskOpenModeV1::Create,
                published_task: published.clone(),
                fence, circuit, routes, bundle, model, worker_generation,
                maximum_cell_records, queue_capacity, clock,
            },
        )?;
    OriginalSameActorRootContext::require_current(&context)?;
    let parts = runtime.into_original_same_actor_task_parts(
        context.identity(), Arc::clone(context.gate()), published.clone(), ledger,
    )?;
    let (route, invocation) = SameActorTaskRoute::pending_original(
        context.identity(), Arc::clone(context.gate()),
    )?;
    let route: Arc<SameActorTaskRoute> = route;
    let (bootstrap, source, cell, ledger) =
        SameActorTaskRoute::install_original_a(route.as_ref(), parts)?;
    OriginalSameActorRootContext::require_current(&context)?;
    let owners = OriginalSameActorAOwners { bootstrap, source, cell, ledger, published };
    let worker = OriginalSameActorTaskWorker::new(
        Arc::clone(&context), Arc::clone(&route), owners, authorities, scoped, host,
    );
    let bootstrap = CircuitTaskRuntimeBootstrapV1::from_original_same_actor_worker(
        context.identity(), route, worker,
    )?;
    let config = config.with_circuit_task_bootstrap(bootstrap, invocation)?;
    OriginalSameActorRootContext::require_current(&context)?;
    closing.disarm();
    Ok(config)
}
