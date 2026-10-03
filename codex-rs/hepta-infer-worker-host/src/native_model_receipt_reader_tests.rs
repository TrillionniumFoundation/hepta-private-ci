use super::*;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn original_hot_cold_and_reopened_receipt_are_identical_and_read_never_replays()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-native.journal");
    let mut control = DurableInferenceControl::open(&path, 8)?;
    super::super::tests::settle_fixture(&mut control);
    let original = control
        .native_record_resolved("assessment-1")?
        .ok_or("original receipt absent")?;
    let control = Arc::new(tokio::sync::Mutex::new(control));
    let reader = NativeModelReceiptReaderV1::new_shared(control.clone());
    let hot = reader
        .read("assessment-1")
        .await?
        .ok_or("hot receipt absent")?;
    assert_eq!(serde_json::from_str::<NativeRunRecord>(&hot)?, original);
    {
        let mut lease = control.lock().await;
        lease.maintain_native_history(1, Duration::from_secs(2))?;
        assert!(lease.native_record("assessment-1").is_none());
    }
    let before = std::fs::read(&path)?;
    assert_eq!(reader.read("assessment-1").await?, Some(hot.clone()));
    assert_eq!(reader.read("missing-request").await?, None);
    assert_eq!(std::fs::read(&path)?, before);
    drop(reader);
    drop(control);
    let reopened = Arc::new(tokio::sync::Mutex::new(DurableInferenceControl::open(
        &path, 8,
    )?));
    let reader = NativeModelReceiptReaderV1::new_shared(reopened.clone());
    assert_eq!(reader.read("assessment-1").await?, Some(hot));
    assert_eq!(
        reopened
            .lock()
            .await
            .native_record_resolved("assessment-1")?,
        Some(original)
    );
    Ok(())
}

#[tokio::test]
async fn competing_serial_owner_never_becomes_missing_or_constructs_another_writer()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-native.journal");
    let mut native = DurableInferenceControl::open(&path, 8)?;
    super::super::tests::settle_fixture(&mut native);
    let control = Arc::new(tokio::sync::Mutex::new(native));
    let reader = NativeModelReceiptReaderV1::new_shared(control.clone());
    let lease = control.clone().lock_owned().await;
    let before = std::fs::read(&path)?;
    assert!(reader.read("missing-request").await.is_err());
    assert_eq!(std::fs::read(&path)?, before);
    drop(lease);
    assert_eq!(reader.read("missing-request").await?, None);
    Ok(())
}
