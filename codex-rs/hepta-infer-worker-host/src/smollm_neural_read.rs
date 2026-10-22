//! Host composition for real SmolLM parameters in the ordinary cognitive read.
//! Uses the existing inference worker, durable control journal and kernel
//! FinalUse issuer. This module issues no authority and selects no artifact.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::NeuralCognitiveInferencePortV1;
use codex_hepta_agentd::NeuralCognitiveObservationV1;
use codex_hepta_agentd::NeuralCognitivePinV1;
use codex_hepta_agentd::NeuralCognitiveRequestV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::InferenceRequest;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::durable_control::Reservation;
use codex_hepta_infer_core::durable_control::TerminalObservation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::model_worker::ExecutionStatus;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;
use crate::model_worker::WorkerRequest;
use crate::native_app_server::TurnStartAuthorizer;

#[path = "smollm_neural_driver.rs"]
mod driver;
use driver::Exchange;
use driver::Mailbox;
use driver::SmolLmDriver;
pub use driver::SmolLmNeuralReadConfigV1;

static REQUEST_SEQUENCE: AtomicU64 = AtomicU64::new(1);

struct ControlContext {
    control: Arc<Mutex<DurableInferenceControl>>,
    authorizer: Arc<dyn TurnStartAuthorizer>,
    runtime: tokio::runtime::Handle,
    owner_id: AgentId,
    body_generation: u64,
    worker_id: String,
    grant: ResourceGrant,
    model_digest: String,
}

struct Admitted {
    request_id: String,
    reservation_id: String,
    payload_digest: String,
    deadline_ms: u64,
    revision: u64,
}

impl ControlContext {
    fn admit(&self, payload: Digest32, timeout_ms: u64) -> Result<Admitted, String> {
        let now = now_ms()?;
        let request_id = format!(
            "neural-{now}-{}",
            REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        );
        let reservation_id = format!("reservation-{request_id}");
        let deadline_ms = now
            .checked_add(timeout_ms)
            .ok_or("neural deadline overflow")?;
        if deadline_ms > self.grant.expires_at_ms {
            return Err("neural resource grant expires before the operation".to_owned());
        }
        let payload_digest = payload.to_string();
        let mut control = self
            .control
            .lock()
            .map_err(|_| "original inference control poisoned")?;
        let submitted = control
            .submit(
                now,
                InferenceRequest {
                    request_id: request_id.clone(),
                    principal_id: self.owner_id.as_str().to_owned(),
                    model_digest: self.model_digest.clone(),
                    payload_digest: payload_digest.clone(),
                    maximum_tokens: 1,
                    deadline_ms,
                    semantic_digest: self.grant.semantic_digest.clone(),
                },
            )
            .map_err(|error| error.to_string())?;
        // A reused or recovered dispatch is never replayed by this adapter.
        if submitted.idempotent {
            return Err("neural request already exists; owner reconciliation required".to_owned());
        }
        let reserved = control
            .reserve(
                now,
                &request_id,
                submitted.revision,
                Reservation {
                    reservation_id: reservation_id.clone(),
                    quota_units: 1,
                    maximum_tokens: 1,
                    authority_epoch: self.grant.authority_epoch,
                    valid_until_ms: deadline_ms,
                },
            )
            .map_err(|error| error.to_string())?;
        let assigned = control
            .assign(
                &request_id,
                reserved.revision,
                Assignment {
                    worker_id: self.worker_id.clone(),
                    worker_generation: self.grant.generation,
                    assignment_digest: Digest32::of_parts(&[
                        b"hepta.smollm-assignment.v1\0",
                        payload.as_array(),
                        request_id.as_bytes(),
                    ])
                    .to_string(),
                },
            )
            .map_err(|error| error.to_string())?;
        Ok(Admitted {
            request_id,
            reservation_id,
            payload_digest,
            deadline_ms,
            revision: assigned.revision,
        })
    }

