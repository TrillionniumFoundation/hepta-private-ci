use super::*;

impl HardenedFabric {
    pub fn propose_plasticity(
        &self,
        packet: &BoundRecallPacket,
        signal: OutcomeSignal,
    ) -> Result<BoundPlasticityBatch, HardeningError> {
        let expected_packet = self.recall(&packet.source_cue)?;
        if &expected_packet != packet || packet.packet.contains_raw_source_payload {
            return Err(HardeningError::Conflict(
                "recall packet does not match deterministic current snapshot",
            ));
        }
        let modulator_ppm = signal.modulator_ppm()?;
        let active = packet
            .packet
            .active_nodes
            .iter()
            .map(|node| (node.node_id, i64::from(node.activation_ppm)))
            .collect::<BTreeMap<_, _>>();
        let mut weight_proposals = Vec::new();
        for synapse in self.synapses.values().filter(|synapse| !synapse.retired) {
            let pre = active.get(&synapse.source).copied().unwrap_or(0).max(0);
            let post = active.get(&synapse.target).copied().unwrap_or(0).max(0);
            let coactivation = if pre > 0 && post > 0 {
                mul_ppm(pre, post)?
            } else {
                0
            };
            let decayed = mul_ppm(
                i64::from(synapse.eligibility_ppm),
                i64::from(self.runtime.trace_decay_ppm),
            )?;
            let eligibility = clamp(decayed + coactivation, -PPM, PPM);
            let modulated = mul_ppm(eligibility, i64::from(modulator_ppm))?;
            let mut delta = mul_ppm(modulated, i64::from(self.runtime.learning_rate_ppm))?;
            if matches!(
                synapse.relation,
                SynapseRelation::Inhibitory | SynapseRelation::Contradicts
            ) {
                delta = -delta;
            }
            delta = clamp(
                delta,
                -i64::from(self.runtime.maximum_weight_delta_ppm),
                i64::from(self.runtime.maximum_weight_delta_ppm),
            );
            let new_weight = clamp(i64::from(synapse.weight_ppm) + delta, -PPM, PPM);
            if eligibility != i64::from(synapse.eligibility_ppm) || delta != 0 {
                weight_proposals.push(WeightProposal {
                    source: synapse.source,
                    target: synapse.target,
                    relation: synapse.relation,
                    old_weight_ppm: synapse.weight_ppm,
                    new_weight_ppm: new_weight as i32,
                    delta_ppm: delta as i32,
                    new_eligibility_ppm: eligibility as i32,
                });
            }
        }
        weight_proposals
            .sort_by_key(|proposal| (proposal.source, proposal.target, proposal.relation));
        let mut threshold_proposals = Vec::new();
        for node in self.nodes.values().filter(|node| !node.retired) {
            let observed = if active.get(&node.id).copied().unwrap_or(0) > 0 {
                PPM
            } else {
                0
            };
            let difference = observed - i64::from(node.target_activity_ppm);
            let delta = mul_ppm(difference, i64::from(self.runtime.homeostasis_rate_ppm))?;
            let new_threshold = clamp(i64::from(node.threshold_ppm) + delta, -PPM, PPM);
            threshold_proposals.push(ThresholdProposal {
                node_id: node.id,
                old_threshold_ppm: node.threshold_ppm,
                new_threshold_ppm: new_threshold as i32,
                delta_ppm: delta as i32,
            });
        }
        threshold_proposals.sort_by_key(|proposal| proposal.node_id);
        let next_generation = self
            .generation
            .checked_add(1)
            .ok_or(HardeningError::ArithmeticOverflow)?;
        Ok(BoundPlasticityBatch {
            source_packet: packet.clone(),
            outcome_signal: signal,
            batch: PlasticityBatch {
                predecessor_generation: self.generation,
                next_generation,
                modulator_ppm,
                weight_proposals,
                threshold_proposals,
                current_snapshot_immutable: true,
                production_activation_allowed: false,
            },
            current_snapshot_immutable: true,
            production_activation_allowed: false,
        })
    }

