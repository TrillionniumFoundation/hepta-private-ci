//! Root mechanism over an actual SourceBound Model journal. The surrounding
//! Evaluation/Product metadata and Root grants remain explicit test custody;
//! no test counts as ordinary independent B/retention or production adoption.
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

use super::super::super::authentication;
use super::super::super::model::ResidentOriginalModelProofV3;
use super::super::super::runtime::ResidentRuntimeObservationV3;
use super::super::super::transport::ResidentReadbackPinV3;
use super::super::super::wire;
use super::support::ResidentRootFixture;
use crate::LearningIterationRuntimeErrorV1;
use crate::OriginalCellQ24ModelCommandReceiptV1;

fn now() -> anyhow::Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_root_model_four_cut_preserves_original_wire_and_all_signatures()
-> anyhow::Result<()> {
    OriginalCellQ24ModelCommandReceiptV1::fixture_original_root_model(|input| async move {
        let fixture = ResidentRootFixture::for_original_evaluation_window(
            input.initial.clone(),
            input.scope.clone(),
            &input.verifier,
        )?;
        let cuts = input.cuts()?;
        authentication::verify_original_evidence(
            &fixture.profile,
            &input.verifier,
            &cuts[4],
            &input.signatures,
            None,
            now()?,
        )?;
        let reply = wire::encode_current(ResidentRuntimeObservationV3 {
            snapshot: Some(cuts[4].clone()),
            attestations: input.signatures.to_vec(),
            dispatch_pending: false,
            model: None,
        })?;
        let wire::Reply::Current {
            snapshot,
            evidence,
            dispatch_pending,
            model,
        } = &reply
        else {
            anyhow::bail!("actual four-cut response")
        };
        assert!(model.is_none());
        // Ordered fields are the original wire layout. None adds no member,
        // so old non-Proposal clients retain identical serialized bytes.
        #[derive(serde::Serialize)]
        struct PriorWire<'a> {
            status: &'static str,
            snapshot: &'a Option<String>,
            evidence: &'a Vec<String>,
            dispatch_pending: bool,
        }
        assert_eq!(
            serde_json::to_vec(&reply)?,
            serde_json::to_vec(&PriorWire {
                status: "current",
                snapshot,
                evidence,
                dispatch_pending: *dispatch_pending,
            })?
        );
        let observed = wire::decode_current(reply, &fixture.profile, &input.verifier, now()?)?;
        assert_eq!(observed.snapshot(), Some(&cuts[4]));
        assert_eq!(observed.attestations(), input.signatures.as_slice());
        assert!(observed.original_model_record().is_none());
        for index in 0..4 {
            let mut missing = input.signatures.to_vec();
            missing.remove(index);
            assert!(
                authentication::verify_original_evidence(
                    &fixture.profile,
                    &input.verifier,
                    &cuts[4],
                    &missing,
                    None,
                    now()?,
                )
                .is_err()
            );
        }
        Ok(())
    })
    .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_root_model_five_cut_uses_original_record_without_fifth_signature()
-> anyhow::Result<()> {
    OriginalCellQ24ModelCommandReceiptV1::fixture_original_root_model(|input| async move {
        let fixture = ResidentRootFixture::for_original_evaluation_window(
            input.initial.clone(),
            input.scope.clone(),
            &input.verifier,
        )?;
        let proof = ResidentOriginalModelProofV3::from_original_readback(
            &fixture.profile,
            &input.verifier,
            &input.completed,
            &input.signatures,
            &input.original,
            now()?,
        )?;
        authentication::verify_original_evidence(
            &fixture.profile,
            &input.verifier,
            &input.completed,
            &input.signatures,
            Some(&proof),
            now()?,
        )?;
        assert_eq!(input.signatures.len(), 4);
        let reply = wire::encode_current(ResidentRuntimeObservationV3 {
            snapshot: Some(input.completed.clone()),
            attestations: input.signatures.to_vec(),
            dispatch_pending: false,
            model: Some(proof.clone()),
        })?;
        let current = wire::decode_current(reply, &fixture.profile, &input.verifier, now()?)?;
        assert_eq!(current.snapshot(), Some(&input.completed));
        assert_eq!(current.original_model_record(), Some(proof.encode()));
        assert_eq!(current.attestations(), input.signatures.as_slice());
        let coordinator =
            codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
                input.completed,
            )?;
        assert_eq!(
            coordinator.next_stage(),
            Some(codex_hepta_learning_artifacts::LearningIterationStageV1::Selection)
        );
        Ok(())
    })
    .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_root_model_refuses_missing_extra_wrong_stage_or_reordered_evidence()
