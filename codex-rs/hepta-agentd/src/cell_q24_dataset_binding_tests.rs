//! Signed but mismatched ledger facts must fail at the Dataset consumer even
//! when appended directly without the experience intake. Keys and outcomes are
//! explicit fixtures; these are source-binding checks, not ordinary A/B runs.

use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn signed_ledger_facts_cannot_substitute_another_source_profile_or_policy()
-> anyhow::Result<()> {
    for change in [
        "ndu-snapshot",
        "full-run-start-snapshot",
        "policy",
        "decision-support",
        "candidate-set",
        "selected-action",
        "propensity",
        "before-source-admission",
        "before-window-end",
    ] {
        let root = tempfile::tempdir()?;
        let (baseline, bundle) = source::model(root.path())?;
        let fixture = ledger::LedgerFixture::new("original-q24-dataset-ledger");
        let mut writer = fixture.writer;
        let identity = identity(root.path())?;
        let run = circuit_learning_run_id_v1(&writer, &identity.agent_id, &id("episode"))?;
        let (identity, owner) = source::completed(
            root.path(),
            &bundle,
            &run,
            &source::observation([codec::Q / 2, 0]),
        )
        .await?;
        let publication = owner.read_run_publication(&identity, &run)?;
        let mut decision = decision(&publication)?;
        let mut outcome = outcome(&publication, /*value*/ 1 << 32);
        assert_eq!(
            decision.run_snapshot_digest,
            publication.input().ndu_snapshot_digest
        );
        match change {
            "ndu-snapshot" => decision.run_snapshot_digest = d("another-ndu-snapshot"),
            "full-run-start-snapshot" => {
                // Exact separate #6006 profile, not an arbitrary wrong digest.
                // A fresh valid signature cannot change which snapshot this
                // NDU Dataset profile authorizes.
                let snapshot = &publication.original_record().snapshot;
                decision.run_snapshot_digest = Digest32::of_parts(&[
                    b"hepta.cell.q24.dataset-run-start-snapshot.v1\0",
                    &(snapshot.run_id.as_str().len() as u64).to_le_bytes(),
                    snapshot.run_id.as_str().as_bytes(),
                    snapshot.objective_digest.as_array(),
                    snapshot.hard_constraint_digest.as_array(),
                    snapshot.preference_state_digest.as_array(),
                    snapshot.model_tuple_digest.as_array(),
                    snapshot.prompt_registry_digest.as_array(),
                    snapshot.artifact_set_digest.as_array(),
                    &snapshot.authority_epoch.to_le_bytes(),
                    &snapshot.generation.to_le_bytes(),
                    snapshot.fence_digest.as_array(),
                ]);
                assert_ne!(
                    decision.run_snapshot_digest,
                    publication.input().ndu_snapshot_digest
                );
            }
            "policy" => decision.policy_digest = d("another-signed-policy"),
            "decision-support" => decision.support_digest = d("another-decision-support"),
            "candidate-set" => {
                decision.candidate_ids.push(id("unobserved-candidate"));
                decision.candidate_ids.sort();
                decision.completeness.candidates_digest =
                    candidate_ids_digest_v2(&decision.candidate_ids);
                decision.completeness.canonical_order_digest =
                    candidate_order_digest_v2(&decision.candidate_ids);
                decision.completeness.candidate_count = decision.candidate_ids.len() as u32;
            }
            "selected-action" => {
                decision.selected_candidate_id = decision
                    .candidate_ids
                    .iter()
                    .find(|candidate| **candidate != decision.selected_candidate_id)
                    .expect("fixture has two original actions")
                    .clone();
            }
            "propensity" => {
                decision.selected_propensity = ProbabilityQ32::from_raw(1 << 31)?;
            }
            "before-source-admission" => outcome.observed_at = Some(0),
            "before-window-end" => outcome.watermark.finalized_at = Some(41),
            _ => unreachable!(),
        }
        // These calls authenticate the modified messages and append them to
        // real locked ledger/witness owners. Nothing is edited after signing.
        append_decision(&mut writer, decision)?;
        append_outcome(&mut writer, outcome);
        let initial = initial(&publication, &bundle, writer.verifier().trust_digest())?;
        let (plan, signed) = freeze(&writer, &initial, rule())?;
        let before = writer.qualification_file_bytes(8 * 1024 * 1024)?;
        let readback = owner.readback();
        assert!(
            matches!(
                CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer)
                    .read_current_with_clock(&initial, &baseline, rule(), plan, &signed, || Ok(50)),
                Err(CellQ24DatasetErrorV1::Binding(
                    "independent terminal source outcome"
                ))
            ),
            "{change}"
        );
        assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);
        assert_eq!(owner.read_run_publication(&identity, &run)?, publication);
    }
    Ok(())
}

