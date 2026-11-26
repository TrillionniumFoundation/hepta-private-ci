//! Synthetic signatures only; production credentials and holdout are absent.
#![allow(clippy::unwrap_used)]
use super::*;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::inputs;
use crate::paired_supervised_test_support::runner;
use pretty_assertions::assert_eq;

fn fixture() -> (SigningFixture, IndependentEvaluationBundleV1, Vec<u8>) {
    let plan = crate::freeze_paired_supervised_plan_v1(inputs(6)).unwrap();
    let signing = SigningFixture::new(false);
    let execution = runner()
        .evaluate_paired_with_clock(
            &signing.register(&plan),
            &mut signing.provider(&plan),
            &signing.trust,
            &mut crate::paired_supervised_host_clock::PairedHostClockV1::fixture(&[30]),
        )
        .unwrap();
    let bundle =
        crate::paired_supervised_qualification::paired_bundle(&execution, &signing.context())
            .unwrap();
    let mut payload = CANDIDATE.to_vec();
    for value in [
        "original-envelope",
        bundle.candidate_id.as_str(),
        bundle.generator.principal_id.as_str(),
        "original-canary",
        bundle.baseline_id.as_str(),
    ] {
        payload.extend_from_slice(&(value.len() as u64).to_be_bytes());
        payload.extend_from_slice(value.as_bytes());
    }
    let mut identities = [digest("original-owner-identity"); 18];
    identities[2] = bundle.objective_digest;
    identities[5] = bundle.frozen_plan.plan_digest;
    for identity in identities {
        payload.extend_from_slice(identity.as_array());
    }
    for value in [1_u64, 2, 4096, 2, 1, 1, 1, 1_000_000] {
        payload.extend_from_slice(&value.to_be_bytes());
    }
    (signing, bundle, payload)
}

#[test]
fn consumer_is_derived_from_current_original_generator_bytes() {
    let (signing, bundle, payload) = fixture();
    let evidence = signing.sign(0, &payload, 25);
    let bytes = encode_self_iteration_frozen_consumer_v1(&payload, &evidence).unwrap();
    let consumer =
        decode_self_iteration_frozen_consumer_v1(&bytes, &bundle, &signing.trust, 30).unwrap();
    assert_eq!(consumer.frozen_digest(), Digest32::of_bytes(&payload));
    assert_eq!(consumer.expires_at(), evidence.expires_at);
    assert_eq!(consumer.generator().principal(), &bundle.generator);
    assert!(
        decode_self_iteration_frozen_consumer_v1(&bytes, &bundle, &signing.trust, 801,).is_err()
    );
}

#[test]
fn authenticated_other_plan_or_baseline_cannot_name_the_consumer() {
    let (signing, bundle, payload) = fixture();
    let bytes =
        encode_self_iteration_frozen_consumer_v1(&payload, &signing.sign(0, &payload, 25)).unwrap();
    for change in 0..4 {
        let mut other = bundle.clone();
        match change {
            0 => other.candidate_id = StableId::new("another-candidate").unwrap(),
            1 => other.baseline_id = StableId::new("another-baseline").unwrap(),
            2 => other.objective_digest = digest("another-objective"),
            3 => other.frozen_plan.plan_digest = digest("another-plan"),
            _ => unreachable!(),
        }
        assert!(
            decode_self_iteration_frozen_consumer_v1(&bytes, &other, &signing.trust, 30,).is_err(),
            "change {change}"
        );
    }
}

#[test]
fn signed_unbounded_or_noncanonical_candidate_and_other_role_are_rejected() {
    let (signing, bundle, payload) = fixture();
    let values_start = payload.len() - 64;
    for change in 0..4 {
        let mut changed = payload.clone();
        match change {
            0 => changed.push(0),
            1 => {
                changed[values_start + 8..values_start + 16].copy_from_slice(&101_u64.to_be_bytes())
            }
            2 => {
                changed[values_start + 40..values_start + 48].copy_from_slice(&0_u64.to_be_bytes())
            }
            3 => changed[values_start + 56..values_start + 64]
                .copy_from_slice(&10_000_001_u64.to_be_bytes()),
            _ => unreachable!(),
        }
        let bytes =
            encode_self_iteration_frozen_consumer_v1(&changed, &signing.sign(0, &changed, 25))
                .unwrap();
        assert!(
            decode_self_iteration_frozen_consumer_v1(&bytes, &bundle, &signing.trust, 30,).is_err(),
            "change {change}"
        );
    }
    assert!(
        encode_self_iteration_frozen_consumer_v1(&payload, &signing.sign(1, &payload, 25),)
            .is_err()
    );
    let mut tampered =
        encode_self_iteration_frozen_consumer_v1(&payload, &signing.sign(0, &payload, 25)).unwrap();
    *tampered.last_mut().unwrap() ^= 1;
    assert!(
        decode_self_iteration_frozen_consumer_v1(&tampered, &bundle, &signing.trust, 30,).is_err()
    );
}

