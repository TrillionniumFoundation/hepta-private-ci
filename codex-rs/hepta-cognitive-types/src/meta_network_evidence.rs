//! Current-ledger receipt coverage gate for the shadow Meta-Network.
//!
//! The existing source/revision/forget owner must supply this bounded projection
//! of its authenticated receipt index. Equality and membership checks are not
//! authentication, a writer, nor proof that an underlying fact is true.

use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use crate::hnmf::ContractDigestV1;
use crate::hnmf::HnmfContractError;
use crate::meta_network::MAX_META_NETWORK_BIDS_V1;
use crate::meta_network::MAX_META_NETWORK_LINKS_V1;
use crate::meta_network::META_NETWORK_SCHEMA_VERSION_V1;
use crate::meta_network::MetaNetworkLedgerWitnessV1;
use crate::meta_network::MetaNetworkNextSnapshotCandidateV1;
use crate::meta_network::MetaNetworkPlanV1;
use crate::meta_network::MetaNetworkRouteReceiptV1;
use crate::meta_network::propose_meta_network_route_v1;

/// Maximal query-scoped receipt coverage, never a mirror of the full ledger.
pub const MAX_META_NETWORK_EVIDENCE_RECEIPTS_V1: usize =
    MAX_META_NETWORK_BIDS_V1 + MAX_META_NETWORK_LINKS_V1;

/// One bounded view from the authenticated external source/forget owner.
/// Supplying equal digests from an untrusted caller does not authenticate it.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetaNetworkEvidenceCatalogV1 {
    pub schema_version: u32,
    pub ledger_root_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub admission_receipt_digest: ContractDigestV1,
    pub live_receipt_digests: BTreeSet<ContractDigestV1>,
    pub revoked_receipt_digests: BTreeSet<ContractDigestV1>,
}

impl MetaNetworkEvidenceCatalogV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != META_NETWORK_SCHEMA_VERSION_V1 {
            return Err(HnmfContractError::Invalid("meta evidence schema"));
        }
        if self.live_receipt_digests.len() > MAX_META_NETWORK_EVIDENCE_RECEIPTS_V1
            || self.revoked_receipt_digests.len() > MAX_META_NETWORK_EVIDENCE_RECEIPTS_V1
        {
            return Err(HnmfContractError::Invalid("meta evidence bounds"));
        }
        if !self.live_receipt_digests.is_disjoint(&self.revoked_receipt_digests) {
            return Err(HnmfContractError::Conflict("meta evidence live revoked overlap"));
        }
        Ok(())
    }

    /// Every considered bid and graph edge must remain live, including
    /// candidates that would abstain and conflicts that would suppress Cells.
    pub fn validate_against_plan(
        &self,
        plan: &MetaNetworkPlanV1,
        witness: &MetaNetworkLedgerWitnessV1,
    ) -> Result<(), HnmfContractError> {
        self.validate()?;
        plan.validate()?;
        if self.ledger_root_digest != witness.ledger_root_digest
            || self.source_frontier_digest != witness.source_frontier_digest
            || self.forget_frontier_digest != witness.forget_frontier_digest
            || self.admission_receipt_digest != witness.admission_receipt_digest
            || plan.ledger_root_digest != witness.ledger_root_digest
            || plan.source_frontier_digest != witness.source_frontier_digest
            || plan.forget_frontier_digest != witness.forget_frontier_digest
            || plan.admission_receipt_digest != witness.admission_receipt_digest
        {
            return Err(HnmfContractError::Conflict("meta evidence ledger frontier"));
        }
        for bid in &plan.bids {
            if self.revoked_receipt_digests.contains(&bid.evidence_receipt_digest) {
                return Err(HnmfContractError::Conflict("meta revoked bid evidence"));
            }
            if !self.live_receipt_digests.contains(&bid.evidence_receipt_digest) {
                return Err(HnmfContractError::Missing("meta bid evidence"));
            }
        }
        for link in &plan.links {
            if self.revoked_receipt_digests.contains(&link.evidence_receipt_digest) {
                return Err(HnmfContractError::Conflict("meta revoked link evidence"));
            }
            if !self.live_receipt_digests.contains(&link.evidence_receipt_digest) {
                return Err(HnmfContractError::Missing("meta link evidence"));
            }
        }
        Ok(())
    }
}

/// Evidence-covered pure route. It adds no retrieval, selector, writer, model,
/// scheduler, topology-apply, FinalUse or permission path.
pub fn propose_meta_network_route_with_evidence_v1(
    plan: &MetaNetworkPlanV1,
    witness: &MetaNetworkLedgerWitnessV1,
    catalog: &MetaNetworkEvidenceCatalogV1,
) -> Result<MetaNetworkRouteReceiptV1, HnmfContractError> {
    catalog.validate_against_plan(plan, witness)?;
    propose_meta_network_route_v1(plan, witness)
}

impl MetaNetworkNextSnapshotCandidateV1 {
    /// Match a next-snapshot candidate against a recomputed, evidence-covered
    /// route. Replay, Artifact, Evaluation and Topology owners still must
    /// independently authenticate the opaque digest references before use.
    pub fn validate_against_live_evidence(
        &self,
        route: &MetaNetworkRouteReceiptV1,
        plan: &MetaNetworkPlanV1,
        witness: &MetaNetworkLedgerWitnessV1,
        catalog: &MetaNetworkEvidenceCatalogV1,
    ) -> Result<(), HnmfContractError> {
        let expected = propose_meta_network_route_with_evidence_v1(plan, witness, catalog)?;
        if &expected != route {
            return Err(HnmfContractError::Conflict("meta evidence route recomputation"));
        }
        self.validate_against_route(route)
    }
}
