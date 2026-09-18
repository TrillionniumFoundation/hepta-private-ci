use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::model_worker::ModelManifest;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use serde::de::DeserializeOwned;
use tokio::io::AsyncReadExt;
use tokio_util::sync::CancellationToken;

#[cfg(unix)]
use codex_hepta_infer_worker_host::local_process::LocalModelArtifacts;
#[cfg(unix)]
use codex_hepta_infer_worker_host::local_product::LocalExecutionEnvelopeV1;
#[cfg(unix)]
use codex_hepta_infer_worker_host::local_product::LocalProductConfig;
#[cfg(unix)]
use codex_hepta_infer_worker_host::local_product::LocalProductStatus;
#[cfg(unix)]
use codex_hepta_infer_worker_host::local_product::execute_local_product;

const MAX_JSON_BYTES: u64 = 2 * 1024 * 1024;

type MainResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[tokio::main]
async fn main() -> MainResult<()> {
    let args = parse_args()?;
    if args.contains_key("--help") {
        print_help();
        return Ok(());
    }
    match required(&args, "--profile")?.as_str() {
        "native-app-server" => run_native(&args).await,
        "local-process" => run_local(&args),
        other => Err(format!("unsupported worker profile: {other}").into()),
    }
}

async fn run_native(args: &BTreeMap<String, String>) -> MainResult<()> {
    let timeout_ms = optional_parse(args, "--timeout-ms")?.unwrap_or(120_000_u64);
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: PathBuf::from(required(args, "--agentd-socket")?),
        agent_id: AgentId::parse(required(args, "--agent-id")?)?,
        generation: parse_required(args, "--generation")?,
        model: required(args, "--model")?,
        timeout: Duration::from_millis(timeout_ms),
    })?;
    let journal = PathBuf::from(required(args, "--journal")?);
    if !journal.is_absolute() {
        return Err("--journal must be absolute".into());
    }
    let mut control = DurableInferenceControl::open(journal, /*capacity*/ 16_384)?;
    let admission = NativeAdmission {
        request_id: required(args, "--request-id")?,
        maximum_in_flight: parse_required(args, "--maximum-in-flight")?,
    };
    let context_query = args.get("--context-query").cloned();
    let mut prompt = String::new();
    tokio::io::stdin()
        .take(32 * 1024 + 1)
        .read_to_string(&mut prompt)
        .await?;
    if prompt.len() > 32 * 1024 {
        return Err("prompt exceeds 32768 bytes".into());
    }
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
            prompt,
            context_query,
            &cancellation,
        )
        .await;
    signal_task.abort();
    let output = result?;
    println!("{}", serde_json::to_string(&output)?);
    if !output.terminal_observed {
        return Err(
            "model outcome is indeterminate; provider reconciliation remains required".into(),
        );
    }
    if !output.succeeded() {
        return Err(
            "model run lacks successful completion, verified owner authority, or actual token usage"
                .into(),
        );
    }
    Ok(())
}

#[cfg(unix)]
fn run_local(args: &BTreeMap<String, String>) -> MainResult<()> {
    let timeout_ms = optional_parse(args, "--timeout-ms")?.unwrap_or(120_000_u64);
    let manifest_path = PathBuf::from(required(args, "--manifest")?);
    let resource_grant_path = PathBuf::from(required(args, "--resource-grant")?);
    let signed_grant_path = PathBuf::from(required(args, "--signed-resource-grant")?);
    let revocations_path = PathBuf::from(required(args, "--authority-revocations")?);
    let request_path = PathBuf::from(required(args, "--request-envelope")?);

    let manifest: ModelManifest = read_json(&manifest_path)?;
    let resource_grant: ResourceGrant = read_json(&resource_grant_path)?;
    let signed_resource_grant: SignedFinalUseGrant = read_json(&signed_grant_path)?;
    let revocations: FinalUseRevocations = read_json(&revocations_path)?;
    let envelope: LocalExecutionEnvelopeV1 = read_json(&request_path)?;

    let authority_state_dir = PathBuf::from(required(args, "--authority-state-dir")?);
    if !authority_state_dir.is_absolute() {
        return Err("--authority-state-dir must be absolute".into());
    }
    let verifying_key = parse_hex32(&required(args, "--authority-verifying-key-hex")?)?;
    let authority = FinalUseAuthority::open_state_dir(
        &authority_state_dir,
        required(args, "--authority-signer")?,
        verifying_key,
        revocations,
    )?;

    let artifacts = LocalModelArtifacts {
        weights_path: absolute_flag(args, "--weights")?,
        tokenizer_path: absolute_flag(args, "--tokenizer")?,
        preprocessor_path: absolute_flag(args, "--preprocessor")?,
        quantization_path: absolute_flag(args, "--quantization")?,
        runtime_path: absolute_flag(args, "--runtime-binary")?,
        device_descriptor_path: absolute_flag(args, "--device-descriptor")?,
        isolation_receipt_path: absolute_flag(args, "--isolation-receipt")?,
    };
    let config = LocalProductConfig {
        worker_id: required(args, "--worker-id")?,
        generation: parse_required(args, "--generation")?,
        runtime_socket: absolute_flag(args, "--runtime-socket")?,
        artifacts,
        timeout: Duration::from_millis(timeout_ms),
    };
    let output = execute_local_product(
        unix_ms()?,
        config,
        &authority,
        &signed_resource_grant,
        resource_grant,
        manifest,
        envelope,
    )?;
    println!("{}", serde_json::to_string(&output)?);
    if !output.terminal_observed || output.status != LocalProductStatus::Succeeded {
        return Err("local model run did not produce a successful terminal observation".into());
    }
    Ok(())
}

