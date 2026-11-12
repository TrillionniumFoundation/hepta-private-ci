//! Original task capture, signed freeze and explicit retained-cut recovery.

use super::*;

impl CellQ24DatasetFreezePreparationV1 {
    /// Product composition of the original typed authorizer and materializer.
    /// Pending remains unresolved; a completed authorization is never renewed.
    pub fn authorize_and_materialize(
        self,
        owner: &mut OriginalCellQ24DatasetFreezeOwnerV1<impl AnchorWitnessStore>,
    ) -> Result<CellQ24PreparedLearningV1, OriginalCellQ24DatasetFreezeErrorV1> {
        let signed = owner.authorize_or_readback(&self)?;
        Ok(self.materialize_retained(signed)?)
    }

    /// The one-task ordinary path captures the original committed source and
    /// Cell decision directly. No caller-projected input or target is accepted.
    pub fn capture_original(
        config: CellQ24LearningPreparationConfigV1,
        ledger: Arc<Mutex<LedgerWriter>>,
        source: crate::CircuitTaskSourceReadbackV1<impl AnchorWitnessStore + Send + 'static>,
        cell: &crate::PublishedCircuitCellOwnerV1<impl AnchorWitnessStore>,
        identity: AgentdIdentity,
    ) -> Result<Self, Error> {
        let task = CellQ24DatasetTaskV1::capture(
            source,
            cell,
            identity,
            config.request.source_run_id.clone(),
        )?;
        Self::capture(config, ledger, vec![task])
    }

    /// Capture one current witnessed ledger cut after the ordinary task sealed.
    pub fn capture(
        config: CellQ24LearningPreparationConfigV1,
        ledger: Arc<Mutex<LedgerWriter>>,
        tasks: Vec<CellQ24DatasetTaskV1>,
    ) -> Result<Self, Error> {
        require_configuration(&config, &tasks)?;
        if now()? >= config.request.envelope.expiry_unix_seconds {
            return Err(Error::Binding("new preparation deadline"));
        }
        let (snapshot, frontier) = {
            let owner = ledger.lock().map_err(|_| Error::Binding("ledger lock"))?;
            (owner.snapshot()?, owner.witness_frontier()?)
        };
        let preparation = Self {
            config,
            ledger,
            tasks,
            snapshot,
            frontier,
        };
        preparation.signing_payload()?;
        Ok(preparation)
    }

    /// Restore the retained preparation descriptor with actual original owners.
    /// A historical prefix can be read, but cannot authorize a new freeze after
    /// the ledger advances. The original signature journal decides readback.
    pub fn recover(
        config: CellQ24LearningPreparationConfigV1,
        ledger: Arc<Mutex<LedgerWriter>>,
        tasks: Vec<CellQ24DatasetTaskV1>,
        snapshot: LedgerSnapshot,
    ) -> Result<Self, Error> {
        let frontier = ledger
            .lock()
            .map_err(|_| Error::Binding("ledger lock"))?
            .witness_frontier()?;
        let preparation: CellQ24DatasetFreezePreparationV1 = Self {
            config,
            ledger,
            tasks,
            snapshot,
            frontier,
        };
        preparation.revalidate_source()?;
        Ok(preparation)
    }

    pub fn original_snapshot(&self) -> &LedgerSnapshot {
        &self.snapshot
    }

    /// A preparation identity, deliberately distinct from the later Root scope.
    /// Every field is fixed before signing; SGD(batch) is not fabricated here.
    pub fn identity(&self) -> Result<Digest32, Error> {
        self.revalidate_source()?;
        let initial = LearningIterationCoordinatorV1::new(
            self.config.request.clone(),
            self.config.owners.clone(),
        )?;
        let payload = dataset_freeze_signing_payload_v2(&self.snapshot, &self.plan()?)?;
        let ledger = self
            .ledger
            .lock()
            .map_err(|_| Error::Binding("ledger lock"))?;
        Ok(crate::original_q24_dataset_preparation_identity_v1(
            initial.snapshot().head_digest,
            ledger.binding_digest(),
            &payload,
            self.config.baseline.effective_weights_digest(),
            self.config.head,
            self.config.rule,
        ))
    }

