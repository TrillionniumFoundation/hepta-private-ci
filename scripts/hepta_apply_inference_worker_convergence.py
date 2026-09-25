#!/usr/bin/env python3
"""Apply the reviewed inference.worker trust, cancellation and local-driver convergence."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = "aa2940ead13bd559dbe693d2e2e95815cc7e7f9f"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def git_show(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{OLD}:{path}"], cwd=ROOT, text=True
    )


def patch_final_use() -> None:
    path = ROOT / "codex-rs/hepta-contracts/src/final_use.rs"
    source = path.read_text()
    needle = """    /// Atomically validate and claim one nonce immediately before dispatch.
    /// A failed or uncertain dispatch does not refund the nonce: retry needs a
    /// new owner-signed grant, after the caller has reconciled any unknown effect.
    pub fn claim(
"""
    insert = """    /// Verify that an already-admitted long-lived generation remains live
    /// against the current trusted epoch and revocation head without consuming
    /// another nonce. This is a fence check, not authority for a new effect.
    pub fn revalidate(
        &self,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
    ) -> Result<(), FinalUseError> {
        let input = signed.grant.signing_bytes()?;
        if signed.grant.signer_id != self.0.signer_id || &signed.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| FinalUseError::InvalidSignature)?;
        let verified = self.0.issuer_keys.iter().any(|candidate| {
            signed.grant.authority_epoch >= candidate.not_before_authority_epoch
                && signed.grant.authority_epoch <= candidate.not_after_authority_epoch
                && candidate.key.verify_strict(&input, &signature).is_ok()
        });
        if !verified {
            return Err(FinalUseError::InvalidSignature);
        }
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| FinalUseError::Unavailable)?;
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        let now_unix_ms = self.now_unix_ms()?;
        validate_live(&signed.grant, &state.head, now_unix_ms)
    }

""" + needle
    path.write_text(replace_once(source, needle, insert, "final-use revalidate"))

    path = ROOT / "codex-rs/hepta-contracts/src/final_use_tests.rs"
    source = path.read_text()
    needle = """#[test]
fn signed_claim_is_single_use_and_delivers_under_same_owner() {
"""
    insert = """#[test]
fn current_revalidation_fences_long_lived_generation_after_revocation() {
    let (authority, signed, _directory) = fixture().unwrap();
    assert_eq!(authority.revalidate(&signed, &signed.grant.binding), Ok(()));
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: signed.grant.authority_epoch,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
        })
        .unwrap();
    assert_eq!(
        authority.revalidate(&signed, &signed.grant.binding),
        Err(FinalUseError::Revoked)
    );
}

