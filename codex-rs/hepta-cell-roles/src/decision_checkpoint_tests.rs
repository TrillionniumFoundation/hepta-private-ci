use super::tests::definition;
use super::tests::profile;
use super::*;
use pretty_assertions::assert_eq;
use std::path::PathBuf;

fn directory(label: &str) -> Result<PathBuf, Box<dyn Error>> {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "hepta-decision-checkpoint-{label}-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir(&path)?;
    Ok(path)
}

fn owner() -> Result<DecisionCellOwnerV1, DecisionCellOwnerErrorV1> {
    let artifact = Digest32::of_bytes(b"decision-checkpoint-test-artifact");
    DecisionCellOwnerV1::load_committed(
        definition(artifact),
        profile(),
        artifact,
        Digest32::of_bytes(b"decision-checkpoint-test-state"),
    )
}

#[test]
fn existing_temporary_file_preserves_checkpoint_and_reserved_bytes() -> Result<(), Box<dyn Error>> {
    let directory = directory("existing-temp")?;
    let path = directory.join("checkpoint");
    let owner = owner()?;
    owner.save_checkpoint(&path)?;
    let checkpoint = fs::read(&path)?;
    let temp = path.with_extension("decision.checkpoint.tmp");
    let reserved = b"another writer owns these bytes";
    fs::write(&temp, reserved)?;
    let state = owner.state().clone();

    assert_eq!(
        owner.save_checkpoint(&path),
        Err(DecisionCellOwnerErrorV1::DurableIo)
    );
    assert_eq!(fs::read(&temp)?, reserved);
    assert_eq!(fs::read(&path)?, checkpoint);
    assert_eq!(owner.state(), &state);
    fs::remove_dir_all(directory)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn hard_linked_temporary_file_cannot_overwrite_another_file() -> Result<(), Box<dyn Error>> {
    let directory = directory("hard-link")?;
    let path = directory.join("checkpoint");
    let victim = directory.join("unrelated");
    let bytes = b"unrelated committed bytes";
    fs::write(&victim, bytes)?;
    let temp = path.with_extension("decision.checkpoint.tmp");
    fs::hard_link(&victim, &temp)?;
    let owner = owner()?;

    assert_eq!(
        owner.save_checkpoint(&path),
        Err(DecisionCellOwnerErrorV1::DurableIo)
    );
    assert_eq!(fs::read(&victim)?, bytes);
    assert_eq!(fs::read(&temp)?, bytes);
    assert!(!path.try_exists()?);
    fs::remove_dir_all(directory)?;
    Ok(())
}

#[test]
fn oversized_checkpoint_preserves_owner_and_file() -> Result<(), Box<dyn Error>> {
    let directory = directory("oversized")?;
    let path = directory.join("checkpoint");
    let mut owner = owner()?;
    owner.save_checkpoint(&path)?;
    let state = owner.state().clone();
    let prefix = fs::read(&path)?;
    let file = fs::OpenOptions::new().write(true).open(&path)?;
    let oversized = DECISION_CHECKPOINT_MAX_BYTES_V1 as u64 + 1;
    file.set_len(oversized)?;
    file.sync_all()?;
    drop(file);

    assert_eq!(
        owner.restore_checkpoint(&path),
        Err(DecisionCellOwnerErrorV1::InvalidCheckpoint)
    );
    assert_eq!(owner.state(), &state);
    let mut file = File::open(&path)?;
    assert_eq!(file.metadata()?.len(), oversized);
    let mut actual_prefix = vec![0; prefix.len()];
    file.read_exact(&mut actual_prefix)?;
    assert_eq!(actual_prefix, prefix);
    drop(file);
    fs::remove_dir_all(directory)?;
    Ok(())
}

#[test]
fn checkpoint_writer_rejects_history_the_decoder_cannot_restore() -> Result<(), Box<dyn Error>> {
    let directory = directory("history-overflow")?;
    let path = directory.join("checkpoint");
    let mut owner = owner()?;
    owner.state.history.resize(
        DECISION_CHECKPOINT_MAX_HISTORY_V1 + 1,
        owner.state.current_state_digest,
    );
    let state = owner.state().clone();

    assert_eq!(
        owner.save_checkpoint(&path),
        Err(DecisionCellOwnerErrorV1::InvalidCheckpoint)
    );
    assert_eq!(owner.state(), &state);
    assert!(!path.try_exists()?);
    assert!(
        !path
            .with_extension("decision.checkpoint.tmp")
            .try_exists()?
    );
    fs::remove_dir_all(directory)?;
    Ok(())
}

#[test]
fn maximum_existing_history_and_tombstone_round_trip() -> Result<(), Box<dyn Error>> {
    let directory = directory("history-boundary")?;
    let path = directory.join("checkpoint");
    let mut owner = owner()?;
    owner.state.history.resize(
        DECISION_CHECKPOINT_MAX_HISTORY_V1,
        owner.state.current_state_digest,
    );
    owner.state.tombstone_digest = Some(Digest32::of_bytes(b"tombstone"));
    let expected = owner.state().clone();
    let checksum = owner.save_checkpoint(&path)?;
    let mut restored = self::owner()?;
    assert_eq!(restored.restore_checkpoint(&path)?, checksum);
    assert_eq!(restored.state(), &expected);
    fs::remove_dir_all(directory)?;
    Ok(())
}

#[test]
fn noncanonical_tombstone_tag_is_rejected_even_with_a_valid_checksum() -> Result<(), Box<dyn Error>>
{
    let directory = directory("tombstone-tag")?;
    let path = directory.join("checkpoint");
    let mut owner = owner()?;
    let state = owner.state().clone();
    let mut payload = owner.encode_checkpoint()?;
    let tag_index = payload.len() - 1;
    assert_eq!(payload[tag_index], 0);
    payload[tag_index] = 2;
    payload.extend_from_slice(Digest32::of_bytes(b"tombstone").as_array());
    let checksum = Digest32::of_parts(&[b"hepta.decision-cell.checkpoint.v1", &payload]);
    payload.extend_from_slice(checksum.as_array());
    fs::write(&path, &payload)?;

    assert_eq!(
        owner.restore_checkpoint(&path),
        Err(DecisionCellOwnerErrorV1::InvalidCheckpoint)
    );
    assert_eq!(owner.state(), &state);
    assert_eq!(fs::read(&path)?, payload);
    fs::remove_dir_all(directory)?;
    Ok(())
}
