use std::sync::OnceLock;

use trnm_release_bundle::pq_release::PqInitialRootKeyMaterialV1;
use trnm_release_bundle::pq_release::PqReleaseAuthorityV1;
use trnm_release_bundle::pq_release::PqReleaseErrorV1;
use trnm_release_bundle::pq_release::PqReleaseRootV1;

#[cfg(all(test, unix))]
#[path = "release_authority_initial_root_tests.rs"]
mod tests;

/// One owner's immutable initial-root mathematics. No reconstructed authority,
/// initialized time, checkpoint, current-role check or signature result is kept.
/// All callers still hold their original File/recovery lock and replay the log.
#[derive(Default)]
pub(crate) struct InitialRootMaterial {
    keys: OnceLock<PqInitialRootKeyMaterialV1>,
}

impl InitialRootMaterial {
    pub fn bootstrap(
        &self,
        root: PqReleaseRootV1,
        expected_root: [u8; 32],
        initialized_at: u64,
    ) -> Result<PqReleaseAuthorityV1, PqReleaseErrorV1> {
        if self.keys.get().is_none() {
            let prepared = PqInitialRootKeyMaterialV1::prepare_pinned(
                root.clone(),
                expected_root,
                initialized_at,
            )?;
            // A competing initializer may win, but its complete binding is
            // checked below. Never replace the winner or retain a failed result.
            let _ = self.keys.set(prepared);
        }
        let material = self.keys.get().ok_or(PqReleaseErrorV1::RootPin)?;
        PqReleaseAuthorityV1::bootstrap_pinned_with_material(
            root,
            expected_root,
            initialized_at,
            material,
        )
    }
}
