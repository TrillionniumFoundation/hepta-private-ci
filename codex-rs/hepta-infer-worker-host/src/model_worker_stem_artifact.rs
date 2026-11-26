//! Selected, CAS-backed Stem projection read boundary.
//!
//! This binds the existing learning-artifact owner and independent selector to
//! a frozen numeric projection. It cannot sign a load receipt, issue a grant,
//! select another artifact or authorize production use. CURRENT must be
//! authenticated independently before EVERY use; a failure seals this reader.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::VerifiedArtifactSelectionV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::load_selected_candidate;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::Error;
use super::stem_projection::LowRankStemProjectionV1;
use super::stem_projection::ProjectedStemFeatureV1;
use super::stem_projection::StemProjectionBindingV1;
use super::stem_projection::project_bound_f32;
use super::stem_projection::verify_neuron_projected_request;

const MAX_STEM_PROJECTION_JSON_BYTES: usize = 8 * 1024 * 1024;
const STEM_PROJECTION_SCHEMA: &str = "hepta.stem.low-rank-projection-payload.v1";

/// Pinned runtime context. Independent from artifact registry generation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StemProjectionOwnerFenceV1 {
    pub scope_digest: Digest32,
    pub worker_generation: u64,
    pub revocation_frontier_digest: Digest32,
}

#[derive(Debug)]
pub enum StemProjectionArtifactError {
    InvalidBinding,
    InvalidPayload,
    StaleOrUnselected,
    ConsumerSealed,
    Selection(String),
    Storage(String),
    Numeric(Error),
}

impl fmt::Display for StemProjectionArtifactError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for StemProjectionArtifactError {}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProjectionPayloadV1 {
    schema: String,
    projection: LowRankStemProjectionV1,
}

/// Exactly matches the Python `encode_cas_projection_candidate` JSON:
/// sorted ASCII keys, compact separators, integers and ONE final newline.
/// Payload bytes are not a signature, signed selection, or CURRENT witness.
fn canonical_projection_payload(
    projection: &LowRankStemProjectionV1,
) -> Result<Vec<u8>, StemProjectionArtifactError> {
    projection
        .validate()
        .map_err(|_| StemProjectionArtifactError::InvalidPayload)?;
    let mut fields = std::collections::BTreeMap::new();
    fields.insert("a_q24", serde_json::json!(&projection.a_q24));
    fields.insert("b_q24", serde_json::json!(&projection.b_q24));
    fields.insert("bias_q24", serde_json::json!(&projection.bias_q24));
    fields.insert(
        "encoder_digest",
        serde_json::json!(&projection.encoder_digest),
    );
    fields.insert("input_width", serde_json::json!(projection.input_width));
    fields.insert(
        "normalizer_digest",
        serde_json::json!(&projection.normalizer_digest),
    );
    fields.insert("output_width", serde_json::json!(projection.output_width));
    fields.insert(
        "preprocessor_digest",
        serde_json::json!(&projection.preprocessor_digest),
    );
    fields.insert("rank", serde_json::json!(projection.rank));
    fields.insert(
        "representation",
        serde_json::json!(&projection.representation),
    );
    fields.insert(
        "runtime_digest",
        serde_json::json!(&projection.runtime_digest),
    );
    let mut payload = std::collections::BTreeMap::new();
    payload.insert("projection", serde_json::json!(fields));
    payload.insert("schema", serde_json::json!(STEM_PROJECTION_SCHEMA));
    let mut bytes =
        serde_json::to_vec(&payload).map_err(|_| StemProjectionArtifactError::InvalidPayload)?;
    bytes.push(b'\n');
    if bytes.len() > MAX_STEM_PROJECTION_JSON_BYTES {
        return Err(StemProjectionArtifactError::InvalidPayload);
    }
    Ok(bytes)
}

fn decode_projection(bytes: &[u8]) -> Result<LowRankStemProjectionV1, StemProjectionArtifactError> {
    if bytes.is_empty() || bytes.len() > MAX_STEM_PROJECTION_JSON_BYTES {
        return Err(StemProjectionArtifactError::InvalidPayload);
    }
    let value: ProjectionPayloadV1 =
        serde_json::from_slice(bytes).map_err(|_| StemProjectionArtifactError::InvalidPayload)?;
    if value.schema != STEM_PROJECTION_SCHEMA
        || canonical_projection_payload(&value.projection)?.as_slice() != bytes
    {
        return Err(StemProjectionArtifactError::InvalidPayload);
    }
    Ok(value.projection)
}

