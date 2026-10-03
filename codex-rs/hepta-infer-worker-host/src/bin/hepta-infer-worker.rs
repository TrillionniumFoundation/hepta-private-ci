use std::path::PathBuf;
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

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut socket = None;
    let mut agent_id = None;
    let mut generation = None;
    let mut model = None;
    let mut journal = None;
    let mut request_id = None;
    let mut maximum_in_flight = None;
    let mut context_query = None;
    let mut final_use_authority_config = None;
    let mut execution_mode = None;
    let mut intelligence_run_id = None;
    let mut native_profile_selected = false;
    let mut timeout_ms = 120_000_u64;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        if flag == "--help" {
            println!(
                "hepta-infer-worker --profile native-app-server --agentd-socket PATH --agent-id ID --generation N --model MODEL --journal PATH --request-id ID --maximum-in-flight N --final-use-authority-config ABSOLUTE_JSON --execution-mode agentd-admitted|unbound-development [--intelligence-run-id ID] [--context-query TEXT] [--timeout-ms N]\nReads one prompt from stdin. In agentd-admitted mode the worker loads the immutable run revision/context/envelope from Agentd; an independent final-use authority must still sign the exact turn/start binding before model dispatch."
            );
            return Ok(());
        }
        let value = args.next().ok_or("missing argument value")?;
        match flag.as_str() {
            "--profile" if value == "native-app-server" => native_profile_selected = true,
            "--profile" => return Err(format!("unsupported worker profile: {value}").into()),
            "--agentd-socket" => socket = Some(PathBuf::from(value)),
            "--agent-id" => agent_id = Some(AgentId::parse(value)?),
            "--generation" => generation = Some(value.parse()?),
            "--model" => model = Some(value),
            "--journal" => journal = Some(PathBuf::from(value)),
            "--request-id" => request_id = Some(value),
            "--maximum-in-flight" => maximum_in_flight = Some(value.parse()?),
            "--context-query" => context_query = Some(value),
            "--final-use-authority-config" => {
                final_use_authority_config = Some(PathBuf::from(value))
            }
            "--execution-mode" if value == "agentd-admitted" || value == "unbound-development" => {
                execution_mode = Some(value)
            }
            "--execution-mode" => return Err(format!("unsupported execution mode: {value}").into()),
            "--intelligence-run-id" => intelligence_run_id = Some(value),
            "--timeout-ms" => timeout_ms = value.parse()?,
            _ => return Err(format!("unknown argument: {flag}").into()),
        }
    }
    if !native_profile_selected {
        return Err("--profile native-app-server must be selected explicitly".into());
    }
    let final_use_authorizer = UnixFinalUseAuthorizer::open(
        &final_use_authority_config.ok_or("--final-use-authority-config is required")?,
    )?;
    // runtime.codex-agentd-admitted-executor-v1: retain the owner identity
    // for the durable binding lookup; the driver receives the same exact values.
    let agentd_socket = socket.ok_or("--agentd-socket is required")?;
    let agent_id = agent_id.ok_or("--agent-id is required")?;
    let generation = generation.ok_or("--generation is required")?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: agentd_socket.clone(),
        agent_id: agent_id.clone(),
        generation,
        model: model.ok_or("--model is required")?,
        timeout: Duration::from_millis(timeout_ms),
    })?
    .with_turn_start_authorizer(Arc::new(final_use_authorizer));
    let journal = journal.ok_or("--journal is required")?;
    if !journal.is_absolute() {
        return Err("--journal must be absolute".into());
    }
    let mut control = DurableInferenceControl::open(journal, /*capacity*/ 16_384)?;
    let admission = NativeAdmission {
        request_id: request_id.ok_or("--request-id is required")?,
        maximum_in_flight: maximum_in_flight.ok_or("--maximum-in-flight is required")?,
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
    let intelligence = match (execution_mode.as_deref(), intelligence_run_id) {
        (Some("agentd-admitted"), Some(run_id)) => {
            // runtime.codex-agentd-admitted-loader-v1
            Some(
                NativeIntelligenceRunBinding::load_from_agentd(
                    agentd_socket,
                    agent_id,
                    generation,
                    run_id,
                )
                .await?,
            )
        }
        (Some("unbound-development"), None) => None,
        (Some("agentd-admitted"), None) => {
            return Err("agentd-admitted mode requires --intelligence-run-id".into());
        }
        (Some("unbound-development"), Some(_)) => {
            return Err("unbound-development mode forbids --intelligence-run-id".into());
        }
        (None, _) => return Err("--execution-mode must be selected explicitly".into()),
        _ => unreachable!("execution mode was validated while parsing"),
    };
    let result = match intelligence {
        Some(binding) => {
            driver
                .run_intelligence(
                    &mut control,
                    admission,
                    prompt,
                    context_query,
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
                    context_query,
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
