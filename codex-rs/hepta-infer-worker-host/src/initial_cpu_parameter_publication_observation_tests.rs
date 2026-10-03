//! These unsigned join checks do not construct Owner or E authority. Actual
//! ACK authenticity remains the original read-only Owner's historical verifier.
use super::*;

fn head() -> HostResult<SignedCurrentArtifactHeadV1> {
    Ok(SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: Digest32::of_bytes(b"scope"),
        binding: Digest32::of_bytes(b"binding"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("registry")?,
            generation: Generation::new(4)?,
            head_digest: Digest32::of_bytes(b"last completed head"),
            predecessor_head_digest: Digest32::of_bytes(b"third completed head"),
            authority_epoch: 1,
            signer_id: id("original-owner")?,
            signing_key_digest: Digest32::of_bytes(b"public original key"),
            issued_at: 10,
            expires_at: 100,
        },
        signature: [0; 64],
    })
}
#[test]
fn cold_whole_publication_requires_the_original_contiguous_head_chain() -> HostResult<()> {
    let original = head()?;
    let previous = Some((
        original.witness.predecessor_head_digest,
        Generation::new(3)?,
    ));
    validate_chain(previous, &original)?;
    // H' is not spliced into the original Hc completion, even when H' is valid
    // independently. Both a different predecessor and reused ordinal reject.
    let mut changed = original.clone();
    changed.witness.predecessor_head_digest = Digest32::of_bytes(b"later live CURRENT");
    assert!(validate_chain(previous, &changed).is_err());
    let mut changed = original.clone();
    changed.witness.generation = Generation::new(3)?;
    assert!(validate_chain(previous, &changed).is_err());
    let mut changed = original;
    changed.witness.generation = Generation::new(5)?;
    assert!(validate_chain(previous, &changed).is_err());
    Ok(())
}
#[test]
fn absent_completion_observation_does_not_create_a_file_or_parent() -> HostResult<()> {
    let root = tempfile::tempdir()?;
    let missing = root.path().join("not-issued").join("original.head");
    assert_eq!(existing(&missing, 16 * 1024)?, None);
    assert!(!missing.exists());
    assert!(!missing.parent().ok_or("fixture parent")?.exists());
    Ok(())
}
