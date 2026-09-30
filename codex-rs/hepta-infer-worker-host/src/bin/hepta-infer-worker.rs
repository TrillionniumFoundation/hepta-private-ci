use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::control_contracts::ControlTrustStore;
use codex_hepta_infer_core::control_contracts::OutputStorageMode;
use codex_hepta_infer_core::control_contracts::SignedExecutionAuthorityBundle;
use codex_hepta_infer_core::control_contracts::TrustKey;
use codex_hepta_infer_core::control_contracts::verify_execution_plan;
use codex_hepta_infer_worker_host::NativeJournalWriterActor;
use codex_hepta_infer_worker_host::NativeOutputProtector;
use codex_hepta_infer_worker_host::NativeWriterLimits;
use codex_hepta_infer_worker_host::UnixOutputProtector;
use codex_hepta_infer_worker_host::final_use_authorizer::UnixFinalUseAuthorizer;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeIntelligenceRunBinding;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use serde::Deserialize;
use serde::de::DeserializeOwned;
use tokio::io::AsyncReadExt;
use tokio_util::sync::CancellationToken;

const MAX_AUTHORITY_DOCUMENT_BYTES: u64 = 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustStoreDocument {
    schema_version: u32,
    keys: Vec<TrustKey>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut socket = None;
    let mut agent_id = None;
    let mut generation = None;
    let mut model = None;
    let mut journal = None;
    let mut writer_limits = NativeWriterLimits::default();
    let mut request_id = None;
    let mut maximum_in_flight = None;
    let mut context_query = None;
    let mut final_use_authority_config = None;
    let mut execution_trust_store = None;
    let mut execution_authority_bundle = None;
    let mut output_protector_config = None;
    let mut intelligence_run_id = None;
    let mut intelligence_revision = None;
    let mut intelligence_context_digest = None;
    let mut intelligence_envelope_digest = None;
    let mut timeout_ms = 120_000_u64;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        if flag == "--help" {
            println!(
                "hepta-infer-worker [--profile native-app-server] --agentd-socket PATH --agent-id ID --generation N --model MODEL --journal PATH --request-id ID --maximum-in-flight N --final-use-authority-config ABSOLUTE_JSON --execution-trust-store ABSOLUTE_JSON --execution-authority-bundle ABSOLUTE_JSON [--output-protector-config ABSOLUTE_JSON] [--intelligence-run-id ID --intelligence-revision N --intelligence-context-digest HEX --intelligence-envelope-digest HEX] [--context-query TEXT] [--timeout-ms N] [--writer-ordinary-capacity N --writer-terminal-capacity N --writer-reply-timeout-ms N --writer-shutdown-timeout-ms N]\nThe sole release profile is native-app-server and is selected by default. Reads one prompt from stdin. Four independent execution authorities and an independent final-use authority must authenticate the exact model/runtime/resource/quota/data binding before physical turn/start. External-encrypted output policies additionally require the UID-bound output-vault configuration."
            );
            return Ok(());
        }
        let value = args.next().ok_or("missing argument value")?;
        match flag.as_str() {
            "--writer-ordinary-capacity" => {
                writer_limits.ordinary_queue_capacity = value.parse()?
            }
            "--writer-terminal-capacity" => {
                writer_limits.terminal_queue_capacity = value.parse()?
            }
            "--writer-reply-timeout-ms" => {
                writer_limits.reply_timeout = Duration::from_millis(value.parse()?)
            }
            "--writer-shutdown-timeout-ms" => {
                writer_limits.shutdown_timeout = Duration::from_millis(value.parse()?)
            }
            "--profile" if value == "native-app-server" => {}
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
            "--execution-trust-store" => execution_trust_store = Some(PathBuf::from(value)),
            "--execution-authority-bundle" => {
                execution_authority_bundle = Some(PathBuf::from(value))
            }
            "--output-protector-config" => output_protector_config = Some(PathBuf::from(value)),
            "--intelligence-run-id" => intelligence_run_id = Some(value),
            "--intelligence-revision" => intelligence_revision = Some(value.parse()?),
            "--intelligence-context-digest" => intelligence_context_digest = Some(value),
            "--intelligence-envelope-digest" => intelligence_envelope_digest = Some(value),
            "--timeout-ms" => timeout_ms = value.parse()?,
            _ => return Err(format!("unknown argument: {flag}").into()),
        }
    }

    let trust_document: TrustStoreDocument = read_owner_only_json(
        &execution_trust_store.ok_or("--execution-trust-store is required")?,
        "execution trust store",
    )?;
    if trust_document.schema_version != 1 {
        return Err("unsupported execution trust-store schema".into());
    }
    let trust = ControlTrustStore::new(trust_document.keys)?;
    let signed_bundle: SignedExecutionAuthorityBundle = read_owner_only_json(
        &execution_authority_bundle.ok_or("--execution-authority-bundle is required")?,
        "execution authority bundle",
    )?;
    let plan = verify_execution_plan(unix_time_ms()?, &trust, &signed_bundle)?;

    let request_id = request_id.ok_or("--request-id is required")?;
    let agent_id = agent_id.ok_or("--agent-id is required")?;
    let generation = generation.ok_or("--generation is required")?;
    let model = model.ok_or("--model is required")?;
    if plan.request_id() != request_id
        || plan.principal_id() != agent_id.to_string()
        || plan.resource_lease().worker_generation != generation
        || plan.manifest().model_id != model
    {
        return Err(
            "execution authority bundle does not match CLI request/Agent/model/generation".into(),
        );
    }

    let output_protector = match output_protector_config {
        Some(path) => Some(UnixOutputProtector::open(&path)?),
        None => None,
    };
    if plan.output_policy().storage_mode == OutputStorageMode::ExternalEncrypted
        && output_protector.is_none()
    {
        return Err("external-encrypted output policy requires --output-protector-config".into());
    }

    let final_use_authorizer = UnixFinalUseAuthorizer::open(
        &final_use_authority_config.ok_or("--final-use-authority-config is required")?,
    )?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: socket.ok_or("--agentd-socket is required")?,
        agent_id,
        generation,
        model,
        timeout: Duration::from_millis(timeout_ms),
    })?
    .with_turn_start_authorizer(Arc::new(final_use_authorizer));
    let journal = journal.ok_or("--journal is required")?;
    if !journal.is_absolute() {
        return Err("--journal must be absolute".into());
    }
    let actor = NativeJournalWriterActor::spawn_with_limits(
        journal,
        /*capacity*/ 16_384,
        writer_limits,
    )?;
    let mut control = actor.handle();
    let admission = NativeAdmission {
        request_id,
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
    let intelligence = match (
        intelligence_run_id,
        intelligence_revision,
        intelligence_context_digest,
        intelligence_envelope_digest,
    ) {
        (None, None, None, None) => None,
        (Some(run_id), Some(expected_revision), Some(context_digest), Some(envelope_digest)) => {
            Some(NativeIntelligenceRunBinding {
                run_id,
                expected_revision,
                context_digest,
                envelope_digest,
            })
        }
        _ => {
            return Err("all four --intelligence-* arguments must be supplied together".into());
        }
    };
    let output_protector_ref = output_protector
        .as_ref()
        .map(|protector| protector as &dyn NativeOutputProtector);
    let result = match intelligence {
        Some(binding) => {
            driver
                .run_intelligence_authorized(
                    &mut control,
                    admission,
                    prompt,
                    context_query,
                    binding,
                    &plan,
                    output_protector_ref,
                    &cancellation,
                )
                .await
        }
        None => match output_protector_ref {
            Some(protector) => {
                driver
                    .run_authorized_with_output_protector(
                        &mut control,
                        admission,
                        prompt,
                        context_query,
                        &plan,
                        protector,
                        &cancellation,
                    )
                    .await
            }
            None => {
                driver
                    .run_authorized(
                        &mut control,
                        admission,
                        prompt,
                        context_query,
                        &plan,
                        &cancellation,
                    )
                    .await
            }
        },
    };
    signal_task.abort();
    drop(control);
    let shutdown_result = actor.shutdown().await;
    let output = result?;
    shutdown_result?;
    println!("{}", serde_json::to_string(&output)?);
    if !output.terminal_observed {
        return Err("model outcome is indeterminate; this request was not replayed".into());
    }
    if !output.succeeded() {
        return Err("model run lacks successful completion with verified owner authority".into());
    }
    Ok(())
}

fn read_owner_only_json<T: DeserializeOwned>(
    path: &Path,
    label: &str,
) -> Result<T, Box<dyn std::error::Error + Send + Sync>> {
    if !path.is_absolute() {
        return Err(format!("{label} path must be absolute").into());
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(format!("{label} must be a regular non-symlink file").into());
    }
    if metadata.len() == 0 || metadata.len() > MAX_AUTHORITY_DOCUMENT_BYTES {
        return Err(format!("{label} size is outside the accepted bound").into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(format!("{label} must be owner-only").into());
        }
    }
    let bytes = fs::read(path)?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn unix_time_ms() -> Result<u64, Box<dyn std::error::Error + Send + Sync>> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_millis()
        .try_into()?)
}
