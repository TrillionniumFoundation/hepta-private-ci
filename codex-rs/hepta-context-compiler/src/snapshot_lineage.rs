use codex_hepta_types::Digest32;

use crate::ContextAdmissionSnapshotV2;
use crate::ContextAdmissionVerifierV2;
use crate::ContextCompilerV2Error;
use crate::VerifiedAdmissionSnapshotV2;
use crate::verify_admission_snapshot_successor_v2;
use crate::verify_admission_snapshot_v2;

const LINEAGE_DOMAIN: &[u8] = b"hepta.context-admission-snapshot-lineage.v2";

/// A typed, predecessor-checked admission frontier.
///
/// Canonical product code advances this value rather than supplying an arbitrary
/// verified snapshot directly to attachment or pre-dispatch preparation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedSnapshotLineageV2 {
    root_snapshot_digest: Digest32,
    current: VerifiedAdmissionSnapshotV2,
    depth: u64,
    lineage_digest: Digest32,
}

impl VerifiedSnapshotLineageV2 {
    pub fn root(
        snapshot: ContextAdmissionSnapshotV2,
        verifier: &impl ContextAdmissionVerifierV2,
    ) -> Result<Self, ContextCompilerV2Error> {
        let current = verify_admission_snapshot_v2(snapshot, verifier)?;
        let root_snapshot_digest = current.snapshot_digest();
        let depth = 0;
        let lineage_digest = compute_lineage_digest(
            Digest32::ZERO,
            root_snapshot_digest,
            current.verification_digest(),
            depth,
        );
        Ok(Self {
            root_snapshot_digest,
            current,
            depth,
            lineage_digest,
        })
    }

    pub fn advance(
        &self,
        snapshot: ContextAdmissionSnapshotV2,
        verifier: &impl ContextAdmissionVerifierV2,
    ) -> Result<Self, ContextCompilerV2Error> {
        let current = verify_admission_snapshot_successor_v2(snapshot, &self.current, verifier)?;
        let depth = self
            .depth
            .checked_add(1)
            .ok_or(ContextCompilerV2Error::Arithmetic)?;
        let lineage_digest = compute_lineage_digest(
            self.lineage_digest,
            current.snapshot_digest(),
            current.verification_digest(),
            depth,
        );
        Ok(Self {
            root_snapshot_digest: self.root_snapshot_digest,
            current,
            depth,
            lineage_digest,
        })
    }

    #[must_use]
    pub const fn current(&self) -> &VerifiedAdmissionSnapshotV2 {
        &self.current
    }

    #[must_use]
    pub const fn root_snapshot_digest(&self) -> Digest32 {
        self.root_snapshot_digest
    }

    #[must_use]
    pub const fn depth(&self) -> u64 {
        self.depth
    }

    #[must_use]
    pub const fn lineage_digest(&self) -> Digest32 {
        self.lineage_digest
    }
}

fn compute_lineage_digest(
    predecessor_lineage_digest: Digest32,
    snapshot_digest: Digest32,
    verification_digest: Digest32,
    depth: u64,
) -> Digest32 {
    let mut bytes = LINEAGE_DOMAIN.to_vec();
    bytes.extend_from_slice(predecessor_lineage_digest.as_array());
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(verification_digest.as_array());
    bytes.extend_from_slice(&depth.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    use crate::ContextAdmissionRecordV2;
    use crate::ContextAdmissionSnapshotV2;
    use crate::ContextAdmissionVerifierV2;

    use super::VerifiedSnapshotLineageV2;

    #[derive(Clone, Copy)]
    struct Verifier;

    impl ContextAdmissionVerifierV2 for Verifier {
        fn verifier_digest(&self) -> Digest32 {
            Digest32::of_bytes(b"lineage-verifier")
        }

        fn verify_record(&self, _record: &ContextAdmissionRecordV2) -> bool {
            true
        }

        fn verify_snapshot(&self, _snapshot: &ContextAdmissionSnapshotV2) -> bool {
            true
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).unwrap_or_else(|error| panic!("valid id: {error:?}"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn lineage_requires_the_exact_predecessor() {
        let root_snapshot = ContextAdmissionSnapshotV2::new(
            id("snapshot-root"),
            digest("scope"),
            digest("authority"),
            10,
            1,
            Vec::new(),
            true,
            None,
        )
        .unwrap_or_else(|error| panic!("root: {error:?}"));
        let lineage = VerifiedSnapshotLineageV2::root(root_snapshot, &Verifier)
            .unwrap_or_else(|error| panic!("lineage: {error:?}"));
        let successor = ContextAdmissionSnapshotV2::new(
            id("snapshot-next"),
            digest("scope"),
            digest("authority"),
            20,
            2,
            vec![id("revoked")],
            true,
            Some(lineage.current().snapshot_digest()),
        )
        .unwrap_or_else(|error| panic!("successor: {error:?}"));
        let advanced = lineage
            .advance(successor, &Verifier)
            .unwrap_or_else(|error| panic!("advance: {error:?}"));
        assert_eq!(advanced.depth(), 1);
        assert_ne!(advanced.lineage_digest(), lineage.lineage_digest());

        let fork = ContextAdmissionSnapshotV2::new(
            id("snapshot-fork"),
            digest("scope"),
            digest("authority"),
            30,
            3,
            vec![id("revoked")],
            true,
            Some(lineage.current().snapshot_digest()),
        )
        .unwrap_or_else(|error| panic!("fork: {error:?}"));
        assert!(advanced.advance(fork, &Verifier).is_err());
    }
}
