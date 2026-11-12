//! Explicit embedded-host entry for the same live actor's original phase.
//! Default main and all original startup variants are unchanged. A host must
//! supply actual task/Observer/Evaluator/Primary materials; no CLI defaults
//! invent those owners or the Root three-right sender.

use super::*;
use std::os::fd::AsRawFd;

use crate::root_production_handoff::same_actor_phase::receive_original_phase_start;
use crate::root_production_inputs::same_actor_phase::OriginalPhaseReceiveDeadline;
use crate::root_production_inputs::same_actor_phase::OriginalPhaseReceiveStart;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorProductionInputs;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::root_production_inputs::same_actor_phase::receive_original_same_actor_inputs;
use crate::same_actor_q24_phase::OriginalSameActorBusinessInputsV1;
use crate::same_actor_q24_phase::OriginalSameActorPhaseCommandV1;
use crate::same_actor_q24_phase::OriginalSameActorPhaseEventV1;
use crate::same_actor_q24_phase::install_original_initial_task;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;

/// Construct before arg0 or original business owners open any additional
/// descriptors. The two extra phase descriptors are checked against every
/// original parser-owned descriptor before that parser takes ownership.
pub struct AgentdOriginalSameActorPhaseStartupV1 {
    identity: AgentdIdentity,
    cognitive_mode: crate::config::CognitiveRetrievalMode,
    inputs: LaunchInputs,
    receiver: OriginalPhaseReceiveDeadline,
    phase_handoff: UnixDatagram,
    scoped_handoff: UnixDatagram,
}

impl AgentdOriginalSameActorPhaseStartupV1 {
    pub fn from_process_environment(
        arguments: Vec<OsString>,
        phase_handoff: UnixDatagram,
        scoped_handoff: UnixDatagram,
    ) -> Result<(Self, Vec<OsString>), AgentdError> {
        // First statement: these samples precede parser/Registry/offer work.
        let start = OriginalPhaseReceiveStart::capture()?;
        require_disjoint_phase_descriptors(&arguments, &phase_handoff, &scoped_handoff)?;
        let arguments = match late_startup::select_original_startup_entry(arguments)? {
            late_startup::OriginalStartupSelection::Existing(arguments)
            | late_startup::OriginalStartupSelection::LateWriter(arguments) => arguments,
        };
        let (selected, ordinary) = inputs::parse(arguments)?;
        let inputs =
            selected.ok_or_else(|| refused("complete original production inputs required"))?;
        late_writer::require_late_owner(inputs.uid, inputs.gid)?;
        if inputs.learning_handoff.is_some()
            || inputs.q24_model_handoff.is_some()
            || inputs.publication_handoff.is_some()
            || inputs.initial_handoff.is_some()
        {
            return Err(refused(
                "original phase owns its distinct Initial and later scoped purposes",
            ));
        }
        // The ordinary Circuit profile cannot coexist with Notes UI/Desktop
        // task profiles. This explicit first implementation uses the actual
        // Android Primary while retaining all of its original capability gates.
        if !matches!(&inputs.primary, PrimaryInputs::Android { .. }) || inputs.notes_ui.is_some() {
            return Err(refused(
                "original same-actor Circuit phase requires the real Android Primary",
            ));
        }
        let receiver = start
            .finish(inputs.lifetime)?
            .restrict_original_launcher_end(inputs.bootstrap_deadline)?;
        let (identity, cognitive_mode) =
            crate::config::read_original_late_writer_starting_identity()?;
        Ok((
            Self {
                identity,
                cognitive_mode,
                inputs,
                receiver,
                phase_handoff,
                scoped_handoff,
            },
            ordinary,
        ))
    }

