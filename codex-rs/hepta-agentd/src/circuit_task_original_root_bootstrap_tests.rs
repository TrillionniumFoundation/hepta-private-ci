//! The original Driver and AutomationStore produce the receipt used below.
//! Controlled inference qualifies these data/receipt boundaries only: it is
//! not a real Root/daemon process run or a Source publication authorization.

use super::*;
use crate::circuit_cell_binding::root_bootstrap as registry_codec;
use crate::circuit_task::root_bootstrap_cell as cell_codec;
use crate::circuit_task::root_bootstrap_codec::{BOUND, Reader, Writer};
use crate::circuit_task::source::remote_source;

#[test]
fn original_root_bootstrap_preserves_complete_registry_and_cells() -> anyhow::Result<()> {
    let (definition, bindings) = configuration();
    let original = CircuitCellRegistryV1::new(definition.clone(), bindings.clone())?;
    let bytes = registry_codec::encode(&original)?;
    let decoded = registry_codec::decode(&bytes)?;
    assert_eq!(decoded.definition(), &definition);
    assert_eq!(decoded.definition_digest(), original.definition_digest());
    assert_eq!(registry_codec::encode(&decoded)?, bytes);
    for binding in bindings {
        let mut writer = Writer::new(b"original-test-cell");
        cell_codec::encode(&mut writer, &binding.cell)?;
        let bytes = writer.finish();
        let mut reader = Reader::new(&bytes, b"original-test-cell")?;
        let complete = cell_codec::decode(&mut reader)?;
        reader.end()?;
        assert_eq!(complete, binding.cell);
    }
    Ok(())
}

#[test]
fn original_root_bootstrap_rejects_noncanonical_or_incomplete_data() -> anyhow::Result<()> {
    let (definition, bindings) = configuration();
    let original = CircuitCellRegistryV1::new(definition, bindings)?;
    let bytes = registry_codec::encode(&original)?;
    registry_codec::decode(&bytes)?;

    let mut extra = bytes.clone();
    extra.push(/*value*/ 0);
    let truncated = &bytes[..bytes.len() - 1];
    let definition_length = u32::from_be_bytes(bytes[8..12].try_into()?) as usize;
    let mut alternate_json = bytes.clone();
    alternate_json[8..12].copy_from_slice(&u32::try_from(definition_length + 1)?.to_be_bytes());
    alternate_json.insert(/*index*/ 12, b' ');
    let mut excessive_count = bytes.clone();
    excessive_count[12 + definition_length..16 + definition_length]
        .copy_from_slice(&u32::MAX.to_be_bytes());
    let excessive_frame = vec![0; BOUND + 1];
    for candidate in [extra.as_slice(), truncated, alternate_json.as_slice(),
        excessive_count.as_slice(), excessive_frame.as_slice()]
    {
        assert_eq!(registry_codec::decode(candidate).err(), Some(Error::InvalidBinding));
    }
    assert_eq!(registry_codec::encode(&original)?, bytes);
    Ok(())
}

#[tokio::test]
async fn original_completion_loan_encodes_the_actual_receipt_and_readback() -> anyhow::Result<()> {
    let (definition, bindings) = configuration();
    let (_directory, mut driver, request, calls) = fixture(definition, bindings).await;
    let body: anyhow::Result<()> = async {
        let first = driver.execute(&request, CircuitTaskModeV1::Drive, || Ok(time())).await?;
        let dispatches = first.trace().run()
            .completed_computation_dispatches(driver.cells.registry().definition())?;
        anyhow::ensure!(dispatches.len() == 1, "one original completed dispatch");
        let dispatch = &dispatches[0];
        let input = driver.inputs.retained.get(&dispatch.activation_id)
            .ok_or_else(|| anyhow::anyhow!("original retained input is missing"))?;
        let saved = remote_source::encode_original_input(dispatch, input)?;
        let first_bytes = remote_source::original_completion_bytes(
            driver.cells.registry().definition(), &request, &saved, &first,
        )?;
        let readback = driver.execute(&request, CircuitTaskModeV1::Readback, || Ok(time())).await?;
        let readback_bytes = remote_source::original_completion_bytes(
            driver.cells.registry().definition(), &request, &saved, &readback,
        )?;
        anyhow::ensure!(first == readback, "readback must retain the complete original receipt");
        anyhow::ensure!(first_bytes == readback_bytes, "completion loan retains exact original bytes");
        anyhow::ensure!(calls.load(Ordering::SeqCst) == 1, "readback cannot repeat inference");
        Ok(())
    }.await;
    // Every Result failure above still closes the real AutomationStore. This
    // does not claim that cancellation of the outer test future has joined it.
    driver.store.close().await;
    body
}

#[tokio::test]
async fn original_completion_loan_refuses_foreign_run_and_saved_input() -> anyhow::Result<()> {
    let (definition, bindings) = configuration();
    let (_directory, mut driver, request, calls) = fixture(definition, bindings).await;
    let body: anyhow::Result<()> = async {
        let receipt = driver.execute(&request, CircuitTaskModeV1::Drive, || Ok(time())).await?;
        let dispatches = receipt.trace().run()
            .completed_computation_dispatches(driver.cells.registry().definition())?;
        anyhow::ensure!(dispatches.len() == 1, "one original completed dispatch");
        let dispatch = &dispatches[0];
        let input = driver.inputs.retained.get(&dispatch.activation_id)
            .ok_or_else(|| anyhow::anyhow!("original retained input is missing"))?;
        let saved = remote_source::encode_original_input(dispatch, input)?;
        let original = remote_source::original_completion_bytes(
            driver.cells.registry().definition(), &request, &saved, &receipt,
        )?;
        let mut foreign_request = request.clone();
        foreign_request.start.run_id = "foreign-run".into();
        anyhow::ensure!(remote_source::original_completion_bytes(
            driver.cells.registry().definition(), &foreign_request, &saved, &receipt,
        ) == Err(Error::InvalidBinding), "another run is not this original receipt");
        let mut foreign_input = input.clone();
        foreign_input.scope = scope("foreign-run");
        let changed = remote_source::encode_original_input(dispatch, &foreign_input)?;
        anyhow::ensure!(remote_source::original_completion_bytes(
            driver.cells.registry().definition(), &request, &changed, &receipt,
        ) == Err(Error::InvalidBinding), "a changed input scope is not this original decision");
        foreign_input = input.clone();
        foreign_input.source_frontier = d("foreign-frontier");
        let changed = remote_source::encode_original_input(dispatch, &foreign_input)?;
        anyhow::ensure!(remote_source::original_completion_bytes(
            driver.cells.registry().definition(), &request, &changed, &receipt,
        ) == Err(Error::InvalidBinding), "a changed input frontier is not this original decision");
        anyhow::ensure!(remote_source::original_completion_bytes(
            driver.cells.registry().definition(), &request, &saved, &receipt,
        )? == original, "refusal must not replace the original completion bytes");
        anyhow::ensure!(calls.load(Ordering::SeqCst) == 1, "refusal does not execute another model call");
        Ok(())
    }.await;
    driver.store.close().await;
    body
}
