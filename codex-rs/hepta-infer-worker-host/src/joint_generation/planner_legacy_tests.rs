use super::support;
use crate::bridge_state::BridgeState;
use crate::codec::Packet;
use crate::codec::Result;
use crate::codec::sha256;
use crate::model::Model;
use crate::observation::OwnerContext;
use crate::planner;
use crate::protocol::Command;
use crate::protocol::EmissionLaw;
use crate::protocol::Sampler;

fn legacy_bridge_roundtrip(profile: &str) -> Result<()> {
    let mut weights = support::observed_weights();
    weights
        .meta
        .insert("inference_profile".into(), profile.into());
    let fixture = support::observed_fixture(weights.clone())?;
    let model = Model::new(weights)?;
    let owner = OwnerContext {
        required_mask: 8,
        optional_mask: 1,
        budget_total: 1_000_000,
        budget_remaining: 1_000_000,
        task_digest: [9; 32],
    };
    let initial = crate::proposal::propose(&support::request_observed(
        &fixture,
        &[],
        &[],
        Command::Init(EmissionLaw {
            seed: 3,
            sampler: Sampler::Mean,
        }),
        &owner,
    ))?;
    let advanced = crate::proposal::propose(&support::request_observed(
        &fixture,
        &initial.state,
        &[],
        Command::Auto(1_000_000),
        &owner,
    ))?;
    assert!(!advanced.stopped);
    let weights_hash = sha256(&fixture.weights);
    let input_hash = sha256(&fixture.public);
    let packet = Packet::decode(&advanced.state)?;
    let risk_keys = [
        "planning.risk_semantics",
        "planning.risk_parameter",
        "planning.support_particles",
    ];
    // Missing only part of the triplet is malformed, not a legacy packet.
    for key in risk_keys {
        let mut partial = packet.clone();
        assert!(partial.meta.remove(key).is_some());
        assert!(
            BridgeState::read(
                &partial.encode()?,
                &model,
                &weights_hash,
                &input_hash,
                &advanced.delta,
            )
            .is_err()
        );
    }
    // Older v4 snapshots contain the complete original planning receipt but
    // none of the additive risk fields. Their canonical bytes must survive.
    let mut legacy = packet;
    for key in risk_keys {
        assert!(legacy.meta.remove(key).is_some());
    }
    let legacy_bytes = legacy.encode()?;
    let restored = BridgeState::read(
        &legacy_bytes,
        &model,
        &weights_hash,
        &input_hash,
        &advanced.delta,
    )?;
    let receipt = restored.planning.as_ref().ok_or("missing legacy receipt")?;
    assert_eq!(receipt.profile, profile);
    assert_eq!(
        receipt.risk_evidence,
        planner::RiskEvidence::LegacyUnrecorded
    );
    assert_eq!(
        restored.encode(&weights_hash, &input_hash, &advanced.delta)?,
        legacy_bytes
    );
    // The next explicit planning operation may write new metadata. Loading
    // the older receipt itself must not alter continuation or delivery.
    let resume = |state: &[u8]| {
        crate::proposal::propose(&support::request_observed(
            &fixture,
            state,
            &advanced.delta,
            Command::Auto(1_000_000),
            &owner,
        ))
    };
    let resumed_legacy = resume(&legacy_bytes)?;
    let resumed_current = resume(&advanced.state)?;
    assert_eq!(
        (
            resumed_legacy.state,
            resumed_legacy.delta,
            resumed_legacy.stopped,
        ),
        (
            resumed_current.state,
            resumed_current.delta,
            resumed_current.stopped,
        )
    );
    Ok(())
}

#[test]
fn legacy_actor_receipt_roundtrips_full_bridge_and_resumes() -> Result<()> {
    legacy_bridge_roundtrip(planner::ACTOR_PROFILE)
}

#[test]
fn legacy_ndu_receipt_roundtrips_full_bridge_and_resumes() -> Result<()> {
    legacy_bridge_roundtrip(planner::NDU_PROFILE)
}
