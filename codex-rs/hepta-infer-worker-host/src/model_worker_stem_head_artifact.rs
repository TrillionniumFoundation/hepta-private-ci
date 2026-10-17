//! Signed-CURRENT, selected-CAS read boundary for the *Head weights* of a
//! shared Stem. Projection selection alone cannot authenticate a Cell Head.
//!
//! All candidate bytes are immutable and canonical. This layer has no signer,
//! publisher, final-use authority, executable loader, or production promotion
//! path. The product owner must serialize fresh CURRENT issuance, selection,
//! scope/generation revocation and non-effectful CPU dispatch under its fence.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
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

use super::CpuGatedHead;
use super::CpuGatedHeadDriver;
use super::InferenceWorker;
use super::SelectedStemProjectionReaderV1;
use super::StemCpuHeadBatchUseV1;
use super::StemCpuHeadUseV1;
use super::StemProjectionOwnerFenceV1;
use super::cpu_gated_bundle_weights_digest;

const HEAD_BANK_SCHEMA: &str = "hepta.stem.q24-cpu-head-bank-candidate.v1";
const MAX_HEAD_BANK_SIZE: usize = 32;
const MAX_HEAD_BANK_PAYLOAD_BYTES: usize = 16 * 1024 * 1024;

/// A dual-CAS use has ONE caller-supplied selection time. Mixing independently
/// valid Projection and Head selection checks from different time instants
/// is not acceptable, even when both signatures individually verify.
///
/// This equality check is NOT a trusted clock or proof of CURRENT freshness:
/// the product owner must still acquire both views and perform dispatch inside
/// its separately enforced revocation/generation fence.
fn require_same_selection_time(
    projection_now: u64,
    head_now: u64,
) -> Result<(), StemHeadArtifactError> {
    if projection_now != head_now {
        return Err(StemHeadArtifactError::InvalidBinding);
    }
    Ok(())
}

/// Both independently signed artifacts are registered under ONE artifact
/// registry and must be consumed from the SAME verified CURRENT snapshot.
/// Equal caller-supplied time alone does not prevent mixing a stale projection
/// view with a newer Head view in the presence of revocation.
///
/// Exact receipt, independently pinned trust and witness bindings are required.
/// This does NOT independently prove live CURRENT freshness: the product owner
/// still must serialize discovery and use with its generation/revocation fence.
fn require_same_current_registry_view(
    projection: &VerifiedCurrentRegistryViewV1,
    head: &VerifiedCurrentRegistryViewV1,
) -> Result<(), StemHeadArtifactError> {
    if projection.receipt() != head.receipt()
        || projection.witness_digest() != head.witness_digest()
        || projection.trust_digest() != head.trust_digest()
    {
        return Err(StemHeadArtifactError::InvalidBinding);
    }
    Ok(())
}

#[derive(Debug)]
pub enum StemHeadArtifactError {
    InvalidPayload,
    InvalidBinding,
    StaleOrUnselected,
    ConsumerSealed,
    Selection(String),
    Storage(String),
    Projection(super::StemProjectionArtifactError),
}
impl fmt::Display for StemHeadArtifactError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for StemHeadArtifactError {}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HeadBankPayloadV1 {
    schema: String,
    encoder_digest: String,
    heads: Vec<CpuGatedHead>,
    weights_digest: String,
}

