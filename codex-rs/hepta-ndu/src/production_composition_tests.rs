    #![allow(clippy::expect_used)]
    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn candidate() -> NduCandidateIdentityV1 {
        NduCandidateIdentityV1 {
            source_commit_digest: digest(b"commit"),
            source_tree_digest: digest(b"tree"),
            target_triple_digest: digest(b"target"),
            runner_host_digest: digest(b"host"),
            test_set_digest: digest(b"tests"),
            cargo_lock_digest: digest(b"lock"),
            documentation_map_digest: digest(b"docs"),
        }
    }

    fn binding(
        role: NduProductionAdapterRoleV1,
        state: NduAdapterQualificationStateV1,
    ) -> NduProductionAdapterBindingV1 {
        NduProductionAdapterBindingV1::new(
            role,
            id(&format!("adapter-{}", role.tag())),
            digest(&[role.tag(), 1]),
            digest(&[role.tag(), 2]),
            7,
            state,
            (state == NduAdapterQualificationStateV1::HostQualified)
                .then_some(digest(&[role.tag(), 3])),
        )
        .expect("binding")
    }

    #[test]
    fn complete_source_composition_stays_activation_gated() {
        let adapters = [
            NduProductionAdapterRoleV1::PersistentProjectionStore,
            NduProductionAdapterRoleV1::AuthenticatedOwnerWriter,
            NduProductionAdapterRoleV1::ProcessCrossHostFence,
            NduProductionAdapterRoleV1::TrustedTime,
            NduProductionAdapterRoleV1::RevocationFrontier,
            NduProductionAdapterRoleV1::ArtifactRegistry,
            NduProductionAdapterRoleV1::EncryptedRemoteBackup,
            NduProductionAdapterRoleV1::RestoreExecutor,
            NduProductionAdapterRoleV1::MetricsExporter,
            NduProductionAdapterRoleV1::ProductCaller,
        ]
        .into_iter()
        .map(|role| binding(role, NduAdapterQualificationStateV1::SourceBound))
        .collect();
        let receipt = seal_ndu_production_composition_v1(NduProductionCompositionManifestV1 {
            candidate: candidate(),
            owner_generation: Generation::new(9).expect("generation"),
            production_policy_digest: digest(b"policy"),
            production_policy_revision: 4,
            adapters,
        })
        .expect("receipt");
        assert!(!receipt.activation_eligible());
        receipt.validate().expect("valid receipt");
    }
