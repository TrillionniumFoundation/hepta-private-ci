use super::*;

impl HardenedFabric {
    pub fn recall(&self, cue: &MemoryCue) -> Result<BoundRecallPacket, HardeningError> {
        self.validate()?;
        cue.validate()?;
        if cue
            .seed_nodes
            .iter()
            .any(|node_id| !self.nodes.contains_key(node_id))
        {
            return Err(HardeningError::Missing("cue seed node"));
        }

        let mut initial = self
            .events
            .values()
            .filter(|event| eligible(event, cue.now_unix_ms))
            .filter_map(|event| {
                let semantic = event.semantic_keys.intersection(&cue.semantic_keys).count();
                let modality = event.modalities.intersection(&cue.modalities).count();
                let seeded = self.nodes.values().any(|node| {
                    cue.seed_nodes.contains(&node.id) && node.support_events.contains(&event.id)
                });
                if semantic == 0 && modality == 0 && !seeded {
                    return None;
                }
                let score = (semantic as i64)
                    .checked_mul(1_000_000)?
                    .checked_add((modality as i64).checked_mul(250_000)?)?
                    .checked_add(if semantic > 0 && modality == 0 {
                        500_000
                    } else {
                        0
                    })?
                    .checked_add(if seeded { 2_000_000 } else { 0 })?
                    .checked_add(i64::from(event.utility_ppm).max(0))?
                    .checked_sub(i64::from(event.risk_ppm))?;
                Some((event.id, score.max(0) as u64))
            })
            .collect::<Vec<_>>();
        initial.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
        initial.truncate(self.hardening.maximum_candidate_events);
        let initial_events = initial
            .iter()
            .map(|(event_id, _)| *event_id)
            .collect::<BTreeSet<_>>();

        if initial_events.is_empty() {
            return Ok(BoundRecallPacket {
                source_cue: cue.clone(),
                candidate_event_ids: Vec::new(),
                expanded_node_ids: Vec::new(),
                packet: RecallPacket {
                    snapshot_generation: self.generation,
                    candidate_event_count: 0,
                    selected_events: Vec::new(),
                    active_nodes: Vec::new(),
                    activation_paths: Vec::new(),
                    contradictions: Vec::new(),
                    coverage_ppm: 0,
                    confidence_ppm: 0,
                    ood_ppm: PPM as u32,
                    settling_steps: 0,
                    abstain: Some(RecallAbstainReason::NoCandidate),
                    contains_raw_source_payload: false,
                },
            });
        }

        let seeds = self
            .nodes
            .values()
            .filter(|node| !node.retired)
            .filter(|node| {
                cue.seed_nodes.contains(&node.id)
                    || node
                        .support_events
                        .iter()
                        .any(|event_id| initial_events.contains(event_id))
            })
            .map(|node| node.id)
            .collect::<BTreeSet<_>>();
        let expanded = self.expand_nodes(&seeds, cue.now_unix_ms)?;
        let mut candidate_events = initial_events;
        for node_id in &expanded {
            let node = self
                .nodes
                .get(node_id)
                .ok_or(HardeningError::Missing("expanded node"))?;
            for event_id in &node.support_events {
                if candidate_events.len() >= self.hardening.maximum_candidate_events {
                    break;
                }
                if self
                    .events
                    .get(event_id)
                    .is_some_and(|event| eligible(event, cue.now_unix_ms))
                {
                    candidate_events.insert(*event_id);
                }
            }
        }

        let mut direct = BTreeMap::new();
        for node_id in &expanded {
            let node = self
                .nodes
                .get(node_id)
                .ok_or(HardeningError::Missing("candidate node"))?;
            let semantic = node.cue_keys.intersection(&cue.semantic_keys).count() as i64;
            let modality = node.modalities.intersection(&cue.modalities).count() as i64;
            let seeded = if cue.seed_nodes.contains(node_id) {
                1_i64
            } else {
                0_i64
            };
            let cross_modal = if semantic > 0 && modality == 0 {
                1_i64
            } else {
                0_i64
            };
            let drive = semantic
                .checked_mul(300_000)
                .and_then(|value| value.checked_add(modality * 100_000))
                .and_then(|value| value.checked_add(cross_modal * 200_000))
                .and_then(|value| value.checked_add(seeded * 800_000))
                .ok_or(HardeningError::ArithmeticOverflow)?;
            direct.insert(*node_id, clamp(drive, 0, PPM));
        }

        let mut activation = expanded
            .iter()
            .map(|node_id| (*node_id, 0_i64))
            .collect::<BTreeMap<_, _>>();
        let mut last_paths = Vec::new();
        for _ in 0..self.runtime.maximum_recurrent_steps {
            let mut raw = BTreeMap::new();
            let mut paths = Vec::new();
            for node_id in &expanded {
                let node = self
                    .nodes
                    .get(node_id)
                    .ok_or(HardeningError::Missing("candidate node"))?;
                let previous = activation.get(node_id).copied().unwrap_or(0);
                let mut value = direct.get(node_id).copied().unwrap_or(0)
                    + mul_ppm(previous, i64::from(self.runtime.leak_ppm))?
                    - i64::from(node.threshold_ppm);
                for synapse in self.synapses.values().filter(|synapse| {
                    !synapse.retired
                        && synapse.target == *node_id
                        && expanded.contains(&synapse.source)
                }) {
                    let source = activation.get(&synapse.source).copied().unwrap_or(0);
                    if source <= 0 {
                        continue;
                    }
                    let magnitude = mul_ppm(source, i64::from(synapse.weight_ppm).abs())?;
                    let negative = matches!(
                        synapse.relation,
                        SynapseRelation::Inhibitory | SynapseRelation::Contradicts
                    ) || synapse.weight_ppm < 0;
                    let contribution = if negative { -magnitude } else { magnitude };
                    value = value
                        .checked_add(contribution)
                        .ok_or(HardeningError::ArithmeticOverflow)?;
                    if contribution != 0 {
                        paths.push(ActivationPath {
                            source: synapse.source,
                            target: synapse.target,
                            relation: synapse.relation,
                            contribution_ppm: clamp(contribution, -PPM, PPM) as i32,
                        });
                    }
                }
                raw.insert(*node_id, clamp(value, 0, PPM));
            }
            activation = self.sparse_select(&raw)?;
            last_paths = paths;
        }

        let mut active_nodes = activation
            .iter()
            .filter(|(_, value)| **value > 0)
            .map(|(node_id, value)| {
                let node = self.nodes.get(node_id).expect("candidate node exists");
                ActiveNode {
                    node_id: *node_id,
                    population: node.population,
                    activation_ppm: *value as i32,
                }
            })
            .collect::<Vec<_>>();
        active_nodes.sort_by(|left, right| {
            right
                .activation_ppm
                .cmp(&left.activation_ppm)
                .then_with(|| left.node_id.cmp(&right.node_id))
        });
        active_nodes.truncate(self.runtime.maximum_active_nodes);
        let active_ids = active_nodes
            .iter()
            .map(|node| node.node_id)
            .collect::<BTreeSet<_>>();

        let mut path_map = BTreeMap::new();
        for path in last_paths
            .into_iter()
            .filter(|path| active_ids.contains(&path.source) && active_ids.contains(&path.target))
        {
            let key = (path.source, path.target, path.relation);
            path_map
                .entry(key)
                .and_modify(|current: &mut ActivationPath| {
                    if path.contribution_ppm.unsigned_abs()
                        > current.contribution_ppm.unsigned_abs()
                    {
                        *current = path.clone();
                    }
                })
                .or_insert(path);
        }
        let mut activation_paths = path_map.into_values().collect::<Vec<_>>();
        activation_paths.sort_by(|left, right| {
            right
                .contribution_ppm
                .unsigned_abs()
                .cmp(&left.contribution_ppm.unsigned_abs())
                .then_with(|| left.source.cmp(&right.source))
                .then_with(|| left.target.cmp(&right.target))
                .then_with(|| left.relation.cmp(&right.relation))
        });
        activation_paths.truncate(self.runtime.maximum_activation_paths);

        let contradictions = self
            .synapses
            .values()
            .filter(|synapse| {
                !synapse.retired
                    && synapse.relation == SynapseRelation::Contradicts
                    && active_ids.contains(&synapse.source)
                    && active_ids.contains(&synapse.target)
            })
            .map(|synapse| Contradiction {
                left: synapse.source.min(synapse.target),
                right: synapse.source.max(synapse.target),
            })
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();

        let mut event_strength = BTreeMap::<EventId, i64>::new();
        for active in &active_nodes {
            let node = self
                .nodes
                .get(&active.node_id)
                .ok_or(HardeningError::Missing("active node"))?;
            for event_id in &node.support_events {
                if candidate_events.contains(event_id)
                    && self
                        .events
                        .get(event_id)
                        .is_some_and(|event| eligible(event, cue.now_unix_ms))
                {
                    event_strength
                        .entry(*event_id)
                        .and_modify(|value| {
                            *value = (*value).max(i64::from(active.activation_ppm));
                        })
                        .or_insert(i64::from(active.activation_ppm));
                }
            }
        }
        let mut selected_events = event_strength.into_iter().collect::<Vec<_>>();
        selected_events
            .sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
        selected_events.truncate(self.runtime.maximum_recall_events);
        let selected_events = selected_events
            .into_iter()
            .map(|(event_id, _)| event_id)
            .collect::<Vec<_>>();

        let covered = selected_events
            .iter()
            .filter_map(|event_id| self.events.get(event_id))
            .flat_map(|event| event.semantic_keys.iter())
            .filter(|key| cue.semantic_keys.contains(*key))
            .cloned()
            .collect::<BTreeSet<_>>();
        let coverage_ppm = ratio_ppm(covered.len(), cue.semantic_keys.len());
        let ood_ppm = (PPM as u32).saturating_sub(coverage_ppm);
        let confidence_ppm = if active_nodes.is_empty() {
            0
        } else {
            let total = active_nodes.iter().try_fold(0_u64, |sum, active| {
                let node = self
                    .nodes
                    .get(&active.node_id)
                    .ok_or(HardeningError::Missing("active node"))?;
                sum.checked_add(
                    u64::from(active.activation_ppm.unsigned_abs())
                        .min(u64::from(node.confidence_ppm)),
                )
                .ok_or(HardeningError::ArithmeticOverflow)
            })?;
            u32::try_from(total / active_nodes.len() as u64).unwrap_or(PPM as u32)
        };
        let abstain = if selected_events.is_empty() {
            Some(RecallAbstainReason::NoCandidate)
        } else if self.runtime.contradiction_forces_abstention && !contradictions.is_empty() {
            Some(RecallAbstainReason::UnresolvedContradiction)
        } else if ood_ppm >= self.runtime.ood_abstain_ppm {
            Some(RecallAbstainReason::OutOfDistribution)
        } else if confidence_ppm < self.runtime.minimum_confidence_ppm {
            Some(RecallAbstainReason::LowConfidence)
        } else {
            None
        };
        let candidate_event_ids = candidate_events.into_iter().collect::<Vec<_>>();
        let expanded_node_ids = expanded.into_iter().collect::<Vec<_>>();
        Ok(BoundRecallPacket {
            source_cue: cue.clone(),
            candidate_event_ids: candidate_event_ids.clone(),
            expanded_node_ids,
            packet: RecallPacket {
                snapshot_generation: self.generation,
                candidate_event_count: candidate_event_ids.len(),
                selected_events,
                active_nodes,
                activation_paths,
                contradictions,
                coverage_ppm,
                confidence_ppm,
                ood_ppm,
                settling_steps: self.runtime.maximum_recurrent_steps,
                abstain,
                contains_raw_source_payload: false,
            },
        })
    }

