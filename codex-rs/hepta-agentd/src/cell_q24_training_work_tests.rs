//! Actual optimizer, original signed receipt and file readback. Credentials
//! and Dataset custody remain explicit component fixtures, not independent B
//! or daemon/Root whole-chain qualification.
#![cfg(test)]

use super::*;
use crate::cell_composed_q24::OriginalQ24OwnerReadV1;
use crate::cell_composed_q24::OriginalQ24TrainingWorkDataV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use pretty_assertions::assert_eq;

fn snapshot(
    f: &ReceiptFixture,
    receipt: &LearningIterationReceiptV1,
) -> anyhow::Result<LearningIterationSnapshotV1> {
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(f.config.dataset.clone())?;
    coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
    Ok(coordinator.snapshot().clone())
}

fn actual_work(
    f: &ReceiptFixture,
    training: &mut CellQ24TrainingOwnerV1<FileAnchorWitnessStore>,
) -> anyhow::Result<OriginalQ24TrainingWorkDataV1> {
    training
        .read_original_work_with_source(&f.config.dataset, &OriginalQ24OwnerReadV1)?
        .ok_or_else(|| anyhow::anyhow!("actual changed native head required"))
}

fn original_files(f: &ReceiptFixture) -> anyhow::Result<[Vec<u8>; 4]> {
    Ok([
        fs::read(f.root.path().join("job"))?,
        fs::read(f.root.path().join("witness"))?,
        fs::read(f.root.path().join("receipts"))?,
        fs::read(f.root.path().join("receipt-witness"))?,
    ])
}

#[test]
fn original_training_work_matches_signed_native_bytes_and_cold_readback() -> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    let mut receipts = f.create_receipts()?;
    assert!(actual_work(&f, &mut training).is_err());
    let CellQ24TrainingOutcomeV1::Candidate(candidate) =
        training.fit_or_readback(&AtomicBool::new(/*v*/ false))?
    else {
        anyhow::bail!("actual native optimization must change the head")
    };
    let (receipt, signature) = receipts.attest_original_completion(&mut training)?;
    f.config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &signature,
        &learning_iteration_receipt_signing_bytes_v1(&receipt)?,
        clock()?,
    )?;
    let cut = snapshot(&f, &receipt)?;
    let work = actual_work(&f, &mut training)?;
    let observed = work.verify_original_training(
        &cut,
        &f.baseline,
        &candidate.model,
        CellQ24PrivateHeadV1::Drive { index: 0 },
        &candidate.heads,
    )?;
    let total = ["base", "encoder", "heads"]
        .into_iter()
        .map(|name| fs::read(f.root.path().join(name)))
        .collect::<std::io::Result<Vec<_>>>()?
        .iter()
        .map(|bytes| (bytes.len() - 12) / 8)
        .sum::<usize>() as u64;
    let width = u64::from(u16::from_le_bytes(candidate.heads[10..12].try_into()?));
    let (compute, policy, eligibility, schedule) =
        crate::cell_composed_q24::original_q24_work_contract(
            CellQ24PrivateHeadV1::Drive { index: 0 },
            f.rule,
        );
    assert_eq!(
        (
            observed.capacity,
            observed.cumulative,
            observed.selective_update
        ),
        (
            crate::CellParameterCapacityV1 {
                total_parameters: total,
                trainable_parameters: width,
                maximum_active_parameters: total,
            },
            crate::CellTrainingBudgetV1 {
                examples_seen: u64::from(f.data.rows()),
                optimizer_steps: candidate.metrics.optimizer_steps,
                parameter_updates: candidate.metrics.optimizer_steps * width,
                compute_units: candidate.metrics.optimizer_steps * width,
                compute_unit_contract: compute.into_array(),
            },
            crate::CellSelectiveUpdateV1 {
                policy_digest: policy.into_array(),
                eligibility_digest: eligibility.into_array(),
                schedule_digest: schedule.into_array(),
                maximum_parameters_per_step: width,
            },
        )
    );
    let before = original_files(&f)?;
    drop(training);
    drop(receipts);
    let mut training = f.recover_training()?;
    let mut receipts = f.recover_receipts()?;
    assert_eq!(receipts.readback(&mut training)?, (receipt, signature));
    assert_eq!(actual_work(&f, &mut training)?, work);
    let loaded: OriginalQ24TrainingWorkDataV1 =
        serde_json::from_slice(&serde_json::to_vec(&work)?)?;
    assert_eq!(loaded, work);
    loaded.verify_original_training(
        &cut,
        &f.baseline,
        &candidate.model,
        CellQ24PrivateHeadV1::Drive { index: 0 },
        &candidate.heads,
    )?;
    assert_eq!(original_files(&f)?, before);
    Ok(())
}

