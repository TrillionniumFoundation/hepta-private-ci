//! Actual byte-loaded private-head masks and existing Q24 worker execution.
//! No training, evaluator, signer or publication owner is created here.

use pretty_assertions::assert_eq;

use super::*;
use crate::CellQ24PrivateHeadV1;

const ORIGINAL_HEADS: [i64; 8] = [Q, 0, 0, Q, -Q, 0, 0, -Q];

fn reopen(root: &Path) -> anyhow::Result<LoadedCellQ24ModelV1> {
    let file = |name| File::open(root.join(name));
    Ok(LoadedCellQ24ModelV1::open_files(CellQ24ModelFilesV1 {
        base: file("base")?,
        encoder: file("encoder")?,
        heads: file("heads")?,
        organ_adapter: Some(file("organ")?),
        cell_adapter: Some(file("cell")?),
    })?)
}

#[test]
fn q24_single_private_head_preserves_other_actual_outputs_after_loading()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let baseline = Arc::new(load(root.path(), /*factor*/ 1)?);
    let prior = bundle(&baseline, /*prior*/ None)?;
    for (head, coefficient, value, expected) in [
        (
            CellQ24PrivateHeadV1::Drive { index: 1 },
            2,
            Q / 2,
            [Q, 2 * Q, -Q, -3 * Q / 2],
        ),
        (
            CellQ24PrivateHeadV1::Prediction { index: 0 },
            4,
            -Q / 2,
            [Q, 3 * Q / 2, -Q / 2, -3 * Q / 2],
        ),
    ] {
        let mut values = ORIGINAL_HEADS;
        values[coefficient] = value;
        fs::write(
            root.path().join("heads"),
            matrix(/*rows*/ 4, /*cols*/ 2, &values),
        )?;
        let candidate = baseline.validate_single_head_candidate(reopen(root.path())?, head)?;
        let next = bundle(&candidate, Some(&prior))?;
        let config = configured(&candidate, &next)?;
        // The same loaded bytes cannot reuse the original selected bundle.
        assert!(baseline.shared_worker(&next, config.manifest.clone(), Arc::new(|| 11)).is_err());
        let worker = candidate.into_worker(&next, config.manifest.clone(), Arc::new(|| 11))?;
        // Later source-path replacement cannot alter the checked allocation.
        fs::write(root.path().join("heads"), b"changed-after-load")?;
        let request = CellGenerationRequestV2 {
            operation_id: "checked-private-head".into(),
            task_digest: config.task_digest,
            source_frontier: config.source_frontier,
            predecessor: config.initial,
            input: input(),
            admitted_at_micros: 10,
            deadline_micros: 100,
        };
        let result = worker.execute(&config.manifest, &request, &AtomicBool::new(false))?;
        let mut bytes = b"HQ24O001".to_vec();
        bytes.extend_from_slice(&2_u16.to_le_bytes());
        for value in expected {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        assert_eq!(
            (result.disposition, result.output_delta, result.successor_state),
            (CellGenerationDispositionV2::Stopped, bytes, Vec::new())
        );
    }
    Ok(())
}

#[test]
fn q24_single_private_head_rejects_frozen_changes_extra_rows_and_no_change()
-> anyhow::Result<()> {
    let original = tempfile::tempdir()?;
    let baseline = load(original.path(), /*factor*/ 1)?;
    for mutation in 0..9 {
        let root = tempfile::tempdir()?;
        drop(load(root.path(), /*factor*/ 1)?);
        let mut values = ORIGINAL_HEADS;
        values[0] = Q / 2;
        fs::write(
            root.path().join("heads"),
            matrix(/*rows*/ 4, /*cols*/ 2, &values),
        )?;
        let mut head = CellQ24PrivateHeadV1::Drive { index: 0 };
        match mutation {
            0 => fs::write(
                root.path().join("base"),
                matrix(/*rows*/ 2, /*cols*/ 2, &[Q, 0, 0, Q]),
            )?,
            1 => fs::write(
                root.path().join("encoder"),
                matrix(/*rows*/ 2, /*cols*/ 2, &[Q / 2, 0, 0, Q]),
            )?,
            2 => fs::write(root.path().join("organ"), adapter(&[Q, 0], &[0, Q]))?,
            3 => fs::write(root.path().join("cell"), adapter(&[0, Q], &[0, 2 * Q]))?,
            4 => {
                values[7] = -Q / 2;
                fs::write(root.path().join("heads"), matrix(/*rows*/ 4, /*cols*/ 2, &values))?;
            }
            5 => fs::write(
                root.path().join("heads"),
                matrix(/*rows*/ 4, /*cols*/ 2, &ORIGINAL_HEADS),
            )?,
            6 => head = CellQ24PrivateHeadV1::Drive { index: 2 },
            7 => head = CellQ24PrivateHeadV1::Prediction { index: 0 },
            8 => fs::write(
                root.path().join("heads"),
                matrix(/*rows*/ 2, /*cols*/ 2, &[Q / 2, 0, 0, Q]),
            )?,
            _ => unreachable!(),
        }
        assert!(matches!(
            baseline.validate_single_head_candidate(reopen(root.path())?, head),
            Err(CellGenerationErrorV2::InvalidBinding)
        ));
    }
    Ok(())
}
