use std::fmt::Debug;

use super::*;

use crate::SharedEncoderDriver;
use crate::SharedEncoderDriverError;
use crate::SharedEncoderOutputV1;
use crate::SharedEncoderOwnerV1;
use crate::SharedEncoderRequestV1;
use crate::SharedFeatureBatchV1;
use crate::canonical_shared_encoder_feature_digest_v1;
use crate::canonical_shared_encoder_input_digest_v1;

struct FakeDriver {
    output_features: Vec<i64>,
}

impl SharedEncoderDriver for FakeDriver {
    fn encode(
        &mut self,
        request: &SharedEncoderRequestV1,
    ) -> Result<SharedEncoderOutputV1, SharedEncoderDriverError> {
        Ok(SharedEncoderOutputV1 {
            encoder_digest: request.encoder_digest,
            input_digest: request.input_digest,
            feature_digest: canonical_shared_encoder_feature_digest_v1(&self.output_features),
            feature_vector_q24: self.output_features.clone(),
        })
    }
}

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(raw: &str) -> StableId {
    match StableId::new(raw) {
        Ok(value) => value,
        Err(error) => panic!("invalid fixture id: {error:?}"),
    }
}

fn generation(raw: u64) -> Generation {
    match Generation::new(raw) {
        Ok(value) => value,
        Err(error) => panic!("invalid fixture generation: {error:?}"),
    }
}

fn encoder_digest() -> Digest32 {
    Digest32::of_bytes(b"cell-head-test-encoder")
}

fn feature_batch() -> SharedFeatureBatchV1 {
    let values = vec![1, 2, 3];
    let request = SharedEncoderRequestV1 {
        request_id: id("execution:cell-head"),
        generation: generation(7),
        encoder_digest: encoder_digest(),
        input_digest: canonical_shared_encoder_input_digest_v1(&values),
        input_features_q24: values,
    };
    let mut owner = must(SharedEncoderOwnerV1::new(
        encoder_digest(),
        generation(7),
        FakeDriver {
            output_features: vec![11, 12, 13],
        },
    ));
    must(owner.encode_for_cells(&request, &[id("cell:0"), id("cell:1")]))
}

fn head_for(cell_id: StableId) -> CellHeadV1 {
    let scale = 1_i64 << 24;
    let weights = vec![
        scale, 0, 0, // action 0
        0, scale, 0, // action 1
        scale, scale, 0, // value
        0, 0, scale, // uncertainty
    ];
    let bias = vec![0, 0, 0, 0];
    let digest = canonical_cell_head_digest_v1(
        &cell_id,
        generation(7),
        encoder_digest(),
        3,
        2,
        &weights,
        &bias,
        12,
    );
    must(CellHeadV1::new(
        cell_id,
        generation(7),
        encoder_digest(),
        digest,
        3,
        2,
        weights,
        bias,
        12,
    ))
}

#[test]
fn each_cell_gets_private_head_outputs_from_one_shared_feature_artifact() {
    let batch = feature_batch();
    let first = must(head_for(id("cell:0")).evaluate(&batch));
    let second = must(head_for(id("cell:1")).evaluate(&batch));

    assert_eq!(first.action_logits_q24.as_ref(), &[11, 12]);
    assert_eq!(first.value_q24, 23);
    assert_eq!(first.uncertainty_q24, 13);
    assert!(first.abstain);
    assert_ne!(first.head_digest, second.head_digest);
    assert_ne!(first.action_digest, second.action_digest);
    assert_eq!(first.cell_id, id("cell:0"));
    assert_eq!(second.cell_id, id("cell:1"));
}

#[test]
fn head_definition_is_digest_and_shape_bound() {
    let cell_id = id("cell:0");
    let scale = 1_i64 << 24;
    let weights = vec![scale; 4 * 3];
    let bias = vec![0; 4];
    let digest = canonical_cell_head_digest_v1(
        &cell_id,
        generation(7),
        encoder_digest(),
        3,
        2,
        &weights,
        &bias,
        0,
    );

    assert_eq!(
        CellHeadV1::new(
            cell_id.clone(),
            generation(7),
            encoder_digest(),
            Digest32::of_bytes(b"wrong-head"),
            3,
            2,
            weights.clone(),
            bias.clone(),
            0,
        ),
        Err(CellHeadError::ParameterDigestMismatch)
    );
    assert_eq!(
        CellHeadV1::new(
            cell_id.clone(),
            generation(7),
            encoder_digest(),
            digest,
            3,
            2,
            vec![scale],
            bias.clone(),
            0,
        ),
        Err(CellHeadError::ParameterShapeMismatch)
    );
    assert_eq!(
        CellHeadV1::new(
            cell_id,
            generation(7),
            encoder_digest(),
            digest,
            3,
            2,
            weights,
            bias,
            -1,
        ),
        Err(CellHeadError::ThresholdRangeViolation)
    );
}

#[test]
fn binding_generation_cell_and_width_fences_fail_closed() {
    let batch = feature_batch();

    let other_encoder = Digest32::of_bytes(b"other-encoder");
    let cell_id = id("cell:0");
    let weights = vec![0; 4 * 3];
    let bias = vec![0; 4];
    let other_encoder_digest = canonical_cell_head_digest_v1(
        &cell_id,
        generation(7),
        other_encoder,
        3,
        2,
        &weights,
        &bias,
        0,
    );
    let other_encoder_head = must(CellHeadV1::new(
        cell_id.clone(),
        generation(7),
        other_encoder,
        other_encoder_digest,
        3,
        2,
        weights.clone(),
        bias.clone(),
        0,
    ));
    assert_eq!(
        other_encoder_head.evaluate(&batch),
        Err(CellHeadError::EncoderBindingMismatch)
    );

    let other_generation_digest = canonical_cell_head_digest_v1(
        &cell_id,
        generation(8),
        encoder_digest(),
        3,
        2,
        &weights,
        &bias,
        0,
    );
    let other_generation_head = must(CellHeadV1::new(
        cell_id.clone(),
        generation(8),
        encoder_digest(),
        other_generation_digest,
        3,
        2,
        weights,
        bias.clone(),
        0,
    ));
    assert_eq!(
        other_generation_head.evaluate(&batch),
        Err(CellHeadError::GenerationMismatch)
    );

    let missing_head = head_for(id("cell:missing"));
    assert_eq!(
        missing_head.evaluate(&batch),
        Err(CellHeadError::CellNotInBatch)
    );

    let narrow_weights = vec![0; 4 * 2];
    let narrow_digest = canonical_cell_head_digest_v1(
        &cell_id,
        generation(7),
        encoder_digest(),
        2,
        2,
        &narrow_weights,
        &bias,
        0,
    );
    let narrow_head = must(CellHeadV1::new(
        cell_id,
        generation(7),
        encoder_digest(),
        narrow_digest,
        2,
        2,
        narrow_weights,
        bias,
        0,
    ));
    assert_eq!(
        narrow_head.evaluate(&batch),
        Err(CellHeadError::FeatureWidthMismatch)
    );
}
