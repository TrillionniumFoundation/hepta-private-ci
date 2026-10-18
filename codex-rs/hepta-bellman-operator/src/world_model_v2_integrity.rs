//! Fixed-size metadata seal for immutable fitted world-model estimates.

use codex_hepta_types::Digest32;

use super::WorldModelArtifactV2;
use super::WorldModelV2Error;
use super::push_id;

pub(super) fn digest_prediction_metadata(
    artifact: &WorldModelArtifactV2,
) -> Result<Digest32, WorldModelV2Error> {
    let mut bytes = b"hepta.bellman-operator.world-model-inference.v2\0".to_vec();
    bytes.extend_from_slice(&artifact.schema_version.to_be_bytes());
    push_id(&mut bytes, &artifact.model_id)?;
    bytes.extend_from_slice(&artifact.generation.get().to_be_bytes());
    for digest in [
        artifact.objective_digest,
        artifact.dataset_digest,
        artifact.training_profile_digest,
        artifact.runtime_profile_digest,
        artifact.trust_digest,
        artifact.registry_head_digest,
        artifact.row_commitment_root,
        artifact.train_window_digest,
        artifact.holdout_window_digest,
        artifact.future_window_digest,
        artifact.change_point_digest,
        artifact.model_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    match artifact.predecessor_model_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&artifact.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&artifact.minimum_support.to_be_bytes());
    bytes.extend_from_slice(&artifact.one_step_calibration_error.raw().to_be_bytes());
    bytes.extend_from_slice(&artifact.multistep_calibration_error.raw().to_be_bytes());
    bytes.extend_from_slice(&artifact.ood_false_acceptance.raw().to_be_bytes());
    bytes.extend_from_slice(&artifact.drift_score.raw().to_be_bytes());
    bytes.extend_from_slice(&artifact.retained_until.to_be_bytes());
    bytes.extend_from_slice(&artifact.expires_at.to_be_bytes());
    bytes.extend_from_slice(&artifact.work.operations.to_be_bytes());
    bytes.extend_from_slice(&artifact.work.estimated_bytes.to_be_bytes());
    bytes.extend_from_slice(&artifact.work.elapsed_micros.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}
