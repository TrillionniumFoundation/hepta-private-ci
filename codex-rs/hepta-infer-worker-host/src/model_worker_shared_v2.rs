//! Non-authorizing zero-copy feature-reference batch contract for Neuron Cells.
//!
//! This keeps the V1 byte-carrying ABI unchanged. All features are shared as
//! immutable Arc snapshots within the worker, and the physical driver operates
//! on their borrowed Q24 slices. Only owner-verified, source-approved data may
//! enter this seam; this API does not verify grants/signatures or issue authority.

use std::collections::BTreeSet;
use std::sync::Arc;

use codex_hepta_infer_core::shared_feature_v2::ImmutableFeatureSnapshotV2;
use codex_hepta_infer_core::shared_feature_v2::feature_content_digest_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::NonAuthorizingPosture;
use codex_hepta_types::StableId;

use super::DriverModelHandle;
use super::DriverNeuronFeatureObservation;
use super::Error;
use super::ExecutionStatus;
use super::InferenceWorker;
use super::MAX_ACTIVE_REQUESTS;
use super::MAX_NEURON_FEATURES;
use super::ModelDriver;
use super::NeuronFeatureBatchItemObservationV2;
use super::WorkerRequest;
use super::validate_digest;
use super::validate_identity;
use super::validate_request;

const MAX_BATCH_ITEMS_V2: usize = 32;
const MAX_FEATURE_ABS_Q24: i64 = 8 * (1_i64 << 24);

/// One admitted Cell use of an already frozen semantic/numeric feature.
/// Cell and principal are distinct; no two Cells share mutable state.
#[derive(Clone, Debug)]
pub struct SharedNeuronFeatureRequestV2 {
    pub authorization: WorkerRequest,
    pub principal_id: StableId,
    pub purpose_id: StableId,
    pub cell_id: StableId,
    pub snapshot: Arc<ImmutableFeatureSnapshotV2>,
    pub head_digest: String,
    pub weights_digest: String,
    pub expected_output_width: usize,
}

/// Reference-only, non-authorizing execution result; hashes are provenance,
/// NOT signatures and NOT a claim that final-use authority was issued.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedNeuronFeatureResultV2 {
    pub request_id: String,
    pub reservation_id: String,
    pub cell_id: StableId,
    pub principal_id: StableId,
    pub purpose_id: StableId,
    pub feature_identity_digest: Digest32,
    pub feature_content_digest: Digest32,
    pub head_digest: String,
    pub worker_generation: u64,
    pub status: ExecutionStatus,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub observed_memory_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub queue_age_micros: u64,
    pub latency_micros: u64,
    pub observation_digest: Digest32,
    pub authority: NonAuthorizingPosture,
}

/// A real backend has to implement this separately from the V1 Vec API.
/// CPU GatedHead reference implements it with scalar kernels, not a GPU GEMM.
pub(crate) trait NeuronSharedFeatureBatchDriverV2: ModelDriver {
    fn run_shared_neuron_features_batch_v2(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[SharedNeuronFeatureRequestV2],
    ) -> Result<Vec<NeuronFeatureBatchItemObservationV2>, Error>;
}

