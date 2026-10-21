//! Authority-free multi-Cell shadow recall: one immutable cue and snapshot,
//! typed Cell ticks, then evidence-bound Meta-Network routing. This adapter
//! owns no Encoder driver, writer, selector, weight update or topology apply.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::HnmfContractError;
use codex_hepta_cognitive_types::hnmf::PPM;
use codex_hepta_cognitive_types::memory_cell::MemoryCellManifestV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellTickInputV1;
use codex_hepta_cognitive_types::memory_meta_network::MAX_MEMORY_META_CANDIDATES_V1;
use codex_hepta_cognitive_types::memory_meta_network::MAX_MEMORY_META_BUDGET_UNITS_V1;
use codex_hepta_cognitive_types::memory_meta_network::MemoryMetaNetworkPolicyV1;
use codex_hepta_cognitive_types::memory_meta_network::MemoryMetaRoutingCandidateV1;
use codex_hepta_cognitive_types::memory_meta_network::MemoryMetaShadowRouteV1;
use codex_hepta_cognitive_types::memory_meta_network::route_memory_cells_v1;

use codex_hepta_types::Digest32;

use crate::EngramDynamicsPolicyV1;
use crate::EngramSnapshotV1;
use crate::GeneratedCandidateInputV1;
use crate::MemoryCellRuntimeErrorV1;
use crate::MemoryCellShadowTickV1;
use crate::MemoryCueV1;
use crate::RetrievalPolicyV1;
use crate::run_memory_cell_tick;