    pub fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }

    /// Supply actual business owners only after descriptor preflight. This
    /// consumes this startup once and calls the original Launch.run itself.
    /// The host must still submit A and C through signed ObjectiveStart and
    /// provide independent signed Outcomes through the bounded typed channel.
    pub async fn run_original_phase(
        self,
        mut business: OriginalSameActorBusinessInputsV1,
        arg0_paths: Arg0DispatchPaths,
    ) -> Result<(), AgentdError> {
        let runtime = tokio::runtime::Handle::try_current()
            .map_err(|_| refused("original phase requires its actual Tokio runtime"))?;
        if runtime.runtime_flavor() != tokio::runtime::RuntimeFlavor::MultiThread {
            return Err(refused(
                "original phase requires the original multi-thread runtime",
            ));
        }
        let Self {
            identity,
            cognitive_mode,
            inputs,
            mut receiver,
            phase_handoff,
            scoped_handoff,
        } = self;
        let LaunchInputs {
            handoff,
            learning_handoff: _,
            q24_model_handoff: _,
            publication_handoff: _,
            initial_handoff: _,
            uid,
            gid,
            control,
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
            let phase =
                receive_original_phase_start(phase_handoff, timeout, receiver.instant())?;
            receiver.remaining()?;
            Ok::<_, AgentdError>(phase)
        })?;
        let timeout = receiver.remaining()?.min(Duration::from_millis(500));
        let OriginalSameActorProductionInputs {
            mut root,
            context,
            initial,
        } = receive_original_same_actor_inputs(
            bootstrap, root_pidfd, phase, &identity, timeout, receiver,
        )
        .await?;
        // From this point onward the actual same-Gate close guard already
        // exists outside every later future, including never-polled work.
        let _closing = CloseSameActorPhaseOnDrop::new(context.gate());
        let config =
            AgentdConfig::from_root_writer_handoff(&root, writer, std::env::current_dir()?)?
                .with_root_bound_sockets(control, app_server)?
                .with_cognitive_retrieval_mode(cognitive_mode);
        if config.identity() != &identity || context.identity() != &identity {
            return Err(refused(
                "original Starting Config differs from the received phase",
            ));
        }
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
            crate::AgentdRootProductionInputs::take_generation_publication_connection(
                &mut root,
            )?;
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
        let config = tokio::task::block_in_place(|| {
            install_original_initial_task(
                config,
                Arc::clone(&context),
                initial,
                business,
                scoped_handoff,
            )
        })?;
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
        // Actual Primary/session/writer/appserver composition and its
        // original signed ingress/readiness checks are still mandatory.
        // Generic bounded host shutdown can abort its async wrapper while
        // the original blocking owner is still joining real work. This
        // phase has no final completion/owner-join acknowledgement, so
        // generic Ok cannot certify a completed phase or physical join.
        launch.run(config, arg0_paths).await?;
        Err(refused(
            "original phase completion and physical owner join are not acknowledged",
        ))
    }
}

fn require_disjoint_phase_descriptors(
    arguments: &[OsString],
    phase: &UnixDatagram,
    scoped: &UnixDatagram,
) -> Result<(), AgentdError> {
    let extra = [phase.as_raw_fd(), scoped.as_raw_fd()];
    if extra[0] < 3 || extra[1] < 3 || extra[0] == extra[1] {
        return Err(refused(
            "original phase descriptors must be distinct inherited rights",
        ));
    }
    const OWNED_FLAGS: [&str; 15] = [
        "--root-production-handoff-fd",
        "--root-learning-handoff-fd",
        "--root-q24-model-handoff-fd",
        "--root-generation-publication-handoff-fd",
        "--root-generation-initial-handoff-fd",
        "--root-production-control-fd",
        "--root-production-app-server-fd",
        "--android-original-payload-fd",
        "--notes-production-handoff-fd",
        "--notes-literal-deployment-fd",
        "--notes-literal-ui-fd",
        "--notes-session-pidfd",
        "--desktop-production-handoff-fd",
        "--desktop-thread-deployment-fd",
        "--desktop-session-pidfd",
    ];
    for pair in arguments.chunks_exact(2) {
        if pair[0]
            .to_str()
            .is_some_and(|flag| OWNED_FLAGS.contains(&flag))
            && pair[1]
                .to_str()
                .and_then(|value| value.parse::<i32>().ok())
                .is_some_and(|fd| extra.contains(&fd))
        {
            return Err(refused(
                "phase descriptor aliases an original parser-owned right",
            ));
        }
    }
    Ok(())
}

fn refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
