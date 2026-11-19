use super::*;

use crate::strict::ValidateStrictV1;

fn assert_legacy_roundtrip<T: CognitiveContractV1 + std::fmt::Debug>(
    value: &T,
) -> Result<(), CognitiveWireError> {
    let before = canonical_contract_digest_v1(value)?;
    let wire = encode_wire_v1(value)?;
    let decoded = decode_wire_v1::<T>(&wire)?;
    assert_eq!(&decoded, value);
    assert_eq!(canonical_contract_digest_v1(&decoded)?, before);
    Ok(())
}

#[test]
fn wire_v1_keeps_zero_weight_synapse_while_strict_profile_rejects_it()
-> Result<(), CognitiveWireError> {
    let mut value = synapse();
    value.weight_q16 = 0;
    assert_legacy_roundtrip(&value)?;
    assert_eq!(
        value.validate_strict_v1(),
        Err(HnmfContractError::Conflict("synapse relation/weight sign"))
    );
    Ok(())
}

#[test]
fn wire_v1_keeps_empty_plasticity_while_strict_profile_rejects_it() -> Result<(), CognitiveWireError>
{
    let mut value = plasticity();
    value.weight_proposals.clear();
    value.threshold_proposals.clear();
    assert_legacy_roundtrip(&value)?;
    assert_eq!(
        value.validate_strict_v1(),
        Err(HnmfContractError::Invalid("empty plasticity batch"))
    );
    Ok(())
}

#[test]
fn wire_v1_keeps_empty_forget_receipt_while_strict_profile_rejects_it()
-> Result<(), CognitiveWireError> {
    let mut value = forget();
    value.retired_node_ids.clear();
    value.retired_synapses.clear();
    assert_legacy_roundtrip(&value)?;
    assert_eq!(
        value.validate_strict_v1(),
        Err(HnmfContractError::Invalid("empty forget propagation"))
    );
    Ok(())
}

#[test]
fn wire_v1_keeps_legacy_topology_delta_while_strict_profile_checks_cardinality()
-> Result<(), CognitiveWireError> {
    let mut value = topology();
    value.resource_delta.node_delta = 2;
    assert_legacy_roundtrip(&value)?;
    assert_eq!(
        value.validate_strict_v1(),
        Err(HnmfContractError::Conflict("topology node delta"))
    );
    Ok(())
}

#[test]
fn explicit_strict_profile_preserves_valid_zero_origin_and_replay_values()
-> Result<(), Box<dyn std::error::Error>> {
    // These existing fixtures exercise the historical d0a4d093 correction:
    // zero eligibility and zero old weight are legitimate, independently of
    // the stricter policy's nonzero resulting weight requirement.
    let synapse = synapse();
    let plasticity = plasticity();
    let replay = replay_receipt();
    synapse.validate_strict_v1()?;
    plasticity.validate_strict_v1()?;
    replay.validate_strict_v1()?;
    assert_legacy_roundtrip(&synapse)?;
    assert_legacy_roundtrip(&plasticity)?;
    assert_legacy_roundtrip(&replay)?;
    Ok(())
}
