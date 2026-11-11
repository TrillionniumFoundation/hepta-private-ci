//! The actual native batch fixes a single immutable initial Root profile.

use super::*;

impl CellQ24PreparedLearningV1 {
    pub(super) fn from_original(
        config: CellQ24LearningPreparationConfigV1,
        ledger: Arc<Mutex<LedgerWriter>>,
        tasks: Vec<CellQ24DatasetTaskV1>,
        frozen: CellQ24FrozenDatasetV1,
    ) -> Result<Self, Error> {
        let publication = require_configuration(&config, &tasks)?;
        if frozen.receipt.snapshot.snapshot_id != config.snapshot_id
            || frozen.receipt.snapshot.objective_digest != config.request.envelope.objective_digest
        {
            return Err(Error::Binding("original frozen Dataset identity"));
        }
        let batch = CellQ24TrainingBatchV1::from_original_dataset(
            ledger,
            frozen.snapshot.clone(),
            frozen.receipt.clone(),
            frozen.authorization.clone(),
            config.projection.clone(),
            tasks,
        )?;
        batch.require_original_dataset_provenance()?;
        if batch.rows() > config.request.budget.maximum_dataset_rows
            || batch.encoded().len() as u64 > config.request.budget.maximum_dataset_bytes
            || u64::from(batch.rows()) * u64::from(config.rule.epochs)
                > config.request.budget.maximum_training_steps
        {
            return Err(Error::Binding("original Dataset and training budget"));
        }
        let update_rule = cell_q24_single_head_update_rule_v1(
            &config.request.selected_bundle,
            config.head,
            config.rule.digest(&batch)?,
        )?;
        let scope = FrozenLearningScopeV2::freeze(
            &config.request,
            &config.owners,
            LearningUpdateScopeV2::Cell,
            update_rule,
        )?;
        let initial =
            LearningIterationCoordinatorV1::new(config.request.clone(), config.owners.clone())?
                .snapshot()
                .clone();
        let completed = publication
            .history_digest()
            .as_str()
            .parse::<Digest32>()
            .map_err(|_| Error::Binding("original completed history digest"))?;
        let episode = publication.publication_digest();
        let experience_evidence = Digest32::of_parts(&[
            b"hepta.agentd.original-q24-experience-facts.v1\0",
            initial.head_digest.as_array(),
            scope.binding().as_array(),
            episode.as_array(),
            completed.as_array(),
            cell_q24_dataset_run_snapshot_digest_v1(&publication).as_array(),
        ]);
        let dataset_evidence = Digest32::of_parts(&[
            b"hepta.agentd.original-q24-dataset-facts.v1\0",
            experience_evidence.as_array(),
            frozen.receipt.snapshot.dataset_digest.as_array(),
            frozen.receipt.revocation_cut_digest.as_array(),
            frozen.authorization.payload_digest.as_array(),
            &frozen.authorization.signing_bytes(),
            &frozen.authorization.signature,
            batch.digest().as_array(),
            &batch.rows().to_le_bytes(),
            &(batch.encoded().len() as u64).to_le_bytes(),
        ]);
        let facts = CellQ24PreparedLearningFactsV1 {
            experience: LearningIterationObservationV1::Experience {
                episode_digest: episode,
                completed_task_receipt: completed,
            },
            dataset: LearningIterationObservationV1::Dataset {
                snapshot_digest: frozen.receipt.snapshot.dataset_digest,
                episode_digest: episode,
                withdrawal_frontier: frozen.receipt.revocation_cut_digest,
                rows: batch.rows(),
                bytes: batch.encoded().len() as u64,
            },
            experience_evidence,
            dataset_evidence,
        };
        let prepared: CellQ24PreparedLearningV1 = Self {
            config,
            batch,
            frozen,
            initial,
            scope,
            facts,
        };
        prepared.revalidate_source()?;
        Ok(prepared)
    }

