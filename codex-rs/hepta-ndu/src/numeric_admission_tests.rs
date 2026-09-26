use codex_hepta_types::ContractRegistryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::IdProfileV1;
use codex_hepta_types::NumericProfileDefinitionV1;
use codex_hepta_types::NumericProfileV1;
use codex_hepta_types::NumericSignalSchemaV1;
use codex_hepta_types::NumericSignalV1;
use codex_hepta_types::RegistryDefinitionV1;
use codex_hepta_types::RegistryKindV1;
use codex_hepta_types::SignalUnitV1;
use codex_hepta_types::StableId;
use codex_hepta_types::validate_id;

use super::*;
use crate::AxisDirection;
use crate::RequiredOrganSet;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("ID fixture")
}

fn registry_with_extra(extra: bool) -> (NduNumericRegistryV1, Digest32) {
    let normalization = RegistryDefinitionV1::new(
        RegistryKindV1::Normalization,
        validate_id("normalization:ndu-utility-v1", IdProfileV1::Normalization)
            .expect("normalization ID"),
        1,
        "unit=utility;source=ppm;target=signed-q32-nearest-ties-even-v1",
    )
    .expect("normalization definition");
    let normalization_digest = normalization.digest();
    let mut entries = vec![normalization];
    if extra {
        entries.push(
            RegistryDefinitionV1::new(
                RegistryKindV1::Schema,
                validate_id("schema:ndu-extra-v1", IdProfileV1::Schema).expect("schema ID"),
                1,
                "kind=extra-test-definition",
            )
            .expect("extra definition"),
        );
    }
    let registry = ContractRegistryV1::new_with_numeric_profiles(
        entries,
        vec![
            NumericProfileDefinitionV1::canonical(NumericProfileV1::HnmfPpmTowardZero)
                .expect("source profile"),
            NumericProfileDefinitionV1::canonical(NumericProfileV1::SignedQ32NearestTiesEven)
                .expect("target profile"),
        ],
    )
    .expect("registry");
    (
        NduNumericRegistryV1::new(registry).expect("NDU registry"),
        normalization_digest,
    )
}

fn profile(normalization_manifest_digest: Digest32) -> UtilityProfile {
    UtilityProfile {
        profile_id: id("ndu-registered-utility-v1"),
        axis_registry_digest: Digest32::of_bytes(b"axis-registry"),
        normalization_manifest_digest,
        dimensions: vec![
            (id("success"), AxisDirection::Maximize),
            (id("quality"), AxisDirection::Maximize),
        ],
        risk_ceilings: Vec::new(),
        resource_ceilings: Vec::new(),
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("planner")],
        },
    }
}

fn signal(normalization_digest: Digest32) -> NumericSignalV1 {
    NumericSignalV1 {
        schema: NumericSignalSchemaV1 {
            profile: NumericProfileV1::HnmfPpmTowardZero,
            unit: SignalUnitV1::Utility,
            shape: vec![2],
            minimum_raw: -1_000_000,
            maximum_raw: 1_000_000,
            normalization_digest,
        },
        values: vec![500_000, -250_000],
    }
}

#[test]
fn registered_utility_signal_binds_registry_normalization_and_axis_order() {
    let (registry, normalization_digest) = registry_with_extra(false);
    let admitted = registry
        .admit_utility_signal(
            &profile(normalization_digest),
            &signal(normalization_digest),
        )
        .expect("admission");
    assert_eq!(admitted.registry_digest, registry.registry_digest());
    assert_eq!(
        admitted.admission.registry_digest,
        registry.registry_digest()
    );
    assert!(!admitted.admission.admission_digest.is_zero());
    assert_eq!(admitted.axis_values[0].axis, id("success"));
    assert_eq!(admitted.axis_values[0].value.raw(), 1_i64 << 31);
    assert_eq!(admitted.axis_values[1].axis, id("quality"));
    assert_eq!(admitted.axis_values[1].value.raw(), -(1_i64 << 30));
}

#[test]
fn registry_generation_changes_admission_but_not_pure_arithmetic() {
    let (left, normalization_digest) = registry_with_extra(false);
    let (right, right_normalization_digest) = registry_with_extra(true);
    assert_eq!(normalization_digest, right_normalization_digest);
    let utility = profile(normalization_digest);
    let source = signal(normalization_digest);
    let left = left
        .admit_utility_signal(&utility, &source)
        .expect("left admission");
    let right = right
        .admit_utility_signal(&utility, &source)
        .expect("right admission");
    assert_eq!(left.signal, right.signal);
    assert_eq!(left.admission.conversion, right.admission.conversion);
    assert_ne!(left.registry_digest, right.registry_digest);
    assert_ne!(
        left.admission.admission_digest,
        right.admission.admission_digest
    );
}

#[test]
fn normalization_unit_and_axis_mismatch_reject_before_owner_use() {
    let (registry, normalization_digest) = registry_with_extra(false);
    let utility = profile(normalization_digest);
    let mut source = signal(normalization_digest);
    source.schema.normalization_digest = Digest32::of_bytes(b"other normalization");
    assert_eq!(
        registry.admit_utility_signal(&utility, &source),
        Err(NduNumericAdmissionErrorV1::NormalizationMismatch)
    );

    let mut source = signal(normalization_digest);
    source.schema.unit = SignalUnitV1::Dimensionless;
    assert_eq!(
        registry.admit_utility_signal(&utility, &source),
        Err(NduNumericAdmissionErrorV1::UnitMismatch)
    );

    let mut source = signal(normalization_digest);
    source.values.pop();
    assert_eq!(
        registry.admit_utility_signal(&utility, &source),
        Err(NduNumericAdmissionErrorV1::AxisCountMismatch)
    );

    let mut source = signal(normalization_digest);
    source.schema.shape = vec![1, 2];
    assert_eq!(
        registry.admit_utility_signal(&utility, &source),
        Err(NduNumericAdmissionErrorV1::ShapeMismatch)
    );
}
