//! Original host custody for deferred Training, without future Dataset data.
use super::*;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCellQ24MaterialSourceConnectionV1;
use crate::OriginalCellQ24TrainingBootstrapConfigV1;
use crate::OriginalCellQ24TrainingBootstrapCustodyV1;

impl MaterialCommandFixture {
    pub(crate) fn training_configuration(&self) -> OriginalCellQ24TrainingBootstrapConfigV1 {
        OriginalCellQ24TrainingBootstrapConfigV1 {
            material: self.config.clone(),
            optimizer: self.optimizer,
            generator: self.generator.clone(),
            maximum_signature_lifetime_seconds: 300,
        }
    }

    pub(crate) fn training_baseline(&self) -> Arc<LoadedCellQ24ModelV1> {
        Arc::clone(&self.baseline)
    }

    pub(crate) fn fresh_training_custody(
        &self,
        material_source: OriginalCellQ24MaterialSourceConnectionV1,
        experience: LearningIterationEvidenceClientV1,
        dataset: LearningIterationEvidenceClientV1,
    ) -> anyhow::Result<
        OriginalCellQ24TrainingBootstrapCustodyV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    > {
        self.training_custody(material_source, experience, dataset, /*create*/ true)
    }

    pub(crate) fn recovered_training_custody(
        &self,
        material_source: OriginalCellQ24MaterialSourceConnectionV1,
        experience: LearningIterationEvidenceClientV1,
        dataset: LearningIterationEvidenceClientV1,
    ) -> anyhow::Result<
        OriginalCellQ24TrainingBootstrapCustodyV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    > {
        self.training_custody(material_source, experience, dataset, /*create*/ false)
    }

    fn training_custody(
        &self,
        material_source: OriginalCellQ24MaterialSourceConnectionV1,
        experience: LearningIterationEvidenceClientV1,
        dataset: LearningIterationEvidenceClientV1,
        create: bool,
    ) -> anyhow::Result<
        OriginalCellQ24TrainingBootstrapCustodyV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    > {
        let witness = |name: &str| -> anyhow::Result<FileAnchorWitnessStore> {
            Ok(FileAnchorWitnessStore::open(
                opened(&self.root, name, create)?,
                JournalScope {
                    scope_digest: self.config.scope.binding(),
                    objective_digest: self.config.initial.request.envelope.objective_digest,
                },
                Generation::new(1)?,
                64,
            )?)
        };
        Ok(OriginalCellQ24TrainingBootstrapCustodyV1 {
            native_file: opened(&self.root, "deferred-native", create)?,
            native_witness: witness("deferred-native-witness")?,
            receipt_file: opened(&self.root, "deferred-receipts", create)?,
            receipt_witness: witness("deferred-receipt-witness")?,
            generator_key: SigningKey::from_bytes(&[1; 32]),
            baseline: Arc::clone(&self.baseline),
            material_source,
            experience,
            dataset,
        })
    }

    pub(crate) fn readonly_training_receipt(&self) -> anyhow::Result<File> {
        Ok(File::open(self.root.join("deferred-receipts"))?)
    }

    pub(crate) fn training_bytes(&self) -> anyhow::Result<[Vec<u8>; 4]> {
        Ok([
            fs::read(self.root.join("deferred-native"))?,
            fs::read(self.root.join("deferred-native-witness"))?,
            fs::read(self.root.join("deferred-receipts"))?,
            fs::read(self.root.join("deferred-receipt-witness"))?,
        ])
    }
}


impl MaterialCommandFixture {
    pub(crate) fn renewed_material_configuration(&self)
    -> anyhow::Result<OriginalCellQ24MaterialReceiptConfigV1> {
        use ed25519_dalek::Signer;
        let mut config = self.config.clone();
        config.freeze_evidence.issued_at += 1;
        config.freeze_evidence.expires_at += 1;
        config.freeze_evidence.signature = SigningKey::from_bytes(&[3; 32])
            .sign(&config.freeze_evidence.signing_bytes()).to_bytes();
        let payload = dataset_freeze_signing_payload_v2(
            &self.ledger.lock().expect("original fixture ledger").snapshot()?,
            &config.freeze_plan,
        )?;
        config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator, &config.freeze_evidence, &payload, binding::now()?,
        )?;
        Ok(config)
    }
}
