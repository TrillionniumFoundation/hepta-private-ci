//! Long-lived production composition root for local isolated inference.
//!
//! One process owns one authenticated worker generation, resident model
//! runtimes and the live resource-authority handle. JSONL control input is a
//! bounded host-local control surface: run requests execute on the owner thread,
//! cancel signals can interrupt an in-flight request, and trusted revocation
//! updates apply concurrently through the shared FinalUseAuthority.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::io::BufRead;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_worker_host::local_process_driver::LocalModelArtifacts;
use codex_hepta_infer_worker_host::local_process_driver::LocalProcessDriverConfig;
use codex_hepta_infer_worker_host::model_worker::ExecutionStatus;
use codex_hepta_infer_worker_host::model_worker::ModelManifest;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_infer_worker_host::model_worker::WorkerRequest;
use codex_hepta_inferd::local_worker_host::LocalWorkerHost;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

const MAX_CONFIG_BYTES: usize = 128 * 1024;
const MAX_GRANT_BYTES: usize = 32 * 1024;
const MAX_COMMAND_BYTES: usize = 1024 * 1024 + 16 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HostConfig {
    worker_id: String,
    authority_state_dir: PathBuf,
    signer_id: String,
    verifying_key: [u8; 32],
    initial_revocations: FinalUseRevocations,
    resource_grant: ResourceGrantConfig,
    runtime_executable: PathBuf,
    sandbox_launcher: PathBuf,
    immutable_artifact_root: PathBuf,
    maximum_protocol_line_bytes: usize,
    response_timeout_ms: u64,
    shutdown_timeout_ms: u64,
    model: ModelConfig,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceGrantConfig {
    grant_id: String,
    authority_epoch: u64,
    generation: u64,
    expires_at_ms: u64,
    maximum_models: usize,
    maximum_active_requests: usize,
    maximum_memory_bytes: u64,
    semantic_digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ModelConfig {
    model_id: String,
    model_digest: String,
    weights_digest: String,
    tokenizer_digest: String,
    preprocessor_digest: String,
    quantization_digest: String,
    runtime_digest: String,
    device_digest: String,
    maximum_tokens: u32,
    weights_path: PathBuf,
    tokenizer_path: PathBuf,
    preprocessor_path: PathBuf,
    quantization_path: PathBuf,
    device_descriptor_path: PathBuf,
}

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum ControlCommand {
    Run {
        request_id: String,
        reservation_id: String,
        input: String,
        maximum_tokens: u32,
        deadline_ms: u64,
    },
    Cancel {
        request_id: String,
    },
    Revocations {
        authority_epoch: u64,
        revision: u64,
        revoked_grant_ids: BTreeSet<String>,
    },
    Shutdown,
}

enum OwnerCommand {
    Run {
        request: WorkerRequest,
        cancellation: CancellationToken,
    },
    Shutdown,
}

fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut args = std::env::args().skip(1);
    if args.next().as_deref() != Some("serve") {
        return Err(usage().into());
    }
    let config_path = PathBuf::from(args.next().ok_or(usage())?);
    let grant_path = PathBuf::from(args.next().ok_or(usage())?);
    if args.next().is_some() {
        return Err(usage().into());
    }

    let config: HostConfig =
        serde_json::from_slice(&read_private_file(&config_path, MAX_CONFIG_BYTES)?)?;
    let signed: SignedFinalUseGrant =
        serde_json::from_slice(&read_private_file(&grant_path, MAX_GRANT_BYTES)?)?;
    validate_config(&config)?;

    let authority = FinalUseAuthority::open_state_dir(
        &config.authority_state_dir,
        config.signer_id.clone(),
        config.verifying_key,
        config.initial_revocations.clone(),
    )?;
    let authority_updates = authority.clone();

    let resource_grant = ResourceGrant {
        grant_id: config.resource_grant.grant_id.clone(),
        authority_epoch: config.resource_grant.authority_epoch,
        generation: config.resource_grant.generation,
        expires_at_ms: config.resource_grant.expires_at_ms,
        revoked: false,
        maximum_models: config.resource_grant.maximum_models,
        maximum_active_requests: config.resource_grant.maximum_active_requests,
        maximum_memory_bytes: config.resource_grant.maximum_memory_bytes,
        semantic_digest: config.resource_grant.semantic_digest.clone(),
    };
    let manifest = ModelManifest {
        model_id: config.model.model_id.clone(),
        model_digest: config.model.model_digest.clone(),
        weights_digest: config.model.weights_digest.clone(),
        tokenizer_digest: config.model.tokenizer_digest.clone(),
        preprocessor_digest: config.model.preprocessor_digest.clone(),
        quantization_digest: config.model.quantization_digest.clone(),
        runtime_digest: config.model.runtime_digest.clone(),
        device_digest: config.model.device_digest.clone(),
        maximum_tokens: config.model.maximum_tokens,
    };
    let artifacts = LocalModelArtifacts {
        weights_path: config.model.weights_path.clone(),
        tokenizer_path: config.model.tokenizer_path.clone(),
        preprocessor_path: config.model.preprocessor_path.clone(),
        quantization_path: config.model.quantization_path.clone(),
        device_descriptor_path: config.model.device_descriptor_path.clone(),
    };
    let mut models = BTreeMap::new();
    models.insert(manifest.model_id.clone(), artifacts);
    let mut driver = LocalProcessDriverConfig::new(config.runtime_executable.clone(), models)
        .with_production_isolation(
            config.sandbox_launcher.clone(),
            config.immutable_artifact_root.clone(),
        );
    driver.maximum_protocol_line_bytes = config.maximum_protocol_line_bytes;
    driver.response_timeout = Duration::from_millis(config.response_timeout_ms);
    driver.shutdown_timeout = Duration::from_millis(config.shutdown_timeout_ms);

    let mut host = LocalWorkerHost::new(
        now_ms()?,
        config.worker_id.clone(),
        resource_grant,
        authority,
        signed,
        driver,
    )?;
    host.load_model(now_ms()?, manifest.clone())?;

    let (owner_tx, owner_rx) = mpsc::channel::<OwnerCommand>();
    let (output_tx, output_rx) = mpsc::channel::<Value>();
    let current = Arc::new(Mutex::new(None::<(String, CancellationToken)>));
    let current_owner = Arc::clone(&current);
    let busy = Arc::new(AtomicBool::new(false));
    let busy_owner = Arc::clone(&busy);
    let model_id = manifest.model_id.clone();

    let owner = std::thread::Builder::new()
        .name("hepta-local-inference-owner".to_string())
        .spawn(move || {
            while let Ok(command) = owner_rx.recv() {
                match command {
                    OwnerCommand::Run {
                        request,
                        cancellation,
                    } => {
                        let request_id = request.request_id.clone();
                        if let Ok(mut slot) = current_owner.lock() {
                            *slot = Some((request_id.clone(), cancellation.clone()));
                        }
                        let result = host.run(
                            now_ms().unwrap_or(0),
                            &model_id,
                            request,
                            &cancellation,
                        );
                        if let Ok(mut slot) = current_owner.lock() {
                            *slot = None;
                        }
                        busy_owner.store(false, Ordering::Release);
                        let response = match result {
                            Ok(observed) => json!({
                                "op": "run_result",
                                "request_id": observed.request_id,
                                "status": status_name(&observed.status),
                                "terminal_observed": observed.terminal_observed,
                                "output_digest": observed.output_digest,
                                "consumed_tokens": observed.consumed_tokens,
                                "observed_memory_bytes": observed.observed_memory_bytes,
                            }),
                            Err(error) => json!({
                                "op": "run_result",
                                "request_id": request_id,
                                "status": "error",
                                "error": error.to_string(),
                            }),
                        };
                        let _ = output_tx.send(response);
                    }
                    OwnerCommand::Shutdown => {
                        let result = host.shutdown(now_ms().unwrap_or(0));
                        let _ = output_tx.send(match result {
                            Ok(_) => json!({"op":"shutdown","status":"ok"}),
                            Err(error) => {
                                json!({"op":"shutdown","status":"error","error":error.to_string()})
                            }
                        });
                        return;
                    }
                }
            }
        })?;

    let output = std::thread::Builder::new()
        .name("hepta-local-inference-output".to_string())
        .spawn(move || {
            while let Ok(value) = output_rx.recv() {
                println!("{value}");
            }
        })?;

    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        let line = line?;
        if line.len() > MAX_COMMAND_BYTES {
            println!("{}", json!({"status":"error","error":"command exceeds bound"}));
            continue;
        }
        let command: ControlCommand = match serde_json::from_str(&line) {
            Ok(command) => command,
            Err(error) => {
                println!("{}", json!({"status":"error","error":error.to_string()}));
                continue;
            }
        };
        match command {
            ControlCommand::Run {
                request_id,
                reservation_id,
                input,
                maximum_tokens,
                deadline_ms,
            } => {
                if busy.swap(true, Ordering::AcqRel) {
                    println!(
                        "{}",
                        json!({"op":"run","request_id":request_id,"status":"busy"})
                    );
                    continue;
                }
                let payload_digest = sha256(input.as_bytes());
                let request = WorkerRequest {
                    request_id,
                    reservation_id,
                    model_digest: manifest.model_digest.clone(),
                    input,
                    payload_digest: payload_digest.clone(),
                    maximum_tokens,
                    deadline_ms,
                    lease_payload_digest: payload_digest,
                    reservation_model_digest: manifest.model_digest.clone(),
                    reservation_maximum_tokens: maximum_tokens,
                    cancelled: false,
                };
                let cancellation = CancellationToken::new();
                owner_tx.send(OwnerCommand::Run {
                    request,
                    cancellation,
                })?;
            }
            ControlCommand::Cancel { request_id } => {
                let cancelled = current
                    .lock()
                    .ok()
                    .and_then(|slot| slot.as_ref().cloned())
                    .is_some_and(|(active, token)| {
                        if active == request_id {
                            token.cancel();
                            true
                        } else {
                            false
                        }
                    });
                println!(
                    "{}",
                    json!({"op":"cancel","request_id":request_id,"accepted":cancelled})
                );
            }
            ControlCommand::Revocations {
                authority_epoch,
                revision,
                revoked_grant_ids,
            } => {
                let result = authority_updates.update_revocations(FinalUseRevocations {
                    authority_epoch,
                    revision,
                    revoked_grant_ids,
                });
                println!(
                    "{}",
                    match result {
                        Ok(()) => json!({"op":"revocations","status":"ok"}),
                        Err(error) => {
                            json!({"op":"revocations","status":"error","error":error.to_string()})
                        }
                    }
                );
            }
            ControlCommand::Shutdown => {
                if let Ok(slot) = current.lock()
                    && let Some((_, token)) = slot.as_ref()
                {
                    token.cancel();
                }
                owner_tx.send(OwnerCommand::Shutdown)?;
                break;
            }
        }
    }

    drop(owner_tx);
    owner.join().map_err(|_| "local owner thread panicked")?;
    drop(current);
    output.join().map_err(|_| "local output thread panicked")?;
    Ok(())
}

