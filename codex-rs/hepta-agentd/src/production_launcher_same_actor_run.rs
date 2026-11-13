//! Actual selected Startup driver, owned by a retained std thread.
//! The receiver is driven through its original awaits. Its two bootstrap
//! blocking handles and Session tasks are also retained by that outer owner.

use std::io::Write;

use super::*;

#[path = "production_launcher_same_actor_completion.rs"]
mod completion;
pub(super) use completion::OriginalPhaseCompletion;

pub(super) async fn run_owned_original_phase(
    startup: AgentdOriginalSameActorPhaseStartupV1,
    selected: owner::OriginalPhaseSelectedBusiness,
    arg0_paths: Arg0DispatchPaths,
    control: Arc<owner::OriginalPhaseRunControl>,
) -> Result<OriginalPhaseCompletion, AgentdError> {
    let AgentdOriginalSameActorPhaseStartupV1 {
        identity,
        cognitive_mode,
        inputs,
        mut receiver,
        phase_handoff,
        scoped_handoff,
    } = startup;
    let LaunchInputs {
        handoff,
        learning_handoff: _,
        q24_model_handoff: _,
        publication_handoff: _,
        initial_handoff: _,
        uid,
        gid,
        control: control_socket,
        app_server,
        primary,
        bootstrap_deadline: _,
        notes,
        notes_ui,
        lifetime: _,
    } = inputs;
    late_writer::require_late_owner(uid, gid)?;
    let (bootstrap, root_pidfd, writer) = tokio::task::block_in_place(|| {
        let timeout = receiver.remaining()?.min(Duration::from_millis(500));
        let original = crate::receive_root_production_writer_handoff(handoff, timeout)?;
        receiver.remaining()?;
        Ok::<_, AgentdError>(original)
    })?;
    let phase = tokio::task::block_in_place(|| {
        let timeout = receiver.remaining()?.min(Duration::from_millis(500));
        let phase = receive_original_phase_start(phase_handoff, timeout, receiver.instant())?;
        receiver.remaining()?;
        Ok::<_, AgentdError>(phase)
    })?;
    let timeout = receiver.remaining()?.min(Duration::from_millis(500));
    let OriginalSameActorProductionInputs {
        mut root,
        context,
        initial,
    } = receive_original_same_actor_inputs(
        bootstrap,
        root_pidfd,
        phase,
        &identity,
        timeout,
        receiver,
        control.as_ref(),
    )
    .await?;
    // From this point onward the actual same-Gate close guard already
    // exists outside every later future, including never-polled work.
    let _closing = CloseSameActorPhaseOnDrop::new(context.gate());
    owner::OriginalPhaseRunControl::retain_original_context(&control, &context)?;
    let config = AgentdConfig::from_root_writer_handoff(&root, writer, std::env::current_dir()?)?
        .with_root_bound_sockets(control_socket, app_server)?
        .with_cognitive_retrieval_mode(cognitive_mode);
    if config.identity() != &identity || context.identity() != &identity {
        return Err(refused(
            "original Starting Config differs from the received phase",
        ));
    }
    let (mut business, mut coordinator) = match selected {
        owner::OriginalPhaseSelectedBusiness::Embedded(business) => (*business, None),
        owner::OriginalPhaseSelectedBusiness::Deployment(descriptor) => {
            let (business, coordinator) =
                crate::same_actor_q24_deployment::open_original_deployment(
                    Arc::clone(&context),
                    descriptor,
                )
                .await?;
            (business, Some(coordinator))
        }
    };
    OriginalSameActorRootContext::require_current(&context)?;
    business.host.notify_original(
        &context,
        OriginalSameActorPhaseEventV1::InputsOpened {
            identity: Box::new(identity.clone()),
            phase: context.descriptor().phase.clone(),
        },
    )?;
    if !matches!(
        business.host.receive_original(&context).await?,
        OriginalSameActorPhaseCommandV1::InitialRootEnrolled
    ) {
        return Err(refused(
            "actual Initial Root enrollment must precede connection",
        ));
    }
    let connection =
        crate::AgentdRootProductionInputs::take_generation_publication_connection(&mut root)?;
    let initial = initial
        .connect_original_same_actor_initial(
            connection,
            Arc::clone(&context),
            Duration::from_millis(500),
        )
        .await?;
    OriginalSameActorRootContext::require_current(&context)?;
    // Original synchronous owners complete before this poll returns.
    // block_in_place lets the original refresh worker continue; it
    // creates no detached owner task or discardable JoinHandle.
    let (config, circuit) = tokio::task::block_in_place(|| {
        install_original_initial_task(
            config,
            Arc::clone(&context),
            initial,
            business,
            scoped_handoff,
        )
    })?;
    owner::OriginalPhaseRunControl::retain_original_circuit(&control, &context, circuit)?;
    late_writer::require_late_owner(uid, gid)?;
    OriginalSameActorRootContext::require_current(&context)?;
    let launch = AgentdProductionLaunch {
        root,
        inputs: RuntimeInputs {
            primary,
            notes,
            notes_ui,
        },
        q24_model: None,
        publication: None,
        initial_publication: None,
    };
    // Retain the same actual attachment through original Runtime return.
    // Only the concrete joined/paused/acknowledged/cleanup chain below may
    // construct the private result returned to the retained outer thread.
    let result = match AgentdProductionLaunch::run_original_same_actor_with_shutdown(
        launch,
        config,
        arg0_paths,
        Arc::clone(&context),
        Arc::clone(&control),
    )
    .await
    {
        Ok(stopped) => {
            completion::finish_original_phase(
                stopped,
                context,
                Arc::clone(&control),
                coordinator.take(),
            )
            .await
        }
        Err(error) => Err(error),
    };
    if let Some(coordinator) = coordinator.as_mut()
        && let Err(error) = crate::same_actor_q24_deployment::OriginalDeploymentCoordinatorOwner::stop_and_join_original(coordinator) {
            if result.is_ok() { return Err(error); }
            let _ = writeln!(
                std::io::stderr().lock(),
                "hepta-agentd level=error error={error}: original deployment coordinator also failed",
            );
        }
    result
}