""" + needle
    path.write_text(replace_once(source, needle, insert, "final-use regression"))


def rewrite_model_worker() -> None:
    path = ROOT / "codex-rs/hepta-infer-worker-host/src/model_worker.rs"
    current = path.read_text()
    marker = "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct NeuronFeatureRequest"
    second_impl = (
        "impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {\n"
        "    /// Execute the worker path"
    )
    if marker not in current or second_impl not in current:
        raise RuntimeError("current neuron feature implementation shape changed")
    tail = current[current.index(marker) :]
    post = tail[tail.index(second_impl) :]
    types = tail[: tail.index("/// Executes the frozen encoder/head feature path")]
    types = replace_once(
        types,
        """pub struct DriverNeuronFeatureObservation {
    pub terminal_observed: bool,
    pub succeeded: bool,
""",
        """pub struct DriverNeuronFeatureObservation {
    pub terminal_observed: bool,
    pub succeeded: bool,
    /// True only after the runtime acknowledged cancellation as terminal.
    pub cancelled: bool,
""",
        "neuron cancellation field",
    )

    top = r'''#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sha2::Digest;
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

const MAX_MODELS: usize = 8;
const MAX_ACTIVE_REQUESTS: usize = 256;
const MAX_TOKENS: u32 = 1_000_000;
const MAX_INPUT_BYTES: usize = 1024 * 1024;
const MAX_NEURON_FEATURES: usize = 512;
const Q24_STATE_LIMIT: i64 = 8 * (1_i64 << 24);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelManifest {
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
    pub maximum_tokens: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceGrant {
    pub grant_id: String,
    pub authority_epoch: u64,
    pub generation: u64,
    pub expires_at_ms: u64,
    pub revoked: bool,
    pub maximum_models: usize,
    pub maximum_active_requests: usize,
    pub maximum_memory_bytes: u64,
    pub semantic_digest: String,
}

/// Raw grant fields are descriptive data, not an authenticated capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GrantVerification {
    /// Restricted to same-crate fixtures and trusted in-process composition.
    TrustedInProcess,
    /// Evidence produced by the kernel final-use authority for one exact worker.
    Authenticated {
        authority_id: String,
        evidence_digest: String,
        worker_id: String,
    },
}

trait ResourceGrantVerifier {
    fn verify(&self, now_ms: u64, grant: &ResourceGrant) -> Result<GrantVerification, Error>;
}

struct FinalUseResourceGrantVerifier<'a> {
    authority: &'a FinalUseAuthority,
    signed: &'a SignedFinalUseGrant,
    worker_id: String,
}

impl<'a> FinalUseResourceGrantVerifier<'a> {
    fn new(
        authority: &'a FinalUseAuthority,
        signed: &'a SignedFinalUseGrant,
        worker_id: String,
    ) -> Result<Self, Error> {
        validate_identity(&worker_id, "worker")?;
        Ok(Self {
            authority,
            signed,
            worker_id,
        })
    }
}

impl ResourceGrantVerifier for FinalUseResourceGrantVerifier<'_> {
    fn verify(&self, _now_ms: u64, grant: &ResourceGrant) -> Result<GrantVerification, Error> {
        if self.signed.grant.authority_epoch != grant.authority_epoch {
            return Err(Error::InvalidGrant);
        }
        let binding = resource_grant_final_use_binding(&self.worker_id, grant)?;
        let evidence = serde_json::to_vec(self.signed).map_err(|_| Error::InvalidGrant)?;
        let evidence_digest = sha256(&evidence);
        let authority_id = self.signed.grant.signer_id.clone();
        let token = self
            .authority
            .claim(self.signed, &binding)
            .map_err(map_final_use_error)?;
        self.authority
            .with_verified_use(token, &binding, || GrantVerification::Authenticated {
                authority_id,
                evidence_digest,
                worker_id: self.worker_id.clone(),
            })
            .map_err(map_final_use_error)
    }
}

/// Canonical final-use binding for one local resource-grant generation.
pub fn resource_grant_final_use_binding(
    worker_id: &str,
    grant: &ResourceGrant,
) -> Result<FinalUseBinding, Error> {
    validate_identity(worker_id, "worker")?;
    validate_identity(&grant.grant_id, "grant")?;
    validate_digest(&grant.semantic_digest, "grant semantic")?;
    if grant.revoked
        || grant.authority_epoch == 0
        || grant.generation == 0
        || grant.expires_at_ms == 0
        || grant.maximum_models == 0
        || grant.maximum_active_requests == 0
        || grant.maximum_memory_bytes == 0
    {
        return Err(Error::InvalidGrant);
    }
    let payload = serde_json::to_vec(&(
        "hepta.local-resource-grant.v1",
        &grant.grant_id,
        grant.authority_epoch,
        grant.generation,
        grant.expires_at_ms,
        grant.revoked,
        grant.maximum_models,
        grant.maximum_active_requests,
        grant.maximum_memory_bytes,
        &grant.semantic_digest,
    ))
    .map_err(|_| Error::InvalidGrant)?;
    let payload_sha256 = sha256_array(&payload);
    let request_sha256 = sha256_array(
        &serde_json::to_vec(&(
            "hepta.local-resource-grant.request.v1",
            worker_id,
            grant.generation,
            payload_sha256,
        ))
        .map_err(|_| Error::InvalidGrant)?,
    );
    let scope_sha256 = sha256_array(
        &serde_json::to_vec(&(
            "hepta.local-resource-grant.scope.v1",
            worker_id,
            grant.generation,
            &grant.semantic_digest,
        ))
        .map_err(|_| Error::InvalidGrant)?,
    );
    Ok(FinalUseBinding {
        subject_id: worker_id.to_string(),
        destination_id: "resource:local-model-worker".to_string(),
        request_sha256,
        scope_sha256,
        payload_sha256,
    })
}

/// Move-only proof that one exact resource generation was authenticated.
#[derive(Debug, Eq, PartialEq)]
pub struct VerifiedResourceGrant {
    grant: ResourceGrant,
    verification: GrantVerification,
}

impl VerifiedResourceGrant {
    pub(crate) fn trusted_in_process(now_ms: u64, grant: ResourceGrant) -> Result<Self, Error> {
        validate_grant(now_ms, &grant)?;
        Ok(Self {
            grant,
            verification: GrantVerification::TrustedInProcess,
        })
    }

    fn verify_with<V: ResourceGrantVerifier>(
        now_ms: u64,
        grant: ResourceGrant,
        verifier: &V,
    ) -> Result<Self, Error> {
        validate_grant(now_ms, &grant)?;
        let verification = verifier.verify(now_ms, &grant)?;
        match &verification {
            GrantVerification::Authenticated {
                authority_id,
                evidence_digest,
                worker_id,
            } => {
                validate_identity(authority_id, "grant authority")?;
                validate_digest(evidence_digest, "grant evidence")?;
                validate_identity(worker_id, "grant worker")?;
            }
            GrantVerification::TrustedInProcess => return Err(Error::InvalidGrant),
        }
        Ok(Self {
            grant,
            verification,
        })
    }

    /// Authenticate one exact worker generation through kernel final-use authority.
    pub fn verify_final_use(
        now_ms: u64,
        grant: ResourceGrant,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        worker_id: String,
    ) -> Result<Self, Error> {
        let verifier = FinalUseResourceGrantVerifier::new(authority, signed, worker_id)?;
        Self::verify_with(now_ms, grant, &verifier)
    }

    pub fn grant(&self) -> &ResourceGrant {
        &self.grant
    }

    pub fn verification(&self) -> &GrantVerification {
        &self.verification
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorkerRequest {
    pub request_id: String,
    pub reservation_id: String,
    pub model_digest: String,
    /// Exact UTF-8 input presented to the local runtime.
    pub input: String,
    pub payload_digest: String,
    pub maximum_tokens: u32,
    pub deadline_ms: u64,
    pub lease_payload_digest: String,
    pub reservation_model_digest: String,
    pub reservation_maximum_tokens: u32,
    pub cancelled: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverModelHandle {
    pub opaque_id: String,
    /// Runtime memory reserved before the model is declared usable.
    pub reserved_memory_bytes: u64,
    pub observed_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverRunObservation {
    pub terminal_observed: bool,
    pub succeeded: bool,
    /// True only after terminal cancellation acknowledgement.
    pub cancelled: bool,
    pub output_digest: Option<String>,
    /// None means usage was not durably observed and must remain unknown.
    pub consumed_tokens: Option<u32>,
    pub observed_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelLoadObservation {
    pub model_id: String,
    pub worker_generation: u64,
    pub handle_id: String,
    pub observed_memory_bytes: u64,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ExecutionStatus {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceExecutionObservation {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_generation: u64,
    pub model_digest: String,
    pub payload_digest: String,
    pub status: ExecutionStatus,
    pub output_digest: Option<String>,
    pub consumed_tokens: Option<u32>,
    pub observed_memory_bytes: u64,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelUnloadObservation {
    pub model_id: String,
    pub worker_generation: u64,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidManifest,
    InvalidGrant,
    GrantExpired,
    GrantRevoked,
    GrantAuthorityUnavailable,
    ModelCapacity,
    RequestCapacity,
    ModelAlreadyLoaded,
    ModelNotLoaded,
    ModelCleanupPending,
    ModelMismatch,
    PayloadMismatch,
    TokenLimit,
    DeadlineExpired,
    ActiveRequests,
    DriverFailure(String),
    MissingTerminalOutput,
    ArithmeticOverflow,
    FeatureLimit,
    FeatureOutputMismatch,
    FeatureContract,
    CleanupPending(String),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub trait ModelDriver {
    fn load(
        &mut self,
        manifest: &ModelManifest,
        grant: &ResourceGrant,
        maximum_memory_bytes: u64,
    ) -> Result<DriverModelHandle, Error>;

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
        cancellation: &CancellationToken,
        response_timeout: Duration,
    ) -> Result<DriverRunObservation, Error>;

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ModelLifecycle {
    Active,
    CleanupRequired,
}

#[derive(Debug)]
struct LoadedModel {
    manifest: ModelManifest,
    handle: DriverModelHandle,
    active_requests: usize,
    lifecycle: ModelLifecycle,
}

#[derive(Debug)]
pub struct InferenceWorker<D: ModelDriver> {
    worker_id: String,
    generation: u64,
    grant: ResourceGrant,
    grant_verification: GrantVerification,
    driver: D,
    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
}

impl<D: ModelDriver> InferenceWorker<D> {
    pub fn new(
        now_ms: u64,
        worker_id: String,
        generation: u64,
        grant: VerifiedResourceGrant,
        driver: D,
    ) -> Result<Self, Error> {
        validate_identity(&worker_id, "worker")?;
        validate_grant(now_ms, grant.grant())?;
        if generation == 0 || generation != grant.grant().generation {
            return Err(Error::InvalidGrant);
        }
        if let GrantVerification::Authenticated {
            worker_id: authenticated_worker,
            ..
        } = grant.verification()
            && authenticated_worker != &worker_id
        {
            return Err(Error::InvalidGrant);
        }
        let VerifiedResourceGrant {
            grant,
            verification: grant_verification,
        } = grant;
        Ok(Self {
            worker_id,
            generation,
            grant,
            grant_verification,
            driver,
            models: BTreeMap::new(),
            active_requests: BTreeMap::new(),
        })
    }

    pub fn worker_id(&self) -> &str {
        &self.worker_id
    }

    pub fn grant_verification(&self) -> &GrantVerification {
        &self.grant_verification
    }

    /// Count every retained handle, including failed cleanup and invalid-load
    /// compensation state. The larger of reserved and observed bytes is charged.
    #[must_use]
    pub fn resident_memory_bytes(&self) -> u128 {
        self.models
            .values()
            .map(|loaded| {
                u128::from(
                    loaded
                        .handle
                        .reserved_memory_bytes
                        .max(loaded.handle.observed_memory_bytes),
                )
            })
            .sum()
    }

    pub fn load_model(
        &mut self,
        now_ms: u64,
        manifest: ModelManifest,
    ) -> Result<ModelLoadObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_manifest(&manifest)?;
        if self.models.contains_key(&manifest.model_id) {
            return Err(Error::ModelAlreadyLoaded);
        }
        let model_limit = self.grant.maximum_models.min(MAX_MODELS);
        if self.models.len() >= model_limit {
            return Err(Error::ModelCapacity);
        }
        let resident = self.resident_memory_bytes();
        let maximum = u128::from(self.grant.maximum_memory_bytes);
        if resident >= maximum {
            return Err(Error::ModelCapacity);
        }
        let remaining_memory_bytes = u64::try_from(maximum - resident)
            .map_err(|_| Error::ArithmeticOverflow)?;
        let handle = self
            .driver
            .load(&manifest, &self.grant, remaining_memory_bytes)?;
        let accounted = handle
            .reserved_memory_bytes
            .max(handle.observed_memory_bytes);
        let next_resident = resident + u128::from(accounted);
        let load_error = validate_identity(&handle.opaque_id, "model handle")
            .err()
            .or_else(|| {
                (handle.reserved_memory_bytes == 0
                    || handle.observed_memory_bytes > handle.reserved_memory_bytes
                    || next_resident > maximum)
                    .then_some(Error::ModelCapacity)
            });
        if let Some(load_error) = load_error {
            if let Err(cleanup_error) = self.driver.unload(handle.clone()) {
                self.models.insert(
                    manifest.model_id.clone(),
                    LoadedModel {
                        manifest,
                        handle,
                        active_requests: 0,
                        lifecycle: ModelLifecycle::CleanupRequired,
                    },
                );
                return Err(Error::CleanupPending(format!(
                    "post-load validation failed ({load_error}); cleanup failed ({cleanup_error})"
                )));
            }
            return Err(load_error);
        }
        let observation = ModelLoadObservation {
            model_id: manifest.model_id.clone(),
            worker_generation: self.generation,
            handle_id: handle.opaque_id.clone(),
            observed_memory_bytes: handle.observed_memory_bytes,
            terminal_observed: true,
        };
        self.models.insert(
            manifest.model_id.clone(),
            LoadedModel {
                manifest,
                handle,
                active_requests: 0,
                lifecycle: ModelLifecycle::Active,
            },
        );
        Ok(observation)
    }

    pub fn run(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: WorkerRequest,
    ) -> Result<InferenceExecutionObservation, Error> {
        self.run_cancellable(
            now_ms,
            model_id,
            request,
            &CancellationToken::new(),
        )
    }

    pub fn run_cancellable(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: WorkerRequest,
        cancellation: &CancellationToken,
    ) -> Result<InferenceExecutionObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        validate_request(now_ms, &request)?;
        validate_normal_request(&request)?;
        if self.active_requests.contains_key(&request.request_id) {
            return Err(Error::RequestCapacity);
        }
        let request_limit = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        if self.active_requests.len() >= request_limit {
            return Err(Error::RequestCapacity);
        }
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.lifecycle != ModelLifecycle::Active {
            return Err(Error::ModelCleanupPending);
        }
        if request.model_digest != loaded.manifest.model_digest
            || request.reservation_model_digest != loaded.manifest.model_digest
        {
            return Err(Error::ModelMismatch);
        }
        if request.maximum_tokens > loaded.manifest.maximum_tokens
            || request.maximum_tokens > request.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        if request.payload_digest != request.lease_payload_digest {
            return Err(Error::PayloadMismatch);
        }
        if request.cancelled || cancellation.is_cancelled() {
            return Ok(InferenceExecutionObservation {
                request_id: request.request_id,
                reservation_id: request.reservation_id,
                worker_generation: self.generation,
                model_digest: request.model_digest,
                payload_digest: request.payload_digest,
                status: ExecutionStatus::Cancelled,
                output_digest: None,
                consumed_tokens: Some(0),
                observed_memory_bytes: loaded.handle.observed_memory_bytes,
                terminal_observed: true,
            });
        }

        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests
            .insert(request.request_id.clone(), model_id.to_string());
        let response_timeout = Duration::from_millis(
            request
                .deadline_ms
                .checked_sub(now_ms)
                .ok_or(Error::DeadlineExpired)?,
        );
        let observed = self
            .driver
            .run(&loaded.handle, &request, cancellation, response_timeout);
        self.active_requests.remove(&request.request_id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        let observed = match observed {
            Ok(observed) => observed,
            Err(error) => {
                if matches!(error, Error::DriverFailure(_)) {
                    loaded.lifecycle = ModelLifecycle::CleanupRequired;
                }
                return Err(error);
            }
        };
        if observed.consumed_tokens.is_some_and(|tokens| {
            tokens > request.maximum_tokens || tokens > request.reservation_maximum_tokens
        }) {
            return Err(Error::TokenLimit);
        }
        if observed.observed_memory_bytes > loaded.handle.reserved_memory_bytes {
            loaded.lifecycle = ModelLifecycle::CleanupRequired;
            return Err(Error::ModelCapacity);
        }
        let cancelled_race = cancellation.is_cancelled() && !observed.cancelled;
        let (status, output_digest, terminal_observed) = if cancelled_race
            || !observed.terminal_observed
        {
            (ExecutionStatus::Indeterminate, None, false)
        } else if observed.cancelled {
            (ExecutionStatus::Cancelled, None, true)
        } else if observed.succeeded {
            let output = observed
                .output_digest
                .as_ref()
                .ok_or(Error::MissingTerminalOutput)?;
            validate_digest(output, "output")?;
            (ExecutionStatus::Succeeded, observed.output_digest, true)
        } else {
            if let Some(output) = &observed.output_digest {
                validate_digest(output, "output")?;
            }
            (ExecutionStatus::Failed, observed.output_digest, true)
        };
        Ok(InferenceExecutionObservation {
            request_id: request.request_id,
            reservation_id: request.reservation_id,
            worker_generation: self.generation,
            model_digest: request.model_digest,
            payload_digest: request.payload_digest,
            status,
            output_digest,
            consumed_tokens: observed.consumed_tokens,
            observed_memory_bytes: observed.observed_memory_bytes,
            terminal_observed,
        })
    }

    pub fn unload_model(
        &mut self,
        _now_ms: u64,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, Error> {
        validate_identity(model_id, "model")?;
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.active_requests != 0 {
            return Err(Error::ActiveRequests);
        }
        loaded.lifecycle = ModelLifecycle::CleanupRequired;
        self.driver.unload(loaded.handle.clone())?;
        self.models.remove(model_id).ok_or(Error::ModelNotLoaded)?;
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }

    /// Attempt every resident cleanup. Failed handles stay accounted and fenced.
    pub fn unload_all(&mut self, now_ms: u64) -> Result<Vec<ModelUnloadObservation>, Error> {
        if !self.active_requests.is_empty() {
            return Err(Error::ActiveRequests);
        }
        let model_ids = self.models.keys().cloned().collect::<Vec<_>>();
        let mut observations = Vec::with_capacity(model_ids.len());
        let mut failures = Vec::new();
        for model_id in model_ids {
            match self.unload_model(now_ms, &model_id) {
                Ok(observation) => observations.push(observation),
                Err(error) => failures.push(format!("{model_id}: {error}")),
            }
        }
        if failures.is_empty() {
            Ok(observations)
        } else {
            Err(Error::CleanupPending(failures.join("; ")))
        }
    }

    fn validate_current_grant(&self, now_ms: u64) -> Result<(), Error> {
        validate_grant(now_ms, &self.grant)?;
        if self.resident_memory_bytes() > u128::from(self.grant.maximum_memory_bytes) {
            return Err(Error::ModelCapacity);
        }
        Ok(())
    }
}

fn validate_manifest(value: &ModelManifest) -> Result<(), Error> {
    validate_identity(&value.model_id, "model")?;
    for (digest, field) in [
        (&value.model_digest, "model"),
        (&value.weights_digest, "weights"),
        (&value.tokenizer_digest, "tokenizer"),
        (&value.preprocessor_digest, "preprocessor"),
        (&value.quantization_digest, "quantization"),
        (&value.runtime_digest, "runtime"),
        (&value.device_digest, "device"),
    ] {
        validate_digest(digest, field)?;
    }
    if value.maximum_tokens == 0 || value.maximum_tokens > MAX_TOKENS {
        return Err(Error::InvalidManifest);
    }
    Ok(())
}

fn validate_grant(now_ms: u64, value: &ResourceGrant) -> Result<(), Error> {
    validate_identity(&value.grant_id, "grant")?;
    validate_digest(&value.semantic_digest, "grant semantic")?;
    if value.revoked {
        return Err(Error::GrantRevoked);
    }
    if value.authority_epoch == 0
        || value.generation == 0
        || value.maximum_models == 0
        || value.maximum_active_requests == 0
        || value.maximum_memory_bytes == 0
    {
        return Err(Error::InvalidGrant);
    }
    if now_ms >= value.expires_at_ms {
        return Err(Error::GrantExpired);
    }
    Ok(())
}

fn validate_request(now_ms: u64, value: &WorkerRequest) -> Result<(), Error> {
    validate_identity(&value.request_id, "request")?;
    validate_identity(&value.reservation_id, "reservation")?;
    validate_digest(&value.model_digest, "model")?;
    validate_digest(&value.payload_digest, "payload")?;
    validate_digest(&value.lease_payload_digest, "lease payload")?;
    validate_digest(&value.reservation_model_digest, "reservation model")?;
    if value.maximum_tokens == 0
        || value.maximum_tokens > MAX_TOKENS
        || value.reservation_maximum_tokens == 0
        || value.reservation_maximum_tokens > MAX_TOKENS
    {
        return Err(Error::TokenLimit);
    }
    if now_ms >= value.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

fn validate_normal_request(value: &WorkerRequest) -> Result<(), Error> {
    if value.input.is_empty()
        || value.input.len() > MAX_INPUT_BYTES
        || sha256(value.input.as_bytes()) != value.payload_digest
    {
        return Err(Error::PayloadMismatch);
    }
    Ok(())
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn sha256_array(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn map_final_use_error(error: FinalUseError) -> Error {
    match error {
        FinalUseError::Unavailable
        | FinalUseError::UnsafeStateDirectory
        | FinalUseError::StateLocked => Error::GrantAuthorityUnavailable,
        _ => Error::InvalidGrant,
    }
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), Error> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::InvalidDigest(field));
    }
    Ok(())
}

'''

    neuron = r'''/// Executes the frozen encoder/head feature path for an already loaded model.
/// The driver must report the actual encoder/head identities and resource
/// measurements observed for this invocation.
pub trait NeuronFeatureDriver: ModelDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
        cancellation: &CancellationToken,
        response_timeout: Duration,
    ) -> Result<DriverNeuronFeatureObservation, Error>;
}

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    pub fn run_neuron_features(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: NeuronFeatureRequest,
    ) -> Result<NeuronFeatureExecutionObservation, Error> {
        self.run_neuron_features_cancellable(
            now_ms,
            model_id,
            request,
            &CancellationToken::new(),
        )
    }

    pub fn run_neuron_features_cancellable(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: NeuronFeatureRequest,
        cancellation: &CancellationToken,
    ) -> Result<NeuronFeatureExecutionObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        validate_request(now_ms, &request.authorization)?;
        validate_neuron_feature_request(&request)?;
        if self
            .active_requests
            .contains_key(&request.authorization.request_id)
        {
            return Err(Error::RequestCapacity);
        }
        let request_limit = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        if self.active_requests.len() >= request_limit {
            return Err(Error::RequestCapacity);
        }
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.lifecycle != ModelLifecycle::Active {
            return Err(Error::ModelCleanupPending);
        }
        if request.authorization.model_digest != loaded.manifest.model_digest
            || request.authorization.reservation_model_digest != loaded.manifest.model_digest
            || request.weights_digest != loaded.manifest.weights_digest
        {
            return Err(Error::ModelMismatch);
        }
        let payload_digest = canonical_neuron_feature_payload_digest(&request);
        if request.authorization.payload_digest != payload_digest
            || request.authorization.lease_payload_digest != payload_digest
        {
            return Err(Error::PayloadMismatch);
        }
        if request.authorization.cancelled || cancellation.is_cancelled() {
            return Ok(NeuronFeatureExecutionObservation {
                request_id: request.authorization.request_id,
                reservation_id: request.authorization.reservation_id,
                worker_generation: self.generation,
                manifest: loaded.manifest.clone(),
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                input_digest: request.input_digest,
                status: ExecutionStatus::Cancelled,
                drive_q24: Vec::new(),
                prediction_q24: Vec::new(),
                observed_memory_bytes: loaded.handle.observed_memory_bytes,
                transient_allocation_bytes: 0,
                queue_age_micros: 0,
                latency_micros: 0,
                terminal_observed: true,
            });
        }

        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests.insert(
            request.authorization.request_id.clone(),
            model_id.to_string(),
        );
        let response_timeout = Duration::from_millis(
            request
                .authorization
                .deadline_ms
                .checked_sub(now_ms)
                .ok_or(Error::DeadlineExpired)?,
        );
        let observed = self.driver.run_neuron_features(
            &loaded.handle,
            &request,
            cancellation,
            response_timeout,
        );
        self.active_requests
            .remove(&request.authorization.request_id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        let observed = match observed {
            Ok(observed) => observed,
            Err(error) => {
                if matches!(error, Error::DriverFailure(_)) {
                    loaded.lifecycle = ModelLifecycle::CleanupRequired;
                }
                return Err(error);
            }
        };
        if observed.observed_memory_bytes > loaded.handle.reserved_memory_bytes {
            loaded.lifecycle = ModelLifecycle::CleanupRequired;
            return Err(Error::ModelCapacity);
        }
        let cancelled_race = cancellation.is_cancelled() && !observed.cancelled;
        let (status, drive_q24, prediction_q24, terminal_observed) = if cancelled_race
            || !observed.terminal_observed
        {
            (ExecutionStatus::Indeterminate, Vec::new(), Vec::new(), false)
        } else if observed.cancelled {
            (ExecutionStatus::Cancelled, Vec::new(), Vec::new(), true)
        } else if observed.succeeded {
            validate_neuron_feature_output(&request, &observed)?;
            (
                ExecutionStatus::Succeeded,
                observed.drive_q24,
                observed.prediction_q24,
                true,
            )
        } else {
            (
                ExecutionStatus::Failed,
                observed.drive_q24,
                observed.prediction_q24,
                true,
            )
        };
        Ok(NeuronFeatureExecutionObservation {
            request_id: request.authorization.request_id,
            reservation_id: request.authorization.reservation_id,
            worker_generation: self.generation,
            manifest: loaded.manifest.clone(),
            encoder_digest: observed.encoder_digest,
            head_digest: observed.head_digest,
            input_digest: request.input_digest,
            status,
            drive_q24,
            prediction_q24,
            observed_memory_bytes: observed.observed_memory_bytes,
            transient_allocation_bytes: observed.transient_allocation_bytes,
            queue_age_micros: observed.queue_age_micros,
            latency_micros: observed.latency_micros,
            terminal_observed,
        })
    }
}

'''
    path.write_text(top + types + neuron + post)


def patch_model_worker_tests() -> None:
    path = ROOT / "codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs"
    source = path.read_text()
    source = replace_once(
        source,
        """    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            observed_memory_bytes: 1_024,
        })
    }
