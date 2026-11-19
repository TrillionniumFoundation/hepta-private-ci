//! Real original journals under a non-escaping source borrow; not a Root
//! enrollment or ordinary-loop qualification.

use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn source_operation_rejects_another_actual_prepared_owner() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let other_root = tempfile::tempdir()?;
    let (mut session, dataset, prepared, _current) =
        source_fixture(root.path(), "source-operation-original").await?;
    let (mut other, _other_dataset, other_prepared, _other_current) =
        source_fixture(other_root.path(), "source-operation-other").await?;
    let files = tempfile::tempdir()?;
    let mut experience = owner(files.path(), &prepared, &dataset, Stage::Experience)?;
    let original = experience.attest_experience()?;
    let bytes = fs::read(files.path().join("source"))?;
    let observed = prepared
        .with_original_prepared_operation(|read| experience.read_experience_in_operation(read))??;
    assert_eq!(observed, original);
    let other_read = other_prepared
        .with_original_prepared_operation(|read| experience.read_experience_in_operation(read))?;
    assert!(other_read.is_err());
    assert_eq!(fs::read(files.path().join("source"))?, bytes);
    session.stop().await?;
    other.stop().await?;
    Ok(())
}

#[tokio::test]
async fn source_operation_withdrawal_refuses_read_and_outer_completion() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (mut session, dataset, prepared, _current) =
        source_fixture(root.path(), "source-operation-withdrawal").await?;
    let experience_files = tempfile::tempdir()?;
    let dataset_files = tempfile::tempdir()?;
    let mut experience = owner(
        experience_files.path(),
        &prepared,
        &dataset,
        Stage::Experience,
    )?;
    let mut frozen = owner(dataset_files.path(), &prepared, &dataset, Stage::Dataset)?;
    experience.attest_experience()?;
    let completed = frozen.attest_dataset(&mut experience)?;
    let before = fs::read(dataset_files.path().join("source"))?;
    let result = prepared.with_original_prepared_operation(|read| -> anyhow::Result<()> {
        assert_eq!(
            frozen.read_dataset_in_operation(&mut experience, read)?,
            completed
        );
        session
            .source
            .withdraw_for_dataset_test(&prepared.initial().request.source_run_id)?;
        assert!(
            frozen
                .read_dataset_in_operation(&mut experience, read)
                .is_err()
        );
        Ok(())
    });
    assert!(result.is_err());
    assert_eq!(fs::read(dataset_files.path().join("source"))?, before);
    session.stop().await?;
    Ok(())
}