/// Complete request/payload digest; the feature bytes themselves are
/// represented by their independently validated content digest.
pub fn canonical_shared_neuron_payload_digest_v2(
    req: &SharedNeuronFeatureRequestV2,
) -> Result<String, Error> {
    let identity_digest = req
        .snapshot
        .identity
        .digest()
        .map_err(|_| Error::FeatureContract)?;
    let mut bytes = b"hepta.infer-worker.shared-neuron-payload.v2".to_vec();
    for value in [
        req.authorization.request_id.as_str(),
        req.authorization.reservation_id.as_str(),
        req.authorization.model_digest.as_str(),
        req.authorization.reservation_model_digest.as_str(),
        req.principal_id.as_str(),
        req.purpose_id.as_str(),
        req.cell_id.as_str(),
        req.head_digest.as_str(),
        req.weights_digest.as_str(),
    ] {
        let raw = value.as_bytes();
        bytes.extend_from_slice(
            &u32::try_from(raw.len())
                .map_err(|_| Error::ArithmeticOverflow)?
                .to_be_bytes(),
        );
        bytes.extend_from_slice(raw);
    }
    bytes.extend_from_slice(identity_digest.as_array());
    bytes.extend_from_slice(req.snapshot.content_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(req.snapshot.features_q24.len())
            .map_err(|_| Error::ArithmeticOverflow)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &u64::try_from(req.expected_output_width)
            .map_err(|_| Error::ArithmeticOverflow)?
            .to_be_bytes(),
    );
    // Bind the entire admission envelope, not just tensor identity. In
    // particular, a caller must not extend an expired snapshot or deadline
    // while replaying an earlier lease/payload digest.
    bytes.extend_from_slice(&req.snapshot.expires_at_ms.to_be_bytes());
    bytes.extend_from_slice(&req.authorization.deadline_ms.to_be_bytes());
    bytes.extend_from_slice(&req.authorization.maximum_tokens.to_be_bytes());
    bytes.extend_from_slice(&req.authorization.reservation_maximum_tokens.to_be_bytes());
    bytes.push(u8::from(req.authorization.cancelled));
    Ok(Digest32::of_bytes(&bytes).to_string())
}

fn validate_item(
    req: &SharedNeuronFeatureRequestV2,
    now_ms: u64,
    worker_generation: u64,
    authority_epoch: u64,
    manifest: &super::ModelManifest,
) -> Result<(), Error> {
    validate_request(now_ms, &req.authorization)?;
    validate_digest(&req.head_digest, "head")?;
    validate_digest(&req.weights_digest, "weights")?;
    if req.authorization.cancelled {
        return Err(Error::FeatureContract);
    }
    if req.authorization.maximum_tokens > manifest.maximum_tokens
        || req.authorization.maximum_tokens > req.authorization.reservation_maximum_tokens
    {
        return Err(Error::TokenLimit);
    }
    let identity = &req.snapshot.identity;
    if req.principal_id != identity.principal_id
        || req.purpose_id != identity.purpose_id
        || identity.generation.get() != worker_generation
        || identity.authority_epoch != authority_epoch
        || now_ms >= req.snapshot.expires_at_ms
    {
        return Err(Error::FeatureContract);
    }
    if identity
        .digest()
        .map_err(|_| Error::FeatureContract)?
        .is_zero()
        || req.snapshot.content_digest != feature_content_digest_v2(&req.snapshot.features_q24)
    {
        return Err(Error::FeatureContract);
    }
    if req.snapshot.features_q24.is_empty()
        || req.snapshot.features_q24.len() > MAX_NEURON_FEATURES
        || req.expected_output_width == 0
        || req.expected_output_width > MAX_NEURON_FEATURES
        || req
            .snapshot
            .features_q24
            .iter()
            .any(|v| !(-MAX_FEATURE_ABS_Q24..=MAX_FEATURE_ABS_Q24).contains(v))
    {
        return Err(Error::FeatureLimit);
    }
    if identity.tokenizer_digest.to_string() != manifest.tokenizer_digest
        || identity.normalizer_digest.to_string() != manifest.preprocessor_digest
        || identity.quantization_digest.to_string() != manifest.quantization_digest
        || req.weights_digest != manifest.weights_digest
        || req.authorization.model_digest != manifest.model_digest
        || req.authorization.reservation_model_digest != manifest.model_digest
    {
        return Err(Error::ModelMismatch);
    }
    let actual = canonical_shared_neuron_payload_digest_v2(req)?;
    if actual != req.authorization.payload_digest
        || actual != req.authorization.lease_payload_digest
    {
        return Err(Error::PayloadMismatch);
    }
    Ok(())
}

impl<D: ModelDriver + NeuronSharedFeatureBatchDriverV2> InferenceWorker<D> {
    /// Admits and executes an immutable-feature batch without ever expanding
    /// Arc<[i64]> into the old per-request Vec. Returns all rows or an error.
    ///
    /// External final-use admission and source policy MUST precede this call;
    /// all returned results explicitly deny authorization.
    pub(crate) fn run_shared_neuron_features_batch_v2(
        &mut self,
        now_ms: u64,
        model_id: &str,
        requests: Vec<SharedNeuronFeatureRequestV2>,
    ) -> Result<Vec<SharedNeuronFeatureResultV2>, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        if requests.is_empty() || requests.len() > MAX_BATCH_ITEMS_V2 {
            return Err(Error::FeatureLimit);
        }
        let maximum = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        if self
            .active_requests
            .len()
            .checked_add(requests.len())
            .ok_or(Error::ArithmeticOverflow)?
            > maximum
        {
            return Err(Error::RequestCapacity);
        }

