use std::sync::Arc;

use codex_arg0::Arg0DispatchPaths;
use codex_hepta_app_bridge::memory::CognitiveRuntime;
use codex_hepta_app_bridge::memory::ProductionCognitiveMutation;
use codex_hepta_app_host::HeptaAppServerHostOptions;

use crate::AgentdIdentity;
use crate::AgentdState;
use crate::error::contextual_io_error;
use crate::qualification_writer::qualification_turn_writer_host;

#[cfg(feature = "production-cognitive-write")]
const COGNITIVE_WRITE_ENABLED: bool = true;
#[cfg(not(feature = "production-cognitive-write"))]
const COGNITIVE_WRITE_ENABLED: bool = false;

#[cfg(feature = "qualification-cognitive-write")]
const QUALIFICATION_TURN_WRITER_ENABLED: bool = true;
#[cfg(not(feature = "qualification-cognitive-write"))]
const QUALIFICATION_TURN_WRITER_ENABLED: bool = false;

pub(crate) async fn run_app_server(
    identity: AgentdIdentity,
    arg0_paths: Arg0DispatchPaths,
    cognitive_runtime: CognitiveRuntime,
    state: Arc<AgentdState>,
    production_writer_host: Option<Arc<crate::AgentdProductionWriterHost>>,
) -> std::io::Result<()> {
    let production_cognitive_mutation: Option<Arc<dyn ProductionCognitiveMutation>> =
        production_writer_host.and_then(|host| host.production_mutation());
    let prompt_runtime_host = state
        .prompt_pipeline_owner()
        .runtime_owner()
        .host()
        .map_err(std::io::Error::other)?;
    let graceful_drain = state.app_server_drain_handle();
    let qualification_turn_writer =
        qualification_turn_writer_host(&identity, state, &cognitive_runtime);
    let socket_path = identity.app_server_socket.clone();
    let options = HeptaAppServerHostOptions {
        socket_path: socket_path.clone(),
        home_root: identity.home_root.clone(),
        turn_queue_capacity: u64::from(identity.resources.turn_queue_capacity),
        cognitive_runtime,
        production_cognitive_mutation,
        qualification_turn_writer,
        prompt_runtime_host: Some(prompt_runtime_host),
        graceful_drain: Some(graceful_drain),
        cognitive_write_profile: COGNITIVE_WRITE_ENABLED,
        qualification_turn_writer_profile: QUALIFICATION_TURN_WRITER_ENABLED,
    };
    codex_hepta_app_host::run(arg0_paths, options)
        .await
        .map_err(|error| {
            contextual_io_error(
                "run Codex App Server through Hepta app host",
                &socket_path,
                error,
            )
        })
}