/// Canonical, versioned CAS payload for a bounded immutable Head bank.
///
/// This creates bytes only; callers must separately publish them via the real
/// Artifact CAS and gain a separately signed selection from the Selector.
pub fn encode_cpu_head_bank_candidate_v1(
    encoder_digest: &str,
    heads: &[CpuGatedHead],
) -> Result<Vec<u8>, StemHeadArtifactError> {
    if heads.is_empty() || heads.len() > MAX_HEAD_BANK_SIZE {
        return Err(StemHeadArtifactError::InvalidPayload);
    }
    let weights_digest = cpu_gated_bundle_weights_digest(encoder_digest, heads)
        .map_err(|_| StemHeadArtifactError::InvalidPayload)?;
    let mut previous: Option<String> = None;
    let mut values = Vec::with_capacity(heads.len());
    for head in heads {
        let head_digest = head
            .digest()
            .map_err(|_| StemHeadArtifactError::InvalidPayload)?;
        if previous
            .as_ref()
            .is_some_and(|before| before >= &head_digest)
        {
            return Err(StemHeadArtifactError::InvalidPayload);
        }
        previous = Some(head_digest);
        let mut row = BTreeMap::new();
        row.insert("input_width", serde_json::json!(head.input_width));
        row.insert("output_width", serde_json::json!(head.output_width));
        row.insert(
            "drive_weights_q24",
            serde_json::json!(head.drive_weights_q24),
        );
        row.insert(
            "prediction_weights_q24",
            serde_json::json!(head.prediction_weights_q24),
        );
        row.insert("gate_weights_q24", serde_json::json!(head.gate_weights_q24));
        row.insert("drive_bias_q24", serde_json::json!(head.drive_bias_q24));
        row.insert(
            "prediction_bias_q24",
            serde_json::json!(head.prediction_bias_q24),
        );
        row.insert("gate_bias_q24", serde_json::json!(head.gate_bias_q24));
        values.push(row);
    }
    let mut payload = BTreeMap::new();
    payload.insert("encoder_digest", serde_json::json!(encoder_digest));
    payload.insert("heads", serde_json::json!(values));
    payload.insert("schema", serde_json::json!(HEAD_BANK_SCHEMA));
    payload.insert("weights_digest", serde_json::json!(weights_digest));
    let mut encoded =
        serde_json::to_vec(&payload).map_err(|_| StemHeadArtifactError::InvalidPayload)?;
    encoded.push(b'\n');
    if encoded.len() > MAX_HEAD_BANK_PAYLOAD_BYTES {
        return Err(StemHeadArtifactError::InvalidPayload);
    }
    Ok(encoded)
}