        let selected = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        let first_encoder = requests[0].snapshot.identity.encoder_digest;
        let input_width = requests[0].snapshot.features_q24.len();
        let output_width = requests[0].expected_output_width;
        let mut request_ids = BTreeSet::new();
        let mut reservation_ids = BTreeSet::new();
        for item in &requests {
            validate_item(
                item,
                now_ms,
                self.generation,
                self.grant.authority_epoch,
                &selected.manifest,
            )?;
            if item.snapshot.identity.encoder_digest != first_encoder
                || item.snapshot.features_q24.len() != input_width
                || item.expected_output_width != output_width
            {
                return Err(Error::FeatureContract);
            }
            if !request_ids.insert(item.authorization.request_id.as_str())
                || self
                    .active_requests
                    .contains_key(&item.authorization.request_id)
            {
                return Err(Error::RequestCapacity);
            }
            // Separate Cell uses need distinct, independently admitted reservations.
            if !reservation_ids.insert(item.authorization.reservation_id.as_str()) {
                return Err(Error::FeatureContract);
            }
        }

        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        loaded.active_requests = loaded
            .active_requests
            .checked_add(requests.len())
            .ok_or(Error::ArithmeticOverflow)?;
        for item in &requests {
            self.active_requests
                .insert(item.authorization.request_id.clone(), model_id.to_string());
        }
        let driver_result = self
            .driver
            .run_shared_neuron_features_batch_v2(&loaded.handle, &requests);
        for item in &requests {
            self.active_requests.remove(&item.authorization.request_id);
        }
        loaded.active_requests = loaded.active_requests.saturating_sub(requests.len());

        let observed = driver_result?;
        if observed.len() != requests.len() {
            return Err(Error::FeatureOutputMismatch);
        }
        let mut outputs = Vec::with_capacity(requests.len());
        for (request, batch_result) in requests.iter().zip(observed) {
            if batch_result.request_id != request.authorization.request_id
                || batch_result.payload_digest != request.authorization.payload_digest
            {
                return Err(Error::PayloadMismatch);
            }
            let features = batch_result.feature;
            if features.observed_memory_bytes > self.grant.maximum_memory_bytes
                || features.encoder_digest != request.snapshot.identity.encoder_digest.to_string()
                || features.head_digest != request.head_digest
            {
                return Err(Error::FeatureOutputMismatch);
            }
            let status = if !features.terminal_observed {
                ExecutionStatus::Indeterminate
            } else if features.succeeded {
                ExecutionStatus::Succeeded
            } else {
                ExecutionStatus::Failed
            };
            if status == ExecutionStatus::Succeeded {
                if features.drive_q24.len() != request.expected_output_width
                    || features.prediction_q24.len() != request.expected_output_width
                    || features
                        .drive_q24
                        .iter()
                        .chain(features.prediction_q24.iter())
                        .any(|v| !(-MAX_FEATURE_ABS_Q24..=MAX_FEATURE_ABS_Q24).contains(v))
                {
                    return Err(Error::FeatureOutputMismatch);
                }
            } else if !features.drive_q24.is_empty() || !features.prediction_q24.is_empty() {
                return Err(Error::FeatureOutputMismatch);
            }
            let identity_digest = request
                .snapshot
                .identity
                .digest()
                .map_err(|_| Error::FeatureContract)?;
            let observation_digest =
                observation_digest_v2(request, &features, status, self.generation, identity_digest);
            outputs.push(SharedNeuronFeatureResultV2 {
                request_id: request.authorization.request_id.clone(),
                reservation_id: request.authorization.reservation_id.clone(),
                cell_id: request.cell_id.clone(),
                principal_id: request.principal_id.clone(),
                purpose_id: request.purpose_id.clone(),
                feature_identity_digest: identity_digest,
                feature_content_digest: request.snapshot.content_digest,
                head_digest: request.head_digest.clone(),
                worker_generation: self.generation,
                status,
                drive_q24: features.drive_q24,
                prediction_q24: features.prediction_q24,
                observed_memory_bytes: features.observed_memory_bytes,
                transient_allocation_bytes: features.transient_allocation_bytes,
                queue_age_micros: features.queue_age_micros,
                latency_micros: features.latency_micros,
                observation_digest,
                authority: NonAuthorizingPosture::DENY_ALL,
            });
        }
        Ok(outputs)
    }
}

