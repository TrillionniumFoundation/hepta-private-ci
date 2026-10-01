use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::final_use_authorizer::UnixFinalUseAuthorizer;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeIntelligenceRunBinding;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use tokio::io::AsyncReadExt;
use tokio_util::sync::CancellationToken;

#[path = "../native_cli.rs"]
mod cli;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let options = match cli::parse(std::env::args().skip(1))? {
        cli::Invocation::Help => {
            println!(
                "hepta-infer-worker --profile native-app-server --agentd-socket PATH --agent-id ID --generation N --model MODEL --journal PATH --request-id ID --maximum-in-flight N --final-use-authority-config ABSOLUTE_JSON [--intelligence-run-id ID --intelligence-revision N --intelligence-context-digest HEX --intelligence-envelope-digest HEX] [--context-query TEXT] [--timeout-ms N]\nReads one prompt from stdin; an independent final-use authority must sign the exact turn/start binding before model dispatch.\n--context-query and --intelligence-* are mutually exclusive until the owner provides a combined final-use port."
            );
            return Ok(());
        }
        cli::Invocation::Run(options) => *options,
    };
    let intelligence = options
        .intelligence
        .map(|binding| NativeIntelligenceRunBinding {
            run_id: binding.run_id,
            expected_revision: binding.expected_revision,
            context_digest: binding.context_digest,
            envelope_digest: binding.envelope_digest,
        });
    let agent_id = AgentId::parse(options.agent_id)?;
    let final_use_authorizer = UnixFinalUseAuthorizer::open(&options.final_use_authority_config)?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: options.agentd_socket,
        agent_id,
        generation: options.generation,
        model: options.model,
        timeout: Duration::from_millis(options.timeout_ms),
    })?
    .with_turn_start_authorizer(Arc::new(final_use_authorizer));
    let mut control = DurableInferenceControl::open(options.journal, /*capacity*/ 16_384)?;
    let admission = NativeAdmission {
        request_id: options.request_id,
        maximum_in_flight: options.maximum_in_flight,
    };
    let mut prompt = String::new();
    tokio::io::stdin()
        .take(32 * 1024 + 1)
        .read_to_string(&mut prompt)
        .await?;
    let cancellation = CancellationToken::new();
    let signal = cancellation.clone();
    let signal_task = tokio::spawn(async move {
        if tokio::signal::ctrl_c().await.is_ok() {
            signal.cancel();
        }
    });
    let result = match intelligence {
        Some(binding) => {
            driver
                .run_intelligence(
                    &mut control,
                    admission,
                    prompt,
                    options.context_query,
                    binding,
                    &cancellation,
                )
                .await
        }
        None => {
            driver
                .run(
                    &mut control,
                    admission,
                    prompt,
                    options.context_query,
                    &cancellation,
                )
                .await
        }
    };
    signal_task.abort();
    let output = result?;
    println!("{}", serde_json::to_string(&output)?);
    if !output.terminal_observed {
        return Err("model outcome is indeterminate; this request was not replayed".into());
    }
    if !output.succeeded() {
        return Err("model run lacks successful completion with verified owner authority".into());
    }
    Ok(())
}