""",
        """    fn load(
        &mut self,
        manifest: &ModelManifest,
        _grant: &ResourceGrant,
        _maximum_memory_bytes: u64,
    ) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            reserved_memory_bytes: 1_024,
            observed_memory_bytes: 1_024,
        })
    }
""",
        "model test load",
    )
    source = replace_once(
        source,
        """    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
""",
        """    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
        _cancellation: &CancellationToken,
        _response_timeout: Duration,
    ) -> Result<DriverRunObservation, Error> {
""",
        "model test run signature",
    )
    source = source.replace(
        """                succeeded: false,
                output_digest: None,
                consumed_tokens: 4,
""",
        """                succeeded: false,
                cancelled: false,
                output_digest: None,
                consumed_tokens: Some(4),
""",
        1,
    )
    source = source.replace(
        """            succeeded: !self.fail_terminal,
            output_digest: Some("9".repeat(64)),
            consumed_tokens: 16,
""",
        """            succeeded: !self.fail_terminal,
            cancelled: false,
            output_digest: Some("9".repeat(64)),
            consumed_tokens: Some(16),
""",
        1,
    )
    source = replace_once(
        source,
        """    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
""",
        """    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
        _cancellation: &CancellationToken,
        _response_timeout: Duration,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
""",
        "model test feature signature",
    )
    source = source.replace(
        """                succeeded: false,
                encoder_digest: request.encoder_digest.clone(),
""",
        """                succeeded: false,
                cancelled: false,
                encoder_digest: request.encoder_digest.clone(),
""",
        1,
    )
    source = source.replace(
        """            succeeded: !self.fail_terminal,
            encoder_digest: request.encoder_digest.clone(),
""",
        """            succeeded: !self.fail_terminal,
            cancelled: false,
            encoder_digest: request.encoder_digest.clone(),
""",
        1,
    )
    grant_anchor = """fn manifest() -> ModelManifest {
"""
    verified = """fn verified_grant() -> VerifiedResourceGrant {
    VerifiedResourceGrant::trusted_in_process(100, grant()).expect("verified grant")
}

"""
    source = replace_once(source, grant_anchor, verified + grant_anchor, "verified grant helper")
    source = source.replace("3, grant(),", "3, verified_grant(),")
    old_request = """fn request() -> WorkerRequest {
    WorkerRequest {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: "2".repeat(64),
        payload_digest: "3".repeat(64),
        maximum_tokens: 64,
        deadline_ms: 9_000,
        lease_payload_digest: "3".repeat(64),
        reservation_model_digest: "2".repeat(64),
        reservation_maximum_tokens: 64,
        cancelled: false,
    }
}
"""
    new_request = """fn request() -> WorkerRequest {
    let input = "worker request input".to_string();
    let payload_digest = sha256(input.as_bytes());
    WorkerRequest {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: "2".repeat(64),
        input,
        payload_digest: payload_digest.clone(),
        maximum_tokens: 64,
        deadline_ms: 9_000,
        lease_payload_digest: payload_digest,
        reservation_model_digest: "2".repeat(64),
        reservation_maximum_tokens: 64,
        cancelled: false,
    }
}
"""
    path.write_text(replace_once(source, old_request, new_request, "model test request"))


def patch_lifecycle_tests() -> None:
    path = ROOT / "codex-rs/hepta-infer-worker-host/src/model_worker_resource_lifecycle_tests.rs"
    source = path.read_text()
    source = replace_once(
        source,
        """    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        self.load_attempts += 1;
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                String::new()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            observed_memory_bytes: self.bytes,
        })
    }
