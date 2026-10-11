use std::error::Error;

use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use serde_json::json;

use crate::MODEL_RECEIPT_NAMESPACE;
use crate::ModelApprovalState;
use crate::ModelClaimLevel;
use crate::ModelEfficacyStatus;
use crate::ModelEvidenceClass;
use crate::ModelEvidenceStatus;
use crate::ModelReceipt;
use crate::ModelReceiptBindings;
use crate::ModelReceiptChain;
use crate::ModelReceiptError;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn bindings(label: &str) -> ModelReceiptBindings {
    ModelReceiptBindings {
        input_digest: digest(&format!("{label}:input")),
        output_digest: digest(&format!("{label}:output")),
        artifact_sha256: digest(&format!("{label}:artifact")),
        model_sha256: digest(&format!("{label}:model")),
        policy_digest: digest(&format!("{label}:policy")),
        graph_digest: digest(&format!("{label}:graph")),
        calibration_digest: digest(&format!("{label}:calibration")),
        evidence_digest: digest(&format!("{label}:evidence")),
        snapshot_digest: digest(&format!("{label}:snapshot")),
        causal_parent_sha256: Some(digest(&format!("{label}:causal-parent"))),
        fence_sha256: digest(&format!("{label}:fence")),
    }
}

fn root_receipt() -> Result<ModelReceipt, ModelReceiptError> {
    ModelReceipt::qualification("attempt-1", 1, None, None, bindings("attempt-1"))
}

fn child_receipt(
    attempt_id: &str,
    attempt_seq: u32,
    parent_attempt_id: &str,
    parent_receipt_sha256: Sha256Digest,
) -> Result<ModelReceipt, ModelReceiptError> {
    ModelReceipt::qualification(
        attempt_id,
        attempt_seq,
        Some(parent_attempt_id.to_string()),
        Some(parent_receipt_sha256),
        bindings(attempt_id),
    )
}

#[test]
fn model_receipt_round_trips_with_explicit_shadow_claim_status() -> Result<(), Box<dyn Error>> {
    let receipt = root_receipt()?;

    assert!(receipt.is_shadow_only());
    assert_eq!(receipt.namespace, MODEL_RECEIPT_NAMESPACE);
    assert_eq!(
        receipt.claim_level,
        ModelClaimLevel::L0BaselineL1ShadowContractOnly
    );
    assert_eq!(
        receipt.evidence_class,
        ModelEvidenceClass::DeterministicShadowContractFixture
    );
    assert_eq!(receipt.evidence_status, ModelEvidenceStatus::NotMeasured);
    assert_eq!(
        receipt.efficacy_status,
        ModelEfficacyStatus::NoEfficacyClaim
    );
    assert_eq!(receipt.approval_state, ModelApprovalState::NotApproved);
    assert_eq!(receipt.digest()?, receipt.receipt_sha256);

    let encoded = serde_json::to_value(&receipt)?;
    assert_eq!(
        encoded.get("claim_level"),
        Some(&json!("L0_BASELINE_L1_SHADOW_CONTRACT_ONLY"))
    );
    assert_eq!(
        encoded.get("evidence_class"),
        Some(&json!("DETERMINISTIC_SHADOW_CONTRACT_FIXTURE"))
    );
    assert_eq!(encoded.get("evidence_status"), Some(&json!("NOT_MEASURED")));
    assert_eq!(
        encoded.get("efficacy_status"),
        Some(&json!("NO_EFFICACY_CLAIM"))
    );
    assert_eq!(encoded.get("approval_state"), Some(&json!("NOT_APPROVED")));
    assert_eq!(encoded.get("shadow_only"), Some(&json!(true)));
    assert_eq!(encoded.get("runtime_authority"), Some(&json!(false)));
    assert_eq!(encoded.get("production_caller"), Some(&json!(false)));
    assert_eq!(encoded.get("external_effects"), Some(&json!(false)));
    assert_eq!(encoded.get("promotion"), Some(&json!(false)));

    let decoded: ModelReceipt = serde_json::from_value(encoded)?;
    assert_eq!(decoded, receipt);
    decoded.validate()?;
    Ok(())
}

