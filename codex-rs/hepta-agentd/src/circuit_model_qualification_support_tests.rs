//! Narrow test access to the actual independent Evaluation fixture. Synthetic
//! credentials remain explicit test metadata; all publication uses the owner.
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;

use pretty_assertions::assert_eq;

use super::*;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCellEvaluationQualificationErrorV1;

type Owner = OriginalCellEvaluationQualificationOwnerV1<FileAnchorWitnessStore>;
type Error = OriginalCellEvaluationQualificationErrorV1;
type PeerThread = std::thread::JoinHandle<anyhow::Result<usize>>;

impl EvaluationFixture {
    pub(crate) fn qualification_configuration(
        &self,
    ) -> OriginalCellEvaluationQualificationConfigV1 {
        self.qualification_config.clone()
    }

    pub(crate) fn qualification_peer(
        &self,
        signature: SignedLearningEvidenceV1,
    ) -> anyhow::Result<(LearningIterationEvidenceClientV1, PeerThread)> {
        fixture_original_receipt_client_until_close(
            self.initial.clone(),
            self.training
                .receipts
                .last()
                .expect("actual original Training")
                .clone(),
            self.verifier.clone(),
            signature,
        )
    }

    pub(crate) fn qualification_files(
        &self,
        name: &str,
        create: bool,
    ) -> anyhow::Result<(File, FileAnchorWitnessStore)> {
        let root = self.fixture.directory.path();
        let open = |name: &str| -> anyhow::Result<File> {
            let mut options = OpenOptions::new();
            options.read(true).write(true).mode(0o600);
            if create {
                options.create_new(true);
            }
            Ok(options.open(root.join(name))?)
        };
        let raw = open(name)?;
        let witness = FileAnchorWitnessStore::open(
            open(&format!("{name}-witness"))?,
            JournalScope {
                scope_digest: self.qualification_config.scope.binding(),
                objective_digest: self.verifier.objective_digest(),
            },
            Generation::new(1)?,
            64,
        )?;
        Ok((raw, witness))
    }

    pub(crate) fn qualification_bytes(&self, name: &str) -> anyhow::Result<[Vec<u8>; 2]> {
        let root = self.fixture.directory.path();
        Ok([
            std::fs::read(root.join(name))?,
            std::fs::read(root.join(format!("{name}-witness")))?,
        ])
    }

    pub(crate) fn qualification_overwrite(&self, name: &str, bytes: &[u8]) -> anyhow::Result<()> {
        let path = self.fixture.directory.path().join(name);
        assert_eq!(std::fs::metadata(&path)?.len(), bytes.len() as u64);
        let mut file = OpenOptions::new().write(true).open(path)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        Ok(())
    }

    pub(crate) fn qualification_original_file(&self, name: &str) -> anyhow::Result<Vec<u8>> {
        Ok(std::fs::read(self.fixture.directory.path().join(name))?)
    }

    pub(crate) fn drop_original_qualification(&mut self) {
        drop(self.qualification_owner.take());
    }

    pub(crate) fn recover_original_qualification(&mut self) -> anyhow::Result<()> {
        self.drop_original_qualification();
        let (file, witness) = self.qualification_files("positive-qualification", false)?;
        self.qualification_owner = Some(Owner::recover(
            file,
            witness,
            self.qualification_config.clone(),
        )?);
        Ok(())
    }

    fn qualification_sources<'a>(
        &'a mut self,
        trainer: &'a LearningIterationEvidenceClientV1,
    ) -> OriginalCellEvaluationQualificationSourcesV1<
        'a,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
    > {
        OriginalCellEvaluationQualificationSourcesV1 {
            runner: &mut self.fixture.runner,
            journals: CellEvaluationJournalsV1 {
                candidate: &self.fixture.candidate,
                fixed_expert: &self.fixture.fixed,
            },
            candidate_plan: &self.fixture.candidate_temporal,
            baseline_plan: &self.fixture.baseline_temporal,
            executions: &mut self.executions,
            trainer,
        }
    }

    pub(crate) async fn publish_qualification<W: AnchorWitnessStore>(
        &mut self,
        owner: &mut OriginalCellEvaluationQualificationOwnerV1<W>,
        trainer: &LearningIterationEvidenceClientV1,
    ) -> Result<CellEvaluationQualificationV1, Error> {
        owner
            .qualify_or_readback(self.qualification_sources(trainer))
            .await
    }

    pub(crate) async fn read_qualification<W: AnchorWitnessStore>(
        &mut self,
        owner: &mut OriginalCellEvaluationQualificationOwnerV1<W>,
        trainer: &LearningIterationEvidenceClientV1,
    ) -> Result<CellEvaluationQualificationV1, Error> {
        owner.readback(self.qualification_sources(trainer)).await
    }

    pub(crate) async fn read_original_qualification(
        &mut self,
        trainer: &LearningIterationEvidenceClientV1,
    ) -> Result<CellEvaluationQualificationV1, Error> {
        let mut owner = self
            .qualification_owner
            .take()
            .expect("original Qualification owner");
        let result = owner.readback(self.qualification_sources(trainer)).await;
        self.qualification_owner = Some(owner);
        result
    }

    pub(crate) fn qualification_provider_counts(&self) -> (u32, u32) {
        (self.fixture.provider.calls, self.fixture.provider.releases)
    }

    pub(crate) fn renewed_qualification_training(
        &self,
    ) -> anyhow::Result<SignedLearningEvidenceV1> {
        let mut signature = self.qualification_config.training_evidence.clone();
        signature.expires_at = signature.expires_at.checked_add(1).expect("fixture expiry");
        signature.evidence_id = id("explicit-test-renewed-Qualification-Training");
        signature.signature = SigningKey::from_bytes(&[41; 32])
            .sign(&signature.signing_bytes())
            .to_bytes();
        self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &signature,
            &learning_iteration_receipt_signing_bytes_v1(
                self.training.receipts.last().expect("original Training"),
            )?,
            now()?,
        )?;
        Ok(signature)
    }

    pub(crate) fn renewed_qualification_product(
        &self,
        generator: bool,
    ) -> anyhow::Result<SignedEvaluationEvidenceV1> {
        let mut evidence = self.evidence.clone();
        let (signature, seed, role, payload) = if generator {
            (
                &mut evidence.generator_plan,
                41,
                LearningEvidenceRoleV1::Generator,
                self.receipt
                    .plan()
                    .product_plan()
                    .frozen_plan
                    .plan_digest
                    .as_array()
                    .to_vec(),
            )
        } else {
            let bundle = self
                .fixture
                .runner
                .qualification_bundle(&self.receipt, &self.context)?;
            (
                &mut evidence.evaluator_bundle,
                42,
                LearningEvidenceRoleV1::Evaluator,
                evaluation_signing_payload_v2(
                    &bundle,
                    &self.receipt.plan().product_plan().metric_roles,
                )?,
            )
        };
        signature.expires_at = signature.expires_at.checked_add(1).expect("fixture expiry");
        signature.evidence_id = id("explicit-test-renewed-Qualification-Product");
        signature.signature = SigningKey::from_bytes(&[seed; 32])
            .sign(&signature.signing_bytes())
            .to_bytes();
        self.verifier.verify(role, signature, &payload, now()?)?;
        Ok(evidence)
    }
}