#[cfg(not(unix))]
fn run_local(_args: &BTreeMap<String, String>) -> MainResult<()> {
    Err("local-process profile requires a Unix host".into())
}

fn parse_args() -> MainResult<BTreeMap<String, String>> {
    let mut parsed = BTreeMap::new();
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        if flag == "--help" {
            if parsed.insert(flag, String::new()).is_some() {
                return Err("duplicate --help".into());
            }
            continue;
        }
        if !SUPPORTED_FLAGS.contains(&flag.as_str()) {
            return Err(format!("unknown argument: {flag}").into());
        }
        let value = args.next().ok_or("missing argument value")?;
        if parsed.insert(flag.clone(), value).is_some() {
            return Err(format!("duplicate argument: {flag}").into());
        }
    }
    Ok(parsed)
}

const SUPPORTED_FLAGS: &[&str] = &[
    "--profile",
    "--agentd-socket",
    "--agent-id",
    "--generation",
    "--model",
    "--journal",
    "--request-id",
    "--maximum-in-flight",
    "--context-query",
    "--timeout-ms",
    "--worker-id",
    "--manifest",
    "--resource-grant",
    "--signed-resource-grant",
    "--authority-state-dir",
    "--authority-signer",
    "--authority-verifying-key-hex",
    "--authority-revocations",
    "--request-envelope",
    "--runtime-socket",
    "--weights",
    "--tokenizer",
    "--preprocessor",
    "--quantization",
    "--runtime-binary",
    "--device-descriptor",
    "--isolation-receipt",
];

fn required(args: &BTreeMap<String, String>, flag: &'static str) -> MainResult<String> {
    args.get(flag)
        .cloned()
        .ok_or_else(|| format!("{flag} is required").into())
}

fn parse_required<T>(args: &BTreeMap<String, String>, flag: &'static str) -> MainResult<T>
where
    T: std::str::FromStr,
    T::Err: std::error::Error + Send + Sync + 'static,
{
    Ok(required(args, flag)?.parse()?)
}

fn optional_parse<T>(args: &BTreeMap<String, String>, flag: &'static str) -> MainResult<Option<T>>
where
    T: std::str::FromStr,
    T::Err: std::error::Error + Send + Sync + 'static,
{
    args.get(flag)
        .map(|value| value.parse().map_err(Into::into))
        .transpose()
}

fn absolute_flag(args: &BTreeMap<String, String>, flag: &'static str) -> MainResult<PathBuf> {
    let path = PathBuf::from(required(args, flag)?);
    if !path.is_absolute() {
        return Err(format!("{flag} must be absolute").into());
    }
    Ok(path)
}

fn read_json<T: DeserializeOwned>(path: &Path) -> MainResult<T> {
    if !path.is_absolute() {
        return Err(format!("configuration path must be absolute: {}", path.display()).into());
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > MAX_JSON_BYTES {
        return Err(format!("unsafe or oversized configuration file: {}", path.display()).into());
    }
    let bytes = std::fs::read(path)?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn parse_hex32(value: &str) -> MainResult<[u8; 32]> {
    if value.len() != 64 {
        return Err("verifying key must be exactly 64 lowercase hex characters".into());
    }
    let mut output = [0_u8; 32];
    let bytes = value.as_bytes();
    for (index, slot) in output.iter_mut().enumerate() {
        let high = hex_nibble(bytes[index * 2]).ok_or("invalid verifying key hex")?;
        let low = hex_nibble(bytes[index * 2 + 1]).ok_or("invalid verifying key hex")?;
        *slot = (high << 4) | low;
    }
    Ok(output)
}

fn hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

fn unix_ms() -> MainResult<u64> {
    let value = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
    Ok(u64::try_from(value)?)
}

fn print_help() {
    println!(
        "hepta-infer-worker profiles:\n\
         native-app-server: --profile native-app-server --agentd-socket PATH --agent-id ID --generation N --model MODEL --journal PATH --request-id ID --maximum-in-flight N [--context-query TEXT] [--timeout-ms N]; reads one prompt from stdin.\n\
         local-process (Unix): --profile local-process --worker-id ID --generation N --manifest ABS --resource-grant ABS --signed-resource-grant ABS --authority-state-dir ABS --authority-signer ID --authority-verifying-key-hex HEX --authority-revocations ABS --request-envelope ABS --runtime-socket ABS --weights ABS --tokenizer ABS --preprocessor ABS --quantization ABS --runtime-binary ABS --device-descriptor ABS --isolation-receipt ABS [--timeout-ms N]."
    );
}
