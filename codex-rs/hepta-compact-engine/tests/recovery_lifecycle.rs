//! Product-path recovery, outbox and current-source final-use regressions.

pub use codex_hepta_compact_engine::*;

mod lifecycle {
    include!("../src/product_e2e_tests.rs");

    struct AllowCurrentSource;

    impl CurrentSourceUseValidatorV1 for AllowCurrentSource {
        fn validate_current_use<'a>(
            &'a self,
            binding: &'a CurrentSourceUseBindingV1,
            now_unix_seconds: u64,
        ) -> CurrentSourceUseFuture<'a> {
            Box::pin(async move {
                Ok(CurrentSourceUseReceiptV1 {
                    owner_cut_digest: binding.owner_cut_digest()?,
                    deletion_correction_frontier_digest: Digest32::of_bytes(
                        b"source-owner-frontier:current",
                    ),
                    retention_revocation_state_digest: Digest32::of_bytes(
                        b"source-owner-retention:current",
                    ),
                    validation_revision: 1,
                    validated_at_unix_seconds: now_unix_seconds,
                    expires_at_unix_seconds: now_unix_seconds
                        .checked_add(60)
                        .ok_or(CurrentSourceUseErrorV1::Stale)?,
                })
            })
        }
    }

    struct RejectCurrentSource;

    impl CurrentSourceUseValidatorV1 for RejectCurrentSource {
        fn validate_current_use<'a>(
            &'a self,
            _binding: &'a CurrentSourceUseBindingV1,
            _now_unix_seconds: u64,
        ) -> CurrentSourceUseFuture<'a> {
            Box::pin(async { Err(CurrentSourceUseErrorV1::Rejected) })
        }
    }

    async fn published_owner(
        owner_label: &str,
        operation: &str,
        nonce_label: &str,
    ) -> (
        TempDir,
        ProductTrustFixture,
        MemoryCheckpointCoordinatorV2,
        VerifiedCompactionPublicationV1,
    ) {
        let owner = id(owner_label);
        let fixture = ProductTrustFixture::new(&owner);
        let temp = TempDir::new().expect("temp dir");
        let url = database_url(&temp);
        let publication = sealed_publication(
            &fixture,
            &["memory:recovery:a", "memory:recovery:b"],
            1,
            1,
            None,
            nonce_label,
        );
        let coordinator = MemoryCheckpointCoordinatorV2::open(
            &url,
            owner.as_str(),
            fixture.root.verifying_key().to_bytes(),
            &fixture.manifest_bytes,
            &format!("lease:{owner_label}"),
            1,
            NOW + 1_000,
            NOW,
        )
        .await
        .expect("open fenced product owner");
        coordinator
            .publish_verified_checkpoint(operation, &publication, NOW + 900, NOW)
            .await
            .expect("publish checkpoint");
        (temp, fixture, coordinator, publication)
    }

    #[tokio::test]
    async fn live_outbox_claim_survives_checkpoint_read() {
        let (_temp, _fixture, coordinator, _publication) = published_owner(
            "agent:recovery:live-claim",
            "operation:recovery:live-claim",
            "recovery-live-claim",
        )
        .await;

        let claim = coordinator
            .claim_next_outbox_for_worker(
                NOW + 1,
                "worker:recovery:one",
                "claim:recovery:one",
                NOW + 100,
            )
            .await
            .expect("claim publication event")
            .expect("publication event exists");

        let recovered = coordinator
            .recover_current_checkpoint("scope:e2e", "purpose:e2e", NOW + 2)
            .await
            .expect("checkpoint read")
            .expect("checkpoint exists");
        assert_eq!(recovered.generation(), 1);

        let duplicate = coordinator
            .claim_next_outbox_for_worker(
                NOW + 2,
                "worker:recovery:two",
                "claim:recovery:two",
                NOW + 101,
            )
            .await
            .expect("second claim query");
        assert!(duplicate.is_none(), "live claim must remain exclusive");

        coordinator
            .complete_outbox_claim(&claim, NOW + 3)
            .await
            .expect("complete original live claim");
    }

    #[tokio::test]
    async fn only_expired_claim_is_requeued_and_old_completion_is_fenced() {
        let (_temp, _fixture, coordinator, _publication) = published_owner(
            "agent:recovery:expired-claim",
            "operation:recovery:expired-claim",
            "recovery-expired-claim",
        )
        .await;

        let old_claim = coordinator
            .claim_next_outbox_for_worker(
                NOW + 1,
                "worker:recovery:old",
                "claim:recovery:old",
                NOW + 2,
            )
            .await
            .expect("claim event")
            .expect("event exists");
        let summary = coordinator
            .reconcile_claims_bounded(NOW + 3, 16)
            .await
            .expect("reconcile expired claim");
        assert_eq!(summary.requeued, 1);

        let replacement = coordinator
            .claim_next_outbox_for_worker(
                NOW + 3,
                "worker:recovery:new",
                "claim:recovery:new",
                NOW + 100,
            )
            .await
            .expect("replacement claim")
            .expect("replacement event exists");
        assert_eq!(replacement.event.event_id, old_claim.event.event_id);
        assert!(
            coordinator
                .complete_outbox_claim(&old_claim, NOW + 3)
                .await
                .is_err(),
            "superseded claim completion must fail closed"
        );
        coordinator
            .complete_outbox_claim(&replacement, NOW + 4)
            .await
            .expect("complete replacement claim");
    }

    #[tokio::test]
    async fn response_loss_queries_original_operation_identity() {
        let (_temp, _fixture, coordinator, publication) = published_owner(
            "agent:recovery:operation-query",
            "operation:recovery:query",
            "recovery-operation-query",
        )
        .await;

        let status = coordinator
            .query_operation("operation:recovery:query")
            .await
            .expect("query original operation");
        match status {
            CompactionOperationStatusV1::Committed {
                checkpoint_digest,
                publication_digest,
            } => {
                assert_eq!(
                    checkpoint_digest,
                    publication.candidate().checkpoint().checkpoint_digest
                );
                assert_eq!(publication_digest, publication.publication_digest());
            }
            other => panic!("expected committed operation, got {other:?}"),
        }
        assert_eq!(
            coordinator
                .query_operation("operation:recovery:absent")
                .await
                .expect("query absent operation"),
            CompactionOperationStatusV1::Absent
        );
    }

    #[tokio::test]
    async fn payload_return_requires_current_source_owner_acceptance() {
        let (_temp, _fixture, coordinator, publication) = published_owner(
            "agent:recovery:source-use",
            "operation:recovery:source-use",
            "recovery-source-use",
        )
        .await;

        let allowed = coordinator
            .recover_current_checkpoint_validated(
                "scope:e2e",
                "purpose:e2e",
                NOW + 1,
                &AllowCurrentSource,
            )
            .await
            .expect("source owner accepted")
            .expect("validated checkpoint exists");
        assert_eq!(
            allowed.selection().checkpoint_digest(),
            publication.candidate().checkpoint().checkpoint_digest
        );
        allowed
            .receipt()
            .validate_for(allowed.binding(), NOW + 1)
            .expect("receipt remains bound to exact owner cut");

        let rejected = coordinator
            .recover_current_checkpoint_validated(
                "scope:e2e",
                "purpose:e2e",
                NOW + 2,
                &RejectCurrentSource,
            )
            .await
            .expect_err("source owner rejection must stop payload return");
        assert_eq!(rejected.error_class(), CompactionErrorClassV1::TrustRejected);
        assert_eq!(
            rejected.recovery_directive(),
            CompactionRecoveryDirectiveV1::AwaitManifestOrOperator
        );
    }
}
