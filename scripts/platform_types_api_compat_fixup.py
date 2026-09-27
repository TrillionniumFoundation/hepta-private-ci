#!/usr/bin/env python3
"""One-shot source compatibility convergence for platform.types numeric admission."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected one compatibility anchor, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def replace_all(relative: str, old: str, new: str, expected: int) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{relative}: expected {expected} compatibility anchors, found {count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "codex-rs/hepta-types/src/numeric_profile.rs",
    "    Overflow,\n    RegistryAdmission,\n    CanonicalEncoding,\n",
    "    Overflow,\n    CanonicalEncoding,\n",
)

replace_exact(
    "codex-rs/hepta-types/src/numeric_conversion.rs",
    '''/// Production-admission variant. Both native numeric-profile semantics and
/// the shared normalization definition must be present in the exact immutable
/// registry generation supplied by the caller. Authentication of that registry
/// belongs to the product owner, not to platform.types.
pub fn rescale_signal_registered(
    source: &NumericSignalV1,
    target: &NumericSignalSchemaV1,
    registry: &ContractRegistryV1,
) -> Result<(NumericSignalV1, RegisteredNumericConversionReceiptV1), NumericConversionError> {
    source.schema.validate_with_registry(registry)?;
    target.validate_with_registry(registry)?;
    if source.schema.normalization_digest != target.normalization_digest {
        return Err(NumericConversionError::NormalizationMismatch);
    }
    let (output, conversion) = rescale_signal(source, target)?;
    let registry_digest = registry
        .registry_digest()
        .map_err(|_| NumericConversionError::RegistryAdmission)?;
    let admission_digest = registered_admission_digest(
        registry_digest,
        source.schema.normalization_digest,
        &conversion,
    )?;
    let receipt = RegisteredNumericConversionReceiptV1 {
        conversion,
        registry_digest,
        admission_digest,
        authority: NonAuthorizingPosture::DENY_ALL,
    };
    Ok((output, receipt))
}
''',
    '''/// Backward-compatible registry validation variant. Both native numeric-profile
/// semantics and the shared normalization definition must be present in the
/// exact immutable registry supplied by the caller. The return type remains the
/// original pure arithmetic receipt; callers that need registry evidence use
/// `numeric_registry_v2::rescale_signal_registered_receipt_v1` or V2.
pub fn rescale_signal_registered(
    source: &NumericSignalV1,
    target: &NumericSignalSchemaV1,
    registry: &ContractRegistryV1,
) -> Result<(NumericSignalV1, NumericConversionReceiptV1), NumericConversionError> {
    source.schema.validate_with_registry(registry)?;
    target.validate_with_registry(registry)?;
    if source.schema.normalization_digest != target.normalization_digest {
        return Err(NumericConversionError::NormalizationMismatch);
    }
    rescale_signal(source, target)
}
''',
)

replace_exact(
    "codex-rs/hepta-types/src/numeric_conversion.rs",
    "fn registered_admission_digest(\n",
    "pub(crate) fn registered_admission_digest(\n",
)

replace_exact(
    "codex-rs/hepta-types/src/numeric_registry_v2.rs",
    "use crate::NumericConversionReceiptV1;\n",
    "use crate::NumericConversionReceiptV1;\nuse crate::RegisteredNumericConversionReceiptV1;\n",
)
replace_exact(
    "codex-rs/hepta-types/src/numeric_registry_v2.rs",
    "use crate::rescale_signal_registered;\n",
    "use crate::rescale_signal;\n",
)

insert_anchor = '''pub fn rescale_signal_registered_v2(
    source: &NumericSignalV1,
'''
insert_value = '''/// Additive V1 registry-evidence helper. The historical top-level
/// `rescale_signal_registered` signature remains unchanged for source
/// compatibility; consumers that require a distinct registry-admission receipt
/// opt into this explicitly named function.
pub fn rescale_signal_registered_receipt_v1(
    source: &NumericSignalV1,
    target: &NumericSignalSchemaV1,
    registry: &ContractRegistryV1,
) -> Result<(NumericSignalV1, RegisteredNumericConversionReceiptV1), NumericConversionError> {
    source.schema.validate_with_registry(registry)?;
    target.validate_with_registry(registry)?;
    if source.schema.normalization_digest != target.normalization_digest {
        return Err(NumericConversionError::NormalizationMismatch);
    }
    let (output, conversion) = rescale_signal(source, target)?;
    let registry_digest = registry
        .registry_digest()
        .map_err(|_| NumericConversionError::CanonicalEncoding)?;
    let admission_digest = crate::numeric_conversion::registered_admission_digest(
        registry_digest,
        source.schema.normalization_digest,
        &conversion,
    )?;
    Ok((
        output,
        RegisteredNumericConversionReceiptV1 {
            conversion,
            registry_digest,
            admission_digest,
            authority: NonAuthorizingPosture::DENY_ALL,
        },
    ))
}

pub fn rescale_signal_registered_v2(
    source: &NumericSignalV1,
'''
replace_exact(
    "codex-rs/hepta-types/src/numeric_registry_v2.rs",
    insert_anchor,
    insert_value,
)
replace_exact(
    "codex-rs/hepta-types/src/numeric_registry_v2.rs",
    "    let (output, registered_v1) = rescale_signal_registered(source, target, registry)?;\n",
    "    let (output, registered_v1) =\n        rescale_signal_registered_receipt_v1(source, target, registry)?;\n",
)

replace_exact(
    "codex-rs/hepta-ndu/src/numeric_admission.rs",
    "use codex_hepta_types::rescale_signal_registered;\n",
    "use codex_hepta_types::numeric_registry_v2::rescale_signal_registered_receipt_v1;\n",
)
replace_exact(
    "codex-rs/hepta-ndu/src/numeric_admission.rs",
    "        let (signal, admission) = rescale_signal_registered(source, &target, &self.registry)?;\n",
    "        let (signal, admission) =\n            rescale_signal_registered_receipt_v1(source, &target, &self.registry)?;\n",
)

replace_all(
    "codex-rs/hepta-types/src/numeric_conversion_tests.rs",
    "rescale_signal_registered(",
    "crate::numeric_registry_v2::rescale_signal_registered_receipt_v1(",
    3,
)

compat_test = '''

#[test]
fn registered_compatibility_api_retains_original_receipt_shape() {
    let _api: fn(
        &NumericSignalV1,
        &NumericSignalSchemaV1,
        &ContractRegistryV1,
    ) -> Result<(NumericSignalV1, NumericConversionReceiptV1), NumericConversionError> =
        rescale_signal_registered;
}
'''
path = ROOT / "codex-rs/hepta-types/src/numeric_conversion_tests.rs"
text = path.read_text(encoding="utf-8")
if "fn registered_compatibility_api_retains_original_receipt_shape()" in text:
    raise SystemExit("numeric conversion compatibility test already exists")
path.write_text(text.rstrip() + compat_test, encoding="utf-8")

print("platform.types numeric API compatibility fixup: applied")
