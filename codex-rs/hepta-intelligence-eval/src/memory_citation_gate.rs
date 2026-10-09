//! Complete citation census bound to an already independently selected candidate.
//! This consumes attestations from the existing delivery observer; it owns no
//! log, signs nothing, and cannot turn a test clock or fixture signer into truth.
use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CitationAuditError;
use crate::LongitudinalTimeEvidenceV1;
use crate::SelfEvolutionSelectionReceiptV1;
use crate::VerifiedCitationAuditV1;
use crate::VerifiedSelfEvolutionSelectionV1;

const MAX_AUDITS: usize = 20_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemorySnapshotCensusV1 {
    pub snapshot_id: StableId,
    pub source_cut: Digest32,
    /// The current delivery owner's immutable log anchor. Its observer attests
    /// completeness; clients must not invent a head from returned successes.
    pub delivery_log_head: Digest32,
    pub starts_unix_micros: u64,
    pub ends_unix_micros: u64,
    /// All attempted deliveries, including failures, not just audited successes.
    pub attempted_deliveries: u64,
    pub request_digests: Vec<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCitationCensusV1 {
    pub selection_digest: Digest32,
    pub snapshots: Vec<MemorySnapshotCensusV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MemoryCitationGateCountsV1 {
    pub audited_deliveries: u64,
    pub independent_source_groups: u64,
    pub snapshots: u32,
    pub citations: u64,
    pub entailed: u64,
    pub factual_claims: u64,
}

/// Opaque proof of a complete, non-vacuous signed census. It supplements, never
/// replaces, statistical selection, source admission and final-use authority.
#[derive(Clone, Debug)]
pub struct VerifiedMemoryCitationGateV1 {
    decision_digest: Digest32,
    candidate_digest: Digest32,
    objective_digest: Digest32,
    dataset_digest: Digest32,
    digest: Digest32,
    trust_digest: Digest32,
    observer: VerifiedLearningEvidenceV1,
    audits: Vec<VerifiedCitationAuditV1>,
    counts: MemoryCitationGateCountsV1,
    admitted_at: u64,
}
impl VerifiedMemoryCitationGateV1 {
    pub fn decision_digest(&self) -> Digest32 {
        self.decision_digest
    }
    pub fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }
    pub fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }
    pub fn dataset_digest(&self) -> Digest32 {
        self.dataset_digest
    }
    pub fn digest(&self) -> Digest32 {
        self.digest
    }
    pub fn counts(&self) -> MemoryCitationGateCountsV1 {
        self.counts
    }
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    /// Must use host-refreshed trust AND the source owner's withdrawal view.
    /// Neither an old backup nor an empty request-supplied list is a refresh.
    pub fn revalidate_current(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        revoked_roots: &BTreeSet<Digest32>,
        now: u64,
    ) -> Result<(), CitationAuditError> {
        if self.trust_digest != verifier.trust_digest() || now < self.admitted_at {
            return Err(CitationAuditError::Invalid("stale memory citation gate"));
        }
        for audit in &self.audits {
            audit.revalidate_current(verifier, revoked_roots, now)?;
            verify_signed_actor_separation(&self.observer, &audit.generator, now)?;
            verify_signed_actor_separation(&self.observer, &audit.evaluator, now)?;
        }
        Ok(())
    }
}

