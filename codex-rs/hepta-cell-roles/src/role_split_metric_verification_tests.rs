use super::*;
use pretty_assertions::assert_eq;

use crate::role_split_admission::tests::metrics;
use crate::role_split_admission::tests::profile;
use crate::role_split_admission::tests::split;

struct Fixture {
    split: CellSplitV1,
    profile: CellRoleMetricProfileV1,
    metrics: CellRoleMetricReceiptV1,
    bindings: RoleSplitMetricBindingSetV1,
    receipt: RoleSplitMetricAdmissionReceiptV1,
}

fn fixture() -> Fixture {
    let split = split();
    let profile = profile();
    let metrics = metrics(&split, &profile);
    let bindings = RoleSplitMetricBindingSetV1 {
        role: profile.role,
        profile_digest: profile.content_digest().expect("profile"),
        metric_receipt_digest: metrics.content_digest(&profile).expect("metrics"),
        observations: metrics
            .metrics
            .iter()
            .map(|metric| RoleSplitMetricObservationBindingV1 {
                kind: metric.kind,
                observation_digest: metric.observation_digest,
            })
            .collect(),
        authority: AuthorityPosture::DENY_ALL,
    };
    let receipt = RoleSplitMetricAdmissionV1::admit(&split, &profile, &metrics, bindings.clone())
        .expect("admission");
    Fixture {
        split,
        profile,
        metrics,
        bindings,
        receipt,
    }
}

#[test]
fn replay_preserves_valid_complete_split_and_metric_identity() {
    let value = fixture();
    assert_eq!(
        value.receipt.verify(
            &value.split,
            &value.profile,
            &value.metrics,
            &value.bindings
        ),
        Ok(())
    );
    assert_eq!(value.receipt.authority, AuthorityPosture::DENY_ALL);
}

fn assert_metric_identity_rejected(field: &str) {
    let mut value = fixture();
    match field {
        "cell" => value.metrics.cell_id = StableId::new("other.cell").expect("cell"),
        "generation" => {
            value.metrics.generation = value.metrics.generation.next().expect("generation");
        }
        "proposer" => {
            value.metrics.proposer_id = StableId::new("other.proposer").expect("proposer");
        }
        "evaluator" => {
            value.metrics.evaluator_id = StableId::new("other.evaluator").expect("evaluator");
        }
        _ => unreachable!("only the four original admission identity fields are exercised"),
    }
    value.bindings.metric_receipt_digest = value
        .metrics
        .content_digest(&value.profile)
        .expect("independently valid metric receipt");
    value.receipt.binding_digest = value.bindings.content_digest().expect("binding");
    value.receipt.admission_digest = digest_admission(&value.receipt);
    assert_eq!(
        value
            .bindings
            .validate_against(&value.profile, &value.metrics),
        Ok(())
    );
    assert_eq!(
        value.receipt.verify(
            &value.split,
            &value.profile,
            &value.metrics,
            &value.bindings
        ),
        Err(RoleSplitMetricBindingErrorV1::ReceiptMismatch)
    );
}

#[test]
fn replay_rejects_foreign_metric_cell_after_rehash() {
    assert_metric_identity_rejected("cell");
}

#[test]
fn replay_rejects_foreign_metric_generation_after_rehash() {
    assert_metric_identity_rejected("generation");
}

#[test]
fn replay_rejects_foreign_metric_proposer_after_rehash() {
    assert_metric_identity_rejected("proposer");
}

#[test]
fn replay_rejects_foreign_metric_evaluator_after_rehash() {
    assert_metric_identity_rejected("evaluator");
}

#[test]
fn replay_rejects_missing_final_split_evaluation_receipts() {
    let value = fixture();
    for (index, label) in [
        "evaluation receipt",
        "retention receipt",
        "negative transfer receipt",
        "cost receipt",
    ]
    .into_iter()
    .enumerate()
    {
        let mut incomplete = value.split.clone();
        let field = match index {
            0 => &mut incomplete.evaluation.evaluation_receipt_digest,
            1 => &mut incomplete.evaluation.retention_receipt_digest,
            2 => &mut incomplete.evaluation.negative_transfer_receipt_digest,
            _ => &mut incomplete.evaluation.cost_receipt_digest,
        };
        *field = Digest32::ZERO;
        assert_eq!(
            incomplete.evaluation_subject_digest().expect("valid plan"),
            value.receipt.split_subject_digest
        );
        assert_eq!(
            value
                .receipt
                .verify(&incomplete, &value.profile, &value.metrics, &value.bindings),
            Err(RoleSplitMetricBindingErrorV1::Split(
                codex_hepta_types::CellSplitContractErrorV1::EmptyDigest(label)
            ))
        );
    }
}
