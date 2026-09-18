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
}