    fn enter(
        &self,
        admitted: &Admitted,
        scope: Digest32,
    ) -> Result<codex_hepta_contracts::EnteredUseToken, String> {
        let resource_scope = serde_json::to_vec(&(
            "hepta.smollm-final-use-resource.v1",
            scope.to_string(),
            self.owner_id.as_str(),
            self.body_generation,
            &self.grant.grant_id,
            self.grant.authority_epoch,
            self.grant.generation,
            self.grant.expires_at_ms,
            self.grant.revoked,
            self.grant.maximum_models,
            self.grant.maximum_active_requests,
            self.grant.maximum_memory_bytes,
            &self.grant.semantic_digest,
        ))
        .map_err(|error| error.to_string())?;
        let binding = FinalUseBinding {
            subject_id: self.owner_id.as_str().to_owned(),
            destination_id: self.worker_id.clone(),
            request_sha256: Digest32::of_parts(&[
                b"hepta.smollm-final-use.v1\0",
                admitted.request_id.as_bytes(),
                self.model_digest.as_bytes(),
                admitted.payload_digest.as_bytes(),
            ])
            .into_array(),
            scope_sha256: Digest32::of_bytes(&resource_scope).into_array(),
            payload_sha256: admitted
                .payload_digest
                .parse::<Digest32>()
                .map_err(|error| error.to_string())?
                .into_array(),
        };
        let token = self
            .runtime
            .block_on(async {
                tokio::time::timeout(
                    Duration::from_millis(250),
                    self.authorizer.claim(binding.clone()),
                )
                .await
            })
            .map_err(|_| "original final-use claim timed out".to_owned())?
            .map_err(|error| error.to_string())?;
        token.enter(&binding).map_err(|error| error.to_string())
    }

