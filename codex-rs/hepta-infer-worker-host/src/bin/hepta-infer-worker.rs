use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::QuotaReservation;
use codex_hepta_contracts::ResourceAdvertisement;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::GrantResolveError;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeExecutionPolicy;
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
    let mut maximum_output_tokens = None;
    let mut maximum_budget_units = None;
    let mut quota_reservation = None;
    let mut resource_advertisement = None;
    let mut final_use_state_dir = None;
    let mut final_use_signer_id = None;
    let mut final_use_verifying_key = None;
    let mut final_use_revocations = None;
    let mut final_use_grant = None;
    let mut context_query = None;
    let mut native_profile_selected = false;
    let mut timeout_ms = 120_000_u64;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        if flag == "--help" {
            println!(
                "hepta-infer-worker --profile native-app-server --agentd-socket PATH --agent-id ID --generation N --model MODEL --journal PATH --request-id ID --maximum-in-flight N --maximum-output-tokens N --maximum-budget-units N --quota-reservation PATH --resource-advertisement PATH --final-use-state-dir PATH --final-use-signer-id ID --final-use-verifying-key PATH --final-use-revocations PATH --final-use-grant PATH [--context-query TEXT] [--timeout-ms N]\nReads one prompt from stdin. Quota/resource evidence is validated before admission; an independently signed final-use grant must exactly match the frozen physical turn binding before provider dispatch."
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
            "--maximum-output-tokens" => maximum_output_tokens = Some(value.parse()?),
            "--maximum-budget-units" => maximum_budget_units = Some(value.parse()?),
            "--quota-reservation" => quota_reservation = Some(PathBuf::from(value)),
            "--resource-advertisement" => resource_advertisement = Some(PathBuf::from(value)),
            "--final-use-state-dir" => final_use_state_dir = Some(PathBuf::from(value)),
            "--final-use-signer-id" => final_use_signer_id = Some(value),
            "--final-use-verifying-key" => final_use_verifying_key = Some(PathBuf::from(value)),
            "--final-use-revocations" => final_use_revocations = Some(PathBuf::from(value)),
            "--final-use-grant" => final_use_grant = Some(PathBuf::from(value)),
            "--context-query" => context_query = Some(value),
            "--timeout-ms" => timeout_ms = value.parse()?,
            _ => return Err(format!("unknown argument: {flag}").into()),
        }
    }
    if !native_profile_selected {
        return Err("--profile native-app-server must be selected explicitly".into());
    }
    let authority_state_dir =
        final_use_state_dir.ok_or("--final-use-state-dir is required")?;
    if !authority_state_dir.is_absolute() {
        return Err("--final-use-state-dir must be absolute".into());
    }
    let revocations: FinalUseRevocations = serde_json::from_slice(&std::fs::read(
        final_use_revocations.ok_or("--final-use-revocations is required")?,
    )?)?;
    let verifying_key = read_hex_key(
        &final_use_verifying_key.ok_or("--final-use-verifying-key is required")?,
    )?;
    let final_use_authority = FinalUseAuthority::open_state_dir(
        &authority_state_dir,
        final_use_signer_id.ok_or("--final-use-signer-id is required")?,
        verifying_key,
        revocations,
    )?;

    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: socket.ok_or("--agentd-socket is required")?,
        agent_id: agent_id.ok_or("--agent-id is required")?,
        generation: generation.ok_or("--generation is required")?,
        model: model.ok_or("--model is required")?,
        timeout: Duration::from_millis(timeout_ms),
        final_use_authority,
    })?;
    let journal = journal.ok_or("--journal is required")?;
    if !journal.is_absolute() {
        return Err("--journal must be absolute".into());
    }
    let mut control = DurableInferenceControl::open(journal, /*capacity*/ 16_384)?;
    let quota: QuotaReservation = serde_json::from_slice(&std::fs::read(
        quota_reservation.ok_or("--quota-reservation is required")?,
    )?)?;
    let resource: ResourceAdvertisement = serde_json::from_slice(&std::fs::read(
        resource_advertisement.ok_or("--resource-advertisement is required")?,
    )?)?;
    let grant_bytes =
        std::fs::read(final_use_grant.ok_or("--final-use-grant is required")?)?;
    let admission = NativeAdmission {
        request_id: request_id.ok_or("--request-id is required")?,
        maximum_in_flight: maximum_in_flight.ok_or("--maximum-in-flight is required")?,
        maximum_output_tokens: maximum_output_tokens
            .ok_or("--maximum-output-tokens is required")?,
        maximum_budget_units: maximum_budget_units
            .ok_or("--maximum-budget-units is required")?,
        policy: NativeExecutionPolicy { quota, resource },
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
    let grant_resolver =
        |_binding: &FinalUseBinding| -> Result<SignedFinalUseGrant, GrantResolveError> {
            serde_json::from_slice(&grant_bytes).map_err(Into::into)
        };
    let result = driver
        .run(
            &mut control,
            admission,
            prompt,
            context_query,
            &cancellation,
            &grant_resolver,
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

fn read_hex_key(
    path: &std::path::Path,
) -> Result<[u8; 32], Box<dyn std::error::Error + Send + Sync>> {
    let raw = std::fs::read_to_string(path)?;
    let value = raw.trim();
    if value.len() != 64 {
        return Err("final-use verifying key must be 64 hexadecimal characters".into());
    }
    let mut key = [0_u8; 32];
    for (index, byte) in key.iter_mut().enumerate() {
        let offset = index * 2;
        *byte = u8::from_str_radix(&value[offset..offset + 2], 16)
            .map_err(|_| "final-use verifying key must be hexadecimal")?;
    }
    Ok(key)
}
