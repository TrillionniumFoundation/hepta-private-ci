//! Actual member readback mechanisms, not ordinary B deployment or gain.
//! Both cohorts use real Source/Cell/independent Ledger and signed Outcomes;
//! product declarations, credentials, costs and future B clocks are fixtures.
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::io::Write as _;

use super::*;
use crate::OriginalCellEvaluationPanelErrorV1;
use crate::OriginalCellEvaluationPanelOwnerV1;
use crate::OriginalCellEvaluationPanelReadbackV1;
use crate::OriginalCellEvaluationQualificationErrorV1;
use crate::neuron_cell_evaluation::tests::original_provider::panel_members::PanelMemberFixture;

type Panel = OriginalCellEvaluationPanelOwnerV1<
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;

enum TrainingPeer {
    Original,
    RenewedRetention,
}

struct PanelFixture {
    panel: Panel,
    original: PositiveFixture,
    primary_b: BFixture,
    retention_b: BFixture,
    primary: PanelMemberFixture,
    retention: PanelMemberFixture,
    at: u64,
}

async fn completed_member(
    b: &mut BFixture,
    original: &PositiveFixture,
    registration: &crate::OriginalCellEvaluationPanelRegistrationV1,
    retention_receipt_digests: Vec<Digest32>,
) -> anyhow::Result<PanelMemberFixture> {
    b.populate(
        original,
        ObservationMode::Complete,
        /*changed_candidate_action*/ false,
    )
    .await?;
    let config = b.config(original, registration)?;
    let cohort = CohortAt::read(b.owners(), config, b.at)?;
    let training = BFixture::training(original)?;
    let runner = ProviderPlanFixture::for_panel(
        &cohort.original,
        &b.rule,
        &training,
        BFixture::original_manifests(original),
    )?;
    let provider = cohort.consume(runner.plan.clone())?;
    PanelMemberFixture::complete(
        runner,
        provider,
        &original.initial,
        training,
        original.config.training_evidence.clone(),
        &original.config.scope,
        &original.credentials.generator,
        &original.credentials.evaluator,
        original.config.verifier.clone(),
        retention_receipt_digests,
    )
    .await
}

impl PanelFixture {
    fn completed(peer: TrainingPeer) -> impl std::future::Future<Output = anyhow::Result<Self>> {
        Self::completed_for_publication(peer, PublicationMode::AdoptCandidate)
    }

    fn completed_for_publication(
        peer: TrainingPeer,
        publication: PublicationMode,
    ) -> impl std::future::Future<Output = anyhow::Result<Self>> {
        // Keep the complete panel construction future out of enclosing tests.
        // Returning it directly also avoids an extra async forwarding frame.
        Box::pin(async move {
            let (original, mut primary_b, mut retention_b, registration) =
                Box::pin(preregistered_for_publication(publication)).await?;
            assert_eq!(primary_b.at, retention_b.at);
            let at = primary_b.at;
            // Actual retention completes first. Only its original publication
            // digest enters the primary B's signed product declaration.
            let mut retention = Box::pin(completed_member(
                &mut retention_b,
                &original,
                &registration,
                Vec::new(),
            ))
            .await?;
            let retained = retention.qualification.product().evidence_digest;
            let mut primary = Box::pin(completed_member(
                &mut primary_b,
                &original,
                &registration,
                vec![retained],
            ))
            .await?;
            if matches!(peer, TrainingPeer::RenewedRetention) {
                let renewed = original.evaluation.renewed_qualification_training()?;
                assert_ne!(renewed, retention.config.training_evidence);
                retention.renewed_training_peer(renewed)?;
            }
            let panel = Panel::from_original_owners(
                registration,
                primary.take_original_member(),
                vec![retention.take_original_member()],
            )?;
            Ok(Self {
                panel,
                original,
                primary_b,
                retention_b,
                primary,
                retention,
                at,
            })
        })
    }

    async fn read(
        &mut self,
    ) -> Result<OriginalCellEvaluationPanelReadbackV1, OriginalCellEvaluationPanelErrorV1> {
        self.panel.fixture_current(self.at).await
    }

    fn bytes(&mut self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = self.primary.bytes()?;
        bytes.extend(self.retention.bytes()?);
        bytes.extend(self.primary_b.all_source_bytes()?);
        bytes.extend(self.retention_b.all_source_bytes()?);
        bytes.extend(self.panel.fixture_cohort_bytes()?);
        Ok(bytes)
    }