    fn settle(
        &self,
        admitted: &Admitted,
        output: Option<Digest32>,
        terminal: bool,
        tokens: u32,
    ) -> Result<(), String> {
        let status = if terminal {
            Some(if output.is_some() {
                RequestState::Completed
            } else {
                RequestState::Failed
            })
        } else {
            None
        };
        let evidence = Digest32::of_parts(&[
            b"hepta.smollm-observation.v1\0",
            admitted.request_id.as_bytes(),
            output.unwrap_or(Digest32::ZERO).as_array(),
            &[u8::from(terminal)],
            &tokens.to_be_bytes(),
        ]);
        self.control
            .lock()
            .map_err(|_| "original inference control poisoned")?
            .settle(
                &admitted.request_id,
                admitted.revision,
                evidence.to_string(),
                TerminalObservation {
                    request_id: admitted.request_id.clone(),
                    reservation_id: admitted.reservation_id.clone(),
                    worker_id: self.worker_id.clone(),
                    worker_generation: self.grant.generation,
                    model_digest: self.model_digest.clone(),
                    payload_digest: admitted.payload_digest.clone(),
                    terminal_observed: terminal,
                    terminal_status: status,
                    output_digest: output.map(|value| value.to_string()),
                    consumed_tokens: tokens,
                    usage_units: u64::from(tokens),
                },
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }
}

/// One qualified parameter consumer's warm model in the original inference
/// owner. Start it before enabling the Agentd read route; cold loading is not
/// hidden inside the normal two-second cognitive request deadline.
pub struct SmolLmNeuralReadPortV1 {
    pin: NeuralCognitivePinV1,
    model_id: String,
    context: ControlContext,
    worker: Mutex<InferenceWorker<SmolLmDriver>>,
    mailbox: Mailbox,
}

impl SmolLmNeuralReadPortV1 {
    /// The embedding owner supplies its existing journal, resource grant and
    /// original FinalUse authorizer. No key or authority is constructed here.
    /// Call on the host's blocking executor, as the ordinary ranker already does.
    #[allow(clippy::too_many_arguments)]
    pub fn start(
        config: SmolLmNeuralReadConfigV1,
        pin: NeuralCognitivePinV1,
        parameter_bytes: Vec<u8>,
        owner_id: AgentId,
        body_generation: u64,
        worker_id: String,
        grant: ResourceGrant,
        control: Arc<Mutex<DurableInferenceControl>>,
        authorizer: Arc<dyn TurnStartAuthorizer>,
        runtime: tokio::runtime::Handle,
    ) -> Result<Self, String> {
        let now = now_ms()?;
        if body_generation == 0
            || grant.maximum_models != 1
            || grant.maximum_active_requests != 1
            || grant.maximum_memory_bytes != 8 * 1024 * 1024 * 1024
            || grant.expires_at_ms < now.saturating_add(720_000)
            || config.execution_profile_digest()? != pin.execution_profile_digest
            || Digest32::of_bytes(&parameter_bytes) != pin.payload_digest
        {
            return Err(
                "neural worker requires its exact bounded resource and parameter profile"
                    .to_owned(),
            );
        }
        let model_id = format!("smollm-read-{}", pin.payload_digest);
        let model_digest = Digest32::of_parts(&[
            b"hepta.smollm-read-model.v1\0",
            pin.payload_digest.as_array(),
            pin.family_digest.as_array(),
            pin.execution_profile_digest.as_array(),
        ])
        .to_string();
        let manifest = ModelManifest {
            model_id: model_id.clone(),
            model_digest: model_digest.clone(),
            weights_digest: pin.payload_digest.to_string(),
            tokenizer_digest: config.tokenizer_digest.to_string(),
            preprocessor_digest: pin.execution_profile_digest.to_string(),
            quantization_digest: Digest32::of_bytes(b"float32-unquantized").to_string(),
            runtime_digest: pin.execution_profile_digest.to_string(),
            device_digest: Digest32::of_bytes(b"cpu-eager-float32-threads-4").to_string(),
            maximum_tokens: 1,
        };
        let context = ControlContext {
            control,
            authorizer,
            runtime,
            owner_id,
            body_generation,
            worker_id: worker_id.clone(),
            grant: grant.clone(),
            model_digest,
        };
        let mailbox = Arc::new(Mutex::new(None));
        let driver = SmolLmDriver::new(
            config,
            pin.clone(),
            parameter_bytes,
            mailbox.clone(),
            context.runtime.clone(),
        );
        let mut worker = InferenceWorker::new(now, worker_id, grant.generation, grant, driver)
            .map_err(|error| error.to_string())?;
        let admitted = context.admit(
            Digest32::of_parts(&[
                b"hepta.smollm-load.v1\0",
                context.owner_id.as_str().as_bytes(),
                &context.body_generation.to_be_bytes(),
                pin.payload_digest.as_array(),
                pin.execution_profile_digest.as_array(),
            ]),
            120_000,
        )?;
        let entered = match context.enter(&admitted, pin.compatibility_digest()) {
            Ok(token) => token,
            Err(error) => {
                context.settle(&admitted, None, true, 0)?;
                return Err(error);
            }
        };
        let loaded = worker.load_model(now_ms()?, manifest);
        drop(entered);
        let loaded = match loaded {
            Ok(value) => value,
            Err(error) => {
                context.settle(&admitted, None, false, 0)?;
                return Err(error.to_string());
            }
        };
        let observed = Digest32::of_parts(&[
            b"hepta.smollm-loaded.v1\0",
            loaded.handle_id.as_bytes(),
            &loaded.observed_memory_bytes.to_be_bytes(),
        ]);
        context.settle(&admitted, Some(observed), true, 0)?;
        Ok(Self {
            pin,
            model_id,
            context,
            worker: Mutex::new(worker),
            mailbox,
        })
    }