#[tokio::test]
async fn legacy_signed_freeze_cannot_be_reinterpreted_as_the_exact_source_profile()
-> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (baseline, bundle) = source::model(root.path())?;
    let fixture = ledger::LedgerFixture::new("original-q24-dataset-ledger");
    let mut writer = fixture.writer;
    let identity = identity(root.path())?;
    let run = circuit_learning_run_id_v1(&writer, &identity.agent_id, &id("episode"))?;
    let (identity, owner) = source::completed(
        root.path(),
        &bundle,
        &run,
        &source::observation([codec::Q / 2, 0]),
    )
    .await?;
    let publication = owner.read_run_publication(&identity, &run)?;
    append_decision(&mut writer, decision(&publication)?)?;
    // Both old profiles can genuinely authorize this source-bound fixture.
    // No old evidence is rewritten to make the v3 reader accept it.
    let mut original_outcome = outcome(&publication, /*value*/ 1 << 32);
    original_outcome.support_digest = publication.publication_digest();
    append_outcome(&mut writer, original_outcome);
    let initial = initial(&publication, &bundle, writer.verifier().trust_digest())?;
    let readback = owner.readback();
    for profile in [
        b"hepta.cell.q24.original-dataset.v1\0single-run;HQ24I001;active-authenticated-terminal-outcome;optional-same-outcome-credit-lineage;Q32-exact-divide-256;reject-outside-eight;no-output-label".as_slice(),
        b"hepta.cell.q24.original-dataset.v2\0single-run;HQ24I001;active-authenticated-terminal-outcome;optional-same-outcome-credit-lineage;Q32-exact-divide-256;reject-outside-eight;no-output-label;run-snapshot=source-input-ndu;policy=source-output;support=source-publication;candidate-set=ledger-sorted;policy-order=source-output;deterministic-propensity-one;observed-at-or-after-ceil-source-admission;finalized-at-or-after-window-end".as_slice(),
    ] {
        let (mut plan, _) = freeze(&writer, &initial, rule())?;
        plan.inclusion_policy_digest = Digest32::of_parts(&[
            profile,
            initial.head_digest.as_array(),
            rule().unit_profile_digest.as_array(),
            &[2],
            &0_u16.to_le_bytes(),
        ]);
        let signed = ledger::sign(
            &writer,
            LearningEvidenceRoleV1::Evaluator,
            &dataset_freeze_signing_payload_v2(&writer.snapshot()?, &plan)?,
        );
        // The original ledger recognizes each original policy's signature;
        // the v3 consumer cannot assign either signature new support semantics.
        writer.freeze_dataset(plan.clone(), &signed, /*now*/ 50)?;
        let before = writer.qualification_file_bytes(8 * 1024 * 1024)?;
        assert!(matches!(
            CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer).read_current_with_clock(
                &initial,
                &baseline,
                rule(),
                plan,
                &signed,
                || Ok(50)
            ),
            Err(CellQ24DatasetErrorV1::Binding(
                "frozen request, rule, trust or baseline"
            ))
        ));
        assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);
        assert_eq!(owner.read_run_publication(&identity, &run)?, publication);
    }
    Ok(())
}

