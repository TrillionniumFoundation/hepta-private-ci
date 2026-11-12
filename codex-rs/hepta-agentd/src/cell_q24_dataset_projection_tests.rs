//! The pure kernel must preserve original materialization bytes while denying
//! provenance. Fixture issuers and actual local task files remain components,
//! not an authenticated Root historical consumer or independent B acceptance.

use super::*;
use crate::project_original_q24_dataset_v1;

#[tokio::test]
async fn q24_dataset_pure_projection_matches_original_bytes_without_source_authority()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, _, _, _current) = ordinary(
        root.path(),
        "pure-projection-A",
        /*source_envelope*/ None,
    )
    .await?;
    let publication = execute(&session, /*request_id*/ 1).await?;
    let files = tempfile::tempdir()?;
    let dataset = Dataset::new(
        files.path(),
        &[(&session, &publication, Some(-257))],
        OutcomeTerminalityV1::Terminal,
    )?;
    let observed_at = now();
    let records =
        LedgerSnapshot::read_dataset_records(&dataset.frozen, &dataset.receipt, observed_at)?;
    let tasks = vec![(publication.clone(), session.cell.committed(&publication)?)];
    let original = dataset.batch()?;
    let pure = project_original_q24_dataset_v1(
        &dataset.frozen,
        &dataset.receipt,
        &dataset.projection,
        &records,
        &tasks,
        observed_at,
    )?;
    assert_eq!(pure.encoded(), original.encoded());
    assert_eq!(pure.digest(), original.digest());
    assert_eq!(pure.rows(), original.rows());
    assert!(pure.require_original_dataset_provenance().is_err());
    original.require_original_dataset_provenance()?;

    for records in [
        records.iter().rev().cloned().collect(),
        records[..1].to_vec(),
    ] {
        assert!(
            project_original_q24_dataset_v1(
                &dataset.frozen,
                &dataset.receipt,
                &dataset.projection,
                &records,
                &tasks,
                observed_at,
            )
            .is_err()
        );
    }
    let mut changed = tasks;
    changed[0].1.policy.clear();
    assert!(
        project_original_q24_dataset_v1(
            &dataset.frozen,
            &dataset.receipt,
            &dataset.projection,
            &LedgerSnapshot::read_dataset_records(&dataset.frozen, &dataset.receipt, observed_at)?,
            &changed,
            observed_at,
        )
        .is_err()
    );
    session.stop().await?;
    Ok(())
}