/// Canonical binary payload. A signature covers the exact attempted count and
/// request inventory, not a rounded precision or a caller-provided percentage.
pub fn memory_citation_census_payload_v1(
    census: &MemoryCitationCensusV1,
) -> Result<Vec<u8>, CitationAuditError> {
    if census.selection_digest.is_zero() || !(3..=32).contains(&census.snapshots.len()) {
        return Err(CitationAuditError::Invalid("census bounds"));
    }
    let mut out = b"hepta.memory-citation.complete-census.v1\0".to_vec();
    out.extend_from_slice(census.selection_digest.as_array());
    out.extend_from_slice(&(census.snapshots.len() as u64).to_be_bytes());
    let mut ids = BTreeSet::new();
    let mut cuts = BTreeSet::new();
    let mut heads = BTreeSet::new();
    let mut requests = BTreeSet::new();
    for snapshot in &census.snapshots {
        if !ids.insert(&snapshot.snapshot_id)
            || snapshot.source_cut.is_zero()
            || !cuts.insert(snapshot.source_cut)
            || snapshot.delivery_log_head.is_zero()
            || !heads.insert(snapshot.delivery_log_head)
            || snapshot.starts_unix_micros == 0
            || snapshot.starts_unix_micros >= snapshot.ends_unix_micros
            || snapshot.request_digests.is_empty()
            || snapshot.attempted_deliveries != snapshot.request_digests.len() as u64
            || snapshot.request_digests.len() > MAX_AUDITS
        {
            return Err(CitationAuditError::Invalid(
                "incomplete or duplicate snapshot",
            ));
        }
        let id = snapshot.snapshot_id.as_str().as_bytes();
        out.extend_from_slice(&(id.len() as u64).to_be_bytes());
        out.extend_from_slice(id);
        out.extend_from_slice(snapshot.source_cut.as_array());
        out.extend_from_slice(snapshot.delivery_log_head.as_array());
        for value in [
            snapshot.starts_unix_micros,
            snapshot.ends_unix_micros,
            snapshot.attempted_deliveries,
        ] {
            out.extend_from_slice(&value.to_be_bytes());
        }
        for digest in &snapshot.request_digests {
            if digest.is_zero() || !requests.insert(*digest) || requests.len() > MAX_AUDITS {
                return Err(CitationAuditError::Invalid(
                    "duplicate or oversized audit census",
                ));
            }
            out.extend_from_slice(digest.as_array());
        }
    }
    Ok(out)
}

pub fn verify_memory_citation_census_v1(
    selected: &VerifiedSelfEvolutionSelectionV1,
    census: &MemoryCitationCensusV1,
    observer: &SignedLearningEvidenceV1,
    audits: Vec<VerifiedCitationAuditV1>,
    verifier: &LearningEvidenceVerifierV1,
    revoked_roots: &BTreeSet<Digest32>,
    now: u64,
) -> Result<VerifiedMemoryCitationGateV1, CitationAuditError> {
    selected
        .revalidate_current(verifier, now)
        .map_err(|_| CitationAuditError::Invalid("stale selection"))?;
    if census.selection_digest != selected.selection_digest() {
        return Err(CitationAuditError::Invalid("different selection census"));
    }
    let gate = verify_census(
        CensusContext {
            selection: selected.receipt(),
            snapshot_ids: &selected.snapshot_ids,
            timing: &selected.timing,
            verifier,
            revoked_roots,
            now,
        },
        census,
        observer,
        audits,
    )?;
    selected
        .check_observer(&gate.observer, verifier, now)
        .map_err(|_| CitationAuditError::Invalid("selector/observer separation"))?;
    Ok(gate)
}

struct CensusContext<'a> {
    selection: &'a SelfEvolutionSelectionReceiptV1,
    snapshot_ids: &'a [StableId],
    timing: &'a LongitudinalTimeEvidenceV1,
    verifier: &'a LearningEvidenceVerifierV1,
    revoked_roots: &'a BTreeSet<Digest32>,
    now: u64,
}