#[test]
fn original_training_work_rejects_changed_header_rule_heads_and_row() -> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    let mut receipts = f.create_receipts()?;
    let CellQ24TrainingOutcomeV1::Candidate(candidate) =
        training.fit_or_readback(&AtomicBool::new(/*v*/ false))?
    else {
        anyhow::bail!("actual native candidate required")
    };
    let (receipt, _) = receipts.attest_original_completion(&mut training)?;
    let cut = snapshot(&f, &receipt)?;
    let work = actual_work(&f, &mut training)?;
    let verify = |data: &OriginalQ24TrainingWorkDataV1, head, heads: &[u8]| {
        data.verify_original_training(&cut, &f.baseline, &candidate.model, head, heads)
    };
    verify(
        &work,
        CellQ24PrivateHeadV1::Drive { index: 0 },
        &candidate.heads,
    )?;
    let before = original_files(&f)?;
    // Every field is in the exact original 221-byte header; even error totals
    // cannot be changed while preserving the actual signed receipt preimage.
    for offset in [0, 8, 40, 41, 73, 105, 137, 169, 177, 193, 209, 217] {
        let mut changed = serde_json::to_value(&work)?;
        let byte = changed["prefix"][offset]
            .as_u64()
            .ok_or_else(|| anyhow::anyhow!("actual header byte missing"))?;
        changed["prefix"][offset] = serde_json::json!(byte ^ 1);
        let changed = serde_json::from_value::<OriginalQ24TrainingWorkDataV1>(changed)?;
        assert!(
            verify(
                &changed,
                CellQ24PrivateHeadV1::Drive { index: 0 },
                &candidate.heads
            )
            .is_err()
        );
    }
    for (field, value) in [
        ("epochs", i64::from(f.rule.epochs) + 1),
        ("learning_rate_q24", f.rule.learning_rate_q24 + 1),
    ] {
        let mut changed = serde_json::to_value(&work)?;
        changed[field] = serde_json::json!(value);
        let changed = serde_json::from_value::<OriginalQ24TrainingWorkDataV1>(changed)?;
        assert!(
            verify(
                &changed,
                CellQ24PrivateHeadV1::Drive { index: 0 },
                &candidate.heads
            )
            .is_err()
        );
    }
    let mut changed_heads = candidate.heads.clone();
    let last = changed_heads
        .last_mut()
        .ok_or_else(|| anyhow::anyhow!("actual heads absent"))?;
    *last ^= 1;
    assert!(
        verify(
            &work,
            CellQ24PrivateHeadV1::Drive { index: 0 },
            &changed_heads
        )
        .is_err()
    );
    let other_directory = tempfile::tempdir()?;
    let other_baseline = load(other_directory.path(), /*factor*/ 2)?;
    assert!(
        work.verify_original_training(
            &cut,
            &other_baseline,
            &candidate.model,
            CellQ24PrivateHeadV1::Drive { index: 0 },
            &candidate.heads,
        )
        .is_err()
    );
    assert!(
        verify(
            &work,
            CellQ24PrivateHeadV1::Prediction { index: 0 },
            &candidate.heads
        )
        .is_err()
    );
    let mut extra = serde_json::to_value(&work)?;
    extra["claimed_completed"] = serde_json::json!(true);
    assert!(serde_json::from_value::<OriginalQ24TrainingWorkDataV1>(extra).is_err());
    assert_eq!(original_files(&f)?, before);
    Ok(())
}

