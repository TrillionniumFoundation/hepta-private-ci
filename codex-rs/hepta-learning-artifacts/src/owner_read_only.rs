//! A deployed consumer reads Root-owned CURRENT without obtaining the writer's
//! fence, lease, private keys or mutable storage API.
use super::root_read_frontier::protected_inventory;
use super::root_read_frontier::read_frontier;
use super::*;

pub struct ReadOnlyArtifactCurrentOwnerV1 {
    root: PathBuf,
    verifier: ArtifactOwnerVerifierV1,
    required: Option<SignedCurrentArtifactHeadV1>,
    withdrawals: DatasetWithdrawalRegistry,
    frontier_bytes: Vec<u8>,
}
impl ReadOnlyArtifactCurrentOwnerV1 {
    /// Root's physically protected live frontier must match every supplied
    /// trust/withdrawal field. Raw DTOs alone do not admit a reader.
    pub fn open(
        root: impl AsRef<Path>,
        trust: ArtifactOwnerTrustV1,
        withdrawals: DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<Self, ArtifactOwnerHostError> {
        let root = root.as_ref().to_owned();
        protected_inventory(&root)?;
        let (frontier, frontier_bytes) = read_frontier(&root)?;
        let verifier = ArtifactOwnerVerifierV1::new(trust)?;
        if frontier.trust != verifier.trust_digest()
            || frontier.withdrawal_scope != verifier.trust.withdrawal_scope_digest
            || withdrawals.scope_digest() != Some(frontier.withdrawal_scope)
            || withdrawals.head_digest() != frontier.withdrawal_head
        {
            return Err(ArtifactOwnerHostError::ProvenanceMismatch);
        }
        let owner = Self {
            root,
            verifier,
            required: Some(frontier.current),
            withdrawals,
            frontier_bytes,
        };
        owner.current_registry_view(now)?;
        Ok(owner)
    }
    /// Return only a complete current snapshot with exact native V2 provenance,
    /// withdrawals, original operation history and live signed-head time facts.
    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        protected_inventory(&self.root)?;
        let (frontier, bytes) = read_frontier(&self.root)?;
        if bytes != self.frontier_bytes {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let context = ArtifactOwnerReadContext {
            root: &self.root,
            verifier: &self.verifier,
            required_current_head: &self.required,
        };
        let current = context
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        if current.signed != frontier.current {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let mut view = context.current_registry_view(now)?;
        let provenance = context.current_provenance(view.registry(), &self.withdrawals, now)?;
        view.restrict_eligibility(provenance.ineligible);
        view.bind_source_datasets(provenance.source_datasets);
        protected_inventory(&self.root)?;
        if read_frontier(&self.root)?.1 != bytes
            || context
                .discover_current_head(now)?
                .is_none_or(|head| head.signed != frontier.current)
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok(view)
    }
}

#[cfg(test)]
#[path = "owner_read_only_tests.rs"]
mod tests;
