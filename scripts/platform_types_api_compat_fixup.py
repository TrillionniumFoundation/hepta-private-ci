#!/usr/bin/env python3
"""One-shot compatibility convergence for platform.types and named owners.

The branch already contains the additive V2 protocol surface. This migration
restores the frozen V1 public signatures and exhaustive error enums, moves the
explicit registered-receipt helper behind the public numeric_registry_v2
module, and leaves all HPTC commitments and V2 verification semantics intact.
"""

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


# NumericConversionError has already been restored to its historical exhaustive
# variant set. Refuse to run against a branch that reintroduced the temporary
# RegistryAdmission variant.
numeric_profile = (
    ROOT / "codex-rs/hepta-types/src/numeric_profile.rs"
).read_text(encoding="utf-8")
if "    RegistryAdmission,\n" in numeric_profile:
    raise SystemExit("numeric_profile.rs: temporary RegistryAdmission variant returned")

# Keep the pre-existing exhaustive topology error enum source-compatible while
# retaining canonical-order rejection and the complete HPTC commitment.
replace_exact(
    "codex-rs/hepta-types/src/topology.rs",
    "use crate::CanonicalDigestError;\n",
    "",
)
replace_exact(
    "codex-rs/hepta-types/src/topology.rs",
    '''    DuplicateModule(StableId),
    DuplicateRelatedModule(StableId),
    NonCanonicalDeltaOrder {
        previous: StableId,
        current: StableId,
    },
    NonCanonicalRelatedModuleOrder(StableId),
    InvalidDelta(StableId),
    SplitParticipantMissingAdd(StableId),
    MergeParticipantMissingRetire(StableId),
    InvalidTypeIdentity,
    Canonical(CanonicalDigestError),
''',
    '''    DuplicateModule(StableId),
    DuplicateRelatedModule(StableId),
    InvalidDelta(StableId),
    SplitParticipantMissingAdd(StableId),
    MergeParticipantMissingRetire(StableId),
''',
)
replace_exact(
    "codex-rs/hepta-types/src/topology.rs",
    '''        canonical_digest_v1(&type_id, 1, &fields)
            .map_err(RuntimeTopologyContractErrorV1::Canonical)
    }
}

impl RuntimeTopologyCandidateV1 {
''',
    '''        canonical_digest_v1(&type_id, 1, &fields).map_err(|_| {
            RuntimeTopologyContractErrorV1::InvalidDelta(self.module_id.clone())
        })
    }
}

impl RuntimeTopologyCandidateV1 {
''',
)
replace_exact(
    "codex-rs/hepta-types/src/topology.rs",
    '''        canonical_digest_v1(&type_id, 1, &fields)
            .map_err(RuntimeTopologyContractErrorV1::Canonical)
    }
}

fn topology_type_id(value: &str) -> Result<StableId, RuntimeTopologyContractErrorV1> {
''',
    '''        canonical_digest_v1(&type_id, 1, &fields)
            .map_err(|_| RuntimeTopologyContractErrorV1::CandidateShape)
    }
}

fn topology_type_id(value: &str) -> Result<StableId, RuntimeTopologyContractErrorV1> {
''',
)
replace_exact(
    "codex-rs/hepta-types/src/topology.rs",
    '''    StableId::new(value).map_err(|_| RuntimeTopologyContractErrorV1::InvalidTypeIdentity)
''',
    '''    StableId::new(value).map_err(|_| RuntimeTopologyContractErrorV1::CandidateShape)
''',
)
replace_exact(
    "codex-rs/hepta-types/src/topology.rs",
    '''                return Err(RuntimeTopologyContractErrorV1::NonCanonicalDeltaOrder {
                    previous: previous.clone(),
                    current: delta.module_id.clone(),
                });
''',
    '''                return Err(RuntimeTopologyContractErrorV1::InvalidDelta(
                    delta.module_id.clone(),
                ));
''',
)
replace_exact(
    "codex-rs/hepta-types/src/topology.rs",
    '''                return Err(
                    RuntimeTopologyContractErrorV1::NonCanonicalRelatedModuleOrder(
                        delta.module_id.clone(),
                    ),
                );
''',
    '''                return Err(RuntimeTopologyContractErrorV1::DuplicateRelatedModule(
                    delta.module_id.clone(),
                ));
''',
)
replace_exact(
    "codex-rs/hepta-types/src/topology.rs",
    "            Err(RuntimeTopologyContractErrorV1::NonCanonicalDeltaOrder { .. })\n",
    "            Err(RuntimeTopologyContractErrorV1::InvalidDelta(_))\n",
)
replace_exact(
    "codex-rs/hepta-types/src/topology.rs",
    "            Err(RuntimeTopologyContractErrorV1::NonCanonicalRelatedModuleOrder(_))\n",
    "            Err(RuntimeTopologyContractErrorV1::DuplicateRelatedModule(_))\n",
)