/// A diagnostic only. Signed selection and CURRENT remain separately owned;
/// this digest-only observation is never a trusted execution/load signature.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StemProjectionReadObservationV1 {
    pub artifact_id: StableId,
    pub selection_digest: Digest32,
    pub current_witness_digest: Digest32,
    pub current_trust_digest: Digest32,
    pub artifact_content_digest: Digest32,
    pub projection_digest: Digest32,
    pub projected_input_digest: Digest32,
    pub production_authorized: bool,
}

/// One model-only, read-only dispatch over a previously projected and
/// pre-authorized Q24 request. All identity and authority inputs are supplied
/// by independent product owners: this type manufactures none of them.
#[derive(Debug)]
pub struct StemCpuHeadUseV1<'a> {
    pub selector: &'a ArtifactSelectionVerifierV1,
    pub signed_selection: &'a SignedArtifactSelectionV1,
    pub current: VerifiedCurrentRegistryViewV1,
    pub selection_now: u64,
    pub binding: &'a StemProjectionBindingV1,
    /// The actual full-width frozen Encoder feature, NOT a caller-supplied
    /// projected feature reference. The source Encoder receipt remains an
    /// independent, still-required production authority boundary.
    pub source_features: &'a [f32],
    pub token_count: u64,
    pub request: super::NeuronFeatureRequest,
    pub worker_now_ms: u64,
    pub model_id: &'a str,
}

/// One already-admitted Cell request whose output must be recomputed from
/// the selected immutable projection inside a fresh signed CURRENT guard.
#[derive(Debug)]
pub struct StemCpuHeadBatchItemV1<'a> {
    pub binding: &'a StemProjectionBindingV1,
    pub source_features: &'a [f32],
    pub token_count: u64,
    pub request: super::NeuronFeatureRequest,
}

/// A single same-scope/generation batch admitted by the owning inference
/// control. The artifact reader cannot manufacture a lease or production grant.
pub struct StemCpuHeadBatchUseV1<'a> {
    pub selector: &'a ArtifactSelectionVerifierV1,
    pub signed_selection: &'a SignedArtifactSelectionV1,
    pub current: VerifiedCurrentRegistryViewV1,
    pub selection_now: u64,
    pub items: Vec<StemCpuHeadBatchItemV1<'a>>,
    pub worker_now_ms: u64,
    pub model_id: &'a str,
}

#[derive(Debug)]
pub struct SelectedStemProjectionReaderV1 {
    candidate: RevalidatingCandidate,
    artifact_id: StableId,
    artifact_content_digest: Digest32,
    selected_digest: Digest32,
    projection: LowRankStemProjectionV1,
    projection_digest: Digest32,
    fence: StemProjectionOwnerFenceV1,
    sealed: bool,
}

impl SelectedStemProjectionReaderV1 {
    /// Load only with an opaque independent selection token. The host provides
    /// separately authenticated CURRENT and already opened trusted File handles.
    /// No file path, registry write or signer key is accepted at this boundary.
    pub fn load(
        snapshot_file: File,
        payload_file: File,
        selection: VerifiedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        expected_projection_digest: Digest32,
        fence: StemProjectionOwnerFenceV1,
    ) -> Result<Self, StemProjectionArtifactError> {
        if fence.scope_digest.is_zero()
            || fence.worker_generation == 0
            || fence.revocation_frontier_digest.is_zero()
            || expected_projection_digest.is_zero()
        {
            return Err(StemProjectionArtifactError::InvalidBinding);
        }
        let selection_digest = selection.selection_digest();
        let mut candidate = load_selected_candidate(snapshot_file, payload_file, selection)
            .map_err(|error| StemProjectionArtifactError::Storage(error.to_string()))?;
        if candidate.spec().manifest.kind != ArtifactKind::Parameters {
            return Err(StemProjectionArtifactError::InvalidBinding);
        }
        let content_digest = candidate.spec().manifest.content_digest;
        let compatibility_digest = candidate.spec().manifest.compatibility_digest;
        let artifact_id = candidate.spec().manifest.artifact_id.clone();
        let projection = candidate
            .with_current(current, decode_projection)
            .map_err(|error| StemProjectionArtifactError::Storage(error.to_string()))??;
        let projection_digest = projection
            .digest()
            .map_err(StemProjectionArtifactError::Numeric)?;
        if projection_digest != expected_projection_digest
            || compatibility_digest != expected_projection_digest
        {
            return Err(StemProjectionArtifactError::InvalidBinding);
        }
        Ok(Self {
            candidate,
            artifact_id,
            artifact_content_digest: content_digest,
            selected_digest: selection_digest,
            projection,
            projection_digest,
            fence,
            sealed: false,
        })
    }