    pub fn revalidate_source(&self) -> Result<(), Error> {
        require_configuration(&self.config, &self.tasks)?;
        let ledger = self
            .ledger
            .lock()
            .map_err(|_| Error::Binding("ledger lock"))?;
        let current = ledger.snapshot()?;
        let frontier = ledger.witness_frontier()?;
        if current.records().len() > 4096
            || self.snapshot.records().len() > 4096
            || current.records().len() as u64 != frontier.anchor.sequence
            || current.head_digest != frontier.anchor.chain_digest
            || !current.records().starts_with(self.snapshot.records())
        {
            return Err(Error::Binding("original preparation ledger prefix"));
        }
        require_configuration(&self.config, &self.tasks)?;
        if ledger.snapshot()? != current || ledger.witness_frontier()? != frontier {
            return Err(Error::Binding("original preparation changed during read"));
        }
        Ok(())
    }

    /// The existing Evaluator signs these exact bytes with its original key.
    /// A changed ledger cut requires a distinct explicit preparation attempt.
    pub fn signing_payload(&self) -> Result<Vec<u8>, Error> {
        require_configuration(&self.config, &self.tasks)?;
        let owner = self
            .ledger
            .lock()
            .map_err(|_| Error::Binding("ledger lock"))?;
        self.require_frozen_cut(&owner)?;
        Ok(dataset_freeze_signing_payload_v2(
            &self.snapshot,
            &self.plan()?,
        )?)
    }

    pub fn materialize(
        self,
        authorization: SignedLearningEvidenceV1,
    ) -> Result<CellQ24PreparedLearningV1, Error> {
        if now()? >= self.config.request.envelope.expiry_unix_seconds {
            return Err(Error::Binding("new preparation deadline"));
        }
        let receipt = {
            let owner = self
                .ledger
                .lock()
                .map_err(|_| Error::Binding("ledger lock"))?;
            self.require_frozen_cut(&owner)?;
            owner.freeze_dataset(self.plan()?, &authorization, now()?)?
        };
        CellQ24PreparedLearningV1::from_original(
            self.config,
            self.ledger,
            self.tasks,
            CellQ24FrozenDatasetV1 {
                snapshot: self.snapshot,
                receipt,
                authorization,
            },
        )
    }

    /// Explicit recovery of an already signed original freeze. Unrelated later
    /// appends do not rewrite that cut; current withdrawal/correction still fail.
    pub fn materialize_retained(
        self,
        authorization: SignedLearningEvidenceV1,
    ) -> Result<CellQ24PreparedLearningV1, Error> {
        let frozen = self.validate_authorization(&authorization)?;
        CellQ24PreparedLearningV1::from_original(self.config, self.ledger, self.tasks, frozen)
    }

    pub(super) fn validate_authorization(
        &self,
        authorization: &SignedLearningEvidenceV1,
    ) -> Result<CellQ24FrozenDatasetV1, Error> {
        self.revalidate_source()?;
        let receipt = {
            let owner = self
                .ledger
                .lock()
                .map_err(|_| Error::Binding("ledger lock"))?;
            let payload = dataset_freeze_signing_payload_v2(&self.snapshot, &self.plan()?)?;
            let verified = owner.verifier().verify(
                LearningEvidenceRoleV1::Evaluator,
                authorization,
                &payload,
                now()?,
            )?;
            freeze_dataset_from_ledger(
                &self.snapshot,
                self.plan()?,
                verified.principal().clone(),
                now()?,
            )?
        };
        let frozen = CellQ24FrozenDatasetV1 {
            snapshot: self.snapshot.clone(),
            receipt,
            authorization: authorization.clone(),
        };
        let batch: CellQ24TrainingBatchV1 = CellQ24TrainingBatchV1::from_original_dataset(
            Arc::clone(&self.ledger),
            frozen.snapshot.clone(),
            frozen.receipt.clone(),
            authorization.clone(),
            self.config.projection.clone(),
            self.tasks.clone(),
        )?;
        batch.require_original_dataset_provenance()?;
        Ok(frozen)
    }

    pub(super) fn plan(&self) -> Result<DatasetFreezePlanV2, Error> {
        Ok(DatasetFreezePlanV2 {
            snapshot_id: self.config.snapshot_id.clone(),
            objective_digest: self.config.request.envelope.objective_digest,
            inclusion_policy_digest: self.config.projection.inclusion_policy_digest()?,
        })
    }

    fn require_frozen_cut(&self, owner: &LedgerWriter) -> Result<(), Error> {
        if owner.snapshot()? != self.snapshot
            || owner.witness_frontier()? != self.frontier
            || self.snapshot.records().len() > 4096
            || self.snapshot.records().len() as u64 != self.frontier.anchor.sequence
            || self.snapshot.head_digest != self.frontier.anchor.chain_digest
        {
            return Err(Error::Binding("original witnessed freeze cut changed"));
        }
        Ok(())
    }
}
