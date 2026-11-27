use pretty_assertions::assert_eq;

use super::*;

fn lineage() -> FeatureSnapshotLineageV1 {
    FeatureSnapshotLineageV1 {
        source_frontier: Digest32::of_bytes(b"frontier"),
        model: Digest32::of_bytes(b"model"),
        adapter: Digest32::of_bytes(b"adapter"),
        tokenizer: Digest32::of_bytes(b"tokenizer"),
        normalizer: Digest32::of_bytes(b"normalizer"),
        calibration: Digest32::of_bytes(b"calibration"),
    }
}

fn explicit_identity(
    lineage: FeatureSnapshotLineageV1,
    question: Digest32,
    options: Digest32,
) -> Result<FeatureSnapshotIdentityV1, Box<dyn StdError>> {
    Ok(FeatureSnapshotIdentityV1::new_with_question_options(
        StableId::new("scope")?,
        StableId::new("workspace")?,
        StableId::new("purpose")?,
        question,
        options,
        lineage,
    )?)
}

#[test]
fn parameter_bundling_preserves_complete_identity_and_fixed_digests()
-> Result<(), Box<dyn StdError>> {
    let identity = explicit_identity(
        lineage(),
        Digest32::of_bytes(b"question"),
        Digest32::of_bytes(b"options"),
    )?;
    assert_eq!(
        identity,
        FeatureSnapshotIdentityV1 {
            scope: StableId::new("scope")?,
            workspace: StableId::new("workspace")?,
            purpose: StableId::new("purpose")?,
            question: Digest32::of_bytes(b"question"),
            options: Digest32::of_bytes(b"options"),
            source_frontier: Digest32::of_bytes(b"frontier"),
            model: Digest32::of_bytes(b"model"),
            adapter: Digest32::of_bytes(b"adapter"),
            tokenizer: Digest32::of_bytes(b"tokenizer"),
            normalizer: Digest32::of_bytes(b"normalizer"),
            calibration: Digest32::of_bytes(b"calibration"),
        }
    );
    assert_eq!(
        identity.semantic_digest().to_string(),
        "865e338410500039a1f0c840735b9bcdbd8fbf81a6040accb935d387a4be473a"
    );

    let legacy = FeatureSnapshotIdentityV1::new(
        StableId::new("scope")?,
        StableId::new("workspace")?,
        StableId::new("purpose")?,
        lineage(),
    )?;
    assert_eq!(
        legacy.semantic_digest().to_string(),
        "c3e67ea22c620b12f5d36eec9d67efcc23159609ac6401a198e9c00f6763ce30"
    );
    Ok(())
}

#[test]
fn bundled_lineage_preserves_each_zero_digest_rejection() -> Result<(), Box<dyn StdError>> {
    for (field, lineage) in [
        (
            "source frontier",
            FeatureSnapshotLineageV1 {
                source_frontier: Digest32::ZERO,
                ..lineage()
            },
        ),
        (
            "model",
            FeatureSnapshotLineageV1 {
                model: Digest32::ZERO,
                ..lineage()
            },
        ),
        (
            "adapter",
            FeatureSnapshotLineageV1 {
                adapter: Digest32::ZERO,
                ..lineage()
            },
        ),
        (
            "tokenizer",
            FeatureSnapshotLineageV1 {
                tokenizer: Digest32::ZERO,
                ..lineage()
            },
        ),
        (
            "normalizer",
            FeatureSnapshotLineageV1 {
                normalizer: Digest32::ZERO,
                ..lineage()
            },
        ),
        (
            "calibration",
            FeatureSnapshotLineageV1 {
                calibration: Digest32::ZERO,
                ..lineage()
            },
        ),
    ] {
        assert_eq!(
            FeatureSnapshotIdentityV1::new(
                StableId::new("scope")?,
                StableId::new("workspace")?,
                StableId::new("purpose")?,
                lineage,
            ),
            Err(DataPlaneError::EmptyDigest(field))
        );
        assert_eq!(
            FeatureSnapshotIdentityV1::new_with_question_options(
                StableId::new("scope")?,
                StableId::new("workspace")?,
                StableId::new("purpose")?,
                Digest32::of_bytes(b"question"),
                Digest32::of_bytes(b"options"),
                lineage,
            ),
            Err(DataPlaneError::EmptyDigest(field))
        );
    }
    for (field, question, options) in [
        ("question", Digest32::ZERO, Digest32::of_bytes(b"options")),
        ("options", Digest32::of_bytes(b"question"), Digest32::ZERO),
    ] {
        assert_eq!(
            FeatureSnapshotIdentityV1::new_with_question_options(
                StableId::new("scope")?,
                StableId::new("workspace")?,
                StableId::new("purpose")?,
                question,
                options,
                lineage(),
            ),
            Err(DataPlaneError::EmptyDigest(field))
        );
    }
    Ok(())
}

#[test]
fn borrowed_request_preserves_fixed_reference_output_v2() -> Result<(), Box<dyn StdError>> {
    let generation = Generation::new(/*value*/ 1)?;
    let encoder_digest = Digest32::of_bytes(b"encoder");
    let features = vec![(1_i64 << 24) / 2, -(1_i64 << 24) / 4];
    let input_digest = canonical_feature_vector_digest_v1(&features);
    let identity = explicit_identity(
        lineage(),
        Digest32::of_bytes(b"question"),
        Digest32::of_bytes(b"options"),
    )?;
    let snapshot = FeatureSnapshotV1::new_with_identity(
        encoder_digest,
        generation,
        input_digest,
        features.clone(),
        identity,
    )?;
    let mut models = CompatibleModelIndexV1::new();
    models.register(
        StableId::new("model")?,
        generation,
        encoder_digest,
        LightweightHeadV1 {
            head_digest: Digest32::of_bytes(b"head"),
            feature_width: 2,
            output_width: 2,
            weights_q24: vec![vec![1 << 24, 0], vec![0, 1 << 24]],
            bias_q24: vec![0, 0],
        },
    )?;
    let backend = ReferenceBackendBatchV1::new(models, RetiredIdRegistryV1::new());
    let outputs = backend.execute(&[HeadExecutionRequestV1 {
        request_id: StableId::new("request")?,
        model_id: StableId::new("model")?,
        generation,
        snapshot,
    }])?;
    assert_eq!(
        outputs,
        vec![HeadExecutionOutputV1 {
            request_id: StableId::new("request")?,
            model_id: StableId::new("model")?,
            generation,
            input_digest,
            output_q24: features,
            output_digest: "f107c7e3722f96ba9d2c1c77ecde0e65b0ffe94ab63c03c21a645f53dfc4be42"
                .parse()?,
            authority: AuthorityPosture::DENY_ALL,
        }]
    );
    Ok(())
}