fn decode_cpu_head_bank(bytes: &[u8]) -> Result<HeadBankPayloadV1, StemHeadArtifactError> {
    if bytes.is_empty() || bytes.len() > MAX_HEAD_BANK_PAYLOAD_BYTES {
        return Err(StemHeadArtifactError::InvalidPayload);
    }
    let candidate: HeadBankPayloadV1 =
        serde_json::from_slice(bytes).map_err(|_| StemHeadArtifactError::InvalidPayload)?;
    if candidate.schema != HEAD_BANK_SCHEMA
        || candidate.weights_digest
            != cpu_gated_bundle_weights_digest(&candidate.encoder_digest, &candidate.heads)
                .map_err(|_| StemHeadArtifactError::InvalidPayload)?
        || encode_cpu_head_bank_candidate_v1(&candidate.encoder_digest, &candidate.heads)?
            .as_slice()
            != bytes
    {
        return Err(StemHeadArtifactError::InvalidPayload);
    }
    Ok(candidate)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StemHeadBankReadObservationV1 {
    pub artifact_id: StableId,
    pub selection_digest: Digest32,
    pub current_witness_digest: Digest32,
    pub current_trust_digest: Digest32,
    pub bank_weights_digest: String,
    pub production_authorized: bool,
}

/// A selected and CURRENT-verified bank of immutable Q24 Cell Heads.
///
/// The bank does not mint an inference request/grant and is never sufficient
/// to authorize a production route or claim shared Encoder execution.
#[derive(Debug)]
pub struct SelectedStemHeadBankReaderV1 {
    candidate: RevalidatingCandidate,
    artifact_id: StableId,
    selected_digest: Digest32,
    encoder_digest: String,
    weights_digest: String,
    head_digests: BTreeSet<String>,
    fence: StemProjectionOwnerFenceV1,
    sealed: bool,
}

impl SelectedStemHeadBankReaderV1 {
    pub fn load(
        snapshot_file: File,
        payload_file: File,
        selected: VerifiedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        expected_encoder_digest: &str,
        expected_weights_digest: &str,
        fence: StemProjectionOwnerFenceV1,
    ) -> Result<Self, StemHeadArtifactError> {
        if fence.scope_digest.is_zero()
            || fence.worker_generation == 0
            || fence.revocation_frontier_digest.is_zero()
        {
            return Err(StemHeadArtifactError::InvalidBinding);
        }
        let selected_digest = selected.selection_digest();
        let mut candidate = load_selected_candidate(snapshot_file, payload_file, selected)
            .map_err(|error| StemHeadArtifactError::Storage(error.to_string()))?;
        if candidate.spec().manifest.kind != ArtifactKind::Parameters
            || candidate.spec().manifest.compatibility_digest.to_string() != expected_weights_digest
        {
            return Err(StemHeadArtifactError::InvalidBinding);
        }
        let artifact_id = candidate.spec().manifest.artifact_id.clone();
        let bank = candidate
            .with_current(current, decode_cpu_head_bank)
            .map_err(|error| StemHeadArtifactError::Storage(error.to_string()))??;
        if bank.encoder_digest != expected_encoder_digest
            || bank.weights_digest != expected_weights_digest
        {
            return Err(StemHeadArtifactError::InvalidBinding);
        }
        let head_digests = bank
            .heads
            .iter()
            .map(|head| {
                head.digest()
                    .map_err(|_| StemHeadArtifactError::InvalidPayload)
            })
            .collect::<Result<BTreeSet<_>, _>>()?;
        if head_digests.len() != bank.heads.len() {
            return Err(StemHeadArtifactError::InvalidPayload);
        }
        Ok(Self {
            candidate,
            artifact_id,
            selected_digest,
            encoder_digest: bank.encoder_digest,
            weights_digest: bank.weights_digest,
            head_digests,
            fence,
            sealed: false,
        })
    }

    /// Seal permanently after any rejected use or revocation. Recovery must
    /// reload exact, independently selected CAS bytes with fresh CURRENT.
    pub fn invalidate(&mut self) {
        self.sealed = true;
    }

    pub fn is_sealed(&self) -> bool {
        self.sealed
    }

    /// BOTH Projection and Head banks must remain independently selected and
    /// currently eligible at the same owner-controlled dispatch boundary.
    /// A signature on either bank alone is insufficient.
    #[allow(clippy::too_many_arguments)]
    pub fn run_selected_cpu_head(
        &mut self,
        projection: &mut SelectedStemProjectionReaderV1,
        worker: &mut InferenceWorker<CpuGatedHeadDriver>,
        use_request: StemCpuHeadUseV1<'_>,
        head_selector: &ArtifactSelectionVerifierV1,
        signed_head_selection: &SignedArtifactSelectionV1,
        head_current: VerifiedCurrentRegistryViewV1,
        selection_now: u64,
    ) -> Result<
        (
            codex_hepta_infer_core::NeuronFeatureReceiptV1,
            StemHeadBankReadObservationV1,
        ),
        StemHeadArtifactError,
    > {
        if self.sealed {
            return Err(StemHeadArtifactError::ConsumerSealed);
        }
        let result = self.run_checked(
            projection,
            worker,
            use_request,
            head_selector,
            signed_head_selection,
            head_current,
            selection_now,
        );
        if result.is_err() {
            self.sealed = true;
        }
        result
    }

    #[allow(clippy::too_many_arguments)]
    fn run_checked(
        &mut self,
        projection: &mut SelectedStemProjectionReaderV1,
        worker: &mut InferenceWorker<CpuGatedHeadDriver>,
        use_request: StemCpuHeadUseV1<'_>,
        head_selector: &ArtifactSelectionVerifierV1,
        signed_head_selection: &SignedArtifactSelectionV1,
        head_current: VerifiedCurrentRegistryViewV1,
        selection_now: u64,
    ) -> Result<
        (
            codex_hepta_infer_core::NeuronFeatureReceiptV1,
            StemHeadBankReadObservationV1,
        ),
        StemHeadArtifactError,
    > {
        require_same_selection_time(use_request.selection_now, selection_now)?;
        require_same_current_registry_view(&use_request.current, &head_current)?;
        let request = &use_request.request;
        let binding = use_request.binding;
        if binding.scope_digest != self.fence.scope_digest.to_string()
            || binding.generation != self.fence.worker_generation
            || binding.revocation_frontier_digest
                != self.fence.revocation_frontier_digest.to_string()
            || request.encoder_digest != self.encoder_digest
            || binding.encoder_digest != self.encoder_digest
            || request.weights_digest != self.weights_digest
            || !self.head_digests.contains(&request.head_digest)
        {
            return Err(StemHeadArtifactError::InvalidBinding);
        }
        let verified = head_selector
            .verify(signed_head_selection, &head_current, selection_now)
            .map_err(|e| StemHeadArtifactError::Selection(e.to_string()))?;
        if verified.selection_digest() != self.selected_digest
            || verified.artifact_id() != &self.artifact_id
        {
            return Err(StemHeadArtifactError::StaleOrUnselected);
        }
        let witness = head_current.witness_digest();
        let trust = head_current.trust_digest();
        let receipt = self
            .candidate
            .with_current(head_current, |_| {
                projection
                    .run_selected_cpu_head(worker, use_request)
                    .map_err(StemHeadArtifactError::Projection)
            })
            .map_err(|e| StemHeadArtifactError::Storage(e.to_string()))??;
        // Emit provenance only AFTER both signed CURRENT checks and the
        // model-only dispatch actually succeeded. Never make an observation
        // from an arbitrary retained/current-like view.
        Ok((
            receipt,
            StemHeadBankReadObservationV1 {
                artifact_id: self.artifact_id.clone(),
                selection_digest: self.selected_digest,
                current_witness_digest: witness,
                current_trust_digest: trust,
                bank_weights_digest: self.weights_digest.clone(),
                production_authorized: false,
            },
        ))
    }

    /// Admit only an exact 2..32-member, same-fence batch from BOTH selected
    /// CAS artifacts. Uses ONE native CPU Head batch driver invocation and
    /// returns non-authoritative per-Cell typed receipts.
    #[allow(clippy::too_many_arguments)]
    pub fn run_selected_cpu_head_backend_batch(
        &mut self,
        projection: &mut SelectedStemProjectionReaderV1,
        worker: &mut InferenceWorker<CpuGatedHeadDriver>,
        use_request: StemCpuHeadBatchUseV1<'_>,
        head_selector: &ArtifactSelectionVerifierV1,
        signed_head_selection: &SignedArtifactSelectionV1,
        head_current: VerifiedCurrentRegistryViewV1,
        selection_now: u64,
    ) -> Result<
        (
            super::NeuronBackendBatchReceipt,
            StemHeadBankReadObservationV1,
        ),
        StemHeadArtifactError,
    > {
        if self.sealed {
            return Err(StemHeadArtifactError::ConsumerSealed);
        }
        let result = self.run_backend_batch_checked(
            projection,
            worker,
            use_request,
            head_selector,
            signed_head_selection,
            head_current,
            selection_now,
        );
        if result.is_err() {
            self.sealed = true;
        }
        result
    }

    #[allow(clippy::too_many_arguments)]
    fn run_backend_batch_checked(
        &mut self,
        projection: &mut SelectedStemProjectionReaderV1,
        worker: &mut InferenceWorker<CpuGatedHeadDriver>,
        use_request: StemCpuHeadBatchUseV1<'_>,
        head_selector: &ArtifactSelectionVerifierV1,
        signed_head_selection: &SignedArtifactSelectionV1,
        head_current: VerifiedCurrentRegistryViewV1,
        selection_now: u64,
    ) -> Result<
        (
            super::NeuronBackendBatchReceipt,
            StemHeadBankReadObservationV1,
        ),
        StemHeadArtifactError,
    > {
        require_same_selection_time(use_request.selection_now, selection_now)?;
        require_same_current_registry_view(&use_request.current, &head_current)?;
        if !(2..=32).contains(&use_request.items.len()) {
            return Err(StemHeadArtifactError::InvalidBinding);
        }
        for member in &use_request.items {
            let binding = member.binding;
            let request = &member.request;
            if binding.scope_digest != self.fence.scope_digest.to_string()
                || binding.generation != self.fence.worker_generation
                || binding.revocation_frontier_digest
                    != self.fence.revocation_frontier_digest.to_string()
                || request.encoder_digest != self.encoder_digest
                || binding.encoder_digest != self.encoder_digest
                || request.weights_digest != self.weights_digest
                || !self.head_digests.contains(&request.head_digest)
            {
                return Err(StemHeadArtifactError::InvalidBinding);
            }
        }
        let verified = head_selector
            .verify(signed_head_selection, &head_current, selection_now)
            .map_err(|error| StemHeadArtifactError::Selection(error.to_string()))?;
        if verified.selection_digest() != self.selected_digest
            || verified.artifact_id() != &self.artifact_id
        {
            return Err(StemHeadArtifactError::StaleOrUnselected);
        }
        let witness = head_current.witness_digest();
        let trust = head_current.trust_digest();
        let receipt = self
            .candidate
            .with_current(head_current, |_| {
                projection
                    .run_selected_cpu_head_backend_batch(worker, use_request)
                    .map_err(StemHeadArtifactError::Projection)
            })
            .map_err(|error| StemHeadArtifactError::Storage(error.to_string()))??;
        Ok((
            receipt,
            StemHeadBankReadObservationV1 {
                artifact_id: self.artifact_id.clone(),
                selection_digest: self.selected_digest,
                current_witness_digest: witness,
                current_trust_digest: trust,
                bank_weights_digest: self.weights_digest.clone(),
                production_authorized: false,
            },
        ))
    }
}

#[cfg(test)]
#[path = "model_worker_stem_head_artifact_tests.rs"]
mod tests;
