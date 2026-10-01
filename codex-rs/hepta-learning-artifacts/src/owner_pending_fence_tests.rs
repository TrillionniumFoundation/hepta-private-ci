use super::tests::*;
use super::*;

use std::sync::Arc;
use std::sync::Barrier;

use pretty_assertions::assert_eq;

use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

fn effect_inventory(root: &Path) -> [usize; 6] {
    [
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "admissions",
    ]
    .map(|name| fs::read_dir(root.join(name)).fixture("effects").count())
}

#[test]
fn host_fences_new_operations_at_every_unfinished_phase_without_side_effects() {
    for stopped_at in [
        ArtifactPublicationPhaseV1::Prepared,
        ArtifactPublicationPhaseV1::PayloadDurable,
        ArtifactPublicationPhaseV1::RegistryDurable,
        ArtifactPublicationPhaseV1::WitnessDurable,
    ] {
        let directory = TestDir::new();
        let key = signer();
        let scope = withdrawal_scope();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope.digest()),
            lease(&key, scope.digest()),
            /*now*/ 20,
        )
        .fixture("owner");
        let (registry, mut first) =
            deterministic_publication(&owner, &withdrawals, /*now*/ 20);
        let first_snapshot = first.snapshot();
        let retry = owner
            .begin_publication(
                first.intent().operation_id.clone(),
                first.intent().admission.clone(),
                &withdrawals,
                &ArtifactRegistry::new(),
                Digest32::ZERO,
                /*now*/ 20,
            )
            .fixture("same-operation Prepared retry");
        assert_eq!(retry.snapshot(), first_snapshot);
        if stopped_at != ArtifactPublicationPhaseV1::Prepared {
            owner
                .ensure_payload_durable(&mut first, &registry, b"payload", /*now*/ 20)
                .fixture("payload durable");
        }
        if matches!(
            stopped_at,
            ArtifactPublicationPhaseV1::RegistryDurable
                | ArtifactPublicationPhaseV1::WitnessDurable
        ) {
            owner
                .ensure_registry_durable(
                    &mut first,
                    &registry,
                    &withdrawals,
                    digest("binding"),
                    /*now*/ 20,
                )
                .fixture("registry durable");
        }
        let signed = signed_head(&key, scope.digest(), registry.snapshot().head_digest);
        if stopped_at == ArtifactPublicationPhaseV1::WitnessDurable {
            owner
                .ensure_witness_durable(&mut first, &signed, &withdrawals, /*now*/ 20)
                .fixture("witness durable");
        }
        let mut unrelated_manifest = manifest();
        unrelated_manifest.artifact_id = id("unrelated-candidate");
        let unrelated_admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            unrelated_manifest,
            /*now*/ 20,
        )
        .fixture("unrelated admission");
        let before = effect_inventory(&directory.0);
        let unrelated_predecessor = if stopped_at == ArtifactPublicationPhaseV1::WitnessDurable {
            registry.snapshot().head_digest
        } else {
            Digest32::ZERO
        };
        let predecessor_registry = if stopped_at == ArtifactPublicationPhaseV1::WitnessDurable {
            registry.clone()
        } else {
            ArtifactRegistry::new()
        };
        assert!(
            owner
                .begin_publication(
                    id("unrelated-operation"),
                    unrelated_admission.clone(),
                    &withdrawals,
                    &predecessor_registry,
                    unrelated_predecessor,
                    20,
                )
                .is_err()
        );
        assert_eq!(effect_inventory(&directory.0), before);
        assert_eq!(first.phase(), stopped_at);
        first = owner
            .resume_publication(first.snapshot(), /*now*/ 20)
            .fixture("resume exact unfinished operation");
        if first.phase() == ArtifactPublicationPhaseV1::Prepared {
            owner
                .ensure_payload_durable(&mut first, &registry, b"payload", /*now*/ 20)
                .fixture("continue payload");
        }
        if first.phase() == ArtifactPublicationPhaseV1::PayloadDurable {
            owner
                .ensure_registry_durable(
                    &mut first,
                    &registry,
                    &withdrawals,
                    digest("binding"),
                    /*now*/ 20,
                )
                .fixture("continue registry");
        }
        if first.phase() == ArtifactPublicationPhaseV1::RegistryDurable {
            owner
                .ensure_witness_durable(&mut first, &signed, &withdrawals, /*now*/ 20)
                .fixture("continue witness");
        }
        owner
            .acknowledge(&mut first, &withdrawals, /*now*/ 20)
            .fixture("finish first operation");
        drop(owner);
        let service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: trust(&key, scope.digest()),
            writer_lease: lease(&key, scope.digest()),
            required_current_head: Some(signed.clone()),
            withdrawal_registry: withdrawals.clone(),
            storage_binding: digest("binding"),
            now: 20,
        })
        .fixture("completed namespace remains recoverable by the product service");
        assert_eq!(service.recovery_required(), None);
        assert_eq!(service.registry().snapshot(), registry.snapshot());
        drop(service);
        let owner = LearningArtifactOwnerHost::open_with_required_current_head(
            &directory.0,
            trust(&key, scope.digest()),
            lease(&key, scope.digest()),
            signed,
            /*now*/ 20,
        )
        .fixture("reopen owner");
        let next = owner
            .begin_publication(
                id("unrelated-operation"),
                unrelated_admission,
                &withdrawals,
                &registry,
                registry.snapshot().head_digest,
                /*now*/ 20,
            )
            .fixture("completed first operation releases the next operation");
        assert_eq!(next.phase(), ArtifactPublicationPhaseV1::Prepared);
    }
}

