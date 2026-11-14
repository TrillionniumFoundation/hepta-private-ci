use std::fmt::Debug;

use super::*;

const Q24: i64 = 1_i64 << 24;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(raw: &str) -> StableId {
    must(StableId::new(raw.to_owned()))
}

fn generation() -> Generation {
    must(Generation::new(1))
}

fn projector(modality: &str, weight: i64) -> ModalityProjectorV1 {
    let modality_id = id(modality);
    let weights = vec![weight, 0];
    let bias = vec![0];
    let digest =
        canonical_modality_projector_digest_v1(&modality_id, generation(), 2, 1, &weights, &bias);
    must(ModalityProjectorV1::new(
        modality_id,
        generation(),
        digest,
        2,
        1,
        weights,
        bias,
    ))
}

fn stem() -> MultimodalStemProjectionV1 {
    must(MultimodalStemProjectionV1::new(
        generation(),
        vec![
            projector("modality:text", Q24),
            projector("modality:image", Q24 / 2),
        ],
    ))
}

#[test]
fn ordered_projection_appends_missing_mask_and_provenance() {
    let stem = stem();
    let inputs = vec![ModalityInputV1 {
        modality_id: id("modality:image"),
        features_q24: vec![2 * Q24, 4],
    }];
    let source_digest = canonical_multimodal_source_digest_v1(&inputs);
    let request = MultimodalStemRequestV1 {
        generation: generation(),
        source_digest,
        modality_manifest_digest: stem.manifest_digest(),
        inputs,
    };
    let output = must(stem.project(&request));

    // Text is slot 0 and missing; image is slot 1 and contributes 1.0 Q24.
    assert_eq!(output.missing_mask(), 0b01);
    assert_eq!(output.projected_feature_width(), 2);
    assert_eq!(output.feature_vector_q24(), &[0, Q24, Q24, 0]);
    assert_eq!(output.source_digest(), source_digest);
    assert_eq!(output.manifest_digest(), stem.manifest_digest());
    assert_eq!(
        output.stem_digest(),
        canonical_multimodal_stem_digest_v1(
            generation(),
            source_digest,
            stem.manifest_digest(),
            0b01,
            output.feature_vector_q24(),
        )
    );
}

#[test]
fn source_digest_is_independent_of_present_input_order() {
    let first = vec![
        ModalityInputV1 {
            modality_id: id("modality:image"),
            features_q24: vec![3 * Q24, 4],
        },
        ModalityInputV1 {
            modality_id: id("modality:text"),
            features_q24: vec![5 * Q24, 6],
        },
    ];
    let second = vec![first[1].clone(), first[0].clone()];
    assert_eq!(
        canonical_multimodal_source_digest_v1(&first),
        canonical_multimodal_source_digest_v1(&second)
    );

    let stem = stem();
    let output = must(stem.project(&MultimodalStemRequestV1 {
        generation: generation(),
        source_digest: canonical_multimodal_source_digest_v1(&second),
        modality_manifest_digest: stem.manifest_digest(),
        inputs: second,
    }));
    assert_eq!(output.missing_mask(), 0);
    assert_eq!(output.feature_vector_q24(), &[5 * Q24, 3 * Q24 / 2, 0, 0]);
}

#[test]
fn provenance_and_shape_fences_fail_closed() {
    let stem = stem();
    let valid_inputs = vec![ModalityInputV1 {
        modality_id: id("modality:text"),
        features_q24: vec![Q24, 0],
    }];
    let valid_source = canonical_multimodal_source_digest_v1(&valid_inputs);

    let mut request = MultimodalStemRequestV1 {
        generation: generation(),
        source_digest: valid_source,
        modality_manifest_digest: stem.manifest_digest(),
        inputs: valid_inputs,
    };
    request.modality_manifest_digest = Digest32::of_bytes(b"other-manifest");
    assert_eq!(
        stem.project(&request),
        Err(MultimodalStemError::ManifestDigestMismatch)
    );

    request.modality_manifest_digest = stem.manifest_digest();
    request.source_digest = Digest32::of_bytes(b"other-source");
    assert_eq!(
        stem.project(&request),
        Err(MultimodalStemError::SourceDigestMismatch)
    );

    request.source_digest = valid_source;
    request.inputs[0].features_q24 = vec![Q24];
    assert!(matches!(
        stem.project(&request),
        Err(MultimodalStemError::InputWidthMismatch { .. })
    ));

    request.inputs[0].features_q24 = vec![MAX_MULTIMODAL_Q24_V1 + 1, 0];
    assert!(matches!(
        stem.project(&request),
        Err(MultimodalStemError::InputRangeViolation { .. })
    ));
}

#[test]
fn duplicate_and_unknown_modalities_are_rejected() {
    let stem = stem();
    let duplicate = vec![
        ModalityInputV1 {
            modality_id: id("modality:text"),
            features_q24: vec![1, 2],
        },
        ModalityInputV1 {
            modality_id: id("modality:text"),
            features_q24: vec![3, 4],
        },
    ];
    let request = MultimodalStemRequestV1 {
        generation: generation(),
        source_digest: canonical_multimodal_source_digest_v1(&duplicate),
        modality_manifest_digest: stem.manifest_digest(),
        inputs: duplicate,
    };
    assert!(matches!(
        stem.project(&request),
        Err(MultimodalStemError::DuplicateInput(_))
    ));

    let unknown = vec![ModalityInputV1 {
        modality_id: id("modality:audio"),
        features_q24: vec![1, 2],
    }];
    let request = MultimodalStemRequestV1 {
        generation: generation(),
        source_digest: canonical_multimodal_source_digest_v1(&unknown),
        modality_manifest_digest: stem.manifest_digest(),
        inputs: unknown,
    };
    assert!(matches!(
        stem.project(&request),
        Err(MultimodalStemError::UnknownModality(_))
    ));
}

#[test]
fn projector_digest_and_manifest_order_are_bound() {
    let text = projector("modality:text", Q24);
    let wrong_digest = Digest32::of_bytes(b"wrong");
    assert_eq!(
        ModalityProjectorV1::new(
            id("modality:text"),
            generation(),
            wrong_digest,
            2,
            1,
            vec![Q24, 0],
            vec![0],
        ),
        Err(MultimodalStemError::ProjectorDigestMismatch)
    );

    let reversed = must(MultimodalStemProjectionV1::new(
        generation(),
        vec![projector("modality:image", Q24 / 2), text],
    ));
    assert_ne!(reversed.manifest_digest(), stem().manifest_digest());
}
