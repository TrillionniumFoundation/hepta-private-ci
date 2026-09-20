//! Canonical durable owner runtime for neuron ticks.
//!
//! This is the product-facing owner path. It freezes the complete selected model
//! manifest, revalidates current lineage at every tick, prepares the exact
//! canonical result durably before the sparse checkpoint commit, records a
//! terminal operation marker after that commit, and only then advances the
//! independently retained recovery witness. Recovery reclassifies prepared
//! operations against the exact sparse checkpoint and never advances the witness
//! without re-admitting the lineage bound to that operation.

use std::fs::File;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::CalibrationObservationV1;
use crate::CalibrationPolicyV1;
use crate::JournalAnchor;
use crate::JournalError;
use crate::JournalScope;
use crate::NativeSparseProfileV1;
use crate::NeuronCalibrationArtifactV1;
use crate::NeuronResourceReceiptV1;
use crate::NeuronRuntimeConfigV1;
use crate::NeuronSignalReceiptV1;
use crate::NeuronTickInputV1;
use crate::NeuronTickReceiptV1;
use crate::ProtocolError;
use crate::RecoveryWitnessStore;
use crate::RuntimeScopeBindingV1;
use crate::SelectedNeuronModelManifestV1;
use crate::SignalFallbackReasonV1;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseJournal;
use crate::active_indices;
use crate::apply_calibration;
use crate::bound_runtime_profile_digest;
use crate::bound_sparse_config;
use crate::encode_neuron_tick_input_v1;
use crate::operation::FileRuntimeOperationJournal;
use crate::operation::PreparedRuntimeOperationV1;
use crate::operation::RuntimeOperationStateV1;
use crate::runtime::FrozenModelExecutor;
use crate::runtime::FrozenModelRequestV1;
use crate::runtime::LineagePolicy;
use crate::runtime::RuntimeError;
use crate::runtime::RuntimeTickObservationV1;
use crate::runtime::RuntimeTickResultV1;
use crate::runtime::witness_context_digest;
use crate::sparse_tick;

const MAX_OWNER_OPERATIONS: usize = 4096;

pub struct NeuronRuntimeHost<E, W, L>
where
    E: FrozenModelExecutor,
    W: RecoveryWitnessStore,
    L: LineagePolicy,
{
    config: NeuronRuntimeConfigV1,
    native: NativeSparseProfileV1,
    model_manifest: SelectedNeuronModelManifestV1,
    sparse_config: SparseConfig,
    config_digest: Digest32,
    scope: RuntimeScopeBindingV1,
    journal: SparseJournal,
    operations: FileRuntimeOperationJournal,
    executor: E,
    witness: W,
    lineage: L,
    witness_anchor: Option<JournalAnchor>,
    calibration_policy: CalibrationPolicyV1,
    calibration_artifact: Option<NeuronCalibrationArtifactV1>,
    poisoned: bool,
}

