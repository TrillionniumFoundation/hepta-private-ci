//! Structural record tests only. These data fixtures cannot call the actual
//! Root acceptance producer, execute B or construct a historical capability.

use pretty_assertions::assert_eq;

use super::super::super::provider::OriginalBReleasedSource;
use super::super::OriginalBOutputHeads;
use super::*;

fn record_data() -> io::Result<OriginalBEnrollment> {
    let source = OriginalBReleasedSource::from_original_digests(
        Digest32::from_array([21; 32]),
        Digest32::from_array([22; 32]),
        Digest32::from_array([23; 32]),
    );
    Ok(OriginalBEnrollment {
        initial_head: [1; 32],
        protocol: [2; 32],
        trust: [3; 32],
        deployment: [4; 32],
        protocol_statement: [5; 32],
        files: vec![serde_json::from_value(serde_json::json!({
            "device": 1, "inode": 2,
        }))?],
        registered_at_seconds: 100,
        expires_at_seconds: 300,
        namespace: [6; 32],
        original_generation: 1,
        original_lease: [7; 32],
        heads: Some(OriginalBOutputHeads {
            holdout_generation: 1,
            holdout_records: 2,
            holdout_state: [8; 32],
            execution_sequence: 3,
            execution_history: [9; 32],
        }),
        cell_images: Some(vec![[10; 32], [11; 32]]),
        realized_training_head: Some([12; 32]),
        realized_plan: Some([13; 32]),
        completed_receipt: Some([14; 32]),
        released_source: Some(source.clone()),
        output_images: vec![[15; 32], [16; 32]],
        realized_plan_statement: Some([17; 32]),
        original_training_attestation: Some(vec![18, 19]),
        // Deliberately not an authenticated native result. This test only
        // checks that its exact bytes are part of the immutable record cut.
        original_training_work: Some(serde_json::from_value(serde_json::json!({
            "prefix": [20], "epochs": 2, "learning_rate_q24": 1,
        }))?),
        admitted_source: Some(source),
        completed_acceptance: None,
    })
}

fn structural_acceptance(
    original: &OriginalBEnrollment,
) -> io::Result<OriginalBCompletedAcceptanceV1> {
    Ok(OriginalBCompletedAcceptanceV1 {
        schema: 1,
        frozen_scope: [24; 32],
        root_verified_at_seconds: 150,
        native_verified_at_seconds: 149,
        training_attestation: Digest32::of_bytes(
            original
                .original_training_attestation
                .as_ref()
                .ok_or_else(|| io::Error::other("test signature data missing"))?,
        )
        .into_array(),
        evaluation_attestation: [25; 32],
        enrollment_cut: original.completed_enrollment_cut()?.into_array(),
    })
}

#[test]
fn independent_b_acceptance_rejects_completed_records_without_original_fact() -> io::Result<()> {
    let mut original = record_data()?;
    assert!(original.require_completed_acceptance().is_err());
    original.completed_acceptance = Some(structural_acceptance(&original)?);
    original.require_completed_acceptance()?;
    original.completed_receipt = None;
    assert!(original.require_completed_acceptance().is_err());
    original.completed_acceptance = None;
    original.require_completed_acceptance()?;
    Ok(())
}

#[test]
fn independent_b_acceptance_binds_every_original_receipt_and_physical_cut() -> io::Result<()> {
    let original = record_data()?;
    let proof = structural_acceptance(&original)?;
    proof.require_original(&original)?;
    let encoded = serde_json::to_value(&original)?;
    for (field, value) in [
        ("initial_head", serde_json::to_value([31; 32])?),
        ("trust", serde_json::to_value([32; 32])?),
        ("protocol_statement", serde_json::to_value([33; 32])?),
        ("original_lease", serde_json::to_value([34; 32])?),
        ("files", serde_json::json!([{ "device": 1, "inode": 3 }])),
        ("cell_images", serde_json::to_value(vec![[35; 32]])?),
        ("output_images", serde_json::to_value(vec![[36; 32]])?),
        ("completed_receipt", serde_json::to_value([37; 32])?),
        ("original_training_attestation", serde_json::json!([18, 20])),
        ("realized_plan_statement", serde_json::to_value([38; 32])?),
        ("admitted_source", serde_json::Value::Null),
    ] {
        let mut changed = encoded.clone();
        changed[field] = value;
        let changed: OriginalBEnrollment = serde_json::from_value(changed)?;
        assert!(proof.require_original(&changed).is_err(), "{field}");
    }
    let mut changed = original.clone();
    changed.original_training_work = None;
    assert!(proof.require_original(&changed).is_err());
    assert_eq!(serde_json::to_value(&original)?, encoded);
    Ok(())
}

#[test]
fn independent_b_acceptance_rejects_times_outside_original_verification() -> io::Result<()> {
    let original = record_data()?;
    let proof = structural_acceptance(&original)?;
    for (root, native) in [(99, 99), (300, 149), (150, 99), (150, 151)] {
        let mut changed = proof.clone();
        changed.root_verified_at_seconds = root;
        changed.native_verified_at_seconds = native;
        assert!(changed.require_original(&original).is_err());
    }
    let mut changed = proof.clone();
    changed.frozen_scope = [0; 32];
    assert!(changed.require_original(&original).is_err());
    let mut changed = proof.clone();
    changed.evaluation_attestation = [0; 32];
    assert!(changed.require_original(&original).is_err());
    proof.require_original(&original)?;
    Ok(())
}

#[test]
fn independent_b_acceptance_data_roundtrip_preserves_cut_and_rejects_unknown_fields()
-> io::Result<()> {
    let mut original = record_data()?;
    original.completed_acceptance = Some(structural_acceptance(&original)?);
    let bytes = serde_json::to_vec(&original)?;
    let decoded: OriginalBEnrollment = serde_json::from_slice(&bytes)?;
    decoded.require_completed_acceptance()?;
    assert_eq!(decoded, original);
    let mut unknown = serde_json::to_value(&original)?;
    unknown["completed_acceptance"]["caller_claimed_verified_at"] = serde_json::json!(150);
    assert!(serde_json::from_value::<OriginalBEnrollment>(unknown).is_err());
    Ok(())
}