fn verify_census(
    context: CensusContext<'_>,
    census: &MemoryCitationCensusV1,
    signed: &SignedLearningEvidenceV1,
    audits: Vec<VerifiedCitationAuditV1>,
) -> Result<VerifiedMemoryCitationGateV1, CitationAuditError> {
    let CensusContext {
        selection,
        snapshot_ids: expected_snapshots,
        timing,
        verifier,
        revoked_roots,
        now,
    } = context;
    let payload = memory_citation_census_payload_v1(census)?;
    let observer = verifier.verify(LearningEvidenceRoleV1::Observer, signed, &payload, now)?;
    let snapshots = census
        .snapshots
        .iter()
        .map(|s| (s.snapshot_id.clone(), s))
        .collect::<BTreeMap<_, _>>();
    if snapshots.keys().collect::<BTreeSet<_>>() != expected_snapshots.iter().collect()
        || expected_snapshots.len() < 3
        || timing.windows.len() < 2
        || selection.minimum_dataset_records < 200
        || selection.evaluation_trust_digest != verifier.trust_digest()
        || selection.objective_digest != verifier.objective_digest()
    {
        return Err(CitationAuditError::Invalid("selection/census context"));
    }
    for snapshot in &census.snapshots {
        if snapshot.ends_unix_micros > signed.issued_at || snapshot.ends_unix_micros > now {
            return Err(CitationAuditError::Invalid("unobserved snapshot"));
        }
    }
    for window in &timing.windows {
        let snapshot = snapshots
            .get(&window.snapshot_id)
            .ok_or(CitationAuditError::Invalid("missing observed window"))?;
        if snapshot.source_cut != window.observed_source_cut
            || snapshot.starts_unix_micros != window.starts_unix_micros
            || snapshot.ends_unix_micros != window.ends_unix_micros
            || snapshot.attempted_deliveries != window.observation_count
        {
            return Err(CitationAuditError::Invalid("window/census mismatch"));
        }
    }
    let expected = census
        .snapshots
        .iter()
        .flat_map(|s| s.request_digests.iter().map(move |d| (*d, &s.snapshot_id)))
        .collect::<BTreeMap<_, _>>();
    if audits.len() != expected.len() {
        return Err(CitationAuditError::Invalid(
            "missing or extra citation audit",
        ));
    }
    let mut seen = BTreeSet::new();
    let mut identities = BTreeSet::new();
    let mut parent = (0..audits.len()).collect::<Vec<_>>();
    let mut family_owner = BTreeMap::new();
    let mut root_owner = BTreeMap::new();
    let mut counts = MemoryCitationGateCountsV1 {
        audited_deliveries: audits.len() as u64,
        independent_source_groups: 0,
        snapshots: snapshots.len() as u32,
        citations: 0,
        entailed: 0,
        factual_claims: 0,
    };
    let mut seal = payload;
    seal.extend_from_slice(&signed.signing_bytes());
    seal.extend_from_slice(&signed.signature);
    for (index, audit) in audits.iter().enumerate() {
        audit.revalidate_current(verifier, revoked_roots, now)?;
        verify_signed_actor_separation(&observer, &audit.generator, now)?;
        verify_signed_actor_separation(&observer, &audit.evaluator, now)?;
        if !expected.contains_key(&audit.request_digest())
            || !seen.insert(audit.request_digest())
            || !identities.insert((&audit.scope, &audit.query_id))
            || audit.experiment_digest != selection.frozen_plan_digest
        {
            return Err(CitationAuditError::Invalid(
                "audit inventory or experiment mismatch",
            ));
        }
        let c = audit.counts();
        if c.unreviewed_citations != 0
            || c.unreviewed_claims != 0
            || c.contradicted != 0
            || c.supported_factual_claims != c.factual_claims
        {
            return Err(CitationAuditError::Invalid("unresolved factual audit"));
        }
        counts.citations += u64::from(c.citations);
        counts.entailed += u64::from(c.entailed);
        counts.factual_claims += u64::from(c.factual_claims);
        for prior in family_owner
            .insert(audit.family_digest, index)
            .into_iter()
            .chain(
                audit
                    .source_roots
                    .iter()
                    .filter_map(|root| root_owner.insert(*root, index)),
            )
        {
            let left = representative(&mut parent, index);
            let right = representative(&mut parent, prior);
            parent[left] = right;
        }
        seal.extend_from_slice(audit.request_digest().as_array());
        seal.extend_from_slice(audit.judgement_digest().as_array());
    }
    let mut groups = BTreeMap::new();
    for (index, audit) in audits.iter().enumerate() {
        let group = representative(&mut parent, index);
        let snapshot = expected[&audit.request_digest()];
        if groups
            .insert(group, snapshot)
            .is_some_and(|prior| prior != snapshot)
        {
            return Err(CitationAuditError::Invalid(
                "source family crosses independent snapshots",
            ));
        }
    }
    let citation_groups = audits
        .iter()
        .enumerate()
        .filter(|(_, audit)| audit.counts().citations > 0)
        .map(|(index, _)| representative(&mut parent, index))
        .collect::<BTreeSet<_>>();
    counts.independent_source_groups = citation_groups.len() as u64;
    if counts.independent_source_groups < 200
        || counts.citations == 0
        || counts.factual_claims == 0
        || counts.entailed * 100 < counts.citations * 99
    {
        return Err(CitationAuditError::Invalid(
            "insufficient citation support or precision",
        ));
    }
    Ok(VerifiedMemoryCitationGateV1 {
        decision_digest: census.selection_digest,
        candidate_digest: selection.candidate_artifact_digest,
        objective_digest: selection.objective_digest,
        dataset_digest: selection.dataset_digest,
        digest: Digest32::of_bytes(&seal),
        trust_digest: verifier.trust_digest(),
        observer,
        audits,
        counts,
        admitted_at: now,
    })
}

fn representative(parent: &mut [usize], mut item: usize) -> usize {
    while parent[item] != item {
        parent[item] = parent[parent[item]];
        item = parent[item];
    }
    item
}

#[cfg(test)]
#[path = "memory_citation_gate_tests.rs"]
mod tests;
