//! Actual file mutations against the still-held original source. These Linux
//! fixtures never unlock or replace the production owner to perform a read.

use super::*;
use pretty_assertions::assert_eq;

fn original(root: &Path) -> anyhow::Result<(Source, AgentdIdentity, CircuitTaskSourceInputV1)> {
    let identity = identity(root)?;
    let input = source("A", b"original configured input");
    let owner = Source::create(
        opened(root, "source-journal")?,
        witness(root, "source-witness")?,
        &identity,
        &fence(&identity)?,
        &registry()?,
        vec![input.clone()],
    )?;
    Ok((owner, identity, input))
}

#[test]
fn original_source_current_fences_same_length_mutation_after_restore() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (owner, identity, input) = original(root.path())?;
    let read = owner.readback();
    read.require_original_input(&identity, &input)?;
    let path = root.path().join("source-journal");
    let before = source_bytes(&owner)?;
    let witness_before = fs::read(root.path().join("source-witness"))?;
    let mut changed = before.clone();
    let last = changed
        .last_mut()
        .expect("original initialized source file");
    *last ^= 1;
    fs::write(&path, &changed)?;
    assert_eq!(
        read.require_original_input(&identity, &input),
        Err(Error::CommitUncertain)
    );
    fs::write(&path, &before)?;
    assert_eq!(
        read.require_original_input(&identity, &input),
        Err(Error::CommitUncertain)
    );
    assert_eq!(fs::read(&path)?, before);
    assert_eq!(
        fs::read(root.path().join("source-witness"))?,
        witness_before
    );
    Ok(())
}

#[test]
fn original_source_current_fences_truncation_and_extra_tail_without_repair() -> anyhow::Result<()> {
    for truncate in [true, false] {
        let root = tempfile::tempdir()?;
        let (owner, identity, input) = original(root.path())?;
        let read = owner.readback();
        read.require_original_input(&identity, &input)?;
        let path = root.path().join("source-journal");
        let before = source_bytes(&owner)?;
        let mut changed = before.clone();
        if truncate {
            changed.pop();
        } else {
            changed.push(0);
        }
        fs::write(&path, &changed)?;
        assert_eq!(
            read.require_original_input(&identity, &input),
            Err(Error::CommitUncertain)
        );
        assert_eq!(fs::read(&path)?, changed, "CURRENT cannot repair the file");
        fs::write(&path, &before)?;
        assert_eq!(
            read.require_original_input(&identity, &input),
            Err(Error::CommitUncertain)
        );
    }
    Ok(())
}

#[test]
fn original_source_input_read_is_readonly_and_requires_live_original_configuration()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (owner, identity, input) = original(root.path())?;
    let read = owner.readback();
    let before = source_bytes(&owner)?;
    read.require_original_input(&identity, &input)?;
    let mut wrong = input.clone();
    wrong.observation.push(1);
    assert_eq!(
        read.require_original_input(&identity, &wrong),
        Err(Error::InvalidBinding)
    );
    read.require_original_input(&identity, &input)?;
    assert_eq!(source_bytes(&owner)?, before);
    assert!(
        read.read_run_publication(&identity, &input.scope.run_id)
            .is_err(),
        "configured input does not manufacture a completed publication"
    );
    owner.withdraw_source(&input.scope.run_id)?;
    assert!(read.require_original_input(&identity, &input).is_err());
    Ok(())
}