    fn expand_nodes(
        &self,
        seeds: &BTreeSet<NodeId>,
        now_unix_ms: i64,
    ) -> Result<BTreeSet<NodeId>, HardeningError> {
        let mut selected = seeds.clone();
        let mut frontier = seeds.clone();
        for _ in 0..self.hardening.maximum_graph_hops {
            if frontier.is_empty() || selected.len() >= self.runtime.maximum_nodes {
                break;
            }
            let mut next = BTreeSet::new();
            for synapse in self.synapses.values().filter(|synapse| !synapse.retired) {
                let edge_readable = synapse.support_events.iter().any(|event_id| {
                    self.events
                        .get(event_id)
                        .is_some_and(|event| eligible(event, now_unix_ms))
                });
                if !edge_readable {
                    continue;
                }
                let mut add = |node_id: NodeId| -> Result<(), HardeningError> {
                    if selected.len() >= self.runtime.maximum_nodes || selected.contains(&node_id) {
                        return Ok(());
                    }
                    let node = self
                        .nodes
                        .get(&node_id)
                        .ok_or(HardeningError::Missing("expanded node"))?;
                    let readable = !node.retired
                        && node.support_events.iter().any(|event_id| {
                            self.events
                                .get(event_id)
                                .is_some_and(|event| eligible(event, now_unix_ms))
                        });
                    if readable {
                        selected.insert(node_id);
                        next.insert(node_id);
                    }
                    Ok(())
                };
                if frontier.contains(&synapse.source) {
                    add(synapse.target)?;
                }
                if matches!(
                    synapse.relation,
                    SynapseRelation::Associative | SynapseRelation::Contradicts
                ) && frontier.contains(&synapse.target)
                {
                    add(synapse.source)?;
                }
            }
            frontier = next;
        }
        Ok(selected)
    }