""",
        """    fn load(
        &mut self,
        manifest: &ModelManifest,
        _grant: &ResourceGrant,
        _maximum_memory_bytes: u64,
    ) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        self.load_attempts += 1;
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                String::new()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            reserved_memory_bytes: self.bytes,
            observed_memory_bytes: self.bytes,
        })
    }
""",
        "lifecycle load",
    )
    source = replace_once(
        source,
        """    fn run(
        &mut self,
        handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
""",
        """    fn run(
        &mut self,
        handle: &DriverModelHandle,
        _request: &WorkerRequest,
        _cancellation: &CancellationToken,
        _response_timeout: Duration,
    ) -> Result<DriverRunObservation, Error> {
""",
        "lifecycle run signature",
    )
    source = source.replace(
        """            succeeded: true,
            output_digest: Some("a".repeat(64)),
            consumed_tokens: 1,
""",
        """            succeeded: true,
            cancelled: false,
            output_digest: Some("a".repeat(64)),
            consumed_tokens: Some(1),
""",
        1,
    )
    source = replace_once(
        source,
        """    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
""",
        """    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
        _cancellation: &CancellationToken,
        _response_timeout: Duration,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
""",
        "lifecycle feature signature",
    )
    source = source.replace(
        """            succeeded: true,
            encoder_digest: request.encoder_digest.clone(),
""",
        """            succeeded: true,
            cancelled: false,
            encoder_digest: request.encoder_digest.clone(),
""",
        1,
    )
    old_request = """fn request() -> WorkerRequest {
    WorkerRequest {
        request_id: "request.lifecycle".to_string(),
        reservation_id: "reservation.lifecycle".to_string(),
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        maximum_tokens: 8,
        deadline_ms: 900,
        lease_payload_digest: "2".repeat(64),
        reservation_model_digest: "1".repeat(64),
        reservation_maximum_tokens: 8,
        cancelled: false,
    }
}
"""
    new_request = """fn request() -> WorkerRequest {
    let input = "lifecycle request".to_string();
    let payload_digest = sha256(input.as_bytes());
    WorkerRequest {
        request_id: "request.lifecycle".to_string(),
        reservation_id: "reservation.lifecycle".to_string(),
        model_digest: "1".repeat(64),
        input,
        payload_digest: payload_digest.clone(),
        maximum_tokens: 8,
        deadline_ms: 900,
        lease_payload_digest: payload_digest,
        reservation_model_digest: "1".repeat(64),
        reservation_maximum_tokens: 8,
        cancelled: false,
    }
}
"""
    source = replace_once(source, old_request, new_request, "lifecycle request")
    old_worker = """fn worker(bytes: u64, driver: LifecycleDriver) -> InferenceWorker<LifecycleDriver> {
    InferenceWorker::new(100, "worker.lifecycle".to_string(), 1, grant(bytes), driver)
        .expect("valid lifecycle fixture")
}
"""
    new_worker = """fn worker(bytes: u64, driver: LifecycleDriver) -> InferenceWorker<LifecycleDriver> {
    let grant = VerifiedResourceGrant::trusted_in_process(100, grant(bytes))
        .expect("verified lifecycle grant");
    InferenceWorker::new(100, "worker.lifecycle".to_string(), 1, grant, driver)
        .expect("valid lifecycle fixture")
}
"""
    path.write_text(replace_once(source, old_worker, new_worker, "lifecycle worker"))


def restore_local_driver() -> None:
    driver_path = ROOT / "codex-rs/hepta-infer-worker-host/src/local_process_driver.rs"
    source = git_show("codex-rs/hepta-infer-worker-host/src/local_process_driver.rs")
    source = replace_once(
        source,
        """impl RuntimeProcess {
    fn terminate(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for RuntimeProcess {
    fn drop(&mut self) {
        self.terminate();
    }
}
""",
        """impl RuntimeProcess {
    fn terminate(&mut self) -> Result<(), Error> {
        if self.child.try_wait().map_err(io_error)?.is_some() {
            return Ok(());
        }
        match self.child.kill() {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::InvalidInput => {}
            Err(error) => return Err(io_error(error)),
        }
        self.child.wait().map_err(io_error)?;
        Ok(())
    }
}

impl Drop for RuntimeProcess {
    fn drop(&mut self) {
        let _ = self.terminate();
    }
}
""",
        "runtime termination",
    )
    source = source.replace("process.terminate();", "let _ = process.terminate();")
    source = replace_once(
        source,
        """    fn shutdown_after_ack(&self, process: &mut RuntimeProcess) -> Result<(), Error> {
        let deadline = Instant::now() + self.config.shutdown_timeout;
        loop {
            match process.child.try_wait().map_err(io_error)? {
                Some(status) if status.success() => return Ok(()),
                Some(status) => {
                    return Err(driver_error(format!(
                        "local runtime exited unsuccessfully after unload: {status}"
                    )));
                }
                None if Instant::now() >= deadline => {
                    let _ = process.terminate();
                    return Err(driver_error(
                        "local runtime did not exit within the unload deadline",
                    ));
                }
                None => thread::sleep(Duration::from_millis(10)),
            }
        }
    }
""",
        """    fn shutdown_after_ack(&self, process: &mut RuntimeProcess) -> Result<(), Error> {
        let deadline = Instant::now() + self.config.shutdown_timeout;
        loop {
            match process.child.try_wait().map_err(io_error)? {
                Some(_) => return Ok(()),
                None if Instant::now() >= deadline => return process.terminate(),
                None => thread::sleep(Duration::from_millis(10)),
            }
        }
    }
""",
        "shutdown confirmation",
    )
    start = source.index("    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {")
    end = source.index("\n    }\n}\n\nfn indeterminate", start) + len("\n    }")
    unload = r'''    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        let mut process = self
            .processes
            .remove(&handle.opaque_id)
            .ok_or(Error::ModelNotLoaded)?;
        let result = (|| {
            let request = json!({
                "protocol": LOCAL_RUNTIME_PROTOCOL,
                "op": "unload",
                "handle_id": handle.opaque_id,
            });
            write_message(&mut process.stdin, &request)?;
            let response = read_message(&process.stdout, self.config.response_timeout)?;
            require_string(&response, "protocol", LOCAL_RUNTIME_PROTOCOL)?;
            require_string(&response, "op", "unloaded")?;
            require_string(&response, "handle_id", &handle.opaque_id)?;
            self.shutdown_after_ack(&mut process)
        })();
        match result {
            Ok(()) => Ok(()),
            Err(primary) => match process.terminate() {
                Ok(()) => Ok(()),
                Err(cleanup) => {
                    self.processes.insert(handle.opaque_id, process);
                    Err(Error::CleanupPending(format!(
                        "local runtime unload failed ({primary}); forced cleanup failed ({cleanup})"
                    )))
                }
            },
        }
    }'''
    source = source[:start] + unload + source[end:]
    driver_path.write_text(source)
    (ROOT / "codex-rs/hepta-infer-worker-host/src/local_process_driver_tests.rs").write_text(
        git_show("codex-rs/hepta-infer-worker-host/src/local_process_driver_tests.rs")
    )

    lib = ROOT / "codex-rs/hepta-infer-worker-host/src/lib.rs"
    lib_source = lib.read_text()
    if "pub mod local_process_driver;" not in lib_source:
        anchor = "pub mod model_worker;\n"
        lib_source = replace_once(
            lib_source,
            anchor,
            "pub mod local_process_driver;\n" + anchor,
            "local driver export",
        )
    lib.write_text(lib_source)


def main() -> None:
    patch_final_use()
    rewrite_model_worker()
    patch_model_worker_tests()
    patch_lifecycle_tests()
    restore_local_driver()


if __name__ == "__main__":
    main()