fn validate_config(config: &HostConfig) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    for path in [
        &config.authority_state_dir,
        &config.runtime_executable,
        &config.sandbox_launcher,
        &config.immutable_artifact_root,
        &config.model.weights_path,
        &config.model.tokenizer_path,
        &config.model.preprocessor_path,
        &config.model.quantization_path,
        &config.model.device_descriptor_path,
    ] {
        if !path.is_absolute() {
            return Err("all product host paths must be absolute".into());
        }
    }
    if config.resource_grant.generation == 0
        || config.resource_grant.maximum_models == 0
        || config.resource_grant.maximum_active_requests == 0
        || config.resource_grant.maximum_memory_bytes == 0
        || config.response_timeout_ms == 0
        || config.shutdown_timeout_ms == 0
        || config.maximum_protocol_line_bytes == 0
    {
        return Err("invalid local product host bounds".into());
    }
    Ok(())
}

fn read_private_file(
    path: &Path,
    maximum: usize,
) -> Result<Vec<u8>, Box<dyn std::error::Error + Send + Sync>> {
    if !path.is_absolute() {
        return Err("host input must be absolute".into());
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("host input must be a regular non-symlink file".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err("host input must not be group/world accessible".into());
        }
    }
    let mut bytes = Vec::new();
    fs::File::open(path)?
        .take((maximum + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err("host input exceeds bound".into());
    }
    Ok(bytes)
}

fn now_ms() -> Result<u64, Box<dyn std::error::Error + Send + Sync>> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn status_name(status: &ExecutionStatus) -> &'static str {
    match status {
        ExecutionStatus::Succeeded => "succeeded",
        ExecutionStatus::Failed => "failed",
        ExecutionStatus::Cancelled => "cancelled",
        ExecutionStatus::Indeterminate => "indeterminate",
    }
}

fn usage() -> &'static str {
    "usage: hepta-local-inference-runtime-host serve ABS_CONFIG.json SIGNED_RESOURCE_GRANT.json"
}