    /// Explicit original-owner unload. Success requires the Python supervisor's
    /// exact terminal wait4/RSS receipt; asynchronous Drop cleanup earns no such
    /// completion. Call from the same blocking host executor used by start.
    pub fn shutdown(&self) -> Result<(), String> {
        let mut worker = self
            .worker
            .try_lock()
            .map_err(|_| "original neural worker is active or poisoned")?;
        let observed = worker
            .unload_model(now_ms()?, &self.model_id)
            .map_err(|error| error.to_string())?;
        if !observed.terminal_observed {
            return Err("neural unload terminal observation missing".to_owned());
        }
        Ok(())
    }
}

impl NeuralCognitiveInferencePortV1 for SmolLmNeuralReadPortV1 {
    fn execute(
        &self,
        request: &NeuralCognitiveRequestV1,
        parameters: &[u8],
    ) -> Result<NeuralCognitiveObservationV1, String> {
        if request.owner_id != self.context.owner_id
            || request.body_generation != self.context.body_generation
            || request.pin != self.pin
            || Digest32::of_bytes(parameters) != self.pin.payload_digest
            || request.query_digest != Digest32::of_bytes(request.query.as_bytes())
            || request.query.is_empty()
            || request.query.len() > 2048
            || request.action_ids.is_empty()
            || request.action_ids.len() > 128
        {
            return Err("neural owner request differs from its pinned parameters".to_owned());
        }
        // Queueing behind another call could outlive the ordinary read request
        // and then execute after its caller had already timed out.
        let mut worker = self
            .worker
            .try_lock()
            .map_err(|_| "original neural worker is active or poisoned")?;
        let action_bytes = serde_json::to_vec(
            &request
                .action_ids
                .iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>(),
        )
        .map_err(|error| error.to_string())?;
        let payload = Digest32::of_parts(&[
            b"hepta.smollm-read-request.v1\0",
            request.owner_id.as_str().as_bytes(),
            &request.body_generation.to_be_bytes(),
            self.pin.payload_digest.as_array(),
            self.pin.execution_profile_digest.as_array(),
            request.query_digest.as_array(),
            &action_bytes,
        ]);
        let admitted = self.context.admit(payload, 2_000)?;
        let entered = match self
            .context
            .enter(&admitted, self.pin.compatibility_digest())
        {
            Ok(token) => token,
            Err(error) => {
                self.context.settle(&admitted, None, true, 0)?;
                return Err(error);
            }
        };
        *self
            .mailbox
            .lock()
            .map_err(|_| "neural exchange poisoned")? = Some(Exchange {
            request: request.clone(),
            request_id: admitted.request_id.clone(),
            payload_digest: admitted.payload_digest.clone(),
            response: None,
        });
        let observed = worker.run(
            now_ms()?,
            &self.model_id,
            WorkerRequest {
                request_id: admitted.request_id.clone(),
                reservation_id: admitted.reservation_id.clone(),
                model_digest: self.context.model_digest.clone(),
                payload_digest: admitted.payload_digest.clone(),
                maximum_tokens: 1,
                deadline_ms: admitted.deadline_ms,
                lease_payload_digest: admitted.payload_digest.clone(),
                reservation_model_digest: self.context.model_digest.clone(),
                reservation_maximum_tokens: 1,
                cancelled: false,
            },
        );
        drop(entered);
        let observed = match observed {
            Ok(value) => value,
            Err(error) => {
                self.mailbox
                    .lock()
                    .map_err(|_| "neural exchange poisoned")?
                    .take();
                self.context.settle(&admitted, None, false, 0)?;
                return Err(error.to_string());
            }
        };
        let exchange = self
            .mailbox
            .lock()
            .map_err(|_| "neural exchange poisoned")?
            .take()
            .ok_or("neural observation missing")?;
        let (response, receipt) = exchange
            .response
            .ok_or("neural terminal response missing")?;
        if observed.status != ExecutionStatus::Succeeded
            || !observed.terminal_observed
            || observed.output_digest != Some(receipt.to_string())
            || now_ms()? > admitted.deadline_ms
        {
            self.context.settle(
                &admitted,
                None,
                observed.terminal_observed,
                observed.consumed_tokens,
            )?;
            return Err(
                "neural operation did not complete within its original admission".to_owned(),
            );
        }
        self.context
            .settle(&admitted, Some(receipt), true, observed.consumed_tokens)?;
        let scores = request
            .action_ids
            .iter()
            .map(|action| {
                response
                    .action_ids
                    .iter()
                    .position(|value| value == action.as_str())
                    .map(|index| response.scores_q32[index])
            })
            .collect::<Option<Vec<_>>>();
        Ok(NeuralCognitiveObservationV1 {
            request: request.clone(),
            scores_q32: scores,
            execution_receipt_digest: receipt,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

fn now_ms() -> Result<u64, String> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_millis(),
    )
    .map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "smollm_neural_read_tests.rs"]
mod tests;
