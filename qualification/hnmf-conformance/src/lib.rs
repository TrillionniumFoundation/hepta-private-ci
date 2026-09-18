#![forbid(unsafe_code)]

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    #[derive(Clone, Copy, Debug)]
    enum Fixture {
        ValidAgentTextEvent,
        PrivacyMismatch,
        ModalityRangeMismatch,
        SameModalityBinding,
    }

    const FIXTURES: [Fixture; 4] = [
        Fixture::ValidAgentTextEvent,
        Fixture::PrivacyMismatch,
        Fixture::ModalityRangeMismatch,
        Fixture::SameModalityBinding,
    ];

    fn hex(character: char) -> String {
        std::iter::repeat_n(character, 64).collect()
    }

    fn production_accepts(fixture: Fixture) -> bool {
        use production::hnmf::*;

        let digest = |character: char| CanonicalDigestV1::parse(&hex(character)).unwrap();
        let privacy = if matches!(fixture, Fixture::PrivacyMismatch) {
            PrivacyClassV1::WorkspacePrivate
        } else {
            PrivacyClassV1::AgentPrivate
        };
        let modality = if matches!(fixture, Fixture::ModalityRangeMismatch) {
            ModalityKindV1::Image
        } else {
            ModalityKindV1::Text
        };
        let first = ModalitySpanRefV1::try_new(
            1,
            modality,
            digest('a'),
            SpanRangeV1::ByteRange { start: 0, end: 4 },
            digest('b'),
            Some(digest('c')),
            None,
            10_000,
            privacy,
            None,
        );
        let Ok(first) = first else {
            return false;
        };

        let mut spans = vec![first];
        let mut bindings = Vec::new();
        if matches!(fixture, Fixture::SameModalityBinding) {
            let second = ModalitySpanRefV1::try_new(
                2,
                ModalityKindV1::Text,
                digest('f'),
                SpanRangeV1::ByteRange { start: 4, end: 8 },
                digest('b'),
                None,
                None,
                10_000,
                PrivacyClassV1::AgentPrivate,
                None,
            )
            .unwrap();
            spans.push(second);
            bindings.push(
                CrossModalBindingV1::try_new(
                    1,
                    7,
                    BTreeSet::from([1, 2]),
                    AlignmentKindV1::SameObservation,
                    900_000,
                    digest('d'),
                )
                .unwrap(),
            );
        }

        MemoryEventV1::try_new(
            7,
            7,
            MemoryScopeV1::try_agent_private("agent-a").unwrap(),
            TimeIntervalV1::try_new(1, None).unwrap(),
            spans,
            bindings,
            BTreeSet::from(["door".to_owned()]),
            vec![
                ProvenanceRefV1::try_new("source-7", 1, digest('e'), 1).unwrap(),
            ],
            MemoryVerificationStateV1::Verified,
            RetentionPolicyV1::try_new(digest('f'), None).unwrap(),
            digest('d'),
            digest('e'),
            Some(500_000),
            MemoryLifecycleV1::Active,
        )
        .is_ok()
    }

    fn reference_accepts(fixture: Fixture) -> bool {
        use reference::*;

        let digest = |character: char| Digest32::parse(hex(character)).unwrap();
        let privacy = if matches!(fixture, Fixture::PrivacyMismatch) {
            PrivacyClass::WorkspacePrivate
        } else {
            PrivacyClass::AgentPrivate
        };
        let modality = if matches!(fixture, Fixture::ModalityRangeMismatch) {
            ModalityKind::Image
        } else {
            ModalityKind::Text
        };
        let first = ModalitySpanRef {
            span_id: 1,
            modality,
            asset_sha256: digest('a'),
            range: SpanRange::ByteRange { start: 0, end: 4 },
            preprocessor_manifest_sha256: digest('b'),
            feature_blob_sha256: Some(digest('c')),
            symbolic_projection_sha256: None,
            uncertainty_ppm: 10_000,
            privacy_class: privacy,
            redaction_mask_sha256: None,
        };

        let mut spans = vec![first];
        let mut bindings = Vec::new();
        if matches!(fixture, Fixture::SameModalityBinding) {
            spans.push(ModalitySpanRef {
                span_id: 2,
                modality: ModalityKind::Text,
                asset_sha256: digest('f'),
                range: SpanRange::ByteRange { start: 4, end: 8 },
                preprocessor_manifest_sha256: digest('b'),
                feature_blob_sha256: None,
                symbolic_projection_sha256: None,
                uncertainty_ppm: 10_000,
                privacy_class: PrivacyClass::AgentPrivate,
                redaction_mask_sha256: None,
            });
            bindings.push(CrossModalBinding {
                binding_id: 1,
                event_id: 7,
                span_ids: BTreeSet::from([1, 2]),
                alignment_kind: AlignmentKind::SameObservation,
                confidence_ppm: 900_000,
                producer_manifest_sha256: digest('d'),
            });
        }

        MemoryEvent {
            event_id: 7,
            episode_id: 7,
            scope: MemoryScope::AgentPrivate {
                agent_id: "agent-a".to_owned(),
            },
            observed_interval: TimeInterval {
                start_unix_ms: 1,
                end_unix_ms: None,
            },
            modality_spans: spans,
            cross_modal_bindings: bindings,
            semantic_keys: BTreeSet::from(["door".to_owned()]),
            provenance: vec![ProvenanceRef {
                source_id: "source-7".to_owned(),
                source_revision: 1,
                source_sha256: digest('e'),
                observed_at_unix_ms: 1,
            }],
            verification: MemoryVerificationState::Verified,
            retention_policy: RetentionPolicy {
                policy_digest: digest('f'),
                retain_until_unix_ms: None,
            },
            objective_digest: digest('d'),
            ndu_state_digest: digest('e'),
            behavior_propensity_ppm: Some(500_000),
            lifecycle: MemoryLifecycle::Active,
        }
        .validate()
        .is_ok()
    }

    #[test]
    fn production_and_reference_accept_the_same_contract_fixtures() {
        for fixture in FIXTURES {
            assert_eq!(
                production_accepts(fixture),
                reference_accepts(fixture),
                "production/reference semantic drift for {fixture:?}"
            );
        }
    }

    fn production_extended_acceptance(case: &str) -> bool {
        use production::hnmf::*;

        let digest = |character: char| CanonicalDigestV1::parse(&hex(character)).unwrap();
        match case {
            "engram_active_support" => EngramNodeV1::try_new(
                1,
                EngramPopulationV1::SemanticConcept,
                BTreeSet::from([ModalityKindV1::Text]),
                BTreeSet::from(["door".to_owned()]),
                BTreeSet::from([1]),
                digest('a'),
                0,
                100_000,
                900_000,
                TimeIntervalV1::try_new(1, None).unwrap(),
                1,
                false,
            )
            .is_ok(),
            "synapse_self_loop" => SynapseV1::try_new(
                1,
                1,
                SynapseRelationV1::Associative,
                10_000,
                0,
                PlasticityClassV1::Hebbian,
                0,
                BTreeSet::from([1]),
                digest('a'),
                1,
                false,
            )
            .is_ok(),
            "cue_zero_seed" => MemoryCueV1::try_new(
                1,
                digest('a'),
                digest('b'),
                BTreeSet::from([ModalityKindV1::Text]),
                BTreeSet::from(["door".to_owned()]),
                BTreeSet::from([0]),
                1,
                ResourceBudgetV1::hnmf_default(),
            )
            .is_ok(),
            "outcome_over_ppm" => OutcomeSignalV1::try_new(
                1,
                0,
                1_000_001,
                0,
                0,
                0,
                digest('a'),
            )
            .is_ok(),
            "topology_self_activation" => TopologyProposalV1::try_new(
                1,
                2,
                TopologyOperationV1::RetireNode {
                    node_id: 1,
                    reason: "retire".to_owned(),
                },
                true,
                true,
                false,
                true,
            )
            .is_ok(),
            "plasticity_self_activation" => PlasticityBatchV1::try_new(
                1,
                2,
                digest('a'),
                Vec::new(),
                Vec::new(),
                true,
                true,
            )
            .is_ok(),
            "forget_without_rebuild" => ForgetPropagationReceiptV1::try_new(
                1,
                1,
                2,
                Vec::new(),
                Vec::new(),
                false,
                true,
            )
            .is_ok(),
            "replay_over_ppm" => {
                let candidate = ReplayCandidateV1::try_new(
                    1, 0, 1_000_001, 0, 0, 0, 0, 0, true,
                );
                let Ok(candidate) = candidate else {
                    return false;
                };
                let budget = ResourceBudgetV1::hnmf_default();
                let receipt =
                    ResourceReceiptV1::try_new(1, 0, 0, 0, 0, 0, 0, false, &budget).unwrap();
                select_replay_v1(
                    &[candidate],
                    1,
                    1,
                    digest('a'),
                    digest('b'),
                    receipt,
                )
                .is_ok()
            }
            _ => unreachable!("unknown extended fixture"),
        }
    }

    fn runtime_reference_extended_acceptance(case: &str) -> bool {
        use runtime_reference as oracle;

        match case {
            "engram_active_support" => oracle::EngramNode {
                id: 1,
                population: oracle::EngramPopulation::SemanticConcept,
                modalities: BTreeSet::from([oracle::ModalityKind::Text]),
                cue_keys: BTreeSet::from(["door".to_owned()]),
                support_events: BTreeSet::from([1]),
                threshold_ppm: 0,
                target_activity_ppm: 100_000,
                confidence_ppm: 900_000,
                retired: false,
            }
            .validate()
            .is_ok(),
            "synapse_self_loop" => oracle::Synapse {
                source: 1,
                target: 1,
                relation: oracle::SynapseRelation::Associative,
                weight_ppm: 10_000,
                eligibility_ppm: 0,
                support_events: BTreeSet::from([1]),
                retired: false,
            }
            .validate()
            .is_ok(),
            "cue_zero_seed" => oracle::MemoryCue {
                modalities: BTreeSet::from([oracle::ModalityKind::Text]),
                semantic_keys: BTreeSet::from(["door".to_owned()]),
                seed_nodes: BTreeSet::from([0]),
                now_unix_ms: 1,
            }
            .validate()
            .is_ok(),
            "outcome_over_ppm" => oracle::OutcomeSignal {
                utility_delta_ppm: 0,
                prediction_error_ppm: 1_000_001,
                novelty_ppm: 0,
                risk_ppm: 0,
                ood_ppm: 0,
            }
            .validate()
            .is_ok(),
            "topology_self_activation" => oracle::TopologyProposal {
                predecessor_generation: 1,
                next_generation: 2,
                operation: oracle::TopologyOperation::RetireNode {
                    node_id: 1,
                    reason: "retire".to_owned(),
                },
                capability_typed: true,
                sandbox_only: true,
                operator_accepted: false,
                production_activation_allowed: true,
            }
            .validate()
            .is_ok(),
            "plasticity_self_activation" => {
                let fabric = oracle::HnmfFabric::new(1, oracle::FabricConfig::default()).unwrap();
                fabric
                    .apply_plasticity(&oracle::PlasticityBatch {
                        predecessor_generation: 1,
                        next_generation: 2,
                        modulator_ppm: 0,
                        weight_proposals: Vec::new(),
                        threshold_proposals: Vec::new(),
                        current_snapshot_immutable: true,
                        production_activation_allowed: true,
                    })
                    .is_ok()
            }
            "forget_without_rebuild" => {
                let mut fabric =
                    oracle::HnmfFabric::new(1, oracle::FabricConfig::default()).unwrap();
                fabric
                    .insert_event(oracle::MemoryEvent {
                        id: 1,
                        episode_id: 1,
                        modalities: BTreeSet::from([oracle::ModalityKind::Text]),
                        semantic_keys: BTreeSet::from(["door".to_owned()]),
                        source_sha256: BTreeSet::from(["a".repeat(64)]),
                        privacy: oracle::PrivacyClass::AgentPrivate,
                        valid_from_unix_ms: 1,
                        valid_to_unix_ms: None,
                        utility_ppm: 0,
                        risk_ppm: 0,
                        tombstoned: false,
                    })
                    .unwrap();
                fabric
                    .apply_forget(&oracle::ForgetBatch {
                        event_id: 1,
                        predecessor_generation: 1,
                        next_generation: 2,
                        affected_nodes: Vec::new(),
                        affected_synapses: Vec::new(),
                        projection_rebuild_required: false,
                        artifact_revocation_required: true,
                        production_activation_allowed: false,
                    })
                    .is_ok()
            }
            "replay_over_ppm" => oracle::select_replay(
                &[oracle::ReplayCandidate {
                    event_id: 1,
                    source_bucket: 0,
                    expected_utility_gain_ppm: 1_000_001,
                    prediction_error_ppm: 0,
                    novelty_ppm: 0,
                    rarity_ppm: 0,
                    forgetting_risk_ppm: 0,
                    coverage_need_ppm: 0,
                    privacy_allowed: true,
                }],
                1,
                1,
            )
            .is_ok(),
            _ => unreachable!("unknown extended fixture"),
        }
    }

    #[test]
    fn production_matches_runtime_oracle_on_extended_contract_invariants() {
        for case in [
            "engram_active_support",
            "synapse_self_loop",
            "cue_zero_seed",
            "outcome_over_ppm",
            "topology_self_activation",
            "plasticity_self_activation",
            "forget_without_rebuild",
            "replay_over_ppm",
        ] {
            assert_eq!(
                production_extended_acceptance(case),
                runtime_reference_extended_acceptance(case),
                "production/runtime-reference semantic drift for {case}"
            );
        }
    }
}