#[tokio::test]
async fn original_observer_measurement_support_is_preserved_without_source_relabeling()
-> anyhow::Result<()> {
    for support_kind in ["independent-file", "opaque-nonzero", "source-publication"] {
        let root = tempfile::tempdir()?;
        let (baseline, bundle) = source::model(root.path())?;
        let fixture = ledger::LedgerFixture::new("original-q24-dataset-ledger");
        let mut writer = fixture.writer;
        let identity = identity(root.path())?;
        let run = circuit_learning_run_id_v1(&writer, &identity.agent_id, &id("episode"))?;
        let (identity, owner) = source::completed(
            root.path(),
            &bundle,
            &run,
            &source::observation([codec::Q / 2, 0]),
        )
        .await?;
        let publication = owner.read_run_publication(&identity, &run)?;
        append_decision(&mut writer, decision(&publication)?)?;
        let mut measured = outcome(&publication, /*value*/ 1 << 32);
        measured.support_digest = match support_kind {
            "independent-file" => d("original-observer-measurement-file"),
            "opaque-nonzero" => Digest32::from_array([0x72; 32]),
            "source-publication" => publication.publication_digest(),
            _ => unreachable!(),
        };
        assert!(!measured.support_digest.is_zero());
        if support_kind != "source-publication" {
            assert_ne!(measured.support_digest, publication.publication_digest());
        }
        let evidence = ledger::sign(
            &writer,
            LearningEvidenceRoleV1::Observer,
            &outcome_signing_payload_v2(&measured),
        );
        let predecessor = writer.snapshot()?.head_digest;
        let before = writer.qualification_file_bytes(8 * 1024 * 1024)?;
        let mut relabeled = measured.clone();
        relabeled.support_digest = d("unsigned-replacement-measurement-support");
        assert_ne!(relabeled.support_digest, measured.support_digest);
        assert!(matches!(
            writer.append_outcome(predecessor, relabeled, &evidence, /*now*/ 50),
            Err(ProductionLedgerError::Evidence(_))
        ));
        assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);

        // Even a valid Observer signature cannot move this measurement to an
        // episode without its original authenticated Decision in this ledger.
        let mut wrong_episode = measured.clone();
        wrong_episode.episode_id = id("another-independent-episode");
        let wrong_episode_evidence = ledger::sign(
            &writer,
            LearningEvidenceRoleV1::Observer,
            &outcome_signing_payload_v2(&wrong_episode),
        );
        assert!(matches!(
            writer.append_outcome(
                predecessor,
                wrong_episode,
                &wrong_episode_evidence,
                /*now*/ 50
            ),
            Err(ProductionLedgerError::AuthenticatedDecisionRequired)
        ));
        assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);

        writer.append_outcome(predecessor, measured.clone(), &evidence, /*now*/ 50)?;
        let initial = initial(&publication, &bundle, writer.verifier().trust_digest())?;
        let (plan, signed) = freeze(&writer, &initial, rule())?;
        let before = writer.qualification_file_bytes(8 * 1024 * 1024)?;
        let readback = owner.readback();
        let material = CellQ24DatasetReaderV1::new(&readback, &identity, &mut writer)
            .read_current_with_clock(&initial, &baseline, rule(), plan, &signed, || Ok(50))?;
        let snapshot = writer.read_current_durable_snapshot()?;
        let LedgerEvent::AuthenticatedOutcomeV2(retained) = &snapshot.records()[1].event else {
            anyhow::bail!("original signed measurement Outcome");
        };
        assert_eq!(retained.support_digest, measured.support_digest);
        assert_eq!(retained.value, measured.value);
        let expected = CellQ24TrainingBatchV1::new(
            material.receipt().snapshot.dataset_digest,
            vec![CellQ24TrainingSampleV1 {
                input: vec![codec::Q / 2, 0],
                target: codec::Q,
            }],
        )?;
        assert_eq!(material.batch().encoded(), expected.encoded());
        assert_eq!(writer.qualification_file_bytes(8 * 1024 * 1024)?, before);
        assert_eq!(owner.read_run_publication(&identity, &run)?, publication);
    }
    Ok(())
}