/// One already-evidenced Cell projection evaluated against the shared immutable
/// retrieval cue/snapshot. The support and assessment are external references.
#[derive(Clone)]
pub struct MemoryMetaCellTickSpecV1 {
    pub manifest: MemoryCellManifestV1,
    pub tick_input: MemoryCellTickInputV1,
    pub generated_input: GeneratedCandidateInputV1,
    pub evidence_ledger_digest: ContractDigestV1,
    pub encoder_feature_digest: ContractDigestV1,
    pub support_digest: Option<ContractDigestV1>,
    pub independent_assessment_digest: ContractDigestV1,
    pub relevance_ppm: u32,
    pub resource_cost_units: u32,
    pub association_group_digest: Option<ContractDigestV1>,
    pub contradiction_group_digest: Option<ContractDigestV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryMetaShadowBatchV1 {
    pub cell_ticks: Vec<MemoryCellShadowTickV1>,
    pub routing: MemoryMetaShadowRouteV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryMetaBatchErrorV1 {
    Contract(HnmfContractError),
    Tick {
        cell_id: ContractIdV1,
        source: MemoryCellRuntimeErrorV1,
    },
}

impl std::fmt::Display for MemoryMetaBatchErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for MemoryMetaBatchErrorV1 {}

fn preflight_memory_meta_batch_v1(
    policy: &MemoryMetaNetworkPolicyV1,
    cue: &MemoryCueV1,
    engram_snapshot: &EngramSnapshotV1,
    cells: &[MemoryMetaCellTickSpecV1],
) -> Result<(), MemoryMetaBatchErrorV1> {
    policy.validate().map_err(MemoryMetaBatchErrorV1::Contract)?;
    if cells.len() > MAX_MEMORY_META_CANDIDATES_V1 {
        return Err(MemoryMetaBatchErrorV1::Contract(
            HnmfContractError::Invalid("memory meta candidate count"),
        ));
    }
    if policy.snapshot_digest.digest() != engram_snapshot.snapshot_digest {
        return Err(MemoryMetaBatchErrorV1::Contract(
            HnmfContractError::Conflict("memory meta shared snapshot"),
        ));
    }
    let mut identities = BTreeSet::new();
    for cell in cells {
        if !identities.insert(cell.manifest.cell_id.clone()) {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::DuplicateIdentity("memory meta cell"),
            ));
        }
        // Validate every Cell and its complete predecessor/generation binding
        // before executing any tick. A late invalid Cell must never cause
        // earlier Cells to expend shadow retrieval work.
        cell.manifest
            .validate()
            .map_err(MemoryMetaBatchErrorV1::Contract)?;
        cell.tick_input
            .validate()
            .map_err(MemoryMetaBatchErrorV1::Contract)?;
        // Check the real invocation cue and objective across the complete
        // batch, including deferred Cells, before the first retrieval tick.
        if cell.tick_input.cue_digest.digest() != cue.digest()
            || cell.tick_input.objective_digest.digest() != cue.objective_digest
        {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::Conflict("memory meta pre-tick cue or objective"),
            ));
        }
        if cell.manifest.cell_id != cell.tick_input.cell_id
            || cell.manifest.graph_generation != cell.tick_input.graph_generation
            || cell.manifest.model_generation != cell.tick_input.model_generation
            || cell.manifest.source_frontier_digest != cell.tick_input.source_frontier_digest
            || cell.manifest.forget_frontier_digest != cell.tick_input.forget_frontier_digest
        {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::Conflict("memory meta tick binding"),
            ));
        }
        // Reject invalid routing metadata before any shadow tick, while
        // preserving the immutable Encoder and evidence-frontier bindings.
        if cell.relevance_ppm > PPM {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::Invalid("memory meta candidate relevance"),
            ));
        }
        if cell.resource_cost_units == 0
            || cell.resource_cost_units > MAX_MEMORY_META_BUDGET_UNITS_V1
        {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::Invalid("memory meta candidate cost"),
            ));
        }
        // A global sparse budget must not admit work exceeding the Cell's
        // own declared tick budget, including a low-ranked deferred Cell.
        if cell.resource_cost_units > cell.tick_input.resource_budget_units {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::Conflict("memory meta local tick budget"),
            ));
        }
        if cell.manifest.shared_base_digest != policy.shared_base_digest
            || cell.manifest.encoder_digest != policy.encoder_digest
            || cell.encoder_feature_digest != policy.encoder_feature_digest
            || cell.evidence_ledger_digest != policy.evidence_ledger_digest
            || cell.manifest.source_frontier_digest != policy.source_frontier_digest
            || cell.manifest.forget_frontier_digest != policy.forget_frontier_digest
            || cell.manifest.graph_generation != policy.graph_generation
            || cell.manifest.model_generation != policy.model_generation
            || cell.tick_input.snapshot_digest != policy.snapshot_digest
        {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::Conflict("memory meta evidence or generation drift"),
            ));
        }
    }

    Ok(())
}

pub fn run_memory_meta_batch_shadow_v1(
    policy: &MemoryMetaNetworkPolicyV1,
    cue: &MemoryCueV1,
    retrieval_policy: &RetrievalPolicyV1,
    engram_snapshot: &EngramSnapshotV1,
    dynamics_policy: &EngramDynamicsPolicyV1,
    cells: &[MemoryMetaCellTickSpecV1],
) -> Result<MemoryMetaShadowBatchV1, MemoryMetaBatchErrorV1> {
    preflight_memory_meta_batch_v1(policy, cue, engram_snapshot, cells)?;

    let mut cell_ticks = Vec::with_capacity(cells.len());
    let mut candidates = Vec::with_capacity(cells.len());
    for cell in cells {
        let tick = run_memory_cell_tick(
            &cell.manifest,
            &cell.tick_input,
            cue,
            retrieval_policy,
            &cell.generated_input,
            engram_snapshot,
            dynamics_policy,
        )
        .map_err(|source| MemoryMetaBatchErrorV1::Tick {
            cell_id: cell.manifest.cell_id.clone(),
            source,
        })?;
        candidates.push(MemoryMetaRoutingCandidateV1 {
            manifest: cell.manifest.clone(),
            tick_input: cell.tick_input.clone(),
            tick_receipt: tick.receipt.clone(),
            evidence_ledger_digest: cell.evidence_ledger_digest,
            encoder_feature_digest: cell.encoder_feature_digest,
            support_digest: cell.support_digest,
            independent_assessment_digest: cell.independent_assessment_digest,
            relevance_ppm: cell.relevance_ppm,
            resource_cost_units: cell.resource_cost_units,
            association_group_digest: cell.association_group_digest,
            contradiction_group_digest: cell.contradiction_group_digest,
        });
        cell_ticks.push(tick);
    }
    let routing =
        route_memory_cells_v1(policy, &candidates).map_err(MemoryMetaBatchErrorV1::Contract)?;
    Ok(MemoryMetaShadowBatchV1 {
        cell_ticks,
        routing,
    })
}


