//! Real journal bytes and process exit; completion payloads remain opaque data.

use pretty_assertions::assert_eq;

use super::*;

#[path = "product_execution_image_data_tests.rs"]
mod image_data;

fn readonly(
    temp: &TempJournal,
    exact: ProductEvaluationExecutionAnchorV1,
) -> Result<ReadOnlyProductEvaluationExecutionStoreV1, FileError> {
    ReadOnlyProductEvaluationExecutionStoreV1::open(
        File::open(&temp.0).map_err(io_error)?,
        digest("owner namespace"),
        exact,
    )
}

#[test]
fn readonly_process_recovers_fully_witnessed_bytes_after_writer_exit()
-> Result<(), Box<dyn std::error::Error>> {
    const TEST: &str = "product_execution_file::tests::readback::readonly_process_recovers_fully_witnessed_bytes_after_writer_exit";
    if let Ok(path) = std::env::var("HEPTA_READONLY_EXECUTION_PATH") {
        let temp = TempJournal(PathBuf::from(path));
        let witness_path = temp.0.with_extension("anchor");
        if std::env::var("HEPTA_READONLY_EXECUTION_MODE").as_deref() == Ok("write") {
            let mut writer = temp.create();
            writer.claim(&key("completed"))?;
            writer.complete(&key("completed"), b"original completed bytes")?;
            writer.claim(&key("pending"))?;
            let exact = writer.anchor();
            let mut witness = File::create(witness_path)?;
            write!(witness, "{}\n{}", exact.sequence, exact.history_digest)?;
            witness.sync_all()?;
            // No Rust destructors: neither journal nor witness depends on Drop.
            std::process::exit(0);
        }
        let anchor_bytes = fs::read_to_string(witness_path)?;
        let (sequence, digest) = anchor_bytes
            .split_once('\n')
            .ok_or("missing witness separator")?;
        let exact = ProductEvaluationExecutionAnchorV1 {
            sequence: sequence.parse()?,
            history_digest: digest.parse()?,
        };
        let mut reader = readonly(&temp, exact)?;
        assert_eq!(
            reader.readback(&key("completed")),
            Ok(State::Completed(b"original completed bytes".to_vec()))
        );
        assert_eq!(reader.readback(&key("pending")), Ok(State::Pending));
        assert_eq!(reader.anchor(), exact);
        // Leave fixture cleanup to the parent, after checking bytes unchanged.
        std::mem::forget(temp);
        return Ok(());
    }
    let temp = TempJournal::new();
    let executable = std::env::current_exe()?;
    let run = |mode: &str| {
        Command::new(&executable)
            .args(["--exact", TEST])
            .env("HEPTA_READONLY_EXECUTION_PATH", &temp.0)
            .env("HEPTA_READONLY_EXECUTION_MODE", mode)
            .status()
    };
    assert!(run("write")?.success());
    let witness_path = temp.0.with_extension("anchor");
    let before = [fs::read(&temp.0)?, fs::read(&witness_path)?];
    assert!(run("read")?.success());
    assert_eq!([fs::read(&temp.0)?, fs::read(&witness_path)?], before);
    fs::remove_file(witness_path)?;
    Ok(())
}

#[test]
fn readonly_requires_the_exact_head_and_never_repairs_a_suffix()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = TempJournal::new();
    let mut writer = temp.create();
    let prefix = writer.anchor();
    assert_eq!(readonly(&temp, prefix).err(), Some(FileError::Busy));
    writer.claim(&key("pending"))?;
    let exact = writer.anchor();
    drop(writer);
    let original = fs::read(&temp.0)?;
    assert_eq!(readonly(&temp, prefix).err(), Some(FileError::Rollback));
    let mut reader = readonly(&temp, exact)?;
    assert_eq!(reader.readback(&key("missing")), Err(StoreError::Missing));
    let mut conflicting = key("pending");
    conflicting.binding_digest = digest("other binding");
    assert_eq!(reader.readback(&conflicting), Err(StoreError::Conflict));
    assert_eq!(reader.readback(&key("pending")), Ok(State::Pending));
    assert_eq!(fs::read(&temp.0)?, original);
    // The historical reader does not keep an exclusive old-owner lease alive.
    let writer = temp.recover(exact)?;
    assert_eq!(
        reader.readback(&key("pending")),
        Err(StoreError::Indeterminate)
    );
    drop(writer);
    assert_eq!(
        reader.readback(&key("pending")),
        Err(StoreError::Indeterminate)
    );
    drop(reader);
    OpenOptions::new()
        .append(true)
        .open(&temp.0)?
        .write_all(&[1])?;
    let torn = fs::read(&temp.0)?;
    assert_eq!(readonly(&temp, exact).err(), Some(FileError::Corrupt));
    assert_eq!(fs::read(&temp.0)?, torn);
    Ok(())
}

#[test]
fn readonly_same_length_corruption_remains_indeterminate_after_restoration()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = TempJournal::new();
    let mut writer = temp.create();
    writer.claim(&key("completed"))?;
    writer.complete(&key("completed"), b"retained")?;
    let exact = writer.anchor();
    drop(writer);
    let original = fs::read(&temp.0)?;
    let mut reader = readonly(&temp, exact)?;
    let mut corrupt = original.clone();
    *corrupt.last_mut().ok_or("missing journal checksum")? ^= 1;
    let mut fault = OpenOptions::new().write(true).open(&temp.0)?;
    fault.write_all(&corrupt)?;
    fault.sync_all()?;
    assert_eq!(
        reader.readback(&key("completed")),
        Err(StoreError::Indeterminate)
    );
    fault.seek(SeekFrom::Start(0))?;
    fault.write_all(&original)?;
    fault.sync_all()?;
    assert_eq!(fs::read(&temp.0)?, original);
    assert_eq!(
        reader.readback(&key("completed")),
        Err(StoreError::Indeterminate)
    );
    Ok(())
}
