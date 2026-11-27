use std::fmt::Debug;

use super::*;

struct FakeDriver {
    calls: usize,
    output_features: Vec<i64>,
}

impl SharedEncoderDriver for FakeDriver {
    fn encode(
        &mut self,
        request: &SharedEncoderRequestV1,
    ) -> Result<SharedEncoderOutputV1, SharedEncoderDriverError> {
        self.calls += 1;
        Ok(SharedEncoderOutputV1 {
            request_id: request.request_id.clone(),
            generation: request.generation,
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

fn shared_encoder_request() -> SharedEncoderRequestV1 {
    let values = vec![1, 2, 3];
    SharedEncoderRequestV1 {
        request_id: id("execution:shared-encoder"),
        generation: Generation::new(1).unwrap_or_else(|error| panic!("{error:?}")),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        input_digest: canonical_shared_encoder_input_digest_v1(&values),
        input_features_q24: values,
    }
}

fn owner() -> SharedEncoderOwnerV1<FakeDriver> {
    must(SharedEncoderOwnerV1::new(
        Digest32::of_bytes(b"encoder"),
        Generation::new(1).unwrap_or_else(|error| panic!("{error:?}")),
        FakeDriver {
            calls: 0,
            output_features: vec![11, 12, 13, 14],
        },
    ))
}

#[test]
fn one_forward_is_shared_by_all_cells() {
    let mut owner = owner();
    let request = shared_encoder_request();
    let cells = vec![id("cell:0"), id("cell:1"), id("cell:2")];
    let batch = must(owner.encode_for_cells(&request, &cells));
    assert_eq!(owner.driver.calls, 1);
    assert_eq!(batch.cell_ids(), cells.as_slice());
    assert_eq!(batch.request_id(), &request.request_id);
    assert_eq!(batch.generation(), request.generation);
    assert_eq!(batch.feature_vector_q24(), &[11, 12, 13, 14]);
    assert_eq!(
        batch.features_for_cell(&cells[0]),
        Some([11, 12, 13, 14].as_slice())
    );
    assert_eq!(batch.features_for_cell(&id("cell:missing")), None);
}

#[test]
fn generation_and_digest_fences_fail_closed() {
    let mut owner = owner();
    let mut request = shared_encoder_request();
    request.generation = Generation::new(2).unwrap_or_else(|error| panic!("{error:?}"));
    assert_eq!(
        owner.encode_for_cells(&request, &[id("cell:0")]),
        Err(SharedEncoderError::GenerationMismatch)
    );

    let mut request = shared_encoder_request();
    request.generation = Generation::new(1).unwrap_or_else(|error| panic!("{error:?}"));
    request.encoder_digest = Digest32::of_bytes(b"other");
    assert_eq!(
        owner.encode_for_cells(&request, &[id("cell:0")]),
        Err(SharedEncoderError::EncoderBindingMismatch)
    );
}

#[test]
fn duplicate_cells_and_bad_output_are_rejected_before_sharing() {
    let mut owner = owner();
    let request = shared_encoder_request();
    let cell = id("cell:0");
    assert_eq!(
        owner.encode_for_cells(&request, &[cell.clone(), cell]),
        Err(SharedEncoderError::DuplicateCellId("cell:0".to_owned()))
    );

    struct BadDriver;
    impl SharedEncoderDriver for BadDriver {
        fn encode(
            &mut self,
            request: &SharedEncoderRequestV1,
        ) -> Result<SharedEncoderOutputV1, SharedEncoderDriverError> {
            Ok(SharedEncoderOutputV1 {
                request_id: request.request_id.clone(),
                generation: request.generation,
                encoder_digest: request.encoder_digest,
                input_digest: request.input_digest,
                feature_digest: Digest32::of_bytes(b"wrong"),
                feature_vector_q24: vec![1],
            })
        }
    }
    let mut bad_owner = must(SharedEncoderOwnerV1::new(
        Digest32::of_bytes(b"encoder"),
        Generation::new(1).unwrap_or_else(|error| panic!("{error:?}")),
        BadDriver,
    ));
    assert_eq!(
        bad_owner.encode_for_cells(&request, &[id("cell:0")]),
        Err(SharedEncoderError::OutputDigestMismatch)
    );
}

#[test]
fn stale_driver_request_or_generation_cannot_be_shared() {
    struct MisboundDriver {
        request_id: StableId,
        generation: Generation,
    }

    impl SharedEncoderDriver for MisboundDriver {
        fn encode(
            &mut self,
            request: &SharedEncoderRequestV1,
        ) -> Result<SharedEncoderOutputV1, SharedEncoderDriverError> {
            let features = vec![11, 12, 13, 14];
            Ok(SharedEncoderOutputV1 {
                request_id: self.request_id.clone(),
                generation: self.generation,
                encoder_digest: request.encoder_digest,
                input_digest: request.input_digest,
                feature_digest: canonical_shared_encoder_feature_digest_v1(&features),
                feature_vector_q24: features,
            })
        }
    }

    let request = shared_encoder_request();
    let other_generation = Generation::new(2).unwrap_or_else(|error| panic!("{error:?}"));
    let cases = [
        (
            id("execution:wrong"),
            request.generation,
            SharedEncoderError::RequestBindingMismatch,
        ),
        (
            request.request_id.clone(),
            other_generation,
            SharedEncoderError::GenerationMismatch,
        ),
    ];

    for (request_id, generation, expected) in cases {
        let driver = MisboundDriver {
            request_id,
            generation,
        };
        let mut owner = must(SharedEncoderOwnerV1::new(
            request.encoder_digest,
            request.generation,
            driver,
        ));
        assert_eq!(
            owner.encode_for_cells(&request, &[id("cell:0"), id("cell:1")]),
            Err(expected)
        );
    }
}
