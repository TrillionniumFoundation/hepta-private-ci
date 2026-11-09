//! Synthetic legal parameters exercise the actual child ABI and Model loader.
//! These tests supply no trained checkpoint, independent role evidence, live
//! journal, loading-authority receipt or product adoption qualification.

use codex_hepta_infer_core::joint_v4_loading_commitment_v1;

use super::init;
use super::support;
use crate::bridge_state::BridgeState;
use crate::codec::Packet;
use crate::codec::Result;
use crate::codec::sha256;
use crate::model::Model;
use crate::observation::OwnerContext;
use crate::proposal::propose;
use crate::protocol::Reader;
use crate::protocol::parse;

fn owner() -> OwnerContext {
    OwnerContext {
        required_mask: 8,
        optional_mask: 1,
        budget_total: 1_000_000,
        budget_remaining: 1_000_000,
        task_digest: [7; 32],
    }
}

fn loaded_request(fixture: &support::Fixture) -> Vec<u8> {
    let mut bytes = support::request_observed(fixture, &[], &[], init(), &owner());
    bytes[..8].copy_from_slice(b"HJREQV03");
    bytes
}

#[test]
fn loaded_request_emits_actual_model_commitment_and_v2_response_frame() -> Result<()> {
    let fixture = support::observed_fixture(support::observed_weights())?;
    let request = loaded_request(&fixture);
    let parsed = parse(&request)?;
    assert!(parsed.loading_attestation);
    let model = Model::new(Packet::decode(&fixture.weights)?)?;
    let projection = model.joint_v4_projection()?;
    let physical_hex = sha256(&fixture.weights);
    let mut physical = [0; 32];
    for (index, byte) in physical.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&physical_hex[index * 2..index * 2 + 2], /*radix*/ 16)
            .map_err(|error| error.to_string())?;
    }
    // The expected commitment consumes the actual Model's complete typed map
    // and independently hashes the exact canonical bytes sent to the child.
    let expected = joint_v4_loading_commitment_v1(physical, projection.components())?;
    let mut response = propose(&request)?;
    assert_eq!(response.loading_commitment, Some(expected));
    let encoded = response.encode()?;
    let checksum_offset = encoded.len() - 64;
    assert_eq!(
        sha256(&encoded[..checksum_offset]).as_bytes(),
        &encoded[checksum_offset..]
    );
    let mut reader = Reader::new(&encoded[..checksum_offset]);
    let header = reader.take(/*length*/ 8)?;
    let digest = reader.take(/*length*/ 32)?;
    let commitment = reader.take(/*length*/ 32)?;
    let stopped = reader.byte()?;
    let mut phases = [0; 4];
    for elapsed in &mut phases {
        *elapsed = reader.u64()?;
    }
    let state_length = reader.u32()? as usize;
    let state = reader.take(state_length)?;
    let delta_length = reader.u32()? as usize;
    let delta = reader.take(delta_length)?;
    assert_eq!(
        (header, digest, commitment, stopped, phases, state, delta),
        (
            b"HJRESV02".as_slice(),
            parsed.digest.as_slice(),
            expected.as_slice(),
            u8::from(response.stopped),
            response.phase_micros,
            response.state.as_slice(),
            response.delta.as_slice(),
        )
    );
    assert!(reader.is_empty());
    let mut wrong_physical = physical;
    wrong_physical[0] ^= 1;
    assert_ne!(
        expected,
        joint_v4_loading_commitment_v1(wrong_physical, projection.components())?
    );
    response.loading_commitment = Some([0; 32]);
    assert_eq!(response.encode(), Err("empty loading commitment".into()));
    Ok(())
}

