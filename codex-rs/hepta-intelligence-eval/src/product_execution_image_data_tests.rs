use pretty_assertions::assert_eq;

use super::*;

#[test]
fn original_image_data_reads_completed_bytes_without_taking_the_live_writer_lock()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = TempJournal::new();
    let mut writer = temp.create();
    writer.claim(&key("completed"))?;
    writer.complete(&key("completed"), b"actual original output")?;
    let exact = writer.anchor();
    let bytes = fs::read(&temp.0)?;
    assert_eq!(readonly(&temp, exact).err(), Some(FileError::Busy));
    assert_eq!(
        decode_original_product_evaluation_execution_image_v1(
            &bytes,
            digest("owner namespace"),
            exact,
            &key("completed"),
        ),
        Ok(State::Completed(b"actual original output".to_vec()))
    );
    assert_eq!(fs::read(&temp.0)?, bytes);
    assert_eq!(readonly(&temp, exact).err(), Some(FileError::Busy));
    assert_eq!(
        writer.readback(&key("completed")),
        Ok(State::Completed(b"actual original output".to_vec()))
    );
    Ok(())
}

#[test]
fn original_image_data_refuses_unwitnessed_suffix_corruption_and_wrong_key()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = TempJournal::new();
    let mut writer = temp.create();
    writer.claim(&key("pending"))?;
    let prefix = writer.anchor();
    writer.claim(&key("completed"))?;
    writer.complete(&key("completed"), b"actual completion")?;
    let exact = writer.anchor();
    let bytes = fs::read(&temp.0)?;
    let decode = |image: &[u8], anchor, key: &ProductEvaluationExecutionKeyV1| {
        decode_original_product_evaluation_execution_image_v1(
            image,
            digest("owner namespace"),
            anchor,
            key,
        )
    };
    assert_eq!(
        decode(&bytes, prefix, &key("completed")),
        Err(StoreError::Indeterminate)
    );
    assert_eq!(decode(&bytes, exact, &key("pending")), Ok(State::Pending));
    assert_eq!(
        decode(&bytes, exact, &key("absent")),
        Err(StoreError::Missing)
    );
    let mut conflicting = key("completed");
    conflicting.binding_digest = digest("different operation binding");
    assert_eq!(
        decode(&bytes, exact, &conflicting),
        Err(StoreError::Conflict)
    );
    let mut corrupt = bytes.clone();
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    assert_eq!(
        decode(&corrupt, exact, &key("completed")),
        Err(StoreError::Indeterminate)
    );
    assert_eq!(
        decode(&bytes[..last], exact, &key("completed")),
        Err(StoreError::Indeterminate)
    );
    assert_eq!(fs::read(&temp.0)?, bytes);
    Ok(())
}