    fn sparse_select(
        &self,
        raw: &BTreeMap<NodeId, i64>,
    ) -> Result<BTreeMap<NodeId, i64>, HardeningError> {
        let mut selected = BTreeMap::new();
        for population in EngramPopulation::ALL {
            let mut group = raw
                .iter()
                .filter_map(|(node_id, value)| {
                    let node = self.nodes.get(node_id)?;
                    (node.population == population && *value > 0).then_some((*node_id, *value))
                })
                .collect::<Vec<_>>();
            group.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
            group.truncate(self.runtime.maximum_active_per_population);
            for (rank, (node_id, value)) in group.into_iter().enumerate() {
                let inhibition = i64::from(self.runtime.lateral_inhibition_ppm)
                    .checked_mul(rank as i64)
                    .ok_or(HardeningError::ArithmeticOverflow)?;
                selected.insert(node_id, clamp(value - inhibition, 0, PPM));
            }
        }
        let mut ranked = selected.into_iter().collect::<Vec<_>>();
        ranked.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
        ranked.truncate(self.runtime.maximum_active_nodes);
        let active = ranked.into_iter().collect::<BTreeMap<_, _>>();
        Ok(raw
            .keys()
            .map(|node_id| (*node_id, active.get(node_id).copied().unwrap_or(0)))
            .collect())
    }
}