#[test]
fn full_canonical_bytes_and_actual_model_receipt_are_authenticated_in_explicit_v2() {
    let (signing, bundle, legacy) = fixture();
    let canonical = br#"{"allowedPaths":["original/store"],"allFields":"retained"}"#.repeat(1024);
    let round = br#"{"goal":"actual.goal","ordinal":9,"originalOwner":"retained"}"#;
    let request = "iteration.actual.goal.round.9.generator";
    let native = digest("actual original model terminal");
    let mut payload = CANONICAL_CANDIDATE.to_vec();
    payload.extend_from_slice(&(canonical.len() as u64).to_be_bytes());
    payload.extend_from_slice(&canonical);
    payload.extend_from_slice(&(round.len() as u64).to_be_bytes());
    payload.extend_from_slice(round);
    payload.extend_from_slice(&(request.len() as u64).to_be_bytes());
    payload.extend_from_slice(request.as_bytes());
    payload.extend_from_slice(native.as_array());
    payload.extend_from_slice(digest("actual model output").as_array());
    payload.extend_from_slice(&legacy);
    // Presign parsing needs no invented signature; authority remains absent.
    let unsigned = inspect_unsigned_self_iteration_candidate_v1(&payload, 30).unwrap();
    assert_eq!(unsigned.payload_digest(), Digest32::of_bytes(&payload));
    assert_eq!(
        unsigned.generator_round_payload_digest(),
        Some(Digest32::of_bytes(round))
    );
    assert_eq!(
        unsigned.generator_model_request_id().unwrap().as_str(),
        request
    );
    assert_eq!(
        unsigned.canonical_envelope_bytes(),
        Some(canonical.as_slice())
    );
    let bytes =
        encode_self_iteration_frozen_consumer_v1(&payload, &signing.sign(0, &payload, 25)).unwrap();
    let verified =
        decode_self_iteration_frozen_consumer_v1(&bytes, &bundle, &signing.trust, 30).unwrap();
    assert_eq!(
        verified.canonical_envelope_bytes(),
        Some(canonical.as_slice())
    );
    assert_eq!(
        verified.canonical_envelope_digest(),
        Some(Digest32::of_bytes(&canonical))
    );
    assert_eq!(
        verified.generator_model_request_id().unwrap().as_str(),
        request
    );
    assert_eq!(verified.generator_native_run_digest(), Some(native));
    assert_eq!(verified.generator_round_bytes(), Some(round.as_slice()));
    assert_eq!(
        verified.generator_model_output_digest(),
        Some(digest("actual model output"))
    );
    let offset =
        CANONICAL_CANDIDATE.len() + 8 + canonical.len() + 8 + round.len() + 8 + request.len();
    let mut missing = payload.clone();
    missing[offset..offset + 32].fill(0);
    let bytes =
        encode_self_iteration_frozen_consumer_v1(&missing, &signing.sign(0, &missing, 25)).unwrap();
    assert!(decode_self_iteration_frozen_consumer_v1(&bytes, &bundle, &signing.trust, 30).is_err());
    let mut tampered =
        encode_self_iteration_frozen_consumer_v1(&payload, &signing.sign(0, &payload, 25)).unwrap();
    let offset = tampered
        .windows(canonical.len())
        .position(|window| window == canonical.as_slice())
        .unwrap();
    tampered[offset] ^= 1;
    assert!(
        decode_self_iteration_frozen_consumer_v1(&tampered, &bundle, &signing.trust, 30).is_err()
    );
}

#[test]
fn unsigned_fields_preserve_the_whole_original_tuple_without_authenticating_g() {
    let (signing, bundle, mut payload) = fixture();
    let digest_start = payload.len() - 64 - 18 * 32;
    let expected: Vec<_> = (0..18)
        .map(|index| digest(&format!("presign-field-{index}")))
        .collect();
    for (index, value) in expected.iter().enumerate() {
        payload[digest_start + index * 32..digest_start + (index + 1) * 32]
            .copy_from_slice(value.as_array());
    }
    let view = inspect_unsigned_self_iteration_candidate_v1(&payload, 30).unwrap();
    assert_eq!(
        [
            view.envelope_id().as_str(),
            view.candidate_id().as_str(),
            view.generator_id().as_str(),
            view.canary_tick_id().as_str(),
            view.baseline_id().as_str()
        ],
        [
            "original-envelope",
            bundle.candidate_id.as_str(),
            bundle.generator.principal_id.as_str(),
            "original-canary",
            bundle.baseline_id.as_str()
        ]
    );
    assert_eq!(
        [
            view.base_commit(),
            view.base_tree(),
            view.objective_digest(),
            view.grammar_digest(),
            view.semantic_diff_digest(),
            view.test_plan_digest(),
            view.rollback_digest(),
            view.governed_proposal_digest(),
            view.governed_anchor_digest(),
            view.governed_composition_digest(),
            view.canary_snapshot_digest(),
            view.canary_candidate_set_digest(),
            view.canary_predecessor_digest(),
            view.successor_body(),
            view.rollback_body(),
            view.successor_configuration(),
            view.rollback_configuration(),
            view.canary_input_digest()
        ]
        .as_slice(),
        expected.as_slice()
    );
    assert_eq!(
        [
            view.base_generation(),
            view.maximum_files(),
            view.maximum_diff_bytes(),
            view.candidate_admissions(),
            view.maximum_parallel_sandboxes(),
            view.expires_unix_seconds(),
            view.changed_files(),
            view.canary_budget_micros()
        ],
        [1, 2, 4096, 2, 1, 1, 1, 1_000_000]
    );
    let mut signature = signing.sign(0, &payload, 25);
    signature.signature[0] ^= 1;
    let publication = encode_self_iteration_frozen_consumer_v1(&payload, &signature).unwrap();
    assert!(
        inspect_signed_self_iteration_frozen_consumer_v1(&publication, &signing.trust, 30).is_err()
    );
    assert!(inspect_unsigned_self_iteration_candidate_v1(&payload, 1000).is_err());
    payload.push(0);
    assert!(inspect_unsigned_self_iteration_candidate_v1(&payload, 30).is_err());
}
