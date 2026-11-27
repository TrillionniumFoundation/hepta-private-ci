use super::*;

#[test]
fn added_error_categories_keep_checked_diagnostic_bounds() {
    assert!(
        ContractViolationV1::new(ContractErrorCodeV1::EmptyDigest, "", "missing digest",).is_err()
    );
    assert!(
        ContractViolationV1::new(
            ContractErrorCodeV1::ContractMismatch,
            "consumer",
            "x".repeat(MAX_CONTRACT_DETAIL_BYTES + 1),
        )
        .is_err()
    );
    let violation = ContractViolationV1::new(
        ContractErrorCodeV1::EmptyDigest,
        "legacyDigest",
        "legacy shadow digest must be non-zero",
    )
    .expect("bounded canonical diagnostic");
    assert_eq!(violation.field_path.as_str(), "legacyDigest");
}

#[derive(Debug, PartialEq)]
struct StructuralValue(bool);

impl ValidateStructuralContractV1 for StructuralValue {
    type Error = &'static str;

    fn validate_structural_contract_v1(&self) -> Result<(), Self::Error> {
        if self.0 {
            Ok(())
        } else {
            Err("invalid structure")
        }
    }
}

#[test]
fn structural_adapter_preserves_owner_error_and_checked_construction() {
    assert_eq!(
        Validated::from_structural_contract(StructuralValue(false)),
        Err("invalid structure")
    );
    let value =
        Validated::from_structural_contract(StructuralValue(true)).expect("valid structure");
    assert_eq!(value.as_inner(), &StructuralValue(true));
    assert_eq!(AsRef::<StructuralValue>::as_ref(&value), value.as_inner());
}
