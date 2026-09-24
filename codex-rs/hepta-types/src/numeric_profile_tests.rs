use super::*;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

#[test]
fn profile_definition_binds_identity_version_scale_and_rounding() {
    let profile = NumericProfileV1::SignedQ32NearestTiesEven;
    let definition = checked(NumericProfileDefinitionV1::canonical(profile));
    assert_eq!(definition.profile(), profile);
    assert_eq!(definition.version(), NUMERIC_PROFILE_DEFINITION_VERSION_V1);
    assert_eq!(definition.scale(), 1_u64 << 32);
    assert_eq!(definition.rounding(), NumericRoundingV1::NearestTiesEven);
    assert!(!definition.digest().is_zero());

    assert_eq!(
        NumericProfileDefinitionV1::new(profile, 2, profile.scale(), profile.rounding()),
        Err(NumericProfileDefinitionError::UnsupportedVersion(2))
    );
    assert_eq!(
        NumericProfileDefinitionV1::new(
            profile,
            NUMERIC_PROFILE_DEFINITION_VERSION_V1,
            profile.scale(),
            NumericRoundingV1::TowardZero,
        ),
        Err(NumericProfileDefinitionError::SemanticMismatch)
    );
    assert_eq!(
        NumericProfileDefinitionV1::new(
            profile,
            NUMERIC_PROFILE_DEFINITION_VERSION_V1,
            0,
            profile.rounding(),
        ),
        Err(NumericProfileDefinitionError::ZeroScale)
    );
}

#[test]
fn q32_raw_scale_compatibility_does_not_imply_arithmetic_compatibility() {
    let profile = NumericProfileV1::SignedQ32NearestTiesEven;
    assert!(profile.shares_fixed_q32_raw_scale());
    assert!(!profile.fixed_q32_arithmetic_compatible());
    assert_eq!(
        profile.fixed_q32_arithmetic_profile_id(),
        crate::FIXED_Q32_ARITHMETIC_PROFILE_V1
    );
    assert_eq!(profile.rounding(), NumericRoundingV1::NearestTiesEven);
    assert_eq!(
        crate::FixedQ32::arithmetic_profile_id(),
        "fixed-q32-toward-zero-v1"
    );
}
#[test]
fn unknown_profile_names_reject_including_javascript_prototype_names() {
    for profile_id in ["constructor", "toString", "__proto__", "unknown-profile"] {
        assert_eq!(
            NumericProfileV1::from_id(profile_id),
            Err(NumericConversionError::UnknownProfile),
            "profile {profile_id:?} must reject",
        );
    }
}
