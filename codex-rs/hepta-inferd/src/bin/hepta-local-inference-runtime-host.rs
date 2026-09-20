//! Long-lived production composition root for local isolated inference.
//!
//! This process owns the canonical inference-control journal and one
//! authenticated local worker generation. Admission/reservation/assignment are
//! durable owner facts. A run command supplies only the stable request identity
//! plus the exact payload bytes; the host derives every model/reservation/token/
//! deadline field from the assigned durable record, commits an execution-entry
//! fence before touching the child runtime, and never replays a post-entry
//! unknown attempt.

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
use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::ExecutionObservation as ControlExecutionObservation;
use codex_hepta_infer_core::durable_control::InferenceRequest as ControlInferenceRequest;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::durable_control::Reservation as ControlReservation;
use codex_hepta_infer_core::durable_control::TerminalObservation;
use codex_hepta_infer_worker_host::local_process_driver::LocalModelArtifacts;
use codex_hepta_infer_worker_host::local_process_driver::LocalProcessDriverConfig;
use codex_hepta_infer_worker_host::model_worker::ExecutionStatus;
use codex_hepta_infer_worker_host::model_worker::InferenceExecutionObservation;
use codex_hepta_infer_worker_host::model_worker::ModelManifest;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_infer_worker_host::model_worker::WorkerRequest;
use codex_hepta_inferd::local_worker_host::LocalWorkerHost;
use codex_hepta_inferd::local_worker_host::LocalWorkerHostError;
use serde::Deserialize;
use serde::Serialize;
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
    control_journal: PathBuf,
    control_capacity: usize,
    authority_state_dir: PathBuf,
    signer_id: String,
    verifying_key: [u8; 32],
    initial_revocations: FinalUseRevocations,
    resource_grant: ResourceGrantConfig,
    runtime_executable: PathBuf,
    sandbox_launcher: PathBuf,
    sandbox_launcher_digest: String,
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
    Submit {
        request_id: String,
        principal_id: String,
        model_digest: String,
        payload_digest: String,
        maximum_tokens: u32,
        deadline_ms: u64,
        semantic_digest: String,
    },
    Reserve {
        request_id: String,
        expected_revision: u64,
        reservation_id: String,
        quota_units: u64,
        maximum_tokens: u32,
        authority_epoch: u64,
        valid_until_ms: u64,
    },
    Assign {
        request_id: String,
        expected_revision: u64,
        worker_id: String,
        worker_generation: u64,
        assignment_digest: String,
    },
    Run {
        request_id: String,
        input: String,
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
    let worker_generation = resource_grant.generation;
    let worker_id = config.worker_id.clone();
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
            config.sandbox_launcher_digest.clone(),
            config.immutable_artifact_root.clone(),
        );
    driver.maximum_protocol_line_bytes = config.maximum_protocol_line_bytes;
    driver.response_timeout = Duration::from_millis(config.response_timeout_ms);
    driver.shutdown_timeout = Duration::from_millis(config.shutdown_timeout_ms);

    let mut host = LocalWorkerHost::new(
        now_ms()?,
        worker_id.clone(),
        resource_grant,
        authority,
        signed,
        driver,
    )?;
    host.load_model(now_ms()?, manifest.clone())?;

    let control = Arc::new(Mutex::new(DurableInferenceControl::open(
        &config.control_journal,
        config.control_capacity,
    )?));
    require_owner_only_file(&config.control_journal)?;

    let (owner_tx, owner_rx) = mpsc::channel::<OwnerCommand>();
    let (output_tx, output_rx) = mpsc::channel::<Value>();
    let current = Arc::new(Mutex::new(None::<(String, CancellationToken)>));
    let current_owner = Arc::clone(&current);
    let control_owner = Arc::clone(&control);
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
                        let result = host.run(
                            now_ms().unwrap_or(0),
                            &model_id,
                            request,
                            &cancellation,
                        );
                        let response =
                            persist_run_result(&control_owner, &request_id, result);
                        if let Ok(mut slot) = current_owner.lock() {
                            *slot = None;
                        }
                        busy_owner.store(false, Ordering::Release);
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
            ControlCommand::Submit {
                request_id,
                principal_id,
                model_digest,
                payload_digest,
                maximum_tokens,
                deadline_ms,
                semantic_digest,
            } => {
                if model_digest != manifest.model_digest {
                    println!("{}", json!({"op":"submit","status":"error","error":"model mismatch"}));
                    continue;
                }
                let result = control
                    .lock()
                    .map_err(|_| "inference control lock poisoned")?
                    .submit(
                        now_ms()?,
                        ControlInferenceRequest {
                            request_id,
                            principal_id,
                            model_digest,
                            payload_digest,
                            maximum_tokens,
                            deadline_ms,
                            semantic_digest,
                        },
                    );
                println!("{}", receipt_or_error("submit", result));
            }
            ControlCommand::Reserve {
                request_id,
                expected_revision,
                reservation_id,
                quota_units,
                maximum_tokens,
                authority_epoch,
                valid_until_ms,
            } => {
                let result = control
                    .lock()
                    .map_err(|_| "inference control lock poisoned")?
                    .reserve(
                        now_ms()?,
                        &request_id,
                        expected_revision,
                        ControlReservation {
                            reservation_id,
                            quota_units,
                            maximum_tokens,
                            authority_epoch,
                            valid_until_ms,
                        },
                    );
                println!("{}", receipt_or_error("reserve", result));
            }
            ControlCommand::Assign {
                request_id,
                expected_revision,
                worker_id: requested_worker,
                worker_generation: requested_generation,
                assignment_digest,
            } => {
                if requested_worker != worker_id || requested_generation != worker_generation {
                    println!(
                        "{}",
                        json!({"op":"assign","request_id":request_id,"status":"error","error":"assignment targets another worker generation"})
                    );
                    continue;
                }
                let result = control
                    .lock()
                    .map_err(|_| "inference control lock poisoned")?
                    .assign(
                        &request_id,
                        expected_revision,
                        Assignment {
                            worker_id: requested_worker,
                            worker_generation: requested_generation,
                            assignment_digest,
                        },
                    );
                println!("{}", receipt_or_error("assign", result));
            }
            ControlCommand::Run { request_id, input } => {
                if busy.swap(true, Ordering::AcqRel) {
                    println!(
                        "{}",
                        json!({"op":"run","request_id":request_id,"status":"busy"})
                    );
                    continue;
                }

                let prepared = prepare_run(
                    &control,
                    &request_id,
                    input,
                    &manifest,
                    &worker_id,
                    worker_generation,
                );
                let request = match prepared {
                    Ok(request) => request,
                    Err(error) => {
                        busy.store(false, Ordering::Release);
                        println!(
                            "{}",
                            json!({"op":"run","request_id":request_id,"status":"error","error":error.to_string()})
                        );
                        continue;
                    }
                };

                let active_request_id = request.request_id.clone();
                let cancellation = CancellationToken::new();
                match current.lock() {
                    Ok(mut slot) => {
                        *slot = Some((active_request_id.clone(), cancellation.clone()));
                    }
                    Err(_) => {
                        mark_current_indeterminate(
                            &control,
                            &active_request_id,
                            "local cancellation registry unavailable",
                        );
                        busy.store(false, Ordering::Release);
                        return Err("local cancellation registry unavailable".into());
                    }
                }
                if owner_tx
                    .send(OwnerCommand::Run {
                        request,
                        cancellation,
                    })
                    .is_err()
                {
                    mark_current_indeterminate(
                        &control,
                        &active_request_id,
                        "local inference owner channel closed before execution",
                    );
                    if let Ok(mut slot) = current.lock() {
                        *slot = None;
                    }
                    busy.store(false, Ordering::Release);
                    return Err("local inference owner stopped".into());
                }
            }
            ControlCommand::Cancel { request_id } => {
                let active = current
                    .lock()
                    .ok()
                    .and_then(|slot| slot.as_ref().cloned());
                if let Some((active_id, token)) = active
                    && active_id == request_id
                {
                    let durable = record_cancel(&control, &request_id);
                    token.cancel();
                    println!(
                        "{}",
                        json!({
                            "op":"cancel",
                            "request_id":request_id,
                            "accepted":true,
                            "durable":durable.is_ok(),
                            "durable_error":durable.err().map(|error| error.to_string()),
                        })
                    );
                    continue;
                }
                println!(
                    "{}",
                    cancel_without_active_run(&control, &request_id)
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
                    && let Some((request_id, token)) = slot.as_ref()
                {
                    let _ = record_cancel(&control, request_id);
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

fn prepare_run(
    control: &Arc<Mutex<DurableInferenceControl>>,
    request_id: &str,
    input: String,
    manifest: &ModelManifest,
    worker_id: &str,
    worker_generation: u64,
) -> Result<WorkerRequest, Box<dyn std::error::Error + Send + Sync>> {
    let now = now_ms()?;
    let mut control = control
        .lock()
        .map_err(|_| "inference control lock poisoned")?;
    let record = control
        .get(request_id)
        .cloned()
        .ok_or("assigned inference request not found")?;

    if matches!(record.state, RequestState::Running | RequestState::Cancelling) {
        let evidence = digest_json(&(
            "hepta.local-inference.recovered-running.v1",
            request_id,
            control_state_name(record.state),
        ))?;
        control.mark_execution_indeterminate(
            request_id,
            record.revision,
            evidence,
        )?;
        return Err("request crossed execution entry before restart; replay is forbidden".into());
    }
    if record.state == RequestState::AwaitingSettlement {
        return Err("request execution is terminal and awaiting authoritative settlement".into());
    }
    if record.state != RequestState::Assigned {
        return Err(format!("request is not executable from state {}", control_state_name(record.state)).into());
    }

    let reservation = record
        .reservation
        .clone()
        .ok_or("assigned request is missing reservation")?;
    let assignment = record
        .assignment
        .clone()
        .ok_or("assigned request is missing worker assignment")?;
    let payload_digest = sha256(input.as_bytes());
    if record.request.model_digest != manifest.model_digest
        || record.request.payload_digest != payload_digest
        || record.request.maximum_tokens > manifest.maximum_tokens
        || record.request.deadline_ms <= now
        || reservation.valid_until_ms <= now
        || assignment.worker_id != worker_id
        || assignment.worker_generation != worker_generation
    {
        return Err("assigned request failed final local execution revalidation".into());
    }

    control.begin_execution(request_id, record.revision)?;
    Ok(WorkerRequest {
        request_id: record.request.request_id,
        reservation_id: reservation.reservation_id,
        model_digest: record.request.model_digest.clone(),
        input,
        payload_digest: record.request.payload_digest.clone(),
        maximum_tokens: record.request.maximum_tokens,
        deadline_ms: record.request.deadline_ms,
        lease_payload_digest: record.request.payload_digest,
        reservation_model_digest: record.request.model_digest,
        reservation_maximum_tokens: reservation.maximum_tokens,
        cancelled: false,
    })
}

fn persist_run_result(
    control: &Arc<Mutex<DurableInferenceControl>>,
    request_id: &str,
    result: Result<InferenceExecutionObservation, LocalWorkerHostError>,
) -> Value {
    let mut control = match control.lock() {
        Ok(control) => control,
        Err(_) => {
            return json!({
                "op":"run_result",
                "request_id":request_id,
                "status":"error",
                "error":"inference control lock poisoned after execution",
            });
        }
    };
    let record = match control.get(request_id).cloned() {
        Some(record) => record,
        None => {
            return json!({
                "op":"run_result",
                "request_id":request_id,
                "status":"error",
                "error":"durable request disappeared after execution",
            });
        }
    };

    match result {
        Ok(observed)
            if observed.terminal_observed
                && !matches!(observed.status, ExecutionStatus::Indeterminate) =>
        {
            let status = match observed.status {
                ExecutionStatus::Succeeded => RequestState::Completed,
                ExecutionStatus::Failed => RequestState::Failed,
                ExecutionStatus::Cancelled => RequestState::Cancelled,
                ExecutionStatus::Indeterminate => unreachable!(),
            };
            let reservation = match &record.reservation {
                Some(reservation) => reservation,
                None => {
                    return durable_result_error(
                        request_id,
                        "terminal execution lost its durable reservation",
                    );
                }
            };
            let assignment = match &record.assignment {
                Some(assignment) => assignment,
                None => {
                    return durable_result_error(
                        request_id,
                        "terminal execution lost its durable assignment",
                    );
                }
            };
            let execution = ControlExecutionObservation {
                request_id: observed.request_id.clone(),
                reservation_id: reservation.reservation_id.clone(),
                worker_id: assignment.worker_id.clone(),
                worker_generation: observed.worker_generation,
                model_digest: observed.model_digest.clone(),
                payload_digest: observed.payload_digest.clone(),
                terminal_status: status,
                output_digest: observed.output_digest.clone(),
                consumed_tokens: observed.consumed_tokens,
            };
            let digest = match digest_json(&(
                "hepta.local-inference.execution-observation.v1",
                &execution.request_id,
                &execution.reservation_id,
                &execution.worker_id,
                execution.worker_generation,
                &execution.model_digest,
                &execution.payload_digest,
                control_state_name(execution.terminal_status),
                &execution.output_digest,
                execution.consumed_tokens,
            )) {
                Ok(digest) => digest,
                Err(error) => return durable_result_error(request_id, &error.to_string()),
            };
            match control.observe_execution(request_id, record.revision, digest, execution) {
                Ok(receipt) => json!({
                    "op":"run_result",
                    "request_id":request_id,
                    "status":status_name(&observed.status),
                    "terminal_observed":true,
                    "output_digest":observed.output_digest,
                    "consumed_tokens":observed.consumed_tokens,
                    "observed_memory_bytes":observed.observed_memory_bytes,
                    "control_state":control_state_name(receipt.state),
                    "settlement_required":true,
                }),
                Err(error) => durable_result_error(request_id, &error.to_string()),
            }
        }
        Ok(observed) => {
            let evidence = digest_json(&(
                "hepta.local-inference.indeterminate.v1",
                request_id,
                status_name(&observed.status),
                &observed.output_digest,
                observed.consumed_tokens,
                observed.observed_memory_bytes,
            ))
            .unwrap_or_else(|_| "f".repeat(64));
            match control.mark_execution_indeterminate(request_id, record.revision, evidence) {
                Ok(_) => json!({
                    "op":"run_result",
                    "request_id":request_id,
                    "status":"indeterminate",
                    "terminal_observed":false,
                    "output_digest":Value::Null,
                    "consumed_tokens":observed.consumed_tokens,
                }),
                Err(error) => durable_result_error(request_id, &error.to_string()),
            }
        }
        Err(error) => {
            let evidence = digest_json(&(
                "hepta.local-inference.owner-error.v1",
                request_id,
                error.to_string(),
            ))
            .unwrap_or_else(|_| "e".repeat(64));
            let durable = control.mark_execution_indeterminate(
                request_id,
                record.revision,
                evidence,
            );
            json!({
                "op":"run_result",
                "request_id":request_id,
                "status":"error",
                "error":error.to_string(),
                "durable_indeterminate":durable.is_ok(),
                "durable_error":durable.err().map(|value| value.to_string()),
            })
        }
    }
}

fn record_cancel(
    control: &Arc<Mutex<DurableInferenceControl>>,
    request_id: &str,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut control = control
        .lock()
        .map_err(|_| "inference control lock poisoned")?;
    let revision = control
        .get(request_id)
        .ok_or("request not found")?
        .revision;
    control.cancel(request_id, revision)?;
    Ok(())
}

fn cancel_without_active_run(
    control: &Arc<Mutex<DurableInferenceControl>>,
    request_id: &str,
) -> Value {
    let mut control = match control.lock() {
        Ok(control) => control,
        Err(_) => {
            return json!({"op":"cancel","request_id":request_id,"accepted":false,"error":"control lock poisoned"});
        }
    };
    let record = match control.get(request_id).cloned() {
        Some(record) => record,
        None => {
            return json!({"op":"cancel","request_id":request_id,"accepted":false,"error":"request not found"});
        }
    };
    let result = match record.state {
        RequestState::Pending | RequestState::Reserved => {
            control.cancel(request_id, record.revision)
        }
        RequestState::Assigned => {
            let reservation = match &record.reservation {
                Some(value) => value,
                None => {
                    return json!({"op":"cancel","request_id":request_id,"accepted":false,"error":"reservation missing"});
                }
            };
            let assignment = match &record.assignment {
                Some(value) => value,
                None => {
                    return json!({"op":"cancel","request_id":request_id,"accepted":false,"error":"assignment missing"});
                }
            };
            let observation = TerminalObservation {
                request_id: request_id.to_string(),
                reservation_id: reservation.reservation_id.clone(),
                worker_id: assignment.worker_id.clone(),
                worker_generation: assignment.worker_generation,
                model_digest: record.request.model_digest.clone(),
                payload_digest: record.request.payload_digest.clone(),
                terminal_observed: true,
                terminal_status: Some(RequestState::Cancelled),
                output_digest: None,
                consumed_tokens: 0,
                usage_units: 0,
            };
            match digest_json(&(
                "hepta.local-inference.pre-entry-cancel.v1",
                request_id,
                record.revision,
            )) {
                Ok(digest) => control.settle(request_id, record.revision, digest, observation),
                Err(_) => return json!({"op":"cancel","request_id":request_id,"accepted":false,"error":"cancel digest failed"}),
            }
        }
        _ => {
            return json!({
                "op":"cancel",
                "request_id":request_id,
                "accepted":false,
                "state":control_state_name(record.state),
            });
        }
    };
    match result {
        Ok(receipt) => json!({
            "op":"cancel",
            "request_id":request_id,
            "accepted":true,
            "state":control_state_name(receipt.state),
        }),
        Err(error) => json!({
            "op":"cancel",
            "request_id":request_id,
            "accepted":false,
            "error":error.to_string(),
        }),
    }
}

fn mark_current_indeterminate(
    control: &Arc<Mutex<DurableInferenceControl>>,
    request_id: &str,
    reason: &str,
) {
    let Ok(mut control) = control.lock() else {
        return;
    };
    let Some(record) = control.get(request_id).cloned() else {
        return;
    };
    if !matches!(record.state, RequestState::Running | RequestState::Cancelling) {
        return;
    }
    let Ok(digest) = digest_json(&(
        "hepta.local-inference.internal-owner-failure.v1",
        request_id,
        reason,
    )) else {
        return;
    };
    let _ = control.mark_execution_indeterminate(request_id, record.revision, digest);
}

fn receipt_or_error(
    operation: &str,
    result: Result<
        codex_hepta_infer_core::durable_control::ControlReceipt,
        codex_hepta_infer_core::durable_control::Error,
    >,
) -> Value {
    match result {
        Ok(receipt) => json!({
            "op":operation,
            "request_id":receipt.request_id,
            "status":"ok",
            "revision":receipt.revision,
            "state":control_state_name(receipt.state),
            "idempotent":receipt.idempotent,
        }),
        Err(error) => json!({"op":operation,"status":"error","error":error.to_string()}),
    }
}

fn durable_result_error(request_id: &str, error: &str) -> Value {
    json!({
        "op":"run_result",
        "request_id":request_id,
        "status":"error",
        "error":error,
    })
}

fn validate_config(config: &HostConfig) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    for path in [
        &config.control_journal,
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
    if config.control_capacity == 0
        || config.resource_grant.generation == 0
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

fn require_owner_only_file(
    path: &Path,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if fs::metadata(path)?.permissions().mode() & 0o077 != 0 {
            return Err("inference control journal must be owner-only".into());
        }
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

fn digest_json(value: &impl Serialize) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    Ok(sha256(&serde_json::to_vec(value)?))
}

fn status_name(status: &ExecutionStatus) -> &'static str {
    match status {
        ExecutionStatus::Succeeded => "succeeded",
        ExecutionStatus::Failed => "failed",
        ExecutionStatus::Cancelled => "cancelled",
        ExecutionStatus::Indeterminate => "indeterminate",
    }
}

fn control_state_name(state: RequestState) -> &'static str {
    match state {
        RequestState::Pending => "pending",
        RequestState::Reserved => "reserved",
        RequestState::Assigned => "assigned",
        RequestState::Running => "running",
        RequestState::Cancelling => "cancelling",
        RequestState::AwaitingSettlement => "awaiting_settlement",
        RequestState::Completed => "completed",
        RequestState::Failed => "failed",
        RequestState::Cancelled => "cancelled",
        RequestState::Indeterminate => "indeterminate",
    }
}

fn usage() -> &'static str {
    "usage: hepta-local-inference-runtime-host serve ABS_CONFIG.json SIGNED_RESOURCE_GRANT.json"
}


#[cfg(test)]
mod tests {
    use super::*;

    fn test_path(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "hepta-local-product-{label}-{}-{nonce}.journal",
            std::process::id()
        ))
    }

    fn manifest() -> ModelManifest {
        ModelManifest {
            model_id: "model.local.product".to_string(),
            model_digest: "1".repeat(64),
            weights_digest: "2".repeat(64),
            tokenizer_digest: "3".repeat(64),
            preprocessor_digest: "4".repeat(64),
            quantization_digest: "5".repeat(64),
            runtime_digest: "6".repeat(64),
            device_digest: "7".repeat(64),
            maximum_tokens: 128,
        }
    }

    #[test]
    fn run_is_derived_from_durable_assignment_and_commits_entry_fence() {
        let path = test_path("assignment");
        let input = "durable input".to_string();
        let payload_digest = sha256(input.as_bytes());
        let now = now_ms().unwrap();
        let mut owner = DurableInferenceControl::open(&path, 16).unwrap();
        owner
            .submit(
                100,
                ControlInferenceRequest {
                    request_id: "request.local.product".to_string(),
                    principal_id: "principal.local".to_string(),
                    model_digest: "1".repeat(64),
                    payload_digest: payload_digest.clone(),
                    maximum_tokens: 32,
                    deadline_ms: now + 9_000,
                    semantic_digest: "8".repeat(64),
                },
            )
            .unwrap();
        owner
            .reserve(
                100,
                "request.local.product",
                1,
                ControlReservation {
                    reservation_id: "reservation.local.product".to_string(),
                    quota_units: 90,
                    maximum_tokens: 40,
                    authority_epoch: 2,
                    valid_until_ms: now + 8_000,
                },
            )
            .unwrap();
        owner
            .assign(
                "request.local.product",
                2,
                Assignment {
                    worker_id: "worker.local.product".to_string(),
                    worker_generation: 7,
                    assignment_digest: "9".repeat(64),
                },
            )
            .unwrap();
        let control = Arc::new(Mutex::new(owner));
        let request = prepare_run(
            &control,
            "request.local.product",
            input.clone(),
            &manifest(),
            "worker.local.product",
            7,
        )
        .unwrap();

        assert_eq!(request.input, input);
        assert_eq!(request.payload_digest, payload_digest);
        assert_eq!(request.reservation_id, "reservation.local.product");
        assert_eq!(request.maximum_tokens, 32);
        assert_eq!(request.reservation_maximum_tokens, 40);
        assert_eq!(request.deadline_ms, now + 9_000);
        assert_eq!(
            control
                .lock()
                .unwrap()
                .get("request.local.product")
                .unwrap()
                .state,
            RequestState::Running
        );

        drop(control);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn a_second_run_after_entry_is_marked_indeterminate_not_replayed() {
        let path = test_path("no-replay");
        let input = "once".to_string();
        let payload_digest = sha256(input.as_bytes());
        let now = now_ms().unwrap();
        let mut owner = DurableInferenceControl::open(&path, 16).unwrap();
        owner
            .submit(
                100,
                ControlInferenceRequest {
                    request_id: "request.local.once".to_string(),
                    principal_id: "principal.local".to_string(),
                    model_digest: "1".repeat(64),
                    payload_digest,
                    maximum_tokens: 16,
                    deadline_ms: now + 9_000,
                    semantic_digest: "8".repeat(64),
                },
            )
            .unwrap();
        owner
            .reserve(
                100,
                "request.local.once",
                1,
                ControlReservation {
                    reservation_id: "reservation.local.once".to_string(),
                    quota_units: 50,
                    maximum_tokens: 16,
                    authority_epoch: 2,
                    valid_until_ms: now + 8_000,
                },
            )
            .unwrap();
        owner
            .assign(
                "request.local.once",
                2,
                Assignment {
                    worker_id: "worker.local.product".to_string(),
                    worker_generation: 7,
                    assignment_digest: "9".repeat(64),
                },
            )
            .unwrap();
        let control = Arc::new(Mutex::new(owner));
        prepare_run(
            &control,
            "request.local.once",
            input.clone(),
            &manifest(),
            "worker.local.product",
            7,
        )
        .unwrap();
        assert!(
            prepare_run(
                &control,
                "request.local.once",
                input,
                &manifest(),
                "worker.local.product",
                7,
            )
            .is_err()
        );
        assert_eq!(
            control
                .lock()
                .unwrap()
                .get("request.local.once")
                .unwrap()
                .state,
            RequestState::Indeterminate
        );

        drop(control);
        std::fs::remove_file(path).unwrap();
    }
}