# Restore the historical registered-conversion signature. The additive helper
# below retains the explicit V1 registry receipt for V2 and named owners.
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
/// original pure arithmetic receipt; callers that need explicit registry
/// evidence use `numeric_registry_v2::rescale_signal_registered_receipt_v1` or V2.
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
    "use codex_hepta_types::rescale_signal_registered_receipt_v1;\n",
    "use codex_hepta_types::numeric_registry_v2::rescale_signal_registered_receipt_v1;\n",
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

# Keep the pre-existing exhaustive NDU owner error enum source-compatible. The
# registry object still exposes detailed admission errors directly; the V1 owner
# surface folds them into its existing InvalidContext variant.
replace_exact(
    "codex-rs/hepta-ndu/src/owner.rs",
    "use crate::NduNumericAdmissionErrorV1;\n",
    "",
)
replace_exact(
    "codex-rs/hepta-ndu/src/owner.rs",
    "    NumericAdmission(NduNumericAdmissionErrorV1),\n",
    "",
)
replace_exact(
    "codex-rs/hepta-ndu/src/owner.rs",
    '''impl From<NduNumericAdmissionErrorV1> for NduOwnerError {
    fn from(error: NduNumericAdmissionErrorV1) -> Self {
        Self::NumericAdmission(error)
    }
}

''',
    "",
)
replace_exact(
    "codex-rs/hepta-ndu/src/owner.rs",
    '''        let registry = self
            .numeric_registry
            .as_ref()
            .ok_or(NduNumericAdmissionErrorV1::RegistryNotConfigured)?;
        registry
            .admit_utility_signal(&self.policy.utility_profile, source)
            .map_err(NduOwnerError::NumericAdmission)
''',
    '''        let registry = self
            .numeric_registry
            .as_ref()
            .ok_or(NduOwnerError::InvalidContext(
                "numeric registry not configured",
            ))?;
        registry
            .admit_utility_signal(&self.policy.utility_profile, source)
            .map_err(|_| NduOwnerError::InvalidContext("numeric admission"))
''',
)
replace_exact(
    "codex-rs/hepta-ndu/src/owner.rs",
    '''                let admitted = registry
                    .admit_utility_axes(&self.policy.utility_profile, &contribution.utility)?;
''',
    '''                let admitted = registry
                    .admit_utility_axes(&self.policy.utility_profile, &contribution.utility)
                    .map_err(|_| NduOwnerError::InvalidContext("numeric admission"))?;
''',
)
replace_exact(
    "codex-rs/hepta-ndu/src/owner.rs",
    '''        return Err(NduOwnerError::NumericAdmission(
            NduNumericAdmissionErrorV1::EmptyRegistryDigest,
        ));
''',
    '''        return Err(NduOwnerError::InvalidContext("numeric registry digest"));
''',
)
replace_exact(
    "codex-rs/hepta-ndu/src/owner_tests.rs",
    "use crate::NduNumericAdmissionErrorV1;\n",
    "",
)
replace_exact(
    "codex-rs/hepta-ndu/src/owner_tests.rs",
    '''        Err(NduOwnerError::NumericAdmission(
            NduNumericAdmissionErrorV1::RegistryNotConfigured
        ))
''',
    '''        Err(NduOwnerError::InvalidContext(
            "numeric registry not configured"
        ))
''',
)
replace_exact(
    "codex-rs/hepta-ndu/src/owner_tests.rs",
    '''        Err(NduOwnerError::NumericAdmission(
            NduNumericAdmissionErrorV1::Conversion(
                codex_hepta_types::NumericConversionError::UnknownNormalization
            )
        ))
''',
    '''        Err(NduOwnerError::InvalidContext("numeric admission"))
''',
)
replace_exact(
    "codex-rs/hepta-ndu/src/owner_tests.rs",
    '''        Err(NduOwnerError::NumericAdmission(
            NduNumericAdmissionErrorV1::AxisIdentityMismatch
        ))
''',
    '''        Err(NduOwnerError::InvalidContext("numeric admission"))
''',
)

print("platform.types V1 API compatibility convergence: applied")