#[test]
fn loaded_commitment_changes_with_parameters_used_by_the_real_encoder() -> Result<()> {
    let original = support::observed_weights();
    let before = support::observed_fixture(original.clone())?;
    let mut changed = original;
    *changed
        .tensors
        .get_mut("encoder_fusion.0.bias")
        .ok_or("missing encoder bias")?
        .data
        .first_mut()
        .ok_or("empty encoder bias")? = 0.25;
    let after = support::observed_fixture(changed)?;
    let before_model = Model::new(Packet::decode(&before.weights)?)?;
    let after_model = Model::new(Packet::decode(&after.weights)?)?;
    assert_ne!(
        before_model.joint_v4_projection()?.components().encoder,
        after_model.joint_v4_projection()?.components().encoder
    );
    assert_ne!(sha256(&before.weights), sha256(&after.weights));
    let before_response = propose(&loaded_request(&before))?;
    let after_response = propose(&loaded_request(&after))?;
    assert_ne!(
        before_response.loading_commitment,
        after_response.loading_commitment
    );
    assert_eq!(
        after_response.loading_commitment,
        Some(
            after_model
                .joint_v4_projection()?
                .loading_commitment_v1(&after.weights)?
        )
    );
    let before_state = BridgeState::read(
        &before_response.state,
        &before_model,
        &sha256(&before.weights),
        &sha256(&before.public),
        &[],
    )?;
    let after_state = BridgeState::read(
        &after_response.state,
        &after_model,
        &sha256(&after.weights),
        &sha256(&after.public),
        &[],
    )?;
    assert_ne!(before_state.model.context, after_state.model.context);
    Ok(())
}

#[test]
fn loaded_request_rejects_legacy_incomplete_noncanonical_and_damaged_weights() -> Result<()> {
    let legacy = support::Fixture::new()?;
    assert_eq!(
        propose(&loaded_request(&legacy)).expect_err("legacy weights cannot attest v4"),
        "model/request observation profile mismatch"
    );
    let mut missing = support::observed_weights();
    missing.tensors.remove("text_condition.bias");
    assert!(propose(&loaded_request(&support::observed_fixture(missing)?)).is_err());
    let mut fixture = support::observed_fixture(support::observed_weights())?;
    let canonical = fixture.weights.clone();
    let checksum_offset = canonical.len() - 64;
    // Swap two intact metadata entries and recompute the valid packet checksum.
    // Decoding still yields the identical map; canonical admission must reject.
    let mut reader = Reader::new(&canonical[..checksum_offset]);
    assert_eq!(reader.take(/*length*/ 8)?, b"HEPTAPK3");
    assert!(reader.u32()? >= 2);
    let mut offset = 12;
    let mut entries = Vec::new();
    for _ in 0..2 {
        let start = offset;
        for _ in 0..2 {
            let length = reader.u32()? as usize;
            reader.take(length)?;
            offset += 4 + length;
        }
        entries.push(start..offset);
    }
    let mut noncanonical = canonical[..12].to_vec();
    noncanonical.extend_from_slice(&canonical[entries[1].clone()]);
    noncanonical.extend_from_slice(&canonical[entries[0].clone()]);
    noncanonical.extend_from_slice(&canonical[offset..checksum_offset]);
    let checksum = sha256(&noncanonical);
    noncanonical.extend_from_slice(checksum.as_bytes());
    assert_eq!(Packet::decode(&noncanonical)?, Packet::decode(&canonical)?);
    fixture.weights = noncanonical;
    assert_eq!(
        propose(&loaded_request(&fixture)).expect_err("noncanonical physical packet"),
        "noncanonical asset packet"
    );
    fixture.weights = canonical;
    fixture.weights[0] ^= 1;
    assert_eq!(
        propose(&loaded_request(&fixture)).expect_err("damaged physical packet"),
        "packet checksum mismatch"
    );
    Ok(())
}

#[test]
fn legacy_observed_request_keeps_v1_response_and_identical_state_behavior() -> Result<()> {
    let fixture = support::observed_fixture(support::observed_weights())?;
    let legacy_request = support::request_observed(&fixture, &[], &[], init(), &owner());
    assert!(!parse(&legacy_request)?.loading_attestation);
    let legacy = propose(&legacy_request)?;
    let loaded = propose(&loaded_request(&fixture))?;
    assert_eq!(legacy.loading_commitment, None);
    assert!(loaded.loading_commitment.is_some());
    assert_eq!(&legacy.encode()?[..8], b"HJRESV01");
    // The new response proof does not silently change the old state ABI or
    // numeric behavior. Real observed wall intervals are intentionally separate.
    assert_eq!(
        (&legacy.digest, legacy.stopped, &legacy.state, &legacy.delta),
        (&loaded.digest, loaded.stopped, &loaded.state, &loaded.delta)
    );
    Ok(())
}
