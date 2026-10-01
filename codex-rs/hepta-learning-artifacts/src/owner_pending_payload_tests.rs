use super::tests::*;
use super::*;

use pretty_assertions::assert_eq;

use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::LearningArtifactPublishRequestV1;
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
fn unfinished_recovery_and_effects_reject_missing_or_corrupt_declared_payloads() {
    for stopped_at in [
        ArtifactPublicationPhaseV1::PayloadDurable,
        ArtifactPublicationPhaseV1::RegistryDurable,
        ArtifactPublicationPhaseV1::WitnessDurable,
    ] {
        for fault in ["missing", "same-length-corruption"] {
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
            let (registry, mut transaction) =
                deterministic_publication(&owner, &withdrawals, /*now*/ 20);
            let payload = owner
                .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
                .fixture("declared payload durable");
            if stopped_at != ArtifactPublicationPhaseV1::PayloadDurable {
                owner
                    .ensure_registry_durable(
                        &mut transaction,
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
                    .ensure_witness_durable(
                        &mut transaction,
                        &signed,
                        &withdrawals,
                        /*now*/ 20,
                    )
                    .fixture("witness durable");
            }
            match fault {
                "missing" => fs::remove_file(directory.0.join(payload)).fixture("lose payload"),
                "same-length-corruption" => {
                    fs::write(directory.0.join(payload), b"corrupt").fixture("corrupt payload")
                }
                _ => unreachable!("fixed payload faults"),
            }
            let before = effect_inventory(&directory.0);
            let snapshot = transaction.snapshot();
            assert!(
                owner
                    .resume_publication(snapshot.clone(), /*now*/ 21)
                    .is_err()
            );
            let effect = match stopped_at {
                ArtifactPublicationPhaseV1::PayloadDurable => owner
                    .ensure_registry_durable(
                        &mut transaction,
                        &registry,
                        &withdrawals,
                        digest("binding"),
                        /*now*/ 21,
                    )
                    .map(|_| ()),
                ArtifactPublicationPhaseV1::RegistryDurable => owner
                    .ensure_witness_durable(
                        &mut transaction,
                        &signed,
                        &withdrawals,
                        /*now*/ 21,
                    )
                    .map(|_| ()),
                ArtifactPublicationPhaseV1::WitnessDurable => owner
                    .acknowledge(&mut transaction, &withdrawals, /*now*/ 21)
                    .map(|_| ()),
                ArtifactPublicationPhaseV1::Prepared | ArtifactPublicationPhaseV1::Acknowledged => {
                    unreachable!("fixed unfinished phases")
                }
            };
            assert!(effect.is_err());
            assert_eq!(transaction.snapshot(), snapshot);
            assert_eq!(effect_inventory(&directory.0), before);
            assert_eq!(
                owner
                    .recover_publication(&transaction.intent().operation_id)
                    .fixture("checkpoint remains inspectable")
                    .fixture("unfinished checkpoint")
                    .checkpoint
                    .phase,
                stopped_at
            );
            let request = LearningArtifactPublishRequestV1 {
                operation_id: transaction.intent().operation_id.clone(),
                admission: transaction.intent().admission.clone(),
                payload: b"payload".to_vec(),
                signed_current_head: signed.clone(),
                expected_registry_predecessor_head: Digest32::ZERO,
                now: 21,
            };
            drop(owner);
            let mut service =
                LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                    root: directory.0.clone(),
                    trust: trust(&key, scope.digest()),
                    writer_lease: lease(&key, scope.digest()),
                    required_current_head: (stopped_at
                        == ArtifactPublicationPhaseV1::WitnessDurable)
                        .then_some(signed),
                    withdrawal_registry: withdrawals,
                    storage_binding: digest("binding"),
                    now: 21,
                })
                .fixture("restart retains the unfinished operation's recovery fence");
            assert!(service.publish(request.clone()).is_err());
            assert_eq!(service.recovery_required(), Some(&request.operation_id));
            assert_eq!(effect_inventory(&directory.0), before);
        }
    }
}