#[test]
fn original_training_work_rejects_changed_receipt_without_new_signing() -> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    let mut receipts = f.create_receipts()?;
    let CellQ24TrainingOutcomeV1::Candidate(candidate) =
        training.fit_or_readback(&AtomicBool::new(/*v*/ false))?
    else {
        anyhow::bail!("actual native candidate required")
    };
    let (original, signature) = receipts.attest_original_completion(&mut training)?;
    let work = actual_work(&f, &mut training)?;
    let before = original_files(&f)?;
    for field in ["steps", "milliseconds", "artifact_bytes", "evidence_digest"] {
        let mut changed = original.clone();
        let LearningIterationObservationV1::Training {
            steps,
            milliseconds,
            artifact_bytes,
            ..
        } = &mut changed.observation
        else {
            anyhow::bail!("actual Training observation required")
        };
        match field {
            "steps" => *steps += 1,
            "milliseconds" => *milliseconds += 1,
            "artifact_bytes" => *artifact_bytes += 1,
            "evidence_digest" => {
                changed.evidence_digest = d("deliberately-altered-training-evidence")
            }
            _ => anyhow::bail!("unknown negative receipt fixture"),
        }
        assert!(
            f.config
                .verifier
                .verify(
                    LearningEvidenceRoleV1::Generator,
                    &signature,
                    &learning_iteration_receipt_signing_bytes_v1(&changed)?,
                    clock()?
                )
                .is_err()
        );
        // The changed cut is negative DATA, never a newly signed completion.
        if let Ok(cut) = snapshot(&f, &changed) {
            assert!(
                work.verify_original_training(
                    &cut,
                    &f.baseline,
                    &candidate.model,
                    CellQ24PrivateHeadV1::Drive { index: 0 },
                    &candidate.heads
                )
                .is_err()
            );
        }
    }
    assert_eq!(original_files(&f)?, before);
    Ok(())
}

#[test]
fn original_training_work_keeps_training_no_update_without_candidate() -> anyhow::Result<()> {
    let f = ReceiptFixture::new(Q)?;
    let mut training = f.create_training()?;
    let mut receipts = f.create_receipts()?;
    assert!(matches!(
        training.fit_or_readback(&AtomicBool::new(/*v*/ false))?,
        CellQ24TrainingOutcomeV1::NoUpdate { .. }
    ));
    let original = receipts.attest_original_completion(&mut training)?;
    assert!(matches!(
        original.0.observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ));
    assert!(
        training
            .read_original_work_with_source(&f.config.dataset, &OriginalQ24OwnerReadV1)?
            .is_none()
    );
    let before = original_files(&f)?;
    drop(training);
    drop(receipts);
    let mut training = f.recover_training()?;
    let mut receipts = f.recover_receipts()?;
    assert_eq!(receipts.readback(&mut training)?, original);
    assert!(
        training
            .read_original_work_with_source(&f.config.dataset, &OriginalQ24OwnerReadV1)?
            .is_none()
    );
    assert_eq!(original_files(&f)?, before);
    Ok(())
}

#[test]
fn original_training_work_physical_corruption_then_restore_stays_refused() -> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    let mut receipts = f.create_receipts()?;
    training.fit_or_readback(&AtomicBool::new(/*v*/ false))?;
    receipts.attest_original_completion(&mut training)?;
    actual_work(&f, &mut training)?;
    let path = f.root.path().join("job");
    let original = fs::read(&path)?;
    let mut damaged = original.clone();
    let last = damaged
        .last_mut()
        .ok_or_else(|| anyhow::anyhow!("original job empty"))?;
    *last ^= 1;
    fs::write(&path, damaged)?;
    File::open(&path)?.sync_all()?;
    assert!(actual_work(&f, &mut training).is_err());
    fs::write(&path, &original)?;
    File::open(&path)?.sync_all()?;
    assert!(actual_work(&f, &mut training).is_err());
    assert_eq!(fs::read(&path)?, original);
    // Same-handle poison is not a cross-process permanent refusal claim.
    Ok(())
}
