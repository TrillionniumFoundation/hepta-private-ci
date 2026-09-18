use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeFinalUseAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeLocalSlotAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use serde::Deserialize;
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
    let mut request_id = None;
    let mut maximum_in_flight = None;
    let mut context_query = None;
    let mut final_use_config = None;
    let mut native_profile_selected = false;
    let mut timeout_ms = 120_000_u64;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        if flag == "--help" {
            println!(
                "hepta-infer-worker --profile native-app-server --agentd-socket PATH --agent-id ID --generation N --model MODEL --model-provider PROVIDER --journal PATH --request-id ID --maximum-in-flight N --final-use-config PATH [--context-query TEXT] [--timeout-ms N]\nReads one prompt from stdin; executes only after kernel final-use admission through the owning Agent's configured model provider."
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
            "--model-provider" => model_provider = Some(value),
            "--journal" => journal = Some(PathBuf::from(value)),
            "--request-id" => request_id = Some(value),
            "--maximum-in-flight" => maximum_in_flight = Some(value.parse()?),
            "--context-query" => context_query = Some(value),
            "--final-use-config" => final_use_config = Some(PathBuf::from(value)),
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
    let journal = journal.ok_or("--journal is required")?;
    if !journal.is_absolute() {
        return Err("--journal must be absolute".into());
    }
    let mut control = DurableInferenceControl::open(journal, /*capacity*/ 16_384)?;
    // One migration removes raw provider text from historical native observations.
    // The durable marker makes later opens O(1) for this check; new writes are
    // digest-only by construction.
    control.redact_native_output_history()?;
    let admission = NativeLocalSlotAdmission {
        request_id: request_id.ok_or("--request-id is required")?,
        maximum_in_flight: maximum_in_flight.ok_or("--maximum-in-flight is required")?,
    };
    let final_use_path = final_use_config.ok_or("--final-use-config is required")?;
    if !final_use_path.is_absolute() {
        return Err("--final-use-config must be absolute".into());
    }
    let final_use: NativeFinalUseConfig =
        serde_json::from_slice(&bounded_file(&final_use_path, 64 * 1024)?)?;
    if !final_use.authority_state_dir.is_absolute() {
        return Err("authority_state_dir must be absolute".into());
    }
    let authority = FinalUseAuthority::open_state_dir(
        &final_use.authority_state_dir,
        final_use.signer_id,
        final_use.verifying_key,
        FinalUseRevocations {
            authority_epoch: final_use.authority_epoch,
            revision: final_use.revocation_revision,
            revoked_grant_ids: final_use.revoked_grant_ids,
        },
    )?;
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
    let result = driver
        .run(
            &mut control,
            admission,
            Some(NativeFinalUseAdmission {
                authority: &authority,
                grant: &final_use.grant,
            }),
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
    if !output.succeeded() {
        return Err("model run lacks successful completion with verified owner authority".into());
    }
    Ok(())
}


#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeFinalUseConfig {
    signer_id: String,
    verifying_key: [u8; 32],
    authority_state_dir: PathBuf,
    authority_epoch: u64,
    revocation_revision: u64,
    #[serde(default)]
    revoked_grant_ids: BTreeSet<String>,
    grant: SignedFinalUseGrant,
}

fn bounded_file(
    path: &Path,
    maximum_bytes: usize,
) -> Result<Vec<u8>, Box<dyn std::error::Error + Send + Sync>> {
    let metadata = std::fs::metadata(path)?;
    if metadata.len() > maximum_bytes as u64 {
        return Err("final-use configuration exceeds 64 KiB".into());
    }
    let bytes = std::fs::read(path)?;
    if bytes.len() > maximum_bytes {
        return Err("final-use configuration exceeds 64 KiB".into());
    }
    Ok(bytes)
}