fn observation_digest_v2(
    request: &SharedNeuronFeatureRequestV2,
    observation: &DriverNeuronFeatureObservation,
    status: ExecutionStatus,
    generation: u64,
    identity_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.infer-worker.shared-neuron-observation.v2".to_vec();
    bytes.extend_from_slice(request.authorization.payload_digest.as_bytes());
    bytes.extend_from_slice(identity_digest.as_array());
    bytes.extend_from_slice(request.snapshot.content_digest.as_array());
    bytes.extend_from_slice(request.head_digest.as_bytes());
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.push(match status {
        ExecutionStatus::Succeeded => 1,
        ExecutionStatus::Failed => 2,
        ExecutionStatus::Cancelled => 3,
        ExecutionStatus::Indeterminate => 4,
    });
    for values in [&observation.drive_q24, &observation.prediction_q24] {
        bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    for v in [
        observation.observed_memory_bytes,
        observation.transient_allocation_bytes,
        observation.queue_age_micros,
        observation.latency_micros,
    ] {
        bytes.extend_from_slice(&v.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_infer_core::shared_feature_v2::SharedFeatureCacheV2;
    use codex_hepta_types::Generation;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_string()).expect("id")
    }

    fn frame(epoch: u64) -> Arc<ImmutableFeatureSnapshotV2> {
        let identity = codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2 {
            principal_id: id("principal.a"),
            purpose_id: id("purpose.prediction"),
            generation: Generation::new(3).expect("generation"),
            authority_epoch: epoch,
            encoder_digest: Digest32::of_bytes(b"encoder"),
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            normalizer_digest: Digest32::of_bytes(b"normalizer"),
            quantization_digest: Digest32::of_bytes(b"quantization"),
            input_digest: Digest32::of_bytes(b"full question, options and state"),
        };
        let mut cache = SharedFeatureCacheV2::new(8, 4096).expect("cache");
        cache
            .insert(1, identity, 1000, Arc::from([1_i64 << 23, -(1_i64 << 22)]))
            .expect("frame")
    }

    fn req(
        cell: &str,
        token: &str,
        snapshot: Arc<ImmutableFeatureSnapshotV2>,
    ) -> SharedNeuronFeatureRequestV2 {
        let mut value = SharedNeuronFeatureRequestV2 {
            authorization: WorkerRequest {
                request_id: token.to_string(),
                reservation_id: format!("reservation.{token}"),
                model_digest: "b".repeat(64),
                payload_digest: "c".repeat(64),
                maximum_tokens: 16,
                deadline_ms: 9_000,
                lease_payload_digest: "c".repeat(64),
                reservation_model_digest: "b".repeat(64),
                reservation_maximum_tokens: 32,
                cancelled: false,
            },
            principal_id: id("principal.a"),
            purpose_id: id("purpose.prediction"),
            cell_id: id(cell),
            snapshot,
            head_digest: "d".repeat(64),
            weights_digest: "e".repeat(64),
            expected_output_width: 2,
        };
        let digest = canonical_shared_neuron_payload_digest_v2(&value).expect("payload");
        value.authorization.payload_digest = digest.clone();
        value.authorization.lease_payload_digest = digest;
        value
    }

    #[test]
    fn zero_copy_shared_arc_and_cell_binding_are_in_digest() {
        let shared = frame(2);
        let a = req("cell.a", "request.a", Arc::clone(&shared));
        let b = req("cell.b", "request.b", Arc::clone(&shared));
        assert!(Arc::ptr_eq(&a.snapshot, &b.snapshot));
        assert_ne!(
            canonical_shared_neuron_payload_digest_v2(&a).expect("a"),
            canonical_shared_neuron_payload_digest_v2(&b).expect("b")
        );
        assert_eq!(
            a.snapshot.features_q24.as_ref(),
            &[1_i64 << 23, -(1_i64 << 22)]
        );
    }

    #[test]
    fn all_provenance_and_policy_controls_fail_closed() {
        let a = req("cell.a", "req.1", frame(2));
        let mut manifest = super::super::ModelManifest {
            model_id: "model".into(),
            model_digest: "b".repeat(64),
            weights_digest: "e".repeat(64),
            tokenizer_digest: a.snapshot.identity.tokenizer_digest.to_string(),
            preprocessor_digest: a.snapshot.identity.normalizer_digest.to_string(),
            quantization_digest: a.snapshot.identity.quantization_digest.to_string(),
            runtime_digest: "1".repeat(64),
            device_digest: "2".repeat(64),
            maximum_tokens: 64,
        };
        assert!(validate_item(&a, 10, 3, 2, &manifest).is_ok());
        assert_eq!(
            validate_item(&a, 1000, 3, 2, &manifest),
            Err(Error::FeatureContract)
        );
        assert_eq!(
            validate_item(&a, 10, 4, 2, &manifest),
            Err(Error::FeatureContract)
        );
        assert_eq!(
            validate_item(&a, 10, 3, 3, &manifest),
            Err(Error::FeatureContract)
        );
        manifest.preprocessor_digest = "f".repeat(64);
        assert_eq!(
            validate_item(&a, 10, 3, 2, &manifest),
            Err(Error::ModelMismatch)
        );
        let mut changed = a.clone();
        changed.cell_id = id("cell.b");
        assert_eq!(
            validate_item(&changed, 10, 3, 2, &manifest),
            Err(Error::ModelMismatch)
        );
        manifest.preprocessor_digest = a.snapshot.identity.normalizer_digest.to_string();
        assert_eq!(
            validate_item(&changed, 10, 3, 2, &manifest),
            Err(Error::PayloadMismatch)
        );
        changed = a.clone();
        changed.principal_id = id("other");
        assert_eq!(
            validate_item(&changed, 10, 3, 2, &manifest),
            Err(Error::FeatureContract)
        );
        changed = a.clone();
        changed.authorization.maximum_tokens = 65;
        assert_eq!(
            validate_item(&changed, 10, 3, 2, &manifest),
            Err(Error::TokenLimit)
        );
        let mut altered_snapshot = (*a.snapshot).clone();
        altered_snapshot.features_q24 = Arc::from([42_i64, 2]);
        changed = a.clone();
        changed.snapshot = Arc::new(altered_snapshot);
        assert_eq!(
            validate_item(&changed, 10, 3, 2, &manifest),
            Err(Error::FeatureContract)
        );

        // The input and content digest remain exactly the same, but this
        // expired snapshot is now replayed with a forged later expiry.
        let mut extended = (*a.snapshot).clone();
        extended.expires_at_ms = 2_000;
        changed = a.clone();
        changed.snapshot = Arc::new(extended);
        assert_ne!(
            canonical_shared_neuron_payload_digest_v2(&changed).expect("extended expiry"),
            a.authorization.payload_digest
        );
        assert_eq!(
            validate_item(&changed, 1_000, 3, 2, &manifest),
            Err(Error::PayloadMismatch)
        );

        // Lease payload identity also commits the request/reservation budgets
        // and deadline. Each mutation would otherwise keep the old digest.
        for field in 0..4 {
            changed = a.clone();
            match field {
                0 => changed.authorization.deadline_ms += 1,
                1 => changed.authorization.maximum_tokens += 1,
                2 => changed.authorization.reservation_maximum_tokens += 1,
                3 => changed.authorization.reservation_model_digest = "a".repeat(64),
                _ => unreachable!(),
            }
            assert_ne!(
                canonical_shared_neuron_payload_digest_v2(&changed).expect("admission field"),
                a.authorization.payload_digest
            );
        }
    }
}
