//! Synthetic registry tuples; no actual private role or holdout reads.
use super::*;

#[test]
fn initial_or_changed_artifacts_cannot_authorize_successor_stage() -> HostResult<()> {
    let content = Digest32::of_bytes(b"original-protected-successor-payload");
    let support = Digest32::of_bytes(b"original-independent-qualified-manifest");
    let compatibility = Digest32::of_bytes(b"original-native-execution-profile");
    let objective = Digest32::of_bytes(b"original-qualified-objective");
    let expected = Artifact {
        id: "successor-model".into(),
        content_digest: content.to_string(),
        support_digest: support.to_string(),
        compatibility_digest: compatibility.to_string(),
        objective_digest: objective.to_string(),
        predecessor_id: "installed-model".into(),
    };
    let original = ArtifactManifest {
        artifact_id: id("successor-model")?,
        kind: ArtifactKind::Model,
        generation: Generation::new(2)?,
        predecessor_id: Some(id("installed-model")?),
        content_digest: content,
        objective_digest: objective,
        support_digest: support,
        producer_id: id("original-artifact-owner")?,
        compatibility_digest: compatibility,
        encoded_size_bytes: 64,
    };
    verify_tuple(&expected, &original, ArtifactKind::Model, 2)?;
    for change in 0..10 {
        let mut wrong = original.clone();
        match change {
            0 => wrong.artifact_id = id("another-model")?,
            1 => wrong.kind = ArtifactKind::Policy,
            2 => wrong.generation = Generation::new(1)?,
            3 => wrong.predecessor_id = None,
            4 => wrong.predecessor_id = Some(id("another-predecessor")?),
            5 => wrong.content_digest = Digest32::of_bytes(b"changed-payload"),
            6 => wrong.support_digest = Digest32::of_bytes(b"unqualified-payload"),
            7 => wrong.compatibility_digest = Digest32::of_bytes(b"another-runtime"),
            8 => wrong.objective_digest = Digest32::of_bytes(b"another-objective"),
            9 => wrong.encoded_size_bytes = 16 * 1024 * 1024 + 1,
            _ => unreachable!(),
        }
        assert!(
            verify_tuple(&expected, &wrong, ArtifactKind::Model, 2).is_err(),
            "change {change}"
        );
    }
    Ok(())
}