    async fn finish(self) -> anyhow::Result<[usize; 2]> {
        drop(self.panel);
        let counts = [self.primary.finish()?, self.retention.finish()?];
        drop(self.primary_b);
        drop(self.retention_b);
        self.original.finish().await?;
        Ok(counts)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_panel_reads_actual_b_and_retention_with_full_original_signatures()
-> anyhow::Result<()> {
    let mut fixture = PanelFixture::completed(TrainingPeer::Original).await?;
    let before = fixture.bytes()?;
    let first = fixture.read().await?;
    assert_eq!(first.retention().len(), 1);
    assert_eq!(
        first.training_evidence(),
        &fixture.original.config.training_evidence
    );
    assert_eq!(
        first.primary().product_evidence(),
        &fixture.primary.config.product_evidence
    );
    assert_eq!(
        first.primary().execution_evidence(),
        &fixture.primary.config.execution_evidence
    );
    assert_eq!(
        first.retention()[0].product_evidence(),
        &fixture.retention.config.product_evidence
    );
    assert_eq!(
        first.retention()[0].execution_evidence(),
        &fixture.retention.config.execution_evidence
    );
    assert_eq!(
        first.primary().qualification(),
        &fixture.primary.qualification
    );
    assert_eq!(
        first.retention()[0].qualification(),
        &fixture.retention.qualification
    );
    assert_eq!(
        first
            .primary()
            .qualification()
            .product()
            .decision
            .decision
            .disposition,
        IndependentEvaluationDispositionV1::Ineligible
    );
    assert_eq!(first.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(fixture.read().await?, first);
    assert_eq!(fixture.bytes()?, before);
    // Each member first had two original Qualification reads, then four
    // more per full panel read. Equality never substitutes a cached response.
    assert_eq!(fixture.finish().await?, [10, 10]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_panel_withdrawal_or_restored_source_bytes_permanently_fences_readback()
-> anyhow::Result<()> {
    for mutation in ["withdrawal", "restore-physical-source"] {
        let mut fixture = PanelFixture::completed(TrainingPeer::Original).await?;
        fixture.read().await?;
        let restore = if mutation == "withdrawal" {
            fixture.retention_b.withdraw_target()?;
            None
        } else {
            Some(fixture.retention_b.corrupt_source()?)
        };
        let after_mutation = fixture.bytes()?;
        assert!(
            matches!(
                fixture.read().await,
                Err(OriginalCellEvaluationPanelErrorV1::Cohort(_))
            ),
            "{mutation} must fail in the original B source capability"
        );
        assert_eq!(fixture.bytes()?, after_mutation);
        if let Some((path, bytes)) = restore {
            assert_eq!(std::fs::metadata(&path)?.len(), bytes.len() as u64);
            let mut file = std::fs::OpenOptions::new().write(true).open(&path)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            assert_eq!(std::fs::read(&path)?, bytes);
        }
        let retained = fixture.bytes()?;
        assert!(matches!(
            fixture.read().await,
            Err(OriginalCellEvaluationPanelErrorV1::CommitUncertain)
        ));
        assert_eq!(fixture.bytes()?, retained);
        let counts = fixture.finish().await?;
        assert!(counts.into_iter().all(|count| count >= 2));
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_panel_refuses_valid_renewed_training_without_replacing_member_signatures()
-> anyhow::Result<()> {
    let mut fixture = PanelFixture::completed(TrainingPeer::RenewedRetention).await?;
    let before = fixture.bytes()?;
    assert!(matches!(
        fixture.read().await,
        Err(OriginalCellEvaluationPanelErrorV1::Qualification(
            OriginalCellEvaluationQualificationErrorV1::Binding(
                "changed original Qualification Training signature"
            )
        ))
    ));
    assert_eq!(fixture.bytes()?, before);
    assert!(matches!(
        fixture.read().await,
        Err(OriginalCellEvaluationPanelErrorV1::CommitUncertain)
    ));
    assert_eq!(fixture.bytes()?, before);
    let [primary, retention] = fixture.finish().await?;
    assert_eq!([primary, retention], [4, 1]);
    Ok(())
}

#[path = "circuit_original_evaluation_host_tests.rs"]
mod evaluation_host;
