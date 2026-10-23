//! A full currentness fence cannot combine incompatible signed manifests.

use super::*;
use codex_hepta_intelligence::CurrentOwnerStateV1;
use codex_hepta_intelligence::validate_current_snapshot;

struct SwitchingManifests<'a, O> {
    oracle: O,
    path: &'a std::path::Path,
    a: &'a [OwnerBindingV1],
    b: &'a [OwnerBindingV1],
    frontier: Digest32,
    reads: usize,
}

impl<O: CanonicalFreshnessOracleV1> CanonicalFreshnessOracleV1 for SwitchingManifests<'_, O> {
    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        let result = self.oracle.current(owner_id);
        self.reads += 1;
        if self.reads == 1 {
            write_authority_file(self.path, self.b, self.frontier);
        } else if self.reads == 2 {
            write_authority_file(self.path, self.a, self.frontier);
        }
        result
    }
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Actual signed manifest replacement must fail on fixture drift."
)]
fn batch_fence_cannot_fabricate_a_snapshot_from_two_signed_manifests() {
    let value = fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority");
    let frontier = value.request.snapshot.revocation_frontier_digest();
    let mut a = value.owners.clone();
    let mut b = value.owners;
    for owner in &mut a {
        if owner.owner_id.as_str() == "utility.ndu" {
            owner.generation = generation(owner.generation.get() + 1);
        }
    }
    for owner in &mut b {
        if owner.owner_id.as_str() == "context.compiler" {
            owner.generation = generation(owner.generation.get() + 1);
        }
    }
    // A and B are both properly signed, but neither describes the frozen
    // snapshot: the utility lookup can use B and context lookup can use A.
    write_authority_file(&path, &a, frontier);
    let live = FileBackedFreshnessOracleV1::new(path.clone(), authority_verifier());
    let mut mixed = SwitchingManifests {
        oracle: live,
        path: &path,
        a: &a,
        b: &b,
        frontier,
        reads: 0,
    };
    validate_current_snapshot(&value.request.snapshot, &mut mixed)
        .expect("separate live lookups can combine incompatible manifests");

    write_authority_file(&path, &a, frontier);
    let source = FileBackedFreshnessOracleV1::new(path.clone(), authority_verifier());
    let mut batched = SwitchingManifests {
        oracle: source.snapshot_oracle(),
        path: &path,
        a: &a,
        b: &b,
        frontier,
        reads: 0,
    };
    assert_eq!(
        validate_current_snapshot(&value.request.snapshot, &mut batched),
        Err(CanonicalIntelligenceError::StaleOwner(id("utility.ndu")))
    );
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Every fence and live stage must observe subsequent owner rotation."
)]
fn new_fences_and_live_stage_checks_do_not_reuse_a_cached_manifest() {
    let value = fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority");
    let frontier = value.request.snapshot.revocation_frontier_digest();
    write_authority_file(&path, &value.owners, frontier);
    let mut source = FileBackedFreshnessOracleV1::new(path.clone(), authority_verifier());
    let owner_id = id("utility.ndu");
    let before = source.current(&owner_id).expect("initial live owner");
    source
        .validate_snapshot(&value.request.snapshot)
        .expect("initial full fence");
    let mut rotated = value.owners;
    for owner in &mut rotated {
        if owner.owner_id == owner_id {
            owner.generation = generation(owner.generation.get() + 1);
        }
    }
    write_authority_file(&path, &rotated, frontier);
    let after = source.current(&owner_id).expect("rotated live owner");
    assert_eq!(after.generation.get(), before.generation.get() + 1);
    assert_eq!(
        source.validate_snapshot(&value.request.snapshot),
        Err(CanonicalIntelligenceError::StaleOwner(owner_id))
    );
}