    /// Permanently closes this reader; recovery requires an independently
    /// selected, reloaded artifact and a fresh authenticated CURRENT.
    pub fn invalidate(&mut self) {
        self.sealed = true;
    }

    /// Re-check a fresh signed selection, CURRENT and all runtime fences.
    /// Caller must separately authenticate source Encoder execution and obtain
    /// a pre-existing inference reservation/lease for the exact projected Q24.
    #[allow(clippy::too_many_arguments)]
    pub fn project_with_current(
        &mut self,
        selector: &ArtifactSelectionVerifierV1,
        signed_selection: &SignedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        binding: &StemProjectionBindingV1,
        features: &[f32],
        token_count: u64,
    ) -> Result<
        (ProjectedStemFeatureV1, StemProjectionReadObservationV1),
        StemProjectionArtifactError,
    > {
        if self.sealed {
            return Err(StemProjectionArtifactError::ConsumerSealed);
        }
        let result = self.project_checked(
            selector,
            signed_selection,
            current,
            now,
            binding,
            features,
            token_count,
        );
        if result.is_err() {
            self.sealed = true;
        }
        result
    }

    #[allow(clippy::too_many_arguments)]
    fn project_checked(
        &mut self,
        selector: &ArtifactSelectionVerifierV1,
        signed_selection: &SignedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        binding: &StemProjectionBindingV1,
        features: &[f32],
        token_count: u64,
    ) -> Result<
        (ProjectedStemFeatureV1, StemProjectionReadObservationV1),
        StemProjectionArtifactError,
    > {
        if binding.scope_digest != self.fence.scope_digest.to_string()
            || binding.generation != self.fence.worker_generation
            || binding.revocation_frontier_digest
                != self.fence.revocation_frontier_digest.to_string()
            || binding.encoder_digest != self.projection.encoder_digest
            || binding.preprocessor_digest != self.projection.preprocessor_digest
            || binding.runtime_digest != self.projection.runtime_digest
        {
            return Err(StemProjectionArtifactError::InvalidBinding);
        }
        let verified = selector
            .verify(signed_selection, &current, now)
            .map_err(|error| StemProjectionArtifactError::Selection(error.to_string()))?;
        if verified.selection_digest() != self.selected_digest
            || verified.artifact_id() != &self.artifact_id
        {
            return Err(StemProjectionArtifactError::StaleOrUnselected);
        }
        let witness = current.witness_digest();
        let trust = current.trust_digest();
        let projected = self
            .candidate
            .with_current(current, |_payload| {
                project_bound_f32(&self.projection, binding, features, token_count)
            })
            .map_err(|error| StemProjectionArtifactError::Storage(error.to_string()))?
            .map_err(StemProjectionArtifactError::Numeric)?;

        let observation = StemProjectionReadObservationV1 {
            artifact_id: self.artifact_id.clone(),
            selection_digest: self.selected_digest,
            current_witness_digest: witness,
            current_trust_digest: trust,
            artifact_content_digest: self.artifact_content_digest,
            projection_digest: self.projection_digest,
            projected_input_digest: projected.projected_input_digest,
            production_authorized: false,
        };
        Ok((projected, observation))
    }

    /// Check one already-admitted Worker request with a NEW authenticated
    /// CURRENT view and independently signed exact artifact selection.
    ///
    /// A retained `ProjectedStemFeatureV1` is public data, not a durable
    /// capability: it must not be replayed after the projection was revoked.
    /// Unlike the old check, this entrypoint cannot succeed on cached
    /// provenance and a static generation fence alone.
    ///
    /// The owner still MUST acquire CURRENT from its trusted source and
    /// serialize that acquisition with native inference dispatch. Merely
    /// passing a previously retained `VerifiedCurrentRegistryViewV1`
    /// cannot prove that no newer revocation was published.
    #[cfg(test)]
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn check_worker_request(
        &mut self,
        selector: &ArtifactSelectionVerifierV1,
        signed_selection: &SignedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        binding: &StemProjectionBindingV1,
        projected: &ProjectedStemFeatureV1,
        request: &super::NeuronFeatureRequest,
    ) -> Result<(), StemProjectionArtifactError> {
        if self.sealed {
            return Err(StemProjectionArtifactError::ConsumerSealed);
        }
        let result = self.check_worker_request_current(
            selector,
            signed_selection,
            current,
            now,
            binding,
            projected,
            request,
        );
        if result.is_err() {
            self.sealed = true;
        }
        result
    }