/// A provisional, metadata-only admission plan. Digest values bind claimed
/// inputs; they are not signatures or source-ledger membership proofs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryMetaPreTickPlanV1 {
    pub admission_input_digest: ContractDigestV1,
    pub admission_plan_digest: ContractDigestV1,
    pub admitted_cell_ids: Vec<ContractIdV1>,
    pub deferred_cell_ids: Vec<ContractIdV1>,
    pub reserved_compute_units: u32,
    pub current_snapshot_immutable: bool,
    pub production_activation_allowed: bool,
}

/// Revalidate a rehydrated pre-tick plan against the complete immutable input.
/// The two digests alone are not evidence of a correct admission decision:
/// replay must reproduce all identities, resource accounting and authority.
impl MemoryMetaPreTickPlanV1 {
    pub fn validate_against(
        &self,
        policy: &MemoryMetaNetworkPolicyV1,
        cue: &MemoryCueV1,
        engram_snapshot: &EngramSnapshotV1,
        cells: &[MemoryMetaCellTickSpecV1],
    ) -> Result<(), MemoryMetaBatchErrorV1> {
        if !self.current_snapshot_immutable || self.production_activation_allowed {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::Conflict("memory meta pre-tick authority"),
            ));
        }
        let expected = plan_memory_meta_pre_ticks_shadow_v1(
            policy,
            cue,
            engram_snapshot,
            cells,
        )?;
        if *self != expected {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::Conflict("memory meta pre-tick source binding"),
            ));
        }
        Ok(())
    }
}

/// Pre-tick admission plus post-tick evaluation. A deferred Cell is not run;
/// the final route still independently checks the actual tick receipts.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryMetaPreselectedShadowV1 {
    pub pre_tick_plan: MemoryMetaPreTickPlanV1,
    pub batch: MemoryMetaShadowBatchV1,
}

fn frame_pretick_digest(output: &mut Vec<u8>, digest: ContractDigestV1) {
    output.extend_from_slice(digest.digest().as_array());
}

fn frame_pretick_optional_digest(output: &mut Vec<u8>, digest: Option<ContractDigestV1>) {
    match digest {
        Some(digest) => {
            output.push(1);
            frame_pretick_digest(output, digest);
        }
        None => output.push(0),
    }
}

fn frame_pretick_id(output: &mut Vec<u8>, id: &ContractIdV1) {
    let bytes = id.as_str().as_bytes();
    output.extend_from_slice(&(bytes.len() as u32).to_be_bytes());
    output.extend_from_slice(bytes);
}

fn frame_pretick_optional_id(output: &mut Vec<u8>, id: Option<&ContractIdV1>) {
    match id {
        Some(id) => {
            output.push(1);
            frame_pretick_id(output, id);
        }
        None => output.push(0),
    }
}

fn frame_pretick_text(output: &mut Vec<u8>, text: &str) {
    output.extend_from_slice(&(text.len() as u32).to_be_bytes());
    output.extend_from_slice(text.as_bytes());
}

