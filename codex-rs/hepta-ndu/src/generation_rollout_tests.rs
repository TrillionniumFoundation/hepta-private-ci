use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::GenerationRolloutError;
use super::GenerationRolloutPinsV1;
use super::evaluate_generation_rollout_v1;
use crate::CandidateRejectionReason;
use crate::EvaluationDisposition;
use crate::RejectedCandidate;

fn fixture() -> (String, GenerationRolloutPinsV1) {
    let pins = GenerationRolloutPinsV1 {
        objective_digest: Digest32::of_bytes(b"objective"),
        source_bundle_digest: Digest32::of_bytes(b"source"),
        model_snapshot_digest: Digest32::of_bytes(b"model"),
    };
    let metric = Digest32::of_bytes(b"fixed external metric");
    let scope = format!(
        "scope\t{}\t{}\t{}\tepisode:heldout-1\t1\t3\t10\t1000000000\t2147483648\t{metric}",
        pins.objective_digest, pins.source_bundle_digest, pins.model_snapshot_digest,
    );
    let scope_digest = Digest32::of_bytes(scope.as_bytes());
    let empty = Digest32::of_bytes(b"");
    let evidence = Digest32::of_bytes(b"completed joint text-image execution");
    let input = format!(
        "hepta.ndu.generation-rollout.v1\n{scope}\ncandidate\tabstain\t0\tfeasible\t0\t0\t0\t0\t{empty}\t{scope_digest}\ncandidate\tjoint\t3\tfeasible\t2147483648\t1073741824\t4\t123456789\t{evidence}\t{scope_digest}\n",
    );
    (input, pins)
}

#[test]
fn completed_joint_rollout_reaches_actual_policy_bound_owner() {
    let (input, pins) = fixture();
    let receipt = evaluate_generation_rollout_v1(&input, pins).expect("valid rollout");
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(receipt.input_digest, Digest32::of_bytes(input.as_bytes()));
    assert_eq!(
        (
            receipt.evaluation.base.disposition,
            receipt.evaluation.base.advisory_recommendation
        ),
        (
            EvaluationDisposition::UniqueParetoRecommendation,
            Some(super::id("joint").expect("ID"))
        ),
    );
    assert!(!receipt.evaluation.evaluation_digest_v2.is_zero());
}

#[test]
fn high_utility_cannot_override_missing_required_output_or_hard_violation() {
    let (input, pins) = fixture();
    for modified in [
        input.replace("joint\t3\tfeasible", "joint\t1\tfeasible"),
        input.replace("joint\t3\tfeasible", "joint\t3\thard_violation"),
    ] {
        let receipt = evaluate_generation_rollout_v1(&modified, pins).expect("evaluated rejection");
        assert_eq!(
            receipt.evaluation.base.rejected_candidates,
            vec![RejectedCandidate {
                candidate_id: super::id("joint").expect("ID"),
                reasons: vec![CandidateRejectionReason::HardConstraintViolation],
            }]
        );
        assert_eq!(
            receipt.evaluation.base.disposition,
            EvaluationDisposition::InfeasibleExplicitAbstain
        );
    }
}

#[test]
fn modeled_units_and_physical_time_have_independent_hard_ceilings() {
    let (input, pins) = fixture();
    for modified in [
        input.replace("\t4\t123456789\t", "\t11\t123456789\t"),
        input.replace("\t4\t123456789\t", "\t4\t1000000001\t"),
    ] {
        let receipt = evaluate_generation_rollout_v1(&modified, pins).expect("evaluated rejection");
        assert_eq!(
            receipt.evaluation.base.rejected_candidates,
            vec![RejectedCandidate {
                candidate_id: super::id("joint").expect("ID"),
                reasons: vec![CandidateRejectionReason::ResourceCeilingExceeded],
            }]
        );
    }
}

#[test]
fn frozen_scope_pins_and_per_row_scope_digest_reject_transplants() {
    let (input, mut pins) = fixture();
    pins.model_snapshot_digest = Digest32::of_bytes(b"another model");
    assert_eq!(
        evaluate_generation_rollout_v1(&input, pins),
        Err(GenerationRolloutError::InvalidField("frozen pins"))
    );
    let (input, pins) = fixture();
    let transplanted = input.replace("episode:heldout-1", "episode:heldout-2");
    assert_eq!(
        evaluate_generation_rollout_v1(&transplanted, pins),
        Err(GenerationRolloutError::InvalidField(
            "candidate scope digest"
        ))
    );
}

#[test]
fn exact_abstain_is_required_and_cannot_be_a_hidden_generation() {
    let (input, pins) = fixture();
    let missing = input
        .lines()
        .filter(|line| !line.starts_with("candidate\tabstain\t"))
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";
    assert_eq!(
        evaluate_generation_rollout_v1(&missing, pins),
        Err(GenerationRolloutError::InvalidField("missing abstain"))
    );
    let hidden_effect = input.replace(
        "abstain\t0\tfeasible\t0\t0\t0\t0",
        "abstain\t0\tfeasible\t0\t0\t1\t0",
    );
    assert_eq!(
        evaluate_generation_rollout_v1(&hidden_effect, pins),
        Err(GenerationRolloutError::InvalidField(
            "exact zero-effect abstain"
        ))
    );
}

#[test]
fn fabricated_zero_time_and_duplicate_support_are_not_admitted() {
    let (input, pins) = fixture();
    let unmeasured = input.replace("\t123456789\t", "\t0\t");
    assert_eq!(
        evaluate_generation_rollout_v1(&unmeasured, pins),
        Err(GenerationRolloutError::InvalidField(
            "unobserved active candidate"
        ))
    );
    let original = input.lines().last().expect("candidate");
    let duplicate_support =
        input.clone() + &original.replace("candidate\tjoint\t", "candidate\tother\t") + "\n";
    assert_eq!(
        evaluate_generation_rollout_v1(&duplicate_support, pins),
        Err(GenerationRolloutError::InvalidField(
            "candidate values or duplicate support"
        ))
    );
}

#[test]
fn replay_is_deterministic_but_changed_execution_changes_native_receipt() {
    let (input, pins) = fixture();
    let original = evaluate_generation_rollout_v1(&input, pins).expect("valid");
    assert_eq!(
        original,
        evaluate_generation_rollout_v1(&input, pins).expect("replay")
    );
    let changed = input.replace("\t123456789\t", "\t123456790\t");
    let modified = evaluate_generation_rollout_v1(&changed, pins).expect("changed measurement");
    assert_ne!(
        original.evaluation.evaluation_digest_v2,
        modified.evaluation.evaluation_digest_v2
    );
}

#[test]
fn transport_rejects_ambiguous_numbers_extra_fields_and_empty_rows() {
    let (input, pins) = fixture();
    for invalid in [
        input.replace("\t123456789\t", "\t0123456789\t"),
        input.replace("joint\t3\t", "joint\t3\textra\t"),
        input.clone() + "\n",
        input.replace('\n', "\r\n"),
    ] {
        assert!(evaluate_generation_rollout_v1(&invalid, pins).is_err());
    }
}