    /// Reacquire actual original capabilities from the host, then compare the
    /// retained empty initial/scope. No refreeze, signature or deadline renewal.
    pub fn recover(
        config: CellQ24LearningPreparationConfigV1,
        ledger: Arc<Mutex<LedgerWriter>>,
        tasks: Vec<CellQ24DatasetTaskV1>,
        frozen: CellQ24FrozenDatasetV1,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<Self, Error> {
        let prepared = Self::from_original(config, ledger, tasks, frozen)?;
        prepared.require_initial(initial, scope)?;
        Ok(prepared)
    }

    pub fn initial(&self) -> &LearningIterationSnapshotV1 {
        &self.initial
    }
    pub fn scope(&self) -> &FrozenLearningScopeV2 {
        &self.scope
    }
    pub fn frozen_dataset(&self) -> &CellQ24FrozenDatasetV1 {
        &self.frozen
    }

    pub fn revalidate_source(&self) -> Result<(), Error> {
        self.batch.require_original_dataset_provenance()?;
        Ok(())
    }

    pub fn read_validated_facts(&self) -> Result<CellQ24PreparedLearningFactsV1, Error> {
        self.revalidate_source()?;
        let facts = self.facts.clone();
        self.revalidate_source()?;
        Ok(facts)
    }

    pub fn require_initial(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        self.revalidate_source()?;
        if initial != &self.initial || scope != &self.scope {
            return Err(Error::Binding(
                "original empty initial and frozen row scope",
            ));
        }
        Ok(())
    }

    pub fn root_profile(
        &self,
        identity: &AgentdIdentity,
        original_writer_proof: [u8; 32],
    ) -> Result<HostAuthorityLearningProfileV1, Error> {
        if now()? >= self.initial.request.envelope.expiry_unix_seconds {
            return Err(Error::Binding("new Root enrollment deadline"));
        }
        self.revalidate_source()?;
        let rule = cell_q24_single_head_update_rule_v1(
            &self.config.request.selected_bundle,
            self.config.head,
            self.config.rule.digest(&self.batch)?,
        )?;
        let profile = HostAuthorityLearningProfileV1::new_scoped_v2(
            identity,
            original_writer_proof,
            self.initial.request.clone(),
            self.initial.owners.clone(),
            LearningUpdateScopeV2::Cell,
            rule,
        )?;
        self.require_profile(&profile, identity, original_writer_proof)?;
        Ok(profile)
    }

    pub(crate) fn require_profile(
        &self,
        profile: &HostAuthorityLearningProfileV1,
        identity: &AgentdIdentity,
        original_writer_proof: [u8; 32],
    ) -> Result<(), Error> {
        let initial = profile.require_binding(
            identity,
            &Digest32::from_array(original_writer_proof).to_string(),
        )?;
        let scope = profile
            .frozen_scope(&initial)?
            .ok_or(Error::Binding("scoped Root profile required"))?;
        self.require_initial(&initial, &scope)
    }

    /// The aggregate authenticates the original Observer receipts separately.
    /// This checks their exact observed material before handing the private
    /// source capability to the original durable trainer.
    pub fn training_material(
        &self,
        dataset: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
    ) -> Result<CellQ24PreparedTrainingMaterialV1, Error> {
        let facts = self.read_validated_facts()?;
        if scope != self.scope
            || dataset.request != self.initial.request
            || dataset.owners != self.initial.owners
            || dataset.receipts.len() != 2
            || dataset.receipts[0].observation != facts.experience
            || dataset.receipts[1].observation != facts.dataset
            || dataset.receipts[0].evidence_digest != facts.experience_evidence
            || dataset.receipts[1].evidence_digest != facts.dataset_evidence
        {
            return Err(Error::Binding(
                "original Experience and Dataset observations",
            ));
        }
        let plan = CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
            dataset,
            scope,
            Arc::clone(&self.config.baseline),
            self.config.head,
            self.config.rule.digest(&self.batch)?,
        )?;
        self.revalidate_source()?;
        Ok(CellQ24PreparedTrainingMaterialV1 {
            plan,
            batch: self.batch.clone(),
            rule: self.config.rule,
        })
    }
}
