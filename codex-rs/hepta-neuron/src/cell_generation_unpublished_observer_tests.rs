//! Actual original files distinguish the two formats. The guarded fixture's
//! Current double is only a format test; neither reader supplies Root custody.

#![cfg(test)]

use super::*;
use crate::CellGenerationUnpublishedObserverV1;
use pretty_assertions::assert_eq;

fn unpublished(
    files: &Files,
) -> Result<CellGenerationUnpublishedObserverV1, Box<dyn std::error::Error>> {
    Ok(CellGenerationUnpublishedObserverV1::from_original_files(
        File::open(files.0.join("journal"))?,
        File::open(files.0.join("witness"))?,
        observer_config(),
    )?)
}

#[test]
fn unpublished_observer_reads_actual_drain_but_guarded_observer_rejects_its_header()
-> Result<(), Box<dyn std::error::Error>> {
    let files = Files::new();
    let mut owner = CellGenerationJournalV2::open(
        files.file("journal"),
        files.witness(),
        config(),
        /*max_records*/ 128,
    )?;
    let reader = unpublished(&files)?;
    assert!(reader.observe()?.is_genesis());
    assert_eq!(
        observer(&files).observe().err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );
    owner.drain()?;
    let expected = owner.observe_generation()?;
    let image = (files.bytes(), fs::read(files.0.join("witness"))?);
    drop(owner);
    assert!(reader.observe()?.is_drained());
    assert_eq!(reader.observe()?.observation(), &expected);
    assert_eq!((files.bytes(), fs::read(files.0.join("witness"))?), image);
    Ok(())
}

#[test]
fn unpublished_observer_cannot_accept_the_guarded_original_format()
-> Result<(), Box<dyn std::error::Error>> {
    let files = Files::new();
    let mut original = owner(&files);
    original.drain()?;
    assert!(observer(&files).observe()?.is_drained());
    assert_eq!(
        unpublished(&files)?.observe().err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );
    Ok(())
}

#[test]
fn unpublished_observer_refuses_partial_physical_tail_without_repair()
-> Result<(), Box<dyn std::error::Error>> {
    let files = Files::new();
    let mut owner = CellGenerationJournalV2::open(
        files.file("journal"),
        files.witness(),
        config(),
        /*max_records*/ 128,
    )?;
    owner.drain()?;
    drop(owner);
    let reader = unpublished(&files)?;
    let observed = reader.observe()?;
    let complete = files.bytes();
    let mut extra = OpenOptions::new()
        .append(true)
        .open(files.0.join("journal"))?;
    extra.write_all(&[0, 0])?;
    extra.sync_all()?;
    let partial = files.bytes();
    assert_eq!(reader.observe().err(), Some(CellGenerationErrorV2::Pending));
    assert_eq!(files.bytes(), partial);
    fs::write(files.0.join("journal"), complete)?;
    // This parser has no sticky latch. OriginalBFile and the Root durable
    // attempt supply refusal; a restored parser read is not a cold fence.
    assert_eq!(reader.observe()?, observed);
    Ok(())
}
