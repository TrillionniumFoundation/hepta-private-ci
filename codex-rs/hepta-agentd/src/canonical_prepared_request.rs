//! Private exact fields for the original canonical handoff codec.

use super::*;

impl Request {
    pub(in crate::intelligence_product::canonical_prepared) fn capture(value: &CanonicalIntelligenceRunRequestV1) -> Self {
        let snapshot = value.snapshot.retained_request(); let legal = &value.legal_candidates; let b = value.budget;
        Self { run_id: value.run_id.to_string(), snapshot: Snapshot {
            objective_digest: snapshot.objective_digest.to_string(), authority_epoch: snapshot.authority_epoch,
            body_generation: snapshot.body_generation.get(), configuration_digest: snapshot.configuration_digest.to_string(),
            revocation_frontier_digest: snapshot.revocation_frontier_digest.to_string(),
            owners: snapshot.owner_bindings.iter().map(|owner| Owner { owner_id: owner.owner_id.to_string(),
                generation: owner.generation.get(), implementation_digest: owner.implementation_digest.to_string(),
                key_digest: owner.key_digest.to_string(), key_epoch: owner.key_epoch }).collect(),
        }, legal: Legal { candidate_set_id: legal.candidate_set_id.to_string(), state_digest: legal.state_digest.to_string(),
            generator_id: legal.generator_id.to_string(), grammar_digest: legal.grammar_digest.to_string(),
            candidates: legal.candidates.iter().map(|value| (value.candidate_id.to_string(), value.support_digest.to_string())).collect(),
            support_floor_ppm: legal.support_floor_ppm },
            budget: [b.total_micros, b.objective_micros, b.utility_micros, b.neural_micros, b.prompt_micros,
                b.intuition_micros, b.context_micros, b.evaluation_micros] }
    }
    pub(in crate::intelligence_product::canonical_prepared) fn restore(self) -> anyhow::Result<CanonicalIntelligenceRunRequestV1> {
        anyhow::ensure!(self.snapshot.owners.len() == 7 && self.legal.candidates.len() <= 128, "retained owner/candidate bound");
        let snapshot = self.snapshot;
        let owner_bindings = snapshot.owners.into_iter().map(|value| Ok(OwnerBindingV1 {
            owner_id: StableId::new(value.owner_id)?, generation: codex_hepta_types::Generation::new(value.generation)?,
            implementation_digest: value.implementation_digest.parse()?, key_digest: value.key_digest.parse()?, key_epoch: value.key_epoch,
        })).collect::<anyhow::Result<Vec<_>>>()?;
        let legal = self.legal; let b = self.budget;
        Ok(CanonicalIntelligenceRunRequestV1 { run_id: StableId::new(self.run_id)?, snapshot: CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
            objective_digest: snapshot.objective_digest.parse()?, authority_epoch: snapshot.authority_epoch,
            body_generation: codex_hepta_types::Generation::new(snapshot.body_generation)?,
            configuration_digest: snapshot.configuration_digest.parse()?, revocation_frontier_digest: snapshot.revocation_frontier_digest.parse()?, owner_bindings,
        })?, legal_candidates: LegalActionCandidateSetRequestV1 { candidate_set_id: StableId::new(legal.candidate_set_id)?,
            state_digest: legal.state_digest.parse()?, generator_id: StableId::new(legal.generator_id)?, grammar_digest: legal.grammar_digest.parse()?,
            candidates: legal.candidates.into_iter().map(|(id, digest)| Ok(LegalActionCandidateV1 {
                candidate_id: StableId::new(id)?, support_digest: digest.parse()? })).collect::<anyhow::Result<_>>()?, support_floor_ppm: legal.support_floor_ppm },
            budget: CanonicalBudgetV1 { total_micros: b[0], objective_micros: b[1], utility_micros: b[2], neural_micros: b[3],
                prompt_micros: b[4], intuition_micros: b[5], context_micros: b[6], evaluation_micros: b[7] } })
    }
}