    #[cfg(test)]
    #[allow(clippy::too_many_arguments)]
    fn check_worker_request_current(
        &mut self,
        selector: &ArtifactSelectionVerifierV1,
        signed_selection: &SignedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        now: u64,
        binding: &StemProjectionBindingV1,
        projected: &ProjectedStemFeatureV1,
        request: &super::NeuronFeatureRequest,
    ) -> Result<(), StemProjectionArtifactError> {
        self.verify_worker_static_binding(binding, projected)?;
        let verified = selector
            .verify(signed_selection, &current, now)
            .map_err(|error| StemProjectionArtifactError::Selection(error.to_string()))?;
        if verified.selection_digest() != self.selected_digest
            || verified.artifact_id() != &self.artifact_id
        {
            return Err(StemProjectionArtifactError::StaleOrUnselected);
        }
        let generation = self.fence.worker_generation;
        self.candidate
            .with_current(current, |_payload| {
                verify_neuron_projected_request(binding, projected, request, generation)
            })
            .map_err(|error| StemProjectionArtifactError::Storage(error.to_string()))?
            .map_err(StemProjectionArtifactError::Numeric)
    }

    /// Execute ONLY the installed local Q24 CPU Head while the selected CAS
    /// payload is under an authenticated CURRENT revalidation.
    ///
    /// The worker consumes a pre-existing grant/reservation/lease and returns
    /// a non-authoritative typed receipt. This method cannot dispatch tools or
    /// run a generic provider. The *production* owner must still serialize
    /// CURRENT publication, revocation and this dispatch under its own fence;
    /// a stored CURRENT object is not proof of absolute present-time freshness.
    pub(crate) fn run_selected_cpu_head(
        &mut self,
        worker: &mut super::InferenceWorker<super::CpuGatedHeadDriver>,
        use_request: StemCpuHeadUseV1<'_>,
    ) -> Result<codex_hepta_infer_core::NeuronFeatureReceiptV1, StemProjectionArtifactError> {
        if self.sealed {
            return Err(StemProjectionArtifactError::ConsumerSealed);
        }
        let result = self.run_selected_cpu_head_checked(worker, use_request);
        if result.is_err() {
            self.sealed = true;
        }
        result
    }

    fn run_selected_cpu_head_checked(
        &mut self,
        worker: &mut super::InferenceWorker<super::CpuGatedHeadDriver>,
        use_request: StemCpuHeadUseV1<'_>,
    ) -> Result<codex_hepta_infer_core::NeuronFeatureReceiptV1, StemProjectionArtifactError> {
        let StemCpuHeadUseV1 {
            selector,
            signed_selection,
            current,
            selection_now,
            binding,
            source_features,
            token_count,
            request,
            worker_now_ms,
            model_id,
        } = use_request;
        if worker.generation != self.fence.worker_generation {
            return Err(StemProjectionArtifactError::InvalidBinding);
        }
        self.verify_source_binding(binding)?;
        let verified = selector
            .verify(signed_selection, &current, selection_now)
            .map_err(|error| StemProjectionArtifactError::Selection(error.to_string()))?;
        if verified.selection_digest() != self.selected_digest
            || verified.artifact_id() != &self.artifact_id
        {
            return Err(StemProjectionArtifactError::StaleOrUnselected);
        }
        let generation = self.fence.worker_generation;
        let projection = &self.projection;
        self.candidate
            .with_current(current, |_payload| {
                // Never admit a caller-constructed Q24 feature vector under a
                // trusted projection ID. Recompute the selected CAS matrix
                // inside CURRENT and compare its exact input/output binding.
                let projected =
                    project_bound_f32(projection, binding, source_features, token_count)
                        .map_err(StemProjectionArtifactError::Numeric)?;
                verify_neuron_projected_request(binding, &projected, &request, generation)
                    .map_err(StemProjectionArtifactError::Numeric)?;
                worker
                    .run_neuron_features_receipt(worker_now_ms, model_id, request)
                    .map_err(StemProjectionArtifactError::Numeric)
            })
            .map_err(|error| StemProjectionArtifactError::Storage(error.to_string()))?
    }