impl<E, W, L> NeuronRuntimeHost<E, W, L>
where
    E: FrozenModelExecutor,
    W: RecoveryWitnessStore,
    L: LineagePolicy,
{
    #[allow(clippy::too_many_arguments)]
    pub fn open(
        journal_file: File,
        operation_file: File,
        config: NeuronRuntimeConfigV1,
        native: NativeSparseProfileV1,
        model_manifest: SelectedNeuronModelManifestV1,
        scope: RuntimeScopeBindingV1,
        max_records: usize,
        executor: E,
        mut witness: W,
        mut lineage: L,
        calibration_policy: CalibrationPolicyV1,
        calibration_artifact: Option<NeuronCalibrationArtifactV1>,
        now_unix_micros: u64,
    ) -> Result<Self, RuntimeError> {
        let (config_digest, sparse_config) =
            validate_static_profile(&config, &native, &model_manifest, &scope)?;
        calibration_policy.digest()?;
        if now_unix_micros >= config.expires_at_unix_micros {
            return Err(RuntimeError::ConfigExpired);
        }
        require_model_lineage(&mut lineage, &model_manifest)?;
        if let Some(artifact) = calibration_artifact.as_ref() {
            artifact.validate()?;
            require_calibration_lineage(&mut lineage, artifact)?;
        }

        let context_digest = witness_context_digest(config_digest, &scope);
        let operations =
            FileRuntimeOperationJournal::open(operation_file, context_digest, MAX_OWNER_OPERATIONS)?;
        let witness_anchor = witness.current_anchor()?;

        let journal_scope = JournalScope {
            scope_digest: scope.scope_digest,
            objective_digest: scope.objective_digest,
        };
        let journal = match witness_anchor {
            Some(anchor) => SparseJournal::open_anchored(
                journal_file,
                sparse_config.clone(),
                journal_scope,
                max_records,
                anchor,
            )?,
            None => SparseJournal::open(
                journal_file,
                sparse_config.clone(),
                journal_scope,
                max_records,
            )?,
        };

        let mut host = Self {
            config,
            native,
            model_manifest,
            sparse_config,
            config_digest,
            scope,
            journal,
            operations,
            executor,
            witness,
            lineage,
            witness_anchor,
            calibration_policy,
            calibration_artifact,
            poisoned: false,
        };
        host.reconcile_recovered_state()?;
        Ok(host)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn open_with_genesis(
        journal_file: File,
        operation_file: File,
        config: NeuronRuntimeConfigV1,
        native: NativeSparseProfileV1,
        model_manifest: SelectedNeuronModelManifestV1,
        scope: RuntimeScopeBindingV1,
        max_records: usize,
        executor: E,
        mut witness: W,
        mut lineage: L,
        calibration_policy: CalibrationPolicyV1,
        calibration_artifact: Option<NeuronCalibrationArtifactV1>,
        genesis: SparseCheckpoint,
        now_unix_micros: u64,
    ) -> Result<Self, RuntimeError> {
        let (config_digest, sparse_config) =
            validate_static_profile(&config, &native, &model_manifest, &scope)?;
        calibration_policy.digest()?;
        if now_unix_micros >= config.expires_at_unix_micros {
            return Err(RuntimeError::ConfigExpired);
        }
        require_model_lineage(&mut lineage, &model_manifest)?;
        if let Some(artifact) = calibration_artifact.as_ref() {
            artifact.validate()?;
            require_calibration_lineage(&mut lineage, artifact)?;
        }

        let context_digest = witness_context_digest(config_digest, &scope);
        let operations =
            FileRuntimeOperationJournal::open(operation_file, context_digest, MAX_OWNER_OPERATIONS)?;
        let witness_anchor = witness
            .current_anchor()?
            .ok_or(RuntimeError::RotationRequiresAcknowledgedCheckpoint)?;
        let journal_scope = JournalScope {
            scope_digest: scope.scope_digest,
            objective_digest: scope.objective_digest,
        };
        let journal = SparseJournal::open_anchored_with_genesis(
            journal_file,
            sparse_config.clone(),
            journal_scope,
            max_records,
            witness_anchor,
            genesis,
        )?;
        let mut host = Self {
            config,
            native,
            model_manifest,
            sparse_config,
            config_digest,
            scope,
            journal,
            operations,
            executor,
            witness,
            lineage,
            witness_anchor: Some(witness_anchor),
            calibration_policy,
            calibration_artifact,
            poisoned: false,
        };
        host.reconcile_recovered_state()?;
        Ok(host)
    }

    pub fn tick(
        &mut self,
        input: NeuronTickInputV1,
        observation: RuntimeTickObservationV1,
    ) -> Result<RuntimeTickResultV1, RuntimeError> {
        if self.poisoned {
            return Err(RuntimeError::Poisoned);
        }
        let request_digest = request_digest(self.config_digest, &input)?;
        if let Some(record) = self.operations.record(input.tick_id.as_str()).cloned() {
            if record.prepared.request_digest != request_digest {
                return Err(RuntimeError::OperationConflict);
            }
            match record.state {
                RuntimeOperationStateV1::Committed => {
                    require_lineage_set(
                        &mut self.lineage,
                        &record.prepared.required_lineage,
                    )?;
                    return record.prepared.decode_result().map_err(Into::into);
                }
                RuntimeOperationStateV1::Prepared => {
                    require_lineage_set(
                        &mut self.lineage,
                        &record.prepared.required_lineage,
                    )?;
                    match self.journal.checkpoint_digest_at(record.prepared.sequence)? {
                        Some(digest) if digest == record.prepared.checkpoint_after => {
                            self.operations.mark_committed(
                                &record.prepared.operation_id,
                                record.prepared.request_digest,
                                record.prepared.checkpoint_after,
                                record.prepared.result_digest,
                            )?;
                            self.ensure_witness_for(&record.prepared)?;
                            return record.prepared.decode_result().map_err(Into::into);
                        }
                        None => {
                            self.operations.mark_aborted(
                                &record.prepared.operation_id,
                                record.prepared.request_digest,
                                record.prepared.checkpoint_after,
                                record.prepared.result_digest,
                            )?;
                        }
                        Some(_) => return Err(RuntimeError::OperationConflict),
                    }
                }
                RuntimeOperationStateV1::Aborted => {}
            }
        }

        if observation.now_unix_micros >= self.config.expires_at_unix_micros {
            return Err(RuntimeError::ConfigExpired);
        }
        if self.journal.remaining_records() == 0 {
            return Err(RuntimeError::RotationRequired);
        }

        let mut required_lineage = self.required_lineage_for_input(&input)?;
        require_lineage_set(&mut self.lineage, &required_lineage)?;
        let previous = self.journal.current()?.cloned();
        input.validate_for(&self.config, &self.scope, previous.as_ref())?;

        let model_request = FrozenModelRequestV1 {
            tick_id: input.tick_id.clone(),
            subject_id: input.subject_id.clone(),
            config_digest: self.config_digest,
            objective_digest: input.objective_digest,
            ndu_snapshot_digest: input.ndu_snapshot_digest,
            input_feature_digest: input.input_feature_digest,
            feature_vector_q24: input.feature_vector_q24.clone(),
        };
        let started = Instant::now();
        let execution = self
            .executor
            .execute(&model_request)
            .map_err(RuntimeError::Model)?;
        execution.validate_for(&self.config)?;
        self.model_manifest.validate_execution(&execution)?;
        // Close the model-I/O race for every authoritative input, not only the
        // selected model tuple. A revocation during execution must fail before
        // Prepared or sparse state becomes durable.
        require_lineage_set(&mut self.lineage, &required_lineage)?;

        let model_identity_digest = execution.model_identity_digest()?;
        let model_runtime_digest = execution.model_runtime_digest()?;
        let sparse_input = input.to_sparse_tick(&self.scope, &execution);
        let (checkpoint, sparse_receipt) =
            sparse_tick(&self.sparse_config, &sparse_input, previous.as_ref())
                .map_err(JournalError::Mechanism)?;

        let mut calibration = apply_calibration(
            self.calibration_policy,
            self.calibration_artifact.as_ref(),
            CalibrationObservationV1 {
                config_digest: self.config_digest,
                model_identity_digest,
                ood_detector_digest: execution.ood_detector_digest,
                generation: self.config.generation,
                sequence: input.logical_sequence,
                prediction_error_q24: sparse_receipt.prediction_error_q24,
                ood_score_q24: execution.ood_score_q24,
                active_fraction_ppm: sparse_receipt.active_fraction_ppm,
                projection_count: sparse_receipt.projection_count,
            },
        )?;

        let execution_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let checkpoint_bytes =
            u64::try_from(checkpoint.estimated_encoded_bytes()).unwrap_or(u64::MAX);
        let resources = NeuronResourceReceiptV1 {
            execution_micros,
            transient_allocation_bytes: execution.transient_allocation_bytes,
            checkpoint_bytes,
            saturation_count: sparse_receipt.projection_count,
            queue_age_micros: observation.queue_age_micros,
        };
        if execution_micros > self.config.resource_envelope.p99_latency_micros
            || resources.transient_allocation_bytes
                > self.config.resource_envelope.transient_allocation_bytes
            || resources.checkpoint_bytes > self.config.resource_envelope.checkpoint_bytes
        {
            calibration.confidence_ppm = 0;
            calibration.abstain = true;
            calibration.fallback_reason = Some(SignalFallbackReasonV1::ResourceEnvelopeExceeded);
        }

        let tick_receipt = NeuronTickReceiptV1 {
            tick_id: input.tick_id.clone(),
            checkpoint_before: sparse_receipt.checkpoint_before,
            checkpoint_after: sparse_receipt.checkpoint_after,
            activation_digest: checkpoint.activation_digest(),
            active_indices: active_indices(&sparse_receipt.activation_q24)?,
            sparsity_ppm: sparse_receipt.active_fraction_ppm,
            threshold_digest: checkpoint.threshold_digest(),
            eligibility_digest: checkpoint.eligibility_digest(),
            prediction_error_q24: sparse_receipt.prediction_error_q24,
            confidence_ppm: calibration.confidence_ppm,
            ood_ppm: calibration.ood_ppm,
            abstain: calibration.abstain,
            resource_receipt: resources,
        };
        let signal_receipt = NeuronSignalReceiptV1 {
            signal_set_id: input.tick_id.clone(),
            model_runtime_digest,
            temporal_state_digest: checkpoint.digest(),
            signals_q24: sparse_receipt.activation_q24.clone(),
            activation_sparsity_ppm: sparse_receipt.active_fraction_ppm,
            ood_ppm: calibration.ood_ppm,
            abstain: calibration.abstain,
        };
        let result = RuntimeTickResultV1 {
            tick_receipt,
            signal_receipt,
            sparse_receipt: sparse_receipt.clone(),
            model_runtime_receipt: execution.runtime_receipt,
            calibration,
            authority: AuthorityPosture::DENY_ALL,
        };

        required_lineage.sort_by(|left, right| left.as_array().cmp(right.as_array()));
        required_lineage.dedup();
        let prepared = PreparedRuntimeOperationV1::new(
            input.tick_id.as_str().to_string(),
            input.logical_sequence,
            request_digest,
            required_lineage,
            &result,
        )?;
        self.operations.prepare(prepared.clone())?;

        let committed_sparse = match self.journal.commit(input.checkpoint_digest, &sparse_input) {
            Ok(value) => value,
            Err(error) => return Err(error.into()),
        };
        if committed_sparse != sparse_receipt {
            self.poisoned = true;
            return Err(RuntimeError::OperationConflict);
        }

        if let Err(error) = self.operations.mark_committed(
            &prepared.operation_id,
            prepared.request_digest,
            prepared.checkpoint_after,
            prepared.result_digest,
        ) {
            self.poisoned = true;
            return Err(RuntimeError::Operation(error));
        }

        if let Err(_error) = self.ensure_witness_for(&prepared) {
            self.poisoned = true;
            return Err(RuntimeError::WitnessIndeterminate(
                prepared.checkpoint_after,
            ));
        }
        Ok(result)
    }

    pub fn rotate(self, journal_file: File, max_records: usize) -> Result<Self, RuntimeError> {
        if self.poisoned {
            return Err(RuntimeError::Poisoned);
        }
        if self.operations.has_prepared() {
            return Err(RuntimeError::OperationConflict);
        }
        let Self {
            config,
            native,
            model_manifest,
            sparse_config,
            config_digest,
            scope,
            journal,
            operations,
            executor,
            witness,
            lineage,
            witness_anchor,
            calibration_policy,
            calibration_artifact,
            poisoned: _,
        } = self;
        let genesis = journal
            .current()?
            .cloned()
            .ok_or(RuntimeError::RotationRequiresAcknowledgedCheckpoint)?;
        drop(journal);
        let expected_anchor = JournalAnchor {
            sequence: genesis.sequence(),
            checkpoint_digest: genesis.digest(),
        };
        if witness_anchor != Some(expected_anchor)
            || witness.current_anchor()? != Some(expected_anchor)
        {
            return Err(RuntimeError::RotationRequiresAcknowledgedCheckpoint);
        }
        let journal_scope = JournalScope {
            scope_digest: scope.scope_digest,
            objective_digest: scope.objective_digest,
        };
        let journal = SparseJournal::open_anchored_with_genesis(
            journal_file,
            sparse_config.clone(),
            journal_scope,
            max_records,
            expected_anchor,
            genesis,
        )?;
        Ok(Self {
            config,
            native,
            model_manifest,
            sparse_config,
            config_digest,
            scope,
            journal,
            operations,
            executor,
            witness,
            lineage,
            witness_anchor,
            calibration_policy,
            calibration_artifact,
            poisoned: false,
        })
    }

    pub fn rebuild_from_ordered_inputs(
        &mut self,
        entries: Vec<(NeuronTickInputV1, RuntimeTickObservationV1)>,
    ) -> Result<Vec<RuntimeTickResultV1>, RuntimeError> {
        if self.journal.current()?.is_some() || self.operations.has_committed() {
            return Err(RuntimeError::UnwitnessedHistory);
        }
        let mut results = Vec::with_capacity(entries.len());
        for (input, observation) in entries {
            match self.tick(input, observation) {
                Ok(result) => results.push(result),
                Err(error) => {
                    let durable_progress = match self.journal.current() {
                        Ok(current) => current.is_some(),
                        Err(_) => true,
                    };
                    if self.poisoned || durable_progress || !results.is_empty() {
                        self.poisoned = true;
                    }
                    return Err(error);
                }
            }
        }
        Ok(results)
    }

    pub fn current_checkpoint(&self) -> Result<Option<&SparseCheckpoint>, RuntimeError> {
        if self.poisoned {
            return Err(RuntimeError::Poisoned);
        }
        Ok(self.journal.current()?)
    }

    pub fn remaining_records(&self) -> usize {
        self.journal.remaining_records()
    }

    pub fn config_digest(&self) -> Digest32 {
        self.config_digest
    }

    pub fn model_manifest(&self) -> &SelectedNeuronModelManifestV1 {
        &self.model_manifest
    }

    pub fn native_profile(&self) -> &NativeSparseProfileV1 {
        &self.native
    }

    fn required_lineage_for_input(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<Vec<Digest32>, RuntimeError> {
        let mut digests = self.model_manifest.lineage_digests()?;
        digests.extend([
            self.scope.objective_digest,
            self.scope.body_digest,
            input.input_feature_digest,
            input.objective_digest,
            input.ndu_snapshot_digest,
        ]);
        if let Some(modulator) = input.modulator_digest {
            digests.push(modulator);
        }
        if let Some(artifact) = self.calibration_artifact.as_ref() {
            digests.extend([
                artifact.artifact_digest,
                artifact.subgroup_audit_digest,
                artifact.detector_digest,
                artifact.support_digest,
            ]);
        }
        Ok(digests)
    }

    fn reconcile_recovered_state(&mut self) -> Result<(), RuntimeError> {
        for prepared in self.operations.prepared_records() {
            require_lineage_set(&mut self.lineage, &prepared.required_lineage)?;
            match self.journal.checkpoint_digest_at(prepared.sequence)? {
                Some(digest) if digest == prepared.checkpoint_after => {
                    self.operations.mark_committed(
                        &prepared.operation_id,
                        prepared.request_digest,
                        prepared.checkpoint_after,
                        prepared.result_digest,
                    )?;
                }
                None => {
                    self.operations.mark_aborted(
                        &prepared.operation_id,
                        prepared.request_digest,
                        prepared.checkpoint_after,
                        prepared.result_digest,
                    )?;
                }
                Some(_) => return Err(RuntimeError::OperationConflict),
            }
        }

        let base_sequence = self.journal.base_sequence();
        if base_sequence > 0 {
            let genesis = self
                .journal
                .checkpoint_digest_at(base_sequence)?
                .ok_or(RuntimeError::UntrackedJournalHistory)?;
            let operation = self
                .operations
                .committed_for_sequence(base_sequence)
                .ok_or(RuntimeError::UntrackedJournalHistory)?;
            if operation.checkpoint_after != genesis {
                return Err(RuntimeError::UntrackedJournalHistory);
            }
        }
        for anchor in self.journal.anchors_after(base_sequence)? {
            let operation = self
                .operations
                .committed_for_sequence(anchor.sequence)
                .ok_or(RuntimeError::UntrackedJournalHistory)?;
            if operation.checkpoint_after != anchor.checkpoint_digest {
                return Err(RuntimeError::UntrackedJournalHistory);
            }
        }

        match self.witness_anchor {
            Some(anchor) => {
                if let Some(operation) = self.operations.committed_for_sequence(anchor.sequence) {
                    require_lineage_set(&mut self.lineage, &operation.required_lineage)?;
                    if operation.checkpoint_after != anchor.checkpoint_digest {
                        return Err(RuntimeError::UntrackedJournalHistory);
                    }
                }
                let mut current = anchor;
                for next in self.journal.anchors_after(anchor.sequence)? {
                    let operation = self
                        .operations
                        .committed_for_sequence(next.sequence)
                        .ok_or(RuntimeError::UntrackedJournalHistory)?
                        .clone();
                    if operation.checkpoint_after != next.checkpoint_digest {
                        return Err(RuntimeError::UntrackedJournalHistory);
                    }
                    require_lineage_set(&mut self.lineage, &operation.required_lineage)?;
                    self.witness.compare_and_store(Some(current), next)?;
                    current = next;
                }
                self.witness_anchor = Some(current);
            }
            None => {
                let mut current = None;
                for next in self.journal.anchors_after(self.journal.base_sequence())? {
                    let operation = self
                        .operations
                        .committed_for_sequence(next.sequence)
                        .ok_or(RuntimeError::UntrackedJournalHistory)?
                        .clone();
                    if operation.checkpoint_after != next.checkpoint_digest {
                        return Err(RuntimeError::UntrackedJournalHistory);
                    }
                    require_lineage_set(&mut self.lineage, &operation.required_lineage)?;
                    self.witness.compare_and_store(current, next)?;
                    current = Some(next);
                }
                self.witness_anchor = current;
            }
        }
        Ok(())
    }

    fn ensure_witness_for(
        &mut self,
        prepared: &PreparedRuntimeOperationV1,
    ) -> Result<(), RuntimeError> {
        require_lineage_set(&mut self.lineage, &prepared.required_lineage)?;
        let next = JournalAnchor {
            sequence: prepared.sequence,
            checkpoint_digest: prepared.checkpoint_after,
        };
        if self.witness_anchor == Some(next) {
            return Ok(());
        }
        self.witness.compare_and_store(self.witness_anchor, next)?;
        self.witness_anchor = Some(next);
        Ok(())
    }
}

fn validate_static_profile(
    config: &NeuronRuntimeConfigV1,
    native: &NativeSparseProfileV1,
    model_manifest: &SelectedNeuronModelManifestV1,
    scope: &RuntimeScopeBindingV1,
) -> Result<(Digest32, SparseConfig), RuntimeError> {
    model_manifest.validate_for_config(config)?;
    if scope.scope_digest.is_zero()
        || scope.objective_digest.is_zero()
        || scope.body_digest.is_zero()
    {
        return Err(RuntimeError::Protocol(ProtocolError::InvalidInput(
            "runtime scope",
        )));
    }
    Ok((
        bound_runtime_profile_digest(config, native, model_manifest)?,
        bound_sparse_config(config, native, model_manifest)?,
    ))
}

fn request_digest(
    config_digest: Digest32,
    input: &NeuronTickInputV1,
) -> Result<Digest32, RuntimeError> {
    let encoded = encode_neuron_tick_input_v1(input)
        .map_err(|_| RuntimeError::Protocol(ProtocolError::InvalidInput("canonical tick input")))?;
    let mut bytes = b"hepta.neuron.runtime-operation-request.v1".to_vec();
    bytes.extend_from_slice(config_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(encoded.len())
            .map_err(|_| RuntimeError::Protocol(ProtocolError::InvalidInput("tick input size")))?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(&encoded);
    Ok(Digest32::of_bytes(&bytes))
}

fn require_model_lineage<L: LineagePolicy>(
    lineage: &mut L,
    manifest: &SelectedNeuronModelManifestV1,
) -> Result<(), RuntimeError> {
    require_lineage_set(lineage, &manifest.lineage_digests()?)
}

fn require_calibration_lineage<L: LineagePolicy>(
    lineage: &mut L,
    artifact: &NeuronCalibrationArtifactV1,
) -> Result<(), RuntimeError> {
    require_lineage_set(
        lineage,
        &[
            artifact.artifact_digest,
            artifact.subgroup_audit_digest,
            artifact.detector_digest,
            artifact.support_digest,
        ],
    )
}

fn require_lineage_set<L: LineagePolicy>(
    lineage: &mut L,
    digests: &[Digest32],
) -> Result<(), RuntimeError> {
    for digest in digests {
        match lineage.allows(*digest).map_err(RuntimeError::Lineage)? {
            true => {}
            false => return Err(RuntimeError::RevokedLineage),
        }
    }
    Ok(())
}
