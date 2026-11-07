//! One bounded predecessor belongs to the original signed-intent publisher.
//! It is kept across an uncertain external CAS and is never an automatic local
//! rollback or dispatch instruction. Each file retains the original byte cap.
use super::*;

const PREDECESSOR_FILE: &str = "supervisor-signed-intent-predecessor.json";

pub(crate) fn read(run_root: &Path) -> Result<Option<SignedSupervisorIntent>, SignedIntentError> {
    let Some(bytes) = crate::bounded_regular_file::read_optional(
        &run_root.join(PREDECESSOR_FILE),
        MAX_INTENT_BYTES,
    )?
    else {
        return Ok(None);
    };
    let intent: Option<SignedSupervisorIntent> = serde_json::from_slice(&bytes)?;
    if let Some(intent) = &intent {
        intent.validate()?;
    }
    Ok(intent)
}

/// The caller holds the publication owner and has matched `expected` to the
/// fresh external anchor. Preserve the exact bytes of that matching current
/// file before replacing it, including all prior Unknown facts.
pub(crate) fn stage(
    run_root: &Path,
    expected: &SignedSupervisorIntent,
) -> Result<(), SignedIntentError> {
    let bytes = crate::bounded_regular_file::read_optional(
        &run_root.join(SIGNED_INTENT_FILE),
        MAX_INTENT_BYTES,
    )?
    .ok_or_else(|| SignedIntentError::Invalid("anchored predecessor is missing".to_string()))?;
    let actual: SignedSupervisorIntent = serde_json::from_slice(&bytes)?;
    actual.validate()?;
    if &actual != expected {
        return Err(SignedIntentError::Invalid(
            "anchored predecessor changed before publication".to_string(),
        ));
    }
    let current = crate::signed_intent_confirmation::read_current(run_root)?;
    let previous = crate::signed_intent_confirmation::read_predecessor(run_root)?;
    let retained = current
        .as_ref()
        .filter(|material| material.intent_sha256 == expected.intent_sha256)
        .or_else(|| {
            previous
                .as_ref()
                .filter(|material| material.intent_sha256 == expected.intent_sha256)
        });
    if let Some(material) = retained {
        material.validate_for(expected)?;
    }
    crate::signed_intent_confirmation::write_predecessor(run_root, previous.as_ref(), retained)?;
    // One atomic replacement, never a directory of unbounded predecessors.
    write_atomic_bytes(run_root, PREDECESSOR_FILE, &bytes)
}

/// Only a successfully confirmed new external anchor permits this cleanup.
/// Check current bytes again; an unrelated local replacement cannot discard
/// the retained evidence of an uncertain publication.
pub(crate) fn clear_after_confirmation(
    run_root: &Path,
    expected: &SignedSupervisorIntent,
) -> Result<(), SignedIntentError> {
    if read_intent(run_root)?.as_ref() != Some(expected) {
        return Err(SignedIntentError::Invalid(
            "confirmed intent changed before predecessor cleanup".to_string(),
        ));
    }
    // Tombstones retain the same atomic rename and directory-sync semantics.
    // No untrusted path is followed or unlinked during cleanup.
    write_atomic_bytes(run_root, PREDECESSOR_FILE, b"null\n")?;
    let previous = crate::signed_intent_confirmation::read_predecessor(run_root)?;
    crate::signed_intent_confirmation::write_predecessor(run_root, previous.as_ref(), None)?;
    let current = crate::signed_intent_confirmation::read_current(run_root)?;
    if current
        .as_ref()
        .is_some_and(|material| material.intent_sha256 != expected.intent_sha256)
    {
        crate::signed_intent_confirmation::write_current(run_root, current.as_ref(), None)?;
    }
    Ok(())
}