#[test]
fn shared_host_concurrent_new_operations_create_exactly_one_pending_publication() {
    for round in 0..4 {
        let directory = TestDir::new();
        let key = signer();
        let scope = withdrawal_scope();
        let withdrawals = Arc::new(DatasetWithdrawalRegistry::new_scoped(scope.clone()));
        let owner = Arc::new(
            LearningArtifactOwnerHost::open(
                &directory.0,
                trust(&key, scope.digest()),
                lease(&key, scope.digest()),
                /*now*/ 20,
            )
            .fixture("shared owner"),
        );
        let barrier = Arc::new(Barrier::new(/*n*/ 8));
        let mut contenders = Vec::new();
        for contender in 0..8 {
            let mut candidate = manifest();
            candidate.artifact_id = id(&format!("candidate-{round}-{contender}"));
            let admission = admit_manifest_at_withdrawal_head_v3(
                &withdrawals,
                withdrawals.head_digest(),
                candidate,
                /*now*/ 20,
            )
            .fixture("legal contender admission");
            let owner = Arc::clone(&owner);
            let withdrawals = Arc::clone(&withdrawals);
            let barrier = Arc::clone(&barrier);
            contenders.push(std::thread::spawn(move || {
                barrier.wait();
                owner.begin_publication(
                    id(&format!("operation-{round}-{contender}")),
                    admission,
                    &withdrawals,
                    &ArtifactRegistry::new(),
                    Digest32::ZERO,
                    /*now*/ 20,
                )
            }));
        }
        let results = contenders
            .into_iter()
            .map(|contender| contender.join().fixture("contender thread"))
            .collect::<Vec<_>>();
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(effect_inventory(&directory.0), [1, 0, 0, 0, 0, 2]);
        let mut winner = results
            .into_iter()
            .find_map(Result::ok)
            .fixture("one winning publication");
        let checkpoints = owner
            .recovery_required_operations()
            .fixture("one pending operation");
        assert_eq!(
            checkpoints,
            vec![checkpoint_from_snapshot(
                &winner.snapshot(),
                owner.writer_lease_digest(),
            )]
        );
        let mut registry = ArtifactRegistry::new();
        owner
            .stage_compatibility_registration(&winner, &mut registry, /*now*/ 20)
            .fixture("winning registration");
        owner
            .ensure_payload_durable(&mut winner, &registry, b"payload", /*now*/ 20)
            .fixture("winning payload");
        owner
            .ensure_registry_durable(
                &mut winner,
                &registry,
                &withdrawals,
                digest("binding"),
                /*now*/ 20,
            )
            .fixture("winning registry");
        let signed = signed_head(&key, scope.digest(), registry.snapshot().head_digest);
        owner
            .ensure_witness_durable(&mut winner, &signed, &withdrawals, /*now*/ 20)
            .fixture("winning witness");
        owner
            .acknowledge(&mut winner, &withdrawals, /*now*/ 20)
            .fixture("winning acknowledgement");
        assert_eq!(
            owner
                .recovery_required_operations()
                .fixture("all competitors finished"),
            Vec::new()
        );
    }
}
