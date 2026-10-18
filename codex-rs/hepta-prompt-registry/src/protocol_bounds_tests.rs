use super::*;
use crate::TestMust;

fn bounded_dimensions(last_dimension_bytes: usize) -> Vec<StableId> {
    (0..63)
        .map(|index| {
            let mut value = format!("dimension:{index:03}");
            let bytes = if index == 62 {
                last_dimension_bytes
            } else {
                128
            };
            value.push_str(&"x".repeat(bytes - value.len()));
            StableId::new(value).must("bounded identifier")
        })
        .collect()
}

#[test]
fn factor_dimensions_enforce_exact_encoded_json_byte_boundary() {
    for (last_dimension_bytes, expected) in [
        (65, Ok(())),
        (66, Ok(())),
        (67, Err(ProtocolCodecError::InvalidField)),
    ] {
        let dimensions = bounded_dimensions(last_dimension_bytes);
        let encoded =
            serde_json::to_vec(&dimensions.iter().map(StableId::as_str).collect::<Vec<_>>())
                .must("canonical dimensions");
        assert_eq!(encoded.len(), 8_126 + last_dimension_bytes);
        assert_eq!(
            validate_factor_fields("bounded factor", "registered_prompt_factor", &dimensions),
            expected
        );
    }
}

#[test]
fn factor_dimensions_preserve_canonical_order_at_the_size_boundary() {
    let dimensions = bounded_dimensions(/*last_dimension_bytes*/ 66);
    let factor = PromptFactorV1 {
        factor_id: StableId::new("factor:bounded").must("factor ID"),
        semantic_purpose: "bounded factor".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: dimensions.clone(),
        lifecycle: Lifecycle::Draft,
        revision: 1,
    };
    let encoded = factor.encode_canonical_json().must("maximum factor");
    assert_eq!(
        PromptFactorV1::decode_canonical_json(&encoded).must("canonical factor"),
        factor
    );

    let mut reversed = dimensions.clone();
    reversed.swap(/*a*/ 0, /*b*/ 1);
    let mut duplicate = dimensions;
    duplicate[1] = duplicate[0].clone();
    for invalid in [reversed, duplicate] {
        assert_eq!(
            validate_factor_fields("bounded factor", "registered_prompt_factor", &invalid),
            Err(ProtocolCodecError::InvalidField)
        );
    }
}
