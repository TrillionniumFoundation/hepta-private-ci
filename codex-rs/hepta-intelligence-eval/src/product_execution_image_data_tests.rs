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

#[test]
fn original_image_records_preserve_each_actual_key_and_pending_state()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = TempJournal::new();
    let mut writer = temp.create();
    writer.claim(&key("completed"))?;
    writer.complete(&key("completed"), b"original first receipt")?;
    writer.claim(&key("pending"))?;
    let prefix = writer.anchor();
    writer.claim(&key("second"))?;
    writer.complete(&key("second"), b"original second receipt")?;
    let exact = writer.anchor();
    let bytes = fs::read(&temp.0)?;
    assert_eq!(readonly(&temp, exact).err(), Some(FileError::Busy));
    assert_eq!(
        decode_original_product_evaluation_execution_records_v1(
            &bytes,
            digest("owner namespace"),
            exact,
        )?,
        vec![
            (
                key("completed"),
                State::Completed(b"original first receipt".to_vec())
            ),
            (key("pending"), State::Pending),
            (
                key("second"),
                State::Completed(b"original second receipt".to_vec())
            ),
        ]
    );
    assert_eq!(
        decode_original_product_evaluation_execution_records_v1(
            &bytes,
            digest("owner namespace"),
            prefix,
        ),
        Err(StoreError::Indeterminate)
    );
    assert_eq!(fs::read(&temp.0)?, bytes);
    Ok(())
}

#[test]
fn original_image_records_refuse_excess_records_without_changing_owner()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = TempJournal::new();
    let mut writer = temp.create();
    for index in 0..65 {
        writer.claim(&key(&format!("pending-{index}")))?;
    }
    let exact = writer.anchor();
    let bytes = fs::read(&temp.0)?;
    assert_eq!(
        decode_original_product_evaluation_execution_records_v1(
            &bytes,
            digest("owner namespace"),
            exact,
        ),
        Err(StoreError::Indeterminate)
    );
    assert_eq!(writer.readback(&key("pending-64")), Ok(State::Pending));
    assert_eq!(fs::read(&temp.0)?, bytes);
    Ok(())
}