/// Conservatively select *before* running Cell retrieval. Rankings and costs
/// are untrusted shadow hints; absence of a support reference and ambiguous
/// contradiction groups are filtered, never used to authorize factual claims.
pub fn plan_memory_meta_pre_ticks_shadow_v1(
    policy: &MemoryMetaNetworkPolicyV1,
    cue: &MemoryCueV1,
    engram_snapshot: &EngramSnapshotV1,
    cells: &[MemoryMetaCellTickSpecV1],
) -> Result<MemoryMetaPreTickPlanV1, MemoryMetaBatchErrorV1> {
    preflight_memory_meta_batch_v1(policy, cue, engram_snapshot, cells)?;
    let mut by_identity: Vec<&MemoryMetaCellTickSpecV1> = cells.iter().collect();
    by_identity.sort_by(|a, b| a.manifest.cell_id.cmp(&b.manifest.cell_id));

    // Bind the complete admitted-input *metadata* set, not just winners.
    // Generated evidence is independently bound by the actual tick receipt.
    let mut framed = b"hepta.memory-meta.pretick.inputs.v1".to_vec();
    for digest in [
        policy.shared_base_digest,
        policy.encoder_digest,
        policy.encoder_feature_digest,
        policy.evidence_ledger_digest,
        policy.snapshot_digest,
        policy.source_frontier_digest,
        policy.forget_frontier_digest,
    ] {
        frame_pretick_digest(&mut framed, digest);
    }
    for number in [
        policy.graph_generation.get(),
        policy.model_generation.get(),
        u64::from(policy.maximum_selected_cells),
        u64::from(policy.maximum_compute_units),
        u64::from(policy.minimum_relevance_ppm),
        u64::from(policy.minimum_confidence_ppm),
        u64::from(policy.maximum_ood_ppm),
    ] {
        framed.extend_from_slice(&number.to_be_bytes());
    }
    for cell in &by_identity {
        frame_pretick_id(&mut framed, &cell.manifest.cell_id);
        frame_pretick_optional_id(&mut framed, cell.manifest.parent_cell_id.as_ref());
        // These Debug tags are exact-source shadow framing, not a stable
        // external wire schema or cross-version canonical serialization.
        frame_pretick_text(&mut framed, &format!("{:?}", cell.manifest.role));
        frame_pretick_text(&mut framed, &format!("{:?}", cell.manifest.modalities));
        frame_pretick_text(&mut framed, &format!("{:?}", cell.manifest.populations));
        for digest in [
            cell.manifest.adapter_artifact_digest,
            cell.manifest.head_artifact_digest,
            cell.manifest.state_schema_digest,
            cell.manifest.lineage_digest,
            cell.tick_input.input_digest,
            cell.tick_input.cue_digest,
            cell.tick_input.objective_digest,
            cell.tick_input.ndu_state_digest,
            cell.evidence_ledger_digest,
            cell.encoder_feature_digest,
            cell.independent_assessment_digest,
        ] {
            frame_pretick_digest(&mut framed, digest);
        }
        frame_pretick_optional_digest(&mut framed, cell.tick_input.predecessor_checkpoint_digest);
        frame_pretick_optional_digest(&mut framed, cell.support_digest);
        frame_pretick_optional_digest(&mut framed, cell.association_group_digest);
        frame_pretick_optional_digest(&mut framed, cell.contradiction_group_digest);
        framed.extend_from_slice(cell.generated_input.source_completeness_digest.as_array());
        for value in [
            cell.tick_input.logical_sequence,
            u64::from(cell.tick_input.resource_budget_units),
            u64::from(cell.manifest.max_active_cells),
            u64::from(cell.manifest.max_state_bytes),
            u64::from(cell.relevance_ppm),
            u64::from(cell.resource_cost_units),
        ] {
            framed.extend_from_slice(&value.to_be_bytes());
        }
    }
    let input_digest = ContractDigestV1::from_digest(Digest32::of_bytes(&framed))
        .map_err(MemoryMetaBatchErrorV1::Contract)?;

    let mut conflict_counts: BTreeMap<ContractDigestV1, usize> = BTreeMap::new();
    for cell in &by_identity {
        if cell.support_digest.is_some()
            && cell.relevance_ppm >= policy.minimum_relevance_ppm
        {
            if let Some(group) = cell.contradiction_group_digest {
                *conflict_counts.entry(group).or_default() += 1;
            }
        }
    }
    let mut ranked = by_identity;
    ranked.sort_by(|a, b| {
        b.relevance_ppm
            .cmp(&a.relevance_ppm)
            .then_with(|| a.resource_cost_units.cmp(&b.resource_cost_units))
            .then_with(|| a.manifest.cell_id.cmp(&b.manifest.cell_id))
    });

    let mut admitted = Vec::new();
    let mut deferred = Vec::new();
    let mut spent = 0_u32;
    for cell in ranked {
        let conflict = cell.contradiction_group_digest.is_some_and(|group| {
            conflict_counts.get(&group).copied().unwrap_or(0) > 1
        });
        if cell.support_digest.is_none()
            || cell.relevance_ppm < policy.minimum_relevance_ppm
            || conflict
            || admitted.len() >= usize::from(policy.maximum_selected_cells)
            || cell.resource_cost_units > policy.maximum_compute_units - spent
        {
            deferred.push(cell.manifest.cell_id.clone());
        } else {
            spent += cell.resource_cost_units;
            admitted.push(cell.manifest.cell_id.clone());
        }
    }
    let mut frame = b"hepta.memory-meta.pretick.plan.v1".to_vec();
    frame_pretick_digest(&mut frame, input_digest);
    frame.extend_from_slice(&spent.to_be_bytes());
    frame.extend_from_slice(&(admitted.len() as u32).to_be_bytes());
    for id in &admitted {
        frame_pretick_id(&mut frame, id);
    }
    frame.extend_from_slice(&(deferred.len() as u32).to_be_bytes());
    for id in &deferred {
        frame_pretick_id(&mut frame, id);
    }
    let plan_digest = ContractDigestV1::from_digest(Digest32::of_bytes(&frame))
        .map_err(MemoryMetaBatchErrorV1::Contract)?;
    Ok(MemoryMetaPreTickPlanV1 {
        admission_input_digest: input_digest,
        admission_plan_digest: plan_digest,
        admitted_cell_ids: admitted,
        deferred_cell_ids: deferred,
        reserved_compute_units: spent,
        current_snapshot_immutable: true,
        production_activation_allowed: false,
    })
}

