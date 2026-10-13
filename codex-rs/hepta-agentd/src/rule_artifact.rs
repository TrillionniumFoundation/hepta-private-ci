//! Opt-in research RuleSlot consumption through the existing native owners.
//!
//! The artifact owner, independent selector, inference journal and FinalUse
//! authority remain the owners. This adapter installs nothing in Agentd and
//! accepts no serialized research handle as native authority. The host must
//! supply a bounded synchronous driver and authenticate the exact checkpoint
//! and operation proposal before independently signing its FinalUse binding.

use std::error::Error;
use std::fmt;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::InferenceRequest;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::durable_control::Reservation;
use codex_hepta_infer_core::durable_control::TerminalObservation;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_infer_core::verify_neuron_feature_receipt_v1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::RevalidatingSelectedCandidateV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

/// Exact research operation proposal, not a grant or a production certificate.
/// The checkpoint digest names the immutable selected bundle. The inference
/// input digest must also bind the host's current checkpoint anchor and source
/// verification; the native adapter does not authenticate Python SQLite hashes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuleUseBindingV1 {
    pub checkpoint_digest: Digest32,
    pub rule_revision: u64,
    pub authority_epoch: u64,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub inference: NeuronFeatureRequestV1,
    pub expected_prediction_q24: Vec<i64>,
    pub deadline_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuleArtifactUseFailureV1 {
    Unavailable,
    Binding,
    Current,
    Selection,
    ReconcileOnly,
    Persistence,
    FinalUse,
    Driver,
    Receipt,
    Late,
}

/// Observations survive refusal too. Microseconds are measured elapsed time,
/// not CPU, energy, billing, or independently attested worker resource usage.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuleArtifactUseEvidenceV1 {
    pub callback_entered: bool,
    pub inference: Option<NeuronFeatureReceiptV1>,
    pub elapsed_micros: u64,
    pub callback_micros: u64,
    pub journal_bytes: u64,
}

#[derive(Debug)]
pub struct RuleArtifactUseError {
    pub kind: RuleArtifactUseFailureV1,
    pub reason: String,
    pub evidence: Option<Box<RuleArtifactUseEvidenceV1>>,
}

impl fmt::Display for RuleArtifactUseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:?}: {}", self.kind, self.reason)
    }
}

impl Error for RuleArtifactUseError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuleArtifactUseReceiptV1 {
    pub inference: NeuronFeatureReceiptV1,
    pub rule_binding_digest: Digest32,
    pub elapsed_micros: u64,
    pub callback_micros: u64,
    pub journal_bytes: u64,
}

pub struct RuleArtifactConsumerV1 {
    principal_id: StableId,
    worker_id: StableId,
    selected: RevalidatingSelectedCandidateV1,
    closed: bool,
}

impl RuleArtifactConsumerV1 {
    #[must_use]
    pub fn new(
        principal_id: StableId,
        worker_id: StableId,
        selected: RevalidatingSelectedCandidateV1,
    ) -> Self {
        Self {
            principal_id,
            worker_id,
            selected,
            closed: false,
        }
    }

