use super::*;
use pretty_assertions::assert_eq;

use super::tests::evidence;
use super::tests::metrics;
use super::tests::profile;
use super::tests::split;

#[test]
fn replay_rejects_relabelled_role_with_valid_recomputed_digest() {
    let split = split();
    let profile = profile();
    let metrics = metrics(&split, &profile);
    let evidence = evidence(&split, &profile, &metrics);
    let mut receipt =
        RoleSplitAdmissionV1::admit(&split, evidence, &profile, &metrics).expect("admission");
    RoleSplitAdmissionV1::verify(&split, &receipt, &profile, &metrics).expect("valid replay");
    receipt.role = CellRoleV1::Planner;
    receipt.admission_digest = digest_receipt(&receipt);
    assert_eq!(receipt.evidence.role, CellRoleV1::Plasticity);
    assert_eq!(
        RoleSplitAdmissionV1::verify(&split, &receipt, &profile, &metrics),
        Err(RoleSplitAdmissionErrorV1::RoleMismatch)
    );
}

#[test]
fn replay_rejects_missing_final_evaluation_receipts() {
    let original = split();
    let profile = profile();
    let metrics = metrics(&original, &profile);
    let evidence = evidence(&original, &profile, &metrics);
    let receipt =
        RoleSplitAdmissionV1::admit(&original, evidence, &profile, &metrics).expect("admission");
    for (index, label) in [
        "evaluation receipt",
        "retention receipt",
        "negative transfer receipt",
        "cost receipt",
    ]
    .into_iter()
    .enumerate()
    {
        let mut incomplete = original.clone();
        let field = match index {
            0 => &mut incomplete.evaluation.evaluation_receipt_digest,
            1 => &mut incomplete.evaluation.retention_receipt_digest,
            2 => &mut incomplete.evaluation.negative_transfer_receipt_digest,
            _ => &mut incomplete.evaluation.cost_receipt_digest,
        };
        *field = Digest32::ZERO;
        assert_eq!(
            incomplete.evaluation_subject_digest().expect("valid plan"),
            receipt.split_subject_digest
        );
        assert_eq!(
            RoleSplitAdmissionV1::verify(&incomplete, &receipt, &profile, &metrics),
            Err(RoleSplitAdmissionErrorV1::Split(
                codex_hepta_types::CellSplitContractErrorV1::EmptyDigest(label)
            ))
        );
    }
}