/// This alternative shadow path actually skips non-admitted Cell ticks. The
/// legacy full shadow batch remains unchanged as a control. This is not proof
/// of physical Encoder/GPU FLOPs, correct estimator costs or evidence validity.
pub fn run_memory_meta_preselected_shadow_v1(
    policy: &MemoryMetaNetworkPolicyV1,
    cue: &MemoryCueV1,
    retrieval_policy: &RetrievalPolicyV1,
    engram_snapshot: &EngramSnapshotV1,
    dynamics_policy: &EngramDynamicsPolicyV1,
    cells: &[MemoryMetaCellTickSpecV1],
) -> Result<MemoryMetaPreselectedShadowV1, MemoryMetaBatchErrorV1> {
    let pre_tick_plan =
        plan_memory_meta_pre_ticks_shadow_v1(policy, cue, engram_snapshot, cells)?;
    let admitted: BTreeSet<ContractIdV1> =
        pre_tick_plan.admitted_cell_ids.iter().cloned().collect();
    let mut selected: Vec<MemoryMetaCellTickSpecV1> = cells
        .iter()
        .filter(|cell| admitted.contains(&cell.manifest.cell_id))
        .cloned()
        .collect();
    selected.sort_by(|a, b| a.manifest.cell_id.cmp(&b.manifest.cell_id));
    let batch = run_memory_meta_batch_shadow_v1(
        policy,
        cue,
        retrieval_policy,
        engram_snapshot,
        dynamics_policy,
        &selected,
    )?;
    if batch.routing.receipt.resource_used_units > pre_tick_plan.reserved_compute_units {
        return Err(MemoryMetaBatchErrorV1::Contract(
            HnmfContractError::Conflict("memory meta pre-tick accounting"),
        ));
    }
    Ok(MemoryMetaPreselectedShadowV1 {
        pre_tick_plan,
        batch,
    })
}