    /// Derive the proposal from all exact pins. Editing a field after signature
    /// changes this binding and cannot reuse the claimed FinalUse token.
    pub fn final_use_binding(
        &self,
        binding: &RuleUseBindingV1,
    ) -> Result<FinalUseBinding, RuleArtifactUseError> {
        if self.closed {
            return Err(failure(
                RuleArtifactUseFailureV1::Unavailable,
                "explicit reload required",
            ));
        }
        let manifest = &self.selected.spec().manifest;
        if binding.checkpoint_digest != manifest.content_digest
            || binding.generation != manifest.generation
            || binding.inference.generation != binding.generation
            || binding.inference.model_id != manifest.artifact_id
            || binding.inference.weights_digest != manifest.content_digest
            || binding.authority_epoch == 0
            || binding.scope_digest.is_zero()
            || binding.expected_prediction_q24.len() != binding.inference.expected_output_width
            || binding
                .expected_prediction_q24
                .iter()
                .any(|value| !(-(8 << 24)..=(8 << 24)).contains(value))
            || binding.deadline_unix_ms == 0
        {
            return Err(failure(
                RuleArtifactUseFailureV1::Binding,
                "rule/candidate/inference pin mismatch",
            ));
        }
        let inference_digest = neuron_feature_request_digest_v1(&binding.inference)
            .map_err(|error| failure(RuleArtifactUseFailureV1::Binding, error.to_string()))?;
        let mut bytes = b"hepta.agentd.rule-artifact-use.v1\0".to_vec();
        bytes.extend_from_slice(&(self.worker_id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(self.worker_id.as_str().as_bytes());
        bytes.extend_from_slice(binding.checkpoint_digest.as_array());
        bytes.extend_from_slice(&binding.rule_revision.to_be_bytes());
        bytes.extend_from_slice(&binding.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&binding.generation.get().to_be_bytes());
        bytes.extend_from_slice(&binding.deadline_unix_ms.to_be_bytes());
        bytes.extend_from_slice(binding.scope_digest.as_array());
        bytes.extend_from_slice(self.selected.selection_digest().as_array());
        bytes.extend_from_slice(self.selected.owner_trust_digest().as_array());
        bytes.extend_from_slice(inference_digest.as_array());
        bytes.extend_from_slice(&(binding.expected_prediction_q24.len() as u64).to_be_bytes());
        for value in &binding.expected_prediction_q24 {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(FinalUseBinding {
            subject_id: self.principal_id.to_string(),
            destination_id: format!("rule-artifact:{}", manifest.artifact_id),
            request_sha256: *Digest32::of_bytes(&bytes).as_array(),
            scope_sha256: *binding.scope_digest.as_array(),
            payload_sha256: *inference_digest.as_array(),
        })
    }

    /// The exclusive artifact-owner borrow prevents native publication during
    /// the synchronous use. Intent is synced before entry; terminal observation
    /// is synced before returning. A prior request is always reconcile-only,
    /// including after restart or a lost acknowledgement. No result is replayed.
    #[allow(clippy::too_many_arguments)]
    pub fn execute(
        &mut self,
        owner: &mut LearningArtifactOwnerService,
        control: &mut DurableInferenceControl,
        authority: &FinalUseAuthority,
        token: VerifiedUseToken,
        binding: &RuleUseBindingV1,
        driver: impl FnOnce(&[u8], &NeuronFeatureRequestV1) -> Result<NeuronFeatureReceiptV1, String>,
    ) -> Result<RuleArtifactUseReceiptV1, RuleArtifactUseError> {
        let started = Instant::now();
        let initial_bytes =
            std::fs::metadata(control.journal_path()).map_or(0, |value| value.len());
        let mut evidence = RuleArtifactUseEvidenceV1 {
            callback_entered: false,
            inference: None,
            elapsed_micros: 0,
            callback_micros: 0,
            journal_bytes: 0,
        };
        let result = (|| {
            let expected = self.final_use_binding(binding)?;
            // A panic caught by the host cannot reopen this adapter. Only a
            // completely successful terminal sync restores availability.
            self.closed = true;
            if token.claimed_authority_epoch() != binding.authority_epoch {
                return Err(failure(
                    RuleArtifactUseFailureV1::Binding,
                    "authority epoch mismatch",
                ));
            }
            let token_expires_at_ms = token.expires_at_unix_ms();
            let now_ms = unix_time_ms()?;
            if now_ms >= binding.deadline_unix_ms {
                return Err(failure(
                    RuleArtifactUseFailureV1::Late,
                    "deadline elapsed before intent",
                ));
            }
            let current = owner
                .current_registry_view(now_ms / 1_000)
                .map_err(|error| failure(RuleArtifactUseFailureV1::Current, error.to_string()))?;
            let request_id = binding.inference.request_id.as_str();
            if control.get(request_id).is_some() || control.native_record(request_id).is_some() {
                return Err(failure(
                    RuleArtifactUseFailureV1::ReconcileOnly,
                    "durable request already exists",
                ));
            }
            let model_digest = binding.checkpoint_digest.to_string();
            let payload_digest = Digest32::from_array(expected.payload_sha256).to_string();
            let request_digest = Digest32::from_array(expected.request_sha256).to_string();
            let reservation_id = format!("rule-{}", Digest32::of_bytes(request_id.as_bytes()));
            let principal_id = self.principal_id.to_string();
            let worker_id = self.worker_id.to_string();
            self.selected
                .with_current(current, now_ms / 1_000, |_| ())
                .map_err(|error| failure(RuleArtifactUseFailureV1::Selection, error.to_string()))?;
            let admitted = (|| {
                let submitted = control
                    .submit(
                        now_ms,
                        InferenceRequest {
                            request_id: request_id.to_owned(),
                            principal_id,
                            model_digest: model_digest.clone(),
                            payload_digest: payload_digest.clone(),
                            maximum_tokens: 1,
                            deadline_ms: binding.deadline_unix_ms,
                            semantic_digest: request_digest.clone(),
                        },
                    )
                    .map_err(|error| {
                        failure(RuleArtifactUseFailureV1::Persistence, error.to_string())
                    })?;
                let reserved = control
                    .reserve(
                        now_ms,
                        request_id,
                        submitted.revision,
                        Reservation {
                            reservation_id: reservation_id.clone(),
                            quota_units: binding
                                .deadline_unix_ms
                                .saturating_sub(now_ms)
                                .saturating_mul(1_000)
                                .max(1),
                            maximum_tokens: 1,
                            authority_epoch: binding.authority_epoch,
                            valid_until_ms: binding.deadline_unix_ms,
                        },
                    )
                    .map_err(|error| {
                        failure(RuleArtifactUseFailureV1::Persistence, error.to_string())
                    })?;
                let assigned = control
                    .assign(
                        request_id,
                        reserved.revision,
                        Assignment {
                            worker_id: worker_id.clone(),
                            worker_generation: binding.generation.get(),
                            assignment_digest: request_digest.clone(),
                        },
                    )
                    .map_err(|error| {
                        failure(RuleArtifactUseFailureV1::Persistence, error.to_string())
                    })?;
                let execution = authority.with_verified_effect(token, &expected, || {
                    // FinalUse mutex acquisition may have waited. Reacquire
                    // CURRENT and independent selection after that wait, while
                    // the native publication and revocation fences remain held.
                    let entered_ms = unix_time_ms()?;
                    let current =
                        owner
                            .current_registry_view(entered_ms / 1_000)
                            .map_err(|error| {
                                failure(RuleArtifactUseFailureV1::Current, error.to_string())
                            })?;
                    let current_valid_until = current.valid_until();
                    // This closure only copies the bounded immutable bytes.
                    // Driver dispatch follows it, after a fresh clock check.
                    let payload = self
                        .selected
                        .with_current(current, unix_time_ms()? / 1_000, <[u8]>::to_vec)
                        .map_err(|error| {
                            failure(RuleArtifactUseFailureV1::Selection, error.to_string())
                        })?;
                    require_entry_live(
                        unix_time_ms()?,
                        authority.clock_unix_ms().map_err(|error| {
                            failure(RuleArtifactUseFailureV1::FinalUse, error.to_string())
                        })?,
                        binding.deadline_unix_ms,
                        token_expires_at_ms,
                        current_valid_until,
                        self.selected.valid_until(),
                    )?;
                    evidence.callback_entered = true;
                    let callback_started = Instant::now();
                    let value = driver(&payload, &binding.inference).map_err(|error| {
                        failure(
                            RuleArtifactUseFailureV1::Driver,
                            error.chars().take(512).collect::<String>(),
                        )
                    });
                    evidence.callback_micros = micros(callback_started.elapsed().as_micros());
                    value
                });
                let (status, output_digest, execution_error) = match execution {
                    Err(error) => (
                        Some(RequestState::Failed),
                        None,
                        Some(failure(
                            RuleArtifactUseFailureV1::FinalUse,
                            error.to_string(),
                        )),
                    ),
                    Ok(Err(error)) => (
                        (!evidence.callback_entered).then_some(RequestState::Failed),
                        None,
                        Some(error),
                    ),
                    Ok(Ok(receipt)) => {
                        let validation =
                            verify_neuron_feature_receipt_v1(&binding.inference, &receipt);
                        let completed = receipt.status == NeuronFeatureTerminalStatusV1::Succeeded;
                        let matches = receipt.prediction_q24 == binding.expected_prediction_q24;
                        let output_digest = validation
                            .is_ok()
                            .then(|| receipt.output_digest.to_string());
                        let status = validation
                            .is_ok()
                            .then_some(match receipt.status {
                                NeuronFeatureTerminalStatusV1::Succeeded => RequestState::Completed,
                                NeuronFeatureTerminalStatusV1::Failed => RequestState::Failed,
                                NeuronFeatureTerminalStatusV1::Cancelled => RequestState::Cancelled,
                                NeuronFeatureTerminalStatusV1::Indeterminate => {
                                    RequestState::Indeterminate
                                }
                            })
                            .filter(|status| *status != RequestState::Indeterminate);
                        evidence.inference = Some(receipt);
                        let error = if let Err(error) = validation {
                            Some(failure(
                                RuleArtifactUseFailureV1::Receipt,
                                error.to_string(),
                            ))
                        } else if !completed || !matches {
                            Some(failure(
                                RuleArtifactUseFailureV1::Receipt,
                                "driver failed or rule prediction mismatch",
                            ))
                        } else if unix_time_ms()? >= binding.deadline_unix_ms {
                            Some(failure(
                                RuleArtifactUseFailureV1::Late,
                                "receipt arrived after deadline",
                            ))
                        } else {
                            None
                        };
                        (status, output_digest.filter(|_| status.is_some()), error)
                    }
                };
                let observation_digest = Digest32::of_bytes(
                    format!(
                        "{request_digest}:{status:?}:{output_digest:?}:{}",
                        evidence.callback_micros
                    )
                    .as_bytes(),
                );
                control
                    .settle(
                        request_id,
                        assigned.revision,
                        observation_digest.to_string(),
                        TerminalObservation {
                            request_id: request_id.to_owned(),
                            reservation_id,
                            worker_id,
                            worker_generation: binding.generation.get(),
                            model_digest,
                            payload_digest,
                            terminal_observed: status.is_some(),
                            terminal_status: status,
                            output_digest,
                            consumed_tokens: 0,
                            // The selected finite driver produces no text tokens. Units
                            // record elapsed callback microseconds, not billing or CPU.
                            usage_units: evidence.callback_micros,
                        },
                    )
                    .map_err(|error| {
                        failure(RuleArtifactUseFailureV1::Persistence, error.to_string())
                    })?;
                if let Some(error) = execution_error {
                    return Err(error);
                }
                if unix_time_ms()? >= binding.deadline_unix_ms {
                    return Err(failure(
                        RuleArtifactUseFailureV1::Late,
                        "terminal acknowledgement completed after deadline",
                    ));
                }
                Ok(Digest32::from_array(expected.request_sha256))
            })();
            // Keep the existing artifact writer authority borrowed until all
            // inference effects and terminal persistence above have completed.
            let _ = owner.registry();
            admitted
        })();
        evidence.elapsed_micros = micros(started.elapsed().as_micros());
        evidence.journal_bytes = std::fs::metadata(control.journal_path())
            .map_or(0, |value| value.len().saturating_sub(initial_bytes));
        match result {
            Ok(rule_binding_digest) => {
                let Some(inference) = evidence.inference.take() else {
                    self.selected.close();
                    return Err(RuleArtifactUseError {
                        kind: RuleArtifactUseFailureV1::Unavailable,
                        reason: "terminal result has no retained native receipt".to_owned(),
                        evidence: Some(Box::new(evidence)),
                    });
                };
                self.closed = false;
                Ok(RuleArtifactUseReceiptV1 {
                    inference,
                    rule_binding_digest,
                    elapsed_micros: evidence.elapsed_micros,
                    callback_micros: evidence.callback_micros,
                    journal_bytes: evidence.journal_bytes,
                })
            }
            Err(mut error) => {
                self.closed = true;
                self.selected.close();
                error.evidence = Some(Box::new(evidence));
                Err(error)
            }
        }
    }
}

// CURRENT/selection native seconds are inclusive under host wall time. FinalUse
// expiry uses the authority's protected clock; both millisecond bounds exclude
// equality. The two independently supplied clocks must never be substituted.
fn require_entry_live(
    now_ms: u64,
    protected_now_ms: u64,
    deadline_ms: u64,
    token_expiry_ms: u64,
    current_until_seconds: u64,
    selection_until_seconds: u64,
) -> Result<(), RuleArtifactUseError> {
    if now_ms >= deadline_ms
        || protected_now_ms >= token_expiry_ms
        || now_ms / 1_000 > current_until_seconds
        || now_ms / 1_000 > selection_until_seconds
    {
        return Err(failure(
            RuleArtifactUseFailureV1::Late,
            "native evidence expired before driver entry",
        ));
    }
    Ok(())
}

fn failure(kind: RuleArtifactUseFailureV1, reason: impl Into<String>) -> RuleArtifactUseError {
    RuleArtifactUseError {
        kind,
        reason: reason.into(),
        evidence: None,
    }
}

fn micros(value: u128) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}

fn unix_time_ms() -> Result<u64, RuleArtifactUseError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| failure(RuleArtifactUseFailureV1::Unavailable, error.to_string()))?;
    u64::try_from(elapsed.as_millis())
        .map_err(|error| failure(RuleArtifactUseFailureV1::Unavailable, error.to_string()))
}

#[cfg(test)]
#[path = "rule_artifact_tests.rs"]
mod tests;