    pub fn apply_plasticity(
        &self,
        candidate: &BoundPlasticityBatch,
    ) -> Result<Self, HardeningError> {
        let expected =
            self.propose_plasticity(&candidate.source_packet, candidate.outcome_signal)?;
        if &expected != candidate {
            return Err(HardeningError::Conflict(
                "plasticity batch does not match deterministic source evidence",
            ));
        }
        if !candidate.current_snapshot_immutable
            || candidate.production_activation_allowed
            || !candidate.batch.current_snapshot_immutable
            || candidate.batch.production_activation_allowed
        {
            return Err(HardeningError::AuthorityBoundary);
        }
        let mut next = self.clone();
        for proposal in &candidate.batch.weight_proposals {
            let synapse = next
                .synapses
                .get_mut(&(proposal.source, proposal.target, proposal.relation))
                .ok_or(HardeningError::Missing("plasticity synapse"))?;
            if synapse.weight_ppm != proposal.old_weight_ppm {
                return Err(HardeningError::Conflict("old weight mismatch"));
            }
            synapse.weight_ppm = proposal.new_weight_ppm;
            synapse.eligibility_ppm = proposal.new_eligibility_ppm;
        }
        for proposal in &candidate.batch.threshold_proposals {
            let node = next
                .nodes
                .get_mut(&proposal.node_id)
                .ok_or(HardeningError::Missing("plasticity node"))?;
            if node.threshold_ppm != proposal.old_threshold_ppm {
                return Err(HardeningError::Conflict("old threshold mismatch"));
            }
            node.threshold_ppm = proposal.new_threshold_ppm;
        }
        next.generation = candidate.batch.next_generation;
        next.validate()?;
        Ok(next)
    }

    pub fn propose_forget(&self, event_id: EventId) -> Result<ExactForgetBatch, HardeningError> {
        let event = self
            .events
            .get(&event_id)
            .ok_or(HardeningError::Missing("forget event"))?;
        if event.tombstoned {
            return Err(HardeningError::Conflict("event is already tombstoned"));
        }
        let next_generation = self
            .generation
            .checked_add(1)
            .ok_or(HardeningError::ArithmeticOverflow)?;
        Ok(ExactForgetBatch {
            batch: ForgetBatch {
                event_id,
                predecessor_generation: self.generation,
                next_generation,
                affected_nodes: self
                    .nodes
                    .values()
                    .filter(|node| node.support_events.contains(&event_id))
                    .map(|node| node.id)
                    .collect(),
                affected_synapses: self
                    .synapses
                    .values()
                    .filter(|synapse| synapse.support_events.contains(&event_id))
                    .map(|synapse| (synapse.source, synapse.target, synapse.relation))
                    .collect(),
                projection_rebuild_required: true,
                artifact_revocation_required: true,
                production_activation_allowed: false,
            },
            exact_support_closure: true,
            production_activation_allowed: false,
        })
    }

    pub fn apply_forget(&self, candidate: &ExactForgetBatch) -> Result<Self, HardeningError> {
        let expected = self.propose_forget(candidate.batch.event_id)?;
        if &expected != candidate {
            return Err(HardeningError::Conflict(
                "forget batch does not match exact support closure",
            ));
        }
        if !candidate.exact_support_closure || candidate.production_activation_allowed {
            return Err(HardeningError::AuthorityBoundary);
        }
        let mut next = self.clone();
        next.events
            .get_mut(&candidate.batch.event_id)
            .ok_or(HardeningError::Missing("forget event"))?
            .tombstoned = true;
        for node in next.nodes.values_mut() {
            node.support_events.remove(&candidate.batch.event_id);
            if node.support_events.is_empty() {
                node.retired = true;
            }
        }
        for synapse in next.synapses.values_mut() {
            synapse.support_events.remove(&candidate.batch.event_id);
            if synapse.support_events.is_empty() {
                synapse.retired = true;
            }
        }
        next.generation = candidate.batch.next_generation;
        next.validate()?;
        Ok(next)
    }
}

pub fn select_replay_hardened(
    candidates: &[ReplayCandidate],
    maximum_selected: usize,
    maximum_per_source_bucket: usize,
) -> Result<ReplaySelectionReceipt, HardeningError> {
    let mut ids = BTreeSet::new();
    for candidate in candidates {
        if candidate.event_id == 0 || !ids.insert(candidate.event_id) {
            return Err(HardeningError::Conflict(
                "replay event ids must be unique and non-zero",
            ));
        }
        for value in [
            candidate.expected_utility_gain_ppm,
            candidate.prediction_error_ppm,
            candidate.novelty_ppm,
            candidate.rarity_ppm,
            candidate.forgetting_risk_ppm,
            candidate.coverage_need_ppm,
        ] {
            if u64::from(value) > PPM as u64 {
                return Err(HardeningError::Invalid(
                    "replay score component exceeds one",
                ));
            }
        }
    }
    Ok(hnmf_reference::select_replay(
        candidates,
        maximum_selected,
        maximum_per_source_bucket,
    )?)
}