-> anyhow::Result<()> {
    OriginalCellQ24ModelCommandReceiptV1::fixture_original_root_model(|input| async move {
        let fixture = ResidentRootFixture::for_original_evaluation_window(
            input.initial.clone(),
            input.scope.clone(),
            &input.verifier,
        )?;
        let proof = ResidentOriginalModelProofV3::from_original_readback(
            &fixture.profile,
            &input.verifier,
            &input.completed,
            &input.signatures,
            &input.original,
            now()?,
        )?;
        assert!(
            authentication::verify_original_evidence(
                &fixture.profile,
                &input.verifier,
                &input.completed,
                &input.signatures,
                None,
                now()?,
            )
            .is_err()
        );
        let cuts = input.cuts()?;
        assert!(
            authentication::verify_original_evidence(
                &fixture.profile,
                &input.verifier,
                &cuts[4],
                &input.signatures,
                Some(&proof),
                now()?,
            )
            .is_err()
        );
        let mut extra = input.signatures.to_vec();
        extra.push(input.signatures[3].clone());
        assert!(
            authentication::verify_original_evidence(
                &fixture.profile,
                &input.verifier,
                &input.completed,
                &extra,
                Some(&proof),
                now()?,
            )
            .is_err()
        );
        for index in 0..4 {
            let mut missing = input.signatures.to_vec();
            missing.remove(index);
            assert!(
                authentication::verify_original_evidence(
                    &fixture.profile,
                    &input.verifier,
                    &input.completed,
                    &missing,
                    Some(&proof),
                    now()?,
                )
                .is_err()
            );
        }
        let mut reordered = input.signatures.clone();
        reordered.swap(0, 1);
        assert!(
            authentication::verify_original_evidence(
                &fixture.profile,
                &input.verifier,
                &input.completed,
                &reordered,
                Some(&proof),
                now()?,
            )
            .is_err()
        );
        assert!(
            ResidentOriginalModelProofV3::from_original_readback(
                &fixture.profile,
                &input.verifier,
                &input.completed,
                &reordered,
                &input.original,
                now()?,
            )
            .is_err()
        );
        Ok(())
    })
    .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_root_model_refuses_changed_record_context_and_signature_window()
-> anyhow::Result<()> {
    OriginalCellQ24ModelCommandReceiptV1::fixture_original_root_model(|input| async move {
        let fixture = ResidentRootFixture::for_original_evaluation_window(
            input.initial.clone(),
            input.scope.clone(),
            &input.verifier,
        )?;
        let proof = ResidentOriginalModelProofV3::from_original_readback(
            &fixture.profile,
            &input.verifier,
            &input.completed,
            &input.signatures,
            &input.original,
            now()?,
        )?;
        let original = proof.encode();
        for index in [8_usize, 40, 48, 80, 112, 120] {
            let mut changed = original.clone();
            changed[index] ^= 1;
            assert!(
                ResidentOriginalModelProofV3::decode_root_reply(
                    &changed,
                    &fixture.profile,
                    &input.verifier,
                    &input.completed,
                    &input.signatures,
                    now()?,
                )
                .is_err(),
                "changed original proof byte {index}"
            );
        }
        let mut changed = input.signatures.clone();
        changed[3].expires_at -= 1;
        anyhow::ensure!(
            changed[3].expires_at > now()?,
            "original signature window remains live"
        );
        // A legal re-sign is still a different original attestation pin.
        use ed25519_dalek::Signer;
        changed[3].signature = ed25519_dalek::SigningKey::from_bytes(&[42; 32])
            .sign(&changed[3].signing_bytes())
            .to_bytes();
        input.verifier.verify(
            codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator,
            &changed[3],
            &codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1(
                &input.completed.receipts[3],
            )?,
            now()?,
        )?;
        assert!(
            ResidentOriginalModelProofV3::from_original_readback(
                &fixture.profile,
                &input.verifier,
                &input.completed,
                &changed,
                &input.original,
                now()?,
            )
            .is_err()
        );
        assert!(
            ResidentOriginalModelProofV3::decode_root_reply(
                &original,
                &fixture.profile,
                &input.verifier,
                &input.completed,
                &changed,
                now()?,
            )
            .is_err()
        );
        Ok(())
    })
    .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_root_model_cold_checkpoint_is_readonly_and_pins_complete_original_bytes()
-> anyhow::Result<()> {
    OriginalCellQ24ModelCommandReceiptV1::fixture_original_root_model(|input| async move {
        let mut fixture = ResidentRootFixture::for_original_evaluation_window(
            input.initial.clone(),
            input.scope.clone(),
            &input.verifier,
        )?;
        let proof = ResidentOriginalModelProofV3::from_original_readback(
            &fixture.profile,
            &input.verifier,
            &input.completed,
            &input.signatures,
            &input.original,
            now()?,
        )?;
        let cancellation = CancellationToken::new();
        let cuts = input.cuts()?;
        {
            let original = &fixture
                .registration
                .as_ref()
                .expect("original Root owner")
                .owner;
            let continuation = original
                .admit(&cancellation)
                .await?
                .ok_or_else(|| anyhow::anyhow!("actual vacant Root transition"))?;
            for index in 0..5 {
                let count = (index + 1).min(4);
                let model = if index == 4 { Some(&proof) } else { None };
                authentication::verify_original_evidence(
                    &fixture.profile,
                    &input.verifier,
                    &cuts[index + 1],
                    &input.signatures[..count],
                    model,
                    now()?,
                )?;
                continuation
                    .gate
                    .begin(
                        &cuts[index],
                        cuts[index + 1].receipts[index].observation.stage(),
                    )
                    .await?;
                continuation
                    .gate
                    .checkpoint(&cuts[index], cuts[index + 1].clone())
                    .await?;
            }
            assert_eq!(
                original.read(&cancellation).await?.0.snapshot,
                Some(input.completed.clone())
            );
            drop(continuation);
        }
        fixture.recover()?;
        let cold = &fixture
            .registration
            .as_ref()
            .expect("explicit readonly Root")
            .owner;
        assert!(cold.authority.readonly());
        assert!(cold.admit(&cancellation).await.is_err());
        assert_eq!(
            cold.read(&cancellation).await?.0.snapshot,
            Some(input.completed.clone())
        );
        authentication::verify_model_comparison_pin(
            &fixture.profile,
            &input.verifier,
            &input.completed,
            &input.signatures,
            &proof.encode(),
            now()?,
        )?;
        assert!(
            authentication::verify_attestations(
                &fixture.profile,
                &input.verifier,
                &input.completed,
                &input.signatures,
                now()?,
            )
            .is_err(),
            "old tuple cannot silently recover Model evidence"
        );
        let pin = Some(ResidentReadbackPinV3 {
            snapshot: input.completed.clone(),
            attestations: input.signatures.to_vec(),
            model: Some(proof.encode()),
        });
        let current = wire::decode_current(
            wire::encode_current(ResidentRuntimeObservationV3 {
                snapshot: Some(input.completed.clone()),
                attestations: input.signatures.to_vec(),
                dispatch_pending: false,
                model: Some(proof),
            })?,
            &fixture.profile,
            &input.verifier,
            now()?,
        )?;
        wire::require_original_prefix(&pin, &current)?;
        let rollback = wire::decode_current(
            wire::encode_current(ResidentRuntimeObservationV3 {
                snapshot: Some(cuts[4].clone()),
                attestations: input.signatures.to_vec(),
                dispatch_pending: false,
                model: None,
            })?,
            &fixture.profile,
            &input.verifier,
            now()?,
        )?;
        assert!(matches!(
            wire::require_original_prefix(&pin, &rollback),
            Err(LearningIterationRuntimeErrorV1::CommitUncertain)
        ));
        Ok(())
    })
    .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "explicit actual Root and pre-existing protected bind qualification"]
async fn resident_root_model_unknown_dispatch_never_recommits_or_mints_fresh_gate()
-> anyhow::Result<()> {
    OriginalCellQ24ModelCommandReceiptV1::fixture_original_root_model(|input| async move {
        input.unknown_then_original_readonly().await?;
        let mut fixture = ResidentRootFixture::for_original_evaluation_window(
            input.initial.clone(),
            input.scope.clone(),
            &input.verifier,
        )?;
        let cuts = input.cuts()?;
        let cancellation = CancellationToken::new();
        {
            let original = &fixture
                .registration
                .as_ref()
                .expect("original Root owner")
                .owner;
            let continuation = original
                .admit(&cancellation)
                .await?
                .ok_or_else(|| anyhow::anyhow!("actual original Root admission"))?;
            for index in 0..4 {
                continuation
                    .gate
                    .begin(
                        &cuts[index],
                        cuts[index + 1].receipts[index].observation.stage(),
                    )
                    .await?;
                continuation
                    .gate
                    .checkpoint(&cuts[index], cuts[index + 1].clone())
                    .await?;
            }
            continuation
                .gate
                .begin(
                    &cuts[4],
                    codex_hepta_learning_artifacts::LearningIterationStageV1::Proposal,
                )
                .await?;
            drop(continuation);
        }
        fixture.recover()?;
        let recovered = &fixture
            .registration
            .as_ref()
            .expect("original readonly Root")
            .owner;
        let saved = recovered.read(&cancellation).await?.0;
        assert_eq!(saved.snapshot, Some(cuts[4].clone()));
        assert!(saved.dispatch_pending);
        assert!(recovered.admit(&cancellation).await.is_err());
        Ok(())
    })
    .await
}
