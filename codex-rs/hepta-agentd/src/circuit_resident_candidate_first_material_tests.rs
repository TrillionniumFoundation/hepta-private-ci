//! Actual same-A signatures exercise the first-report verifier. This local
//! mechanism test supplies trusted fixture policy before encoding the report;
//! it does not claim three-UID Root admission or execution of E/D/T.
use super::super::super::evaluation_provider::fresh_training::PreparedBPanel;
use super::super::original_material::ProviderAdmission;
use super::super::original_material::UnstartedProvider;
use super::*;
use anyhow::Context as _;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD_NO_PAD;

fn held_fixture_policy(
    fixture: &UnstartedProvider,
    protocol: crate::OriginalCellEvaluationPanelRegistrationV1,
    trust: LearningEvidenceTrustV1,
    original_expiry: u64,
) -> anyhow::Result<PreheldMaterialInputs> {
    let source = &fixture.source_a;
    let [experience, dataset, generator, evaluator] =
        fixture.credentials.resident_checkpoint_signers();
    let trust_digest = LearningEvidenceVerifierV1::new(trust.clone())?.trust_digest();
    Ok(PreheldMaterialInputs {
        // These are trusted local fixture inputs, never parsed out of Report.
        // The cross-UID orchestrator must supply its own pre-held equivalents.
        task: PreheldTask {
            operation_id: id("positive-original-learning-operation"),
            principal_id: id(&source.scope.principal_digest.to_string()),
            agent_id: source.scope.agent_id.clone(),
            cell_id: source.scope.cell_id.clone(),
            source_run_id: source.scope.run_id.clone(),
            selected_artifact_digest: fixture.bundle.components.base,
            selected_bundle: fixture.bundle.clone(),
            envelope: IterationEnvelopeV1 {
                envelope_id: id("positive-original-envelope"),
                base_commit: d("0bfe47e53bae47977c4423362e4d3823edac99fd"),
                base_tree: d("8663f89daca111ba7f681d2c36442f6f4ded97f5"),
                objective_digest: source.objective_digest,
                grammar_digest: d("explicit-positive-single-head-grammar"),
                maximum_files: 1,
                maximum_diff_bytes: 4_096,
                maximum_candidates: 1,
                maximum_parallel_sandboxes: 1,
                expiry_unix_seconds: original_expiry,
            },
            budget: LearningIterationBudgetV1 {
                maximum_dataset_rows: 1,
                maximum_dataset_bytes: 128,
                maximum_training_steps: 2,
                maximum_training_milliseconds: 10_000,
                maximum_artifact_bytes: 4_096,
            },
        },
        owners: LearningIterationOwnersV1 {
            evidence_trust_digest: trust_digest,
            experience: experience.principal.principal_id.clone(),
            dataset: dataset.principal.principal_id.clone(),
            trainer: generator.principal.principal_id.clone(),
            evaluator: evaluator.principal.principal_id.clone(),
            proposal: id("positive-original-model"),
            selector: fixture.credentials.selector.principal.principal_id.clone(),
            next_use_observer: fixture.credentials.observer.principal.principal_id.clone(),
        },
        protocol,
        trust,
        generator,
        observer: fixture.credentials.observer.clone(),
        evaluator,
        experience,
        dataset,
        baseline: Arc::clone(&fixture.baseline),
        source_input: vec![Q, Q / 4],
        decision_snapshot: source.ndu_snapshot_digest,
        episode_id: id("positive-original-episode"),
        rule: crate::CellQ24DatasetRuleV1 {
            head: crate::CellQ24PrivateHeadV1::Prediction { index: 0 },
            unit_profile_digest: d("explicit-positive-terminal-unit"),
        },
        optimizer: crate::CellQ24SgdRuleV1 {
            epochs: 2,
            learning_rate_q24: Q / 2,
        },
        update_scope: LearningUpdateScopeV2::Cell,
        freeze_snapshot_id: id("positive-original-dataset"),
        maximum_signature_lifetime_seconds: 600,
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn first_pending_material_uses_full_original_signatures_and_preheld_policy()
-> anyhow::Result<()> {
    let admission = ProviderAdmission::new().await?;
    let (_, _, trust) =
        material::original_fixture_trust_at(admission.objective, admission.trust_time)?;
    let panel = PreparedBPanel::new(admission.objective, admission.trust_time)?;
    let protocol = panel.registration().clone();
    let original_expiry = admission
        .trust_time
        .checked_add(900)
        .context("original absolute work expiry")?;
    let fixture = Box::pin(UnstartedProvider::new_with_original_work_deadline(
        admission,
        protocol.evaluation_profile(),
        material::OriginalMaterialWorkDeadline::PreheldExact(original_expiry),
    ))
    .await?;
    let result: anyhow::Result<()> = (|| {
        let before = fixture.original_bytes()?;
        let held = held_fixture_policy(&fixture, protocol, trust, original_expiry)?;
        let ledger = fixture
            .ledger
            .lock()
            .map_err(|_| anyhow::anyhow!("original Ledger poisoned"))?
            .snapshot()?;
        let raw = encode_original_report(
            &fixture.material,
            &ledger,
            &fixture.original_decision,
            &fixture.original_outcome,
        )?;
        let pending = RootMaterialContract::from_preheld(held.clone())?.verify_report(&raw)?;
        anyhow::ensure!(
            pending.admission_binding()?
                == crate::RootResidentLearningProfileV3::admission_binding(
                    &fixture.material.initial,
                    &fixture.material.scope,
                    &fixture.material.verifier
                )?,
            "same original Root binding"
        );
        anyhow::ensure!(
            pending.material.initial == fixture.material.initial,
            "same full original initial cut"
        );
        anyhow::ensure!(
            pending.material.scope == fixture.material.scope,
            "same complete original frozen scope"
        );
        anyhow::ensure!(
            pending.material.freeze_evidence == fixture.material.freeze_evidence,
            "same complete original freeze signature"
        );
        anyhow::ensure!(
            pending.material.initial.receipts.is_empty(),
            "Pending contains no completed E, D or T claim"
        );
        drop(pending);
        let base: serde_json::Value = serde_json::from_slice(&raw)?;
        for role in ["decision", "outcome", "freeze"] {
            for field in [
                "principal_id",
                "trust",
                "scope",
                "objective",
                "payload_digest",
            ] {
                let mut changed = base.clone();
                changed[role][field] = serde_json::json!(d("foreign-original-context").to_string());
                anyhow::ensure!(
                    RootMaterialContract::from_preheld(held.clone())?
                        .verify_report(&wire::canonical_mutation(changed)?)
                        .is_err(),
                    "{role} {field}"
                );
            }
            let mut changed = base.clone();
            let mut signature = STANDARD_NO_PAD
                .decode(changed[role]["signature"].as_str().context("signature")?)?;
            signature[0] ^= 1;
            changed[role]["signature"] = serde_json::json!(STANDARD_NO_PAD.encode(signature));
            anyhow::ensure!(
                RootMaterialContract::from_preheld(held.clone())?
                    .verify_report(&wire::canonical_mutation(changed)?)
                    .is_err(),
                "full-length original {role} signature"
            );
        }
        let mut changed = base.clone();
        changed["completeness"]["omitted_count_bound"] = serde_json::json!(1);
        anyhow::ensure!(
            RootMaterialContract::from_preheld(held.clone())?
                .verify_report(&wire::canonical_mutation(changed)?)
                .is_err(),
            "the full signed completeness, not its digest alone"
        );
        let mut wrong = held.clone();
        wrong.observer.controller_id = wrong.generator.controller_id.clone();
        anyhow::ensure!(
            RootMaterialContract::from_preheld(wrong).is_err(),
            "full pre-held signer binding includes controller"
        );
        let mut wrong = held.clone();
        wrong.task.budget.maximum_training_steps += 1;
        anyhow::ensure!(
            RootMaterialContract::from_preheld(wrong)?
                .verify_report(&raw)
                .is_err(),
            "whole frozen cost contract"
        );
        let mut wrong = held.clone();
        wrong.source_input[0] += 1;
        anyhow::ensure!(
            RootMaterialContract::from_preheld(wrong)?
                .verify_report(&raw)
                .is_err(),
            "same original batch and update rule"
        );
        let mut wrong = held.clone();
        wrong.task.envelope.expiry_unix_seconds = now()?;
        anyhow::ensure!(
            RootMaterialContract::from_preheld(wrong).is_err(),
            "expired original contract cannot be renewed by report"
        );
        let mut changed_initial = fixture.material.initial.clone();
        changed_initial.request.completed_task_receipt = d("unverified-source-substitution");
        let changed_initial =
            LearningIterationCoordinatorV1::new(changed_initial.request, changed_initial.owners)?;
        let mut changed = base.clone();
        changed["initial"] = serde_json::json!(STANDARD_NO_PAD.encode(
            encode_original_owner_snapshot_v1(changed_initial.snapshot())?
        ));
        anyhow::ensure!(
            RootMaterialContract::from_preheld(held.clone())?
                .verify_report(&wire::canonical_mutation(changed)?)
                .is_err(),
            "original freeze pins this exact Pending completion claim"
        );
        let mut replay = LearningLedger::new();
        for record in ledger.records() {
            let mut event = record.event.clone();
            if let LedgerEvent::AuthenticatedDecisionV2(decision) = &mut event {
                decision.support_digest = d("different-Source-publication");
            }
            replay.append(event)?;
        }
        let mut changed = base.clone();
        changed["ledger"] = serde_json::json!(
            STANDARD_NO_PAD.encode(encode_original_ledger_snapshot_v1(&replay.snapshot())?)
        );
        anyhow::ensure!(
            RootMaterialContract::from_preheld(held.clone())?
                .verify_report(&wire::canonical_mutation(changed)?)
                .is_err(),
            "canonical causal replay is not original signature authentication"
        );
        let mut added = base;
        added["host_trust"] = serde_json::json!("child-selected");
        anyhow::ensure!(
            RootMaterialContract::from_preheld(held.clone())?
                .verify_report(&serde_json::to_vec(&added)?)
                .is_err()
        );
        let mut trailing = raw;
        trailing.push(b' ');
        anyhow::ensure!(
            RootMaterialContract::from_preheld(held.clone())?
                .verify_report(&trailing)
                .is_err()
        );
        anyhow::ensure!(
            RootMaterialContract::from_preheld(held)?
                .verify_report(&vec![0; wire::CONTROL_LIMIT + 1])
                .is_err()
        );
        anyhow::ensure!(
            fixture.original_bytes()? == before,
            "verification did not write Source, ledger or any receipt owner"
        );
        Ok(())
    })();
    drop(panel);
    let cleanup = fixture.finish().await;
    match (result, cleanup) {
        (Ok(()), Ok(_)) => Ok(()),
        (Err(error), cleanup) => {
            Err(error.context(format!("original fixture cleanup: {cleanup:?}")))
        }
        (Ok(()), Err(error)) => Err(error),
    }
}
