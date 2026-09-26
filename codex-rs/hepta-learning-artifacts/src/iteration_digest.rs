//! Canonical integrity binding for the control.engineering iteration envelope.
//!
//! The digest is an identity/integrity boundary only. It grants no sandbox,
//! proposal, selection, promotion, merge, deployment or release authority.

use codex_hepta_types::Digest32;

use crate::IterationEnvelopeV1;

/// Canonically bind every semantic field of one validated iteration envelope.
pub fn iteration_envelope_digest_v1(
    envelope: &IterationEnvelopeV1,
) -> Result<Digest32, String> {
    envelope.validate()?;
    let mut bytes = b"hepta.learning-artifacts.iteration-envelope.v1\0".to_vec();
    let envelope_id = envelope.envelope_id.as_str().as_bytes();
    let length = u32::try_from(envelope_id.len())
        .map_err(|_| "iteration envelope identity is too large".to_string())?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(envelope_id);
    for digest in [
        envelope.base_commit,
        envelope.base_tree,
        envelope.objective_digest,
        envelope.grammar_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&envelope.maximum_files.to_be_bytes());
    bytes.extend_from_slice(&envelope.maximum_diff_bytes.to_be_bytes());
    bytes.extend_from_slice(&envelope.maximum_candidates.to_be_bytes());
    bytes.push(envelope.maximum_parallel_sandboxes);
    bytes.extend_from_slice(&envelope.expiry_unix_seconds.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::StableId;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: u8) -> Digest32 {
        Digest32::from_array([value; 32])
    }

    fn envelope() -> IterationEnvelopeV1 {
        IterationEnvelopeV1 {
            envelope_id: id("envelope:coverage"),
            base_commit: digest(1),
            base_tree: digest(2),
            objective_digest: digest(3),
            grammar_digest: digest(4),
            maximum_files: 10,
            maximum_diff_bytes: 1_024,
            maximum_candidates: 4,
            maximum_parallel_sandboxes: 2,
            expiry_unix_seconds: 100,
        }
    }

    #[test]
    fn digest_is_deterministic_and_binds_every_field() {
        let original = envelope();
        let expected = iteration_envelope_digest_v1(&original).expect("digest");
        assert_eq!(
            expected,
            iteration_envelope_digest_v1(&original).expect("same digest")
        );

        let mutations: [fn(&mut IterationEnvelopeV1); 10] = [
            |value| value.envelope_id = id("envelope:other"),
            |value| value.base_commit = digest(11),
            |value| value.base_tree = digest(12),
            |value| value.objective_digest = digest(13),
            |value| value.grammar_digest = digest(14),
            |value| value.maximum_files += 1,
            |value| value.maximum_diff_bytes += 1,
            |value| value.maximum_candidates += 1,
            |value| value.maximum_parallel_sandboxes += 1,
            |value| value.expiry_unix_seconds += 1,
        ];
        for mutate in mutations {
            let mut changed = original.clone();
            mutate(&mut changed);
            assert_ne!(
                expected,
                iteration_envelope_digest_v1(&changed).expect("changed digest")
            );
        }
    }
}