#[test]
fn model_receipt_requires_root_and_child_parent_shapes() {
    let root_with_parent = ModelReceipt::qualification(
        "attempt-1",
        1,
        Some("attempt-0".to_string()),
        Some(digest("attempt-0:receipt")),
        bindings("attempt-1"),
    );
    assert_eq!(root_with_parent, Err(ModelReceiptError::ParentMismatch));

    let child_without_parent =
        ModelReceipt::qualification("attempt-2", 2, None, None, bindings("attempt-2"));
    assert_eq!(child_without_parent, Err(ModelReceiptError::ParentBinding));

    let child_with_half_parent = ModelReceipt::qualification(
        "attempt-2",
        2,
        Some("attempt-1".to_string()),
        None,
        bindings("attempt-2"),
    );
    assert_eq!(
        child_with_half_parent,
        Err(ModelReceiptError::ParentBinding)
    );
}

#[test]
fn model_receipt_rejects_unknown_json_authority_and_digest_tampering() -> Result<(), Box<dyn Error>>
{
    let receipt = root_receipt()?;

    let mut with_unknown = serde_json::to_value(&receipt)?;
    with_unknown["implicit_authority"] = json!(true);
    assert!(serde_json::from_value::<ModelReceipt>(with_unknown).is_err());

    let mut authority_tamper = receipt.clone();
    authority_tamper.execute_allowed = true;
    assert_eq!(
        authority_tamper.validate(),
        Err(ModelReceiptError::AuthorityBoundary)
    );

    let mut digest_tamper = receipt;
    digest_tamper.model_sha256 = digest("other-model");
    assert_eq!(
        digest_tamper.validate(),
        Err(ModelReceiptError::DigestMismatch("receipt"))
    );
    Ok(())
}

#[test]
fn model_receipt_chain_round_trips_and_binds_exact_predecessor() -> Result<(), Box<dyn Error>> {
    let root = root_receipt()?;
    let child = child_receipt(
        "attempt-2",
        2,
        &root.attempt_id,
        root.receipt_sha256.clone(),
    )?;
    let child_digest = child.receipt_sha256.clone();
    let mut chain = ModelReceiptChain::default();
    chain.append(root)?;
    chain.append(child)?;
    chain.validate()?;
    assert_eq!(chain.head_receipt_sha256, Some(child_digest));
    assert_eq!(chain.head()?.map(|receipt| receipt.attempt_seq), Some(2));

    let encoded = serde_json::to_vec(&chain)?;
    let decoded: ModelReceiptChain = serde_json::from_slice(&encoded)?;
    assert_eq!(decoded, chain);
    decoded.validate()?;
    Ok(())
}

#[test]
fn model_receipt_chain_gap_and_parent_rejections_are_atomic() -> Result<(), Box<dyn Error>> {
    let root = root_receipt()?;
    let mut chain = ModelReceiptChain::default();
    chain.append(root.clone())?;

    let before_gap = chain.clone();
    let gap = child_receipt(
        "attempt-3",
        3,
        &root.attempt_id,
        root.receipt_sha256.clone(),
    )?;
    assert_eq!(
        chain.append(gap),
        Err(ModelReceiptError::NonContiguousAttempt {
            expected: 2,
            actual: 3,
        })
    );
    assert_eq!(chain, before_gap);

    let before_parent = chain.clone();
    let wrong_parent = child_receipt("attempt-2", 2, "other-attempt", root.receipt_sha256)?;
    assert_eq!(
        chain.append(wrong_parent),
        Err(ModelReceiptError::ParentMismatch)
    );
    assert_eq!(chain, before_parent);

    let mut corrupt_head = chain;
    corrupt_head.head_receipt_sha256 = Some(digest("other-head"));
    assert_eq!(
        corrupt_head.validate(),
        Err(ModelReceiptError::ChainHeadMismatch)
    );
    Ok(())
}
