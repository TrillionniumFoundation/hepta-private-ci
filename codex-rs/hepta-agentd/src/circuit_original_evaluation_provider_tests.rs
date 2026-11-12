//! Mechanism-only original B/retention provider coverage. Original A,
//! SourceBound Candidate and all source/Cell/ledger owners really execute.
//! Role keys, RunStart admission, held-out clock, models and measured labels
//! remain explicit fixtures; this is not deployed B or scientific gain.
use super::*;
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_types::FixedQ32;
use crate::circuit_original_evaluation_provider::*;
use crate::circuit_original_evaluation_provider::test_access::CohortAt;
use crate::neuron_cell_evaluation::tests::original_provider::ProviderPlanFixture;
use pretty_assertions::assert_eq;

#[path = "circuit_original_evaluation_source_support_tests.rs"]
mod source;
use source::BFixture;
use source::ObservationMode;

async fn preregistered() -> anyhow::Result<(
    PositiveFixture, BFixture, BFixture, crate::OriginalCellEvaluationPanelRegistrationV1,
)> {
    let preview = support::admission("original-B-profile-preview").await?;
    let objective = support::source(&preview, [Q, Q / 4])?.objective_digest;
    drop(preview);
    let at = now()?;
    let primary = BFixture::new("original-B", objective, at)?;
    let retention = BFixture::new("original-retention", objective, at)?;
    let registration = crate::OriginalCellEvaluationPanelRegistrationV1::new(
        primary.task()?, vec![retention.task()?],
    )?;
    let original = PositiveFixture::ready_with_profile(registration.evaluation_profile(), at).await?;
    assert_eq!(original.config.decision.request.envelope.objective_digest, objective);
    assert_eq!(original.config.decision.request.evaluation_profile, registration.evaluation_profile());
    assert!(!registration.retention().is_empty());
    Ok((original, primary, retention, registration))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_provider_releases_actual_b_and_retention_only_after_consumption()
-> anyhow::Result<()> {
    let (original, primary, retention, registration) = preregistered().await?;
    let training = BFixture::training(&original)?;
    assert!(matches!(&training.receipts[2].observation,
        LearningIterationObservationV1::Training { .. }));
    assert_eq!(original.config.training_evidence.role, LearningEvidenceRoleV1::Generator);
    for mut b in [primary, retention] {
        b.populate(&original, ObservationMode::Complete, /*changed_candidate_action*/ false).await?;
        let config = b.config(&original, &registration)?;
        let source_before = b.source_bytes()?;
        let mut cohort = CohortAt::read(b.owners(), config, b.at)?;
        let metadata = cohort.original.observed_manifest_digest()?;
        let ledger_before = cohort.bytes()?;
        assert_eq!(cohort.current()?, metadata);
        assert_eq!(cohort.bytes()?, ledger_before);
        assert_eq!(cohort.original.authority(), AuthorityPosture::DENY_ALL);
        let mut runner = ProviderPlanFixture::new(
            &cohort.original, &b.rule, &training, BFixture::original_manifests(&original),
        )?;
        let plan = runner.plan.clone();
        let before = runner.bytes();
        let mut provider = cohort.consume(plan)?;
        assert_eq!((provider.manifest_calls, provider.releases), (0, 0));
        let receipt = runner.run(&mut provider)?;
        assert_ne!(runner.bytes(), before);
        assert_eq!((provider.manifest_calls, provider.releases), (1, 1));
        assert_eq!(receipt.temporal().candidate.estimate.point.rows, 2);
        // The independently signed 1.0 and 0.5 Outcomes, not Q24 drive or
        // prediction, determine this exact estimate.
        assert_eq!(receipt.temporal().candidate.estimate.point.doubly_robust,
            FixedQ32::from_raw(3_i64 << 30));
        assert_eq!(receipt.temporal().baseline.estimate.point.doubly_robust,
            FixedQ32::from_raw(3_i64 << 30));
        assert_eq!(receipt.temporal().candidate.estimate.cluster_count, 2);
        assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
        let consumed = runner.bytes();
        assert!(runner.run(&mut provider).is_err());
        assert_eq!(provider.releases, 1);
        assert_eq!(runner.bytes(), consumed);
        assert_eq!(b.source_bytes()?, source_before);
    }
    original.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_provider_current_withdrawal_and_corruption_never_release_cached_rows()
-> anyhow::Result<()> {
    let (original, primary, _retention, registration) = preregistered().await?;
    let trust_time = primary.at - 124;
    let objective = primary.rule.objective_digest;
    drop(primary);
    for mutation in ["withdraw", "source-bytes", "ledger-bytes", "rollback"] {
        let mut b = BFixture::new("original-B", objective, trust_time)?;
        b.populate(&original, ObservationMode::Complete, /*changed_candidate_action*/ false).await?;
        let config = b.config(&original, &registration)?;
        let mut cohort = CohortAt::read(b.owners(), config, b.at)?;
        let original_manifest = cohort.current()?;
        let mut restore = None;
        match mutation {
            "withdraw" => b.withdraw_target()?,
            "source-bytes" => restore = Some(b.corrupt_source()?),
            "ledger-bytes" => {
                use std::io::Write;
                let path = b.root.join("positive-ledger");
                let bytes = fs::read(&path)?;
                let mut changed = bytes.clone();
                changed[0] ^= 1;
                let mut file = OpenOptions::new().write(true).open(&path)?;
                file.write_all(&changed)?;
                file.sync_all()?;
                restore = Some((path, bytes));
            }
            "rollback" => cohort.at -= 1,
            _ => unreachable!(),
        }
        assert!(cohort.current().is_err(), "{mutation}");
        if let Some((path, bytes)) = restore {
            use std::io::Write;
            assert_eq!(fs::metadata(&path)?.len(), bytes.len() as u64);
            let mut file = OpenOptions::new().write(true).open(&path)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            assert_eq!(fs::read(path)?, bytes);
        }
        cohort.at = b.at;
        assert!(matches!(cohort.current(), Err(OriginalCircuitEvaluationProviderErrorV1::Indeterminate)),
            "{mutation}");
        assert_eq!(cohort.original.observed_manifest_digest()?, original_manifest);
        // Historical metadata may remain available; it cannot restore release.
        assert!(ProviderPlanFixture::new(
            &cohort.original, &b.rule, &BFixture::training(&original)?,
            BFixture::original_manifests(&original),
        ).and_then(|runner| cohort.consume(runner.plan).map_err(Into::into)).is_err());
    }
    original.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_evaluation_provider_refuses_missing_outcomes_renewal_and_zero_support()
-> anyhow::Result<()> {
    let (original, primary, _retention, registration) = preregistered().await?;
    let trust_time = primary.at - 124;
    let objective = primary.rule.objective_digest;
    drop(primary);
    for mode in [ObservationMode::MissingLast, ObservationMode::WrongUnitLast] {
        let mut b = BFixture::new("original-B", objective, trust_time)?;
        b.populate(&original, mode, /*changed_candidate_action*/ false).await?;
        let config = b.config(&original, &registration)?;
        let bytes = b.source_bytes()?;
        assert!(CohortAt::read(b.owners(), config, b.at).is_err());
        assert_eq!(b.source_bytes()?, bytes);
    }
    for mutation in ["freeze-renewal", "training-renewal", "expired-window"] {
        let mut b = BFixture::new("original-B", objective, trust_time)?;
        b.populate(&original, ObservationMode::Complete, /*changed_candidate_action*/ false).await?;
        let config = b.config(&original, &registration)?;
        let mut cohort = CohortAt::read(b.owners(), config, b.at)?;
        let before = cohort.bytes()?;
        if mutation == "expired-window" {
            cohort.at = cohort.original_config().training_evidence.expires_at;
        } else {
            let mut signed = if mutation == "freeze-renewal" {
                cohort.original_config().freeze_evidence.clone()
            } else {
                cohort.original_config().training_evidence.clone()
            };
            signed.expires_at += 1;
            signed.evidence_id = id(&format!("valid-original-{mutation}"));
            signed.signature = SigningKey::from_bytes(&[if mutation == "freeze-renewal" { 42 } else { 41 }; 32])
                .sign(&signed.signing_bytes()).to_bytes();
            // Signature and payload are valid; the complete original byte pin
            // changes. No new body, label or corrupt signature is substituted.
            cohort.validate_signature(&signed, /*freeze*/ mutation == "freeze-renewal")?;
            if mutation == "freeze-renewal" {
                cohort.resign_freeze(signed);
            } else {
                cohort.resign_training(signed);
            }
        }
        let rejected = cohort.current();
        if mutation == "expired-window" {
            assert!(matches!(rejected, Err(OriginalCircuitEvaluationProviderErrorV1::Evidence(_))));
        } else {
            assert!(matches!(rejected, Err(OriginalCircuitEvaluationProviderErrorV1::Binding(
                "same exact original cohort and signatures"
            ))), "{mutation}: {rejected:?}");
        }
        assert!(matches!(cohort.current(), Err(OriginalCircuitEvaluationProviderErrorV1::Indeterminate)));
        assert_eq!(cohort.bytes()?, before);
    }
    let mut b = BFixture::new("original-B", objective, trust_time)?;
    b.populate(&original, ObservationMode::Complete, /*changed_candidate_action*/ true).await?;
    let config = b.config(&original, &registration)?;
    let cohort = CohortAt::read(b.owners(), config, b.at)?;
    let mut runner = ProviderPlanFixture::new(
        &cohort.original, &b.rule, &BFixture::training(&original)?,
        BFixture::original_manifests(&original),
    )?;
    let before = runner.bytes();
    let mut provider = cohort.consume(runner.plan.clone())?;
    assert!(matches!(runner.run(&mut provider),
        Err(crate::CellEvaluationErrorV1::Product(ProductEvaluationError::Temporal(
            TemporalEvaluationError::Confidence(ClusterConfidenceError::Ope(OpeError::UnsupportedAction))
        )))));
    assert_eq!((provider.manifest_calls, provider.releases), (1, 1));
    assert_ne!(runner.bytes(), before);
    let consumed = runner.bytes();
    assert!(runner.run(&mut provider).is_err());
    assert_eq!(provider.releases, 1);
    assert_eq!(runner.bytes(), consumed);
    original.finish().await
}
