use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeExecutionAuthority;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use codex_hepta_types::Digest32;
use tokio::io::AsyncReadExt;
use tokio_util::sync::CancellationToken;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut socket = None;
    let mut agent_id = None;
    let mut generation = None;
    let mut model = None;
    let mut model_provider = None;
    let mut journal = None;
    let mut operation_id = None;
    let mut request_id = None;
    let mut maximum_in_flight = None;
    let mut quota_reservation_digest = None;
    let mut resource_snapshot_digest = None;
    let mut authority_config = None;
    let mut context_query = None;
    let mut native_profile_selected = false;
    let mut authority_binding_only = false;
    let mut timeout_ms = 120_000_u64;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        if flag == "--help" {
            println!(
                "hepta-infer-worker --profile native-app-server --agentd-socket PATH --agent-id ID --generation N --model MODEL --model-provider PROVIDER --operation-id ID --request-id ID --maximum-in-flight N --quota-reservation-sha256 HEX --resource-snapshot-sha256 HEX [--authority-binding-only | --authority-config /absolute/authority.json --journal /absolute/private/native-runs.journal] [--context-query TEXT] [--timeout-ms N]\nReads one prompt from stdin. --authority-binding-only prints the exact FinalUseBinding without provider contact; execution requires an independently signed single-use grant."
            );
            return Ok(());
        }
        if flag == "--authority-binding-only" {
            authority_binding_only = true;
            continue;
        }
        let value = args.next().ok_or("missing argument value")?;
        match flag.as_str() {
            "--profile" if value == "native-app-server" => native_profile_selected = true,
            "--profile" => return Err(format!("unsupported worker profile: {value}").into()),
            "--agentd-socket" => socket = Some(PathBuf::from(value)),
            "--agent-id" => agent_id = Some(AgentId::parse(value)?),
            "--generation" => generation = Some(value.parse()?),
            "--model" => model = Some(value),
            "--model-provider" => model_provider = Some(value),
            "--journal" => journal = Some(PathBuf::from(value)),
            "--operation-id" => operation_id = Some(value),
            "--request-id" => request_id = Some(value),
            "--maximum-in-flight" => maximum_in_flight = Some(value.parse()?),
            "--quota-reservation-sha256" => quota_reservation_digest = Some(value.parse()?),
            "--resource-snapshot-sha256" => resource_snapshot_digest = Some(value.parse()?),
            "--authority-config" => authority_config = Some(PathBuf::from(value)),
            "--context-query" => context_query = Some(value),
            "--timeout-ms" => timeout_ms = value.parse()?,
            _ => return Err(format!("unknown argument: {flag}").into()),
        }
    }
    if !native_profile_selected {
        return Err("--profile native-app-server must be selected explicitly".into());
    }
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: socket.ok_or("--agentd-socket is required")?,
        agent_id: agent_id.ok_or("--agent-id is required")?,
        generation: generation.ok_or("--generation is required")?,
        model: model.ok_or("--model is required")?,
        model_provider: model_provider.ok_or("--model-provider is required")?,
        timeout: Duration::from_millis(timeout_ms),
    })?;
    let admission = NativeAdmission {
        operation_id: operation_id.ok_or("--operation-id is required")?,
        request_id: request_id.ok_or("--request-id is required")?,
        maximum_in_flight: maximum_in_flight.ok_or("--maximum-in-flight is required")?,
        quota_reservation_digest: quota_reservation_digest
            .ok_or("--quota-reservation-sha256 is required")?,
        resource_snapshot_digest: resource_snapshot_digest
            .ok_or("--resource-snapshot-sha256 is required")?,
    };
    let mut prompt = String::new();
    tokio::io::stdin()
        .take(32 * 1024 + 1)
        .read_to_string(&mut prompt)
        .await?;

    if authority_binding_only {
        let binding = driver
            .authority_binding(&admission, &prompt, context_query.as_deref())
            .await?;
        println!("{}", serde_json::to_string_pretty(&binding)?);
        return Ok(());
    }

    let authority_path = authority_config.ok_or("--authority-config is required")?;
    let authorization = NativeExecutionAuthority::from_file(&authority_path)?;
    let journal = journal.ok_or("--journal is required")?;
    if !journal.is_absolute() {
        return Err("--journal must be absolute".into());
    }
    let mut control = DurableInferenceControl::open(journal, /*capacity*/ 16_384)?;
    let cancellation = CancellationToken::new();
    let signal = cancellation.clone();
    let signal_task = tokio::spawn(async move {
        if tokio::signal::ctrl_c().await.is_ok() {
            signal.cancel();
        }
    });
    let result = driver
        .run(
            &mut control,
            admission,
            Some(&authorization),
            prompt,
            context_query,
            &cancellation,
        )
        .await;
    signal_task.abort();
    let output = result?;
    println!("{}", serde_json::to_string(&output)?);
    if !output.terminal_observed {
        return Err("model outcome is indeterminate; this request was not replayed".into());
    }
    if !output.output_retained {
        return Err(
            "durable terminal receipt exists, but raw model output was intentionally not retained; the request was not replayed"
                .into(),
        );
    }
    if !output.succeeded() {
        return Err(
            "model run lacks successful completion with both final-use and owner authority".into(),
        );
    }
    Ok(())
}
