//! Borrow the same complete snapshot for this admission command only.
use super::*;
use codex_hepta_agent_components::learning_ledger::LedgerSnapshot;

pub(super) struct SnapshotResolver<'a> {
    pub(super) inner: &'a dyn PlasticityOwnerEvidenceResolverV1,
    pub(super) current: &'a LedgerSnapshot,
}
impl PlasticityOwnerEvidenceResolverV1 for SnapshotResolver<'_> {
    fn resolve(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        self.inner.resolve_with_ledger(query, self.current)
    }
}
