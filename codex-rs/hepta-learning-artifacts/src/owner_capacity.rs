//! Bounded create-only namespaces, including abandoned and unrelated entries.
//! The single owner reserves space before admitting a new operation. Exact
//! retries allocate no additional names; existing bytes still require validation.

use super::*;

pub(super) fn reserve(
    host: &LearningArtifactOwnerHost,
    directory: &str,
    maximum: usize,
    additional: usize,
) -> Result<(), ArtifactOwnerHostError> {
    let remaining = maximum
        .checked_sub(additional)
        .ok_or(ArtifactOwnerHostError::Capacity)?;
    for (index, entry) in fs::read_dir(host.root.join(directory))?.enumerate() {
        entry?;
        if index >= remaining {
            return Err(ArtifactOwnerHostError::Capacity);
        }
    }
    Ok(())
}

pub(super) fn reserve_artifact(
    host: &LearningArtifactOwnerHost,
) -> Result<(), ArtifactOwnerHostError> {
    for (name, maximum, additional) in [
        ("transactions", MAX_HEAD_RECORDS * 5, 5),
        ("payloads", MAX_HEAD_RECORDS, 1),
        ("admissions", MAX_HEAD_RECORDS, 1),
        ("registries", MAX_HEAD_RECORDS * 2, 1),
        ("witnesses", MAX_HEAD_RECORDS * 2, 1),
        ("heads", MAX_HEAD_RECORDS, 1),
    ] {
        reserve(host, name, maximum, additional)?;
    }
    Ok(())
}

pub(super) fn reserve_state(
    host: &LearningArtifactOwnerHost,
    signed: &SignedCurrentArtifactHeadV1,
) -> Result<(), ArtifactOwnerHostError> {
    for (name, maximum, additional) in [
        ("state-transactions", MAX_HEAD_RECORDS * 4, 4),
        ("registries", MAX_HEAD_RECORDS * 2, 1),
        ("withdrawals", MAX_HEAD_RECORDS * 3, 2),
        ("witnesses", MAX_HEAD_RECORDS * 2, 1),
        (
            "heads",
            MAX_HEAD_RECORDS,
            usize::from(!host.signed_head_record_path(signed).try_exists()?),
        ),
    ] {
        reserve(host, name, maximum, additional)?;
    }
    Ok(())
}