/// Exact snapshot/frontier tuple presented to the *external* evidence owner.
/// A digest reference is not itself proof of membership or deletion.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryMetaEvidenceLookupV1 {
    pub cell_id: ContractIdV1,
    pub support_digest: ContractDigestV1,
    pub evidence_ledger_digest: ContractDigestV1,
    pub snapshot_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
}

/// Shadow-only admission requiring a caller-owned evidence-ledger check *before*
/// any admitted Cell tick. The caller must supply an independently authenticated,
/// snapshot-consistent verifier that also enforces tombstone/forget membership;
/// this adapter cannot turn a caller-controlled boolean into such proof.
///
/// Every admissible Cell is checked both before and after retrieval; one
/// rejection, including a post-tick revocation, discards the whole batch.
/// Verification callbacks must be idempotent and bound to one trusted ledger
/// owner. This does not implement atomic pinning or independent signatures.
/// Deferred Cells are never retrieved. The ordinary unverified shadow control
/// remains available separately and has no production-use authority.
pub fn run_memory_meta_preselected_evidence_checked_shadow_v1<F>(
    policy: &MemoryMetaNetworkPolicyV1,
    cue: &MemoryCueV1,
    retrieval_policy: &RetrievalPolicyV1,
    engram_snapshot: &EngramSnapshotV1,
    dynamics_policy: &EngramDynamicsPolicyV1,
    cells: &[MemoryMetaCellTickSpecV1],
    mut verify_support: F,
) -> Result<MemoryMetaPreselectedShadowV1, MemoryMetaBatchErrorV1>
where
    F: FnMut(&MemoryMetaEvidenceLookupV1) -> bool,
{
    let plan = plan_memory_meta_pre_ticks_shadow_v1(policy, cue, engram_snapshot, cells)?;
    let mut admitted_evidence = Vec::with_capacity(plan.admitted_cell_ids.len());
    for cell_id in &plan.admitted_cell_ids {
        let cell = cells
            .iter()
            .find(|cell| &cell.manifest.cell_id == cell_id)
            .ok_or(MemoryMetaBatchErrorV1::Contract(HnmfContractError::Missing(
                "memory meta admitted cell",
            )))?;
        let support_digest = cell.support_digest.ok_or(
            MemoryMetaBatchErrorV1::Contract(HnmfContractError::Missing(
                "memory meta admitted support",
            )),
        )?;
        let lookup = MemoryMetaEvidenceLookupV1 {
            cell_id: cell.manifest.cell_id.clone(),
            support_digest,
            evidence_ledger_digest: policy.evidence_ledger_digest,
            snapshot_digest: policy.snapshot_digest,
            source_frontier_digest: policy.source_frontier_digest,
            forget_frontier_digest: policy.forget_frontier_digest,
        };
        if !verify_support(&lookup) {
            return Err(MemoryMetaBatchErrorV1::Contract(HnmfContractError::Conflict(
                "memory meta external evidence rejected",
            )));
        }
        admitted_evidence.push(lookup);
    }
    let outcome = run_memory_meta_preselected_shadow_v1(
        policy,
        cue,
        retrieval_policy,
        engram_snapshot,
        dynamics_policy,
        cells,
    )?;
    if outcome.pre_tick_plan != plan {
        return Err(MemoryMetaBatchErrorV1::Contract(HnmfContractError::Conflict(
            "memory meta evidence plan changed",
        )));
    }
    // An external source may have forgotten a support while ticks were being
    // evaluated. Recheck every admitted identity/frontier tuple immediately
    // before returning; never publish a partly revalidated shadow route.
    // This is a fail-closed detection seam, not an atomic ledger snapshot.
    for lookup in &admitted_evidence {
        if !verify_support(lookup) {
            return Err(MemoryMetaBatchErrorV1::Contract(HnmfContractError::Conflict(
                "memory meta external evidence changed",
            )));
        }
    }
    Ok(outcome)
}