    /// A single backend batch over exact Q24 projections derived *inside*
    /// the selected immutable CAS candidate's CURRENT guard. The shared text
    /// Encoder is NOT executed here and no production authority is granted.
    pub(crate) fn run_selected_cpu_head_backend_batch(
        &mut self,
        worker: &mut super::InferenceWorker<super::CpuGatedHeadDriver>,
        use_request: StemCpuHeadBatchUseV1<'_>,
    ) -> Result<super::NeuronBackendBatchReceipt, StemProjectionArtifactError> {
        if self.sealed {
            return Err(StemProjectionArtifactError::ConsumerSealed);
        }
        let result = self.run_selected_cpu_head_backend_batch_checked(worker, use_request);
        if result.is_err() {
            self.sealed = true;
        }
        result
    }

    fn run_selected_cpu_head_backend_batch_checked(
        &mut self,
        worker: &mut super::InferenceWorker<super::CpuGatedHeadDriver>,
        use_request: StemCpuHeadBatchUseV1<'_>,
    ) -> Result<super::NeuronBackendBatchReceipt, StemProjectionArtifactError> {
        let StemCpuHeadBatchUseV1 {
            selector,
            signed_selection,
            current,
            selection_now,
            items,
            worker_now_ms,
            model_id,
        } = use_request;
        if !(2..=32).contains(&items.len()) || worker.generation != self.fence.worker_generation {
            return Err(StemProjectionArtifactError::InvalidBinding);
        }
        for member in &items {
            self.verify_source_binding(member.binding)?;
        }
        let verified = selector
            .verify(signed_selection, &current, selection_now)
            .map_err(|error| StemProjectionArtifactError::Selection(error.to_string()))?;
        if verified.selection_digest() != self.selected_digest
            || verified.artifact_id() != &self.artifact_id
        {
            return Err(StemProjectionArtifactError::StaleOrUnselected);
        }
        let generation = self.fence.worker_generation;
        let projection = &self.projection;
        self.candidate
            .with_current(current, |_payload| {
                // If ANY member fails source verification, no Head backend
                // invocation occurs. No Q24 vectors supplied by callers are
                // accepted in place of the selected projection computation.
                let mut requests = Vec::with_capacity(items.len());
                for member in items {
                    let projected = project_bound_f32(
                        projection,
                        member.binding,
                        member.source_features,
                        member.token_count,
                    )
                    .map_err(StemProjectionArtifactError::Numeric)?;
                    verify_neuron_projected_request(
                        member.binding,
                        &projected,
                        &member.request,
                        generation,
                    )
                    .map_err(StemProjectionArtifactError::Numeric)?;
                    requests.push(member.request);
                }
                worker
                    .run_neuron_features_backend_batch(worker_now_ms, model_id, requests)
                    .map_err(StemProjectionArtifactError::Numeric)
            })
            .map_err(|error| StemProjectionArtifactError::Storage(error.to_string()))?
    }

    fn verify_worker_static_binding(
        &self,
        binding: &StemProjectionBindingV1,
        projected: &ProjectedStemFeatureV1,
    ) -> Result<(), StemProjectionArtifactError> {
        self.verify_source_binding(binding)?;
        if projected.projection_digest != self.projection_digest {
            return Err(StemProjectionArtifactError::InvalidBinding);
        }
        Ok(())
    }

    fn verify_source_binding(
        &self,
        binding: &StemProjectionBindingV1,
    ) -> Result<(), StemProjectionArtifactError> {
        if binding.scope_digest != self.fence.scope_digest.to_string()
            || binding.generation != self.fence.worker_generation
            || binding.revocation_frontier_digest
                != self.fence.revocation_frontier_digest.to_string()
            || binding.encoder_digest != self.projection.encoder_digest
            || binding.preprocessor_digest != self.projection.preprocessor_digest
            || binding.runtime_digest != self.projection.runtime_digest
        {
            return Err(StemProjectionArtifactError::InvalidBinding);
        }
        Ok(())
    }

    pub fn is_sealed(&self) -> bool {
        self.sealed
    }
}

#[cfg(test)]
#[path = "model_worker_stem_artifact_tests.rs"]
mod tests;
