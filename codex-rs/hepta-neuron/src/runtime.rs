//! Owner host for canonical neuron ticks.
//!
//! This host removes the caller-supplied drive/prediction shortcut from the
//! composed path: every canonical tick invokes a frozen model executor, validates
//! its exact runtime tuple and numerical-output digest, commits the Q24 state,
//! then durably advances an independent recovery witness before acknowledging.
//! The executor and lineage policy are explicit host trust boundaries.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::BoundModelExecutionV1;
use crate::CalibratedSignalV1;
use crate::CalibrationError;
use crate::CalibrationPolicyV1;
use crate::FileRecoveryWitness;
use crate::JournalAnchor;
use crate::JournalError;
use crate::JournalScope;
use crate::LocalModelRuntimeReceiptV1;
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
use crate::SignalFallbackReasonV1;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseJournal;
use crate::SparseSignalReceipt;
use crate::WitnessError;
use crate::active_indices;
use crate::runtime_profile_digest;
use crate::apply_calibration;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenModelRequestV1 {
    pub tick_id: codex_hepta_types::StableId,
    pub subject_id: codex_hepta_types::StableId,
    pub config_digest: Digest32,
    pub objective_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub input_feature_digest: Digest32,
    pub feature_vector_q24: Vec<i64>,
}

pub trait FrozenModelExecutor {
    fn execute(
        &mut self,
        request: &FrozenModelRequestV1,
    ) -> Result<BoundModelExecutionV1, String>;
}

pub trait LineagePolicy {
    /// Return true only when the exact digest is current and admissible.
    fn allows(&mut self, digest: Digest32) -> Result<bool, String>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeTickObservationV1 {
    pub now_unix_micros: u64,
    pub queue_age_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeTickResultV1 {
    pub tick_receipt: NeuronTickReceiptV1,
    pub signal_receipt: NeuronSignalReceiptV1,
    pub sparse_receipt: SparseSignalReceipt,
    pub model_runtime_receipt: LocalModelRuntimeReceiptV1,
    pub calibration: CalibratedSignalV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeError {
    Protocol(ProtocolError),
    Calibration(CalibrationError),
    Journal(JournalError),
    Witness(WitnessError),
    Model(String),
    Lineage(String),
    RevokedLineage,
    ConfigExpired,
    Poisoned,
    UnwitnessedHistory,
    RotationRequiresAcknowledgedCheckpoint,
    RotationRequired,
    WitnessIndeterminate(Digest32),
    /// The journal committed, but receipt finalization failed before the
    /// independent witness advanced. Reopen/reconcile before any retry.
    PostCommitIndeterminate(Digest32, &'static str),
}

impl fmt::Display for RuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RuntimeError {}

impl From<ProtocolError> for RuntimeError {
    fn from(error: ProtocolError) -> Self {
        Self::Protocol(error)
    }
}

impl From<CalibrationError> for RuntimeError {
    fn from(error: CalibrationError) -> Self {
        Self::Calibration(error)
    }
}

impl From<JournalError> for RuntimeError {
    fn from(error: JournalError) -> Self {
        Self::Journal(error)
    }
}

impl From<WitnessError> for RuntimeError {
    fn from(error: WitnessError) -> Self {
        Self::Witness(error)
    }
}

pub struct NeuronRuntimeHost<E, W, L>
where
    E: FrozenModelExecutor,
    W: RecoveryWitnessStore,
    L: LineagePolicy,
{
    config: NeuronRuntimeConfigV1,
    native: NativeSparseProfileV1,
    sparse_config: SparseConfig,
    config_digest: Digest32,
    scope: RuntimeScopeBindingV1,
    journal: SparseJournal,
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
        file: File,
        config: NeuronRuntimeConfigV1,
        native: NativeSparseProfileV1,
        scope: RuntimeScopeBindingV1,
        max_records: usize,
        executor: E,
        mut witness: W,
        mut lineage: L,
        calibration_policy: CalibrationPolicyV1,
        calibration_artifact: Option<NeuronCalibrationArtifactV1>,
        now_unix_micros: u64,
    ) -> Result<Self, RuntimeError> {
        let config_digest = runtime_profile_digest(&config, &native)?;
        if now_unix_micros >= config.expires_at_unix_micros {
            return Err(RuntimeError::ConfigExpired);
        }
        require_lineage(&mut lineage, config.encoder_digest)?;
        require_lineage(&mut lineage, config.head_digest)?;
        if let Some(artifact) = calibration_artifact.as_ref() {
            artifact.validate()?;
            require_calibration_lineage(&mut lineage, artifact)?;
        }
        let sparse_config = config.to_sparse_config(&native)?;
        if scope.scope_digest.is_zero()
            || scope.objective_digest.is_zero()
            || scope.body_digest.is_zero()
        {
            return Err(RuntimeError::Protocol(ProtocolError::InvalidInput(
                "runtime scope",
            )));
        }
        let journal_scope = JournalScope {
            scope_digest: scope.scope_digest,
            objective_digest: scope.objective_digest,
        };
        let witness_anchor = witness.current_anchor()?;
        let journal = match witness_anchor {
            Some(anchor) => SparseJournal::open_anchored(
                file,
                sparse_config.clone(),
                journal_scope,
                max_records,
                anchor,
            )?,
            None => {
                let journal =
                    SparseJournal::open(file, sparse_config.clone(), journal_scope, max_records)?;
                if journal.current()?.is_some() {
                    return Err(RuntimeError::UnwitnessedHistory);
                }
                journal
            }
        };
        let witness_anchor = match witness_anchor {
            Some(anchor) => Some(reconcile_recovered_suffix(&mut witness, &journal, anchor)?),
            None => None,
        };
        Ok(Self {
            config,
            native,
            sparse_config,
            config_digest,
            scope,
            journal,
            executor,
            witness,
            lineage,
            witness_anchor,
            calibration_policy,
            calibration_artifact,
            poisoned: false,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn open_with_genesis(
        file: File,
        config: NeuronRuntimeConfigV1,
        native: NativeSparseProfileV1,
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
        let config_digest = runtime_profile_digest(&config, &native)?;
        if now_unix_micros >= config.expires_at_unix_micros {
            return Err(RuntimeError::ConfigExpired);
        }
        require_lineage(&mut lineage, config.encoder_digest)?;
        require_lineage(&mut lineage, config.head_digest)?;
        if let Some(artifact) = calibration_artifact.as_ref() {
            artifact.validate()?;
            require_calibration_lineage(&mut lineage, artifact)?;
        }
        if scope.scope_digest.is_zero()
            || scope.objective_digest.is_zero()
            || scope.body_digest.is_zero()
        {
            return Err(RuntimeError::Protocol(ProtocolError::InvalidInput(
                "runtime scope",
            )));
        }
        let sparse_config = config.to_sparse_config(&native)?;
        let journal_scope = JournalScope {
            scope_digest: scope.scope_digest,
            objective_digest: scope.objective_digest,
        };
        let witness_anchor = witness
            .current_anchor()?
            .ok_or(RuntimeError::RotationRequiresAcknowledgedCheckpoint)?;
        let journal = SparseJournal::open_anchored_with_genesis(
            file,
            sparse_config.clone(),
            journal_scope,
            max_records,
            witness_anchor,
            genesis,
        )?;
        let witness_anchor = reconcile_recovered_suffix(&mut witness, &journal, witness_anchor)?;
        Ok(Self {
            config,
            native,
            sparse_config,
            config_digest,
            scope,
            journal,
            executor,
            witness,
            lineage,
            witness_anchor: Some(witness_anchor),
            calibration_policy,
            calibration_artifact,
            poisoned: false,
        })
    }

    pub fn tick(
        &mut self,
        input: NeuronTickInputV1,
        observation: RuntimeTickObservationV1,
    ) -> Result<RuntimeTickResultV1, RuntimeError> {
        if self.poisoned {
            return Err(RuntimeError::Poisoned);
        }
        if observation.now_unix_micros >= self.config.expires_at_unix_micros {
            return Err(RuntimeError::ConfigExpired);
        }
        if self.journal.remaining_records() == 0 {
            return Err(RuntimeError::RotationRequired);
        }
        require_lineage(&mut self.lineage, self.config.encoder_digest)?;
        require_lineage(&mut self.lineage, self.config.head_digest)?;
        require_lineage(&mut self.lineage, input.input_feature_digest)?;
        if let Some(modulator_digest) = input.modulator_digest {
            require_lineage(&mut self.lineage, modulator_digest)?;
        }

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
        for digest in [
            execution.runtime_receipt.tokenizer_digest,
            execution.runtime_receipt.preprocessor_digest,
            execution.runtime_receipt.device_identity_digest,
        ] {
            require_lineage(&mut self.lineage, digest)?;
        }
        let model_identity_digest = execution.model_identity_digest()?;
        let model_runtime_digest = execution.model_runtime_digest()?;
        let sparse_tick = input.to_sparse_tick(&self.scope, &execution);
        let sparse_receipt = self
            .journal
            .commit(input.checkpoint_digest, &sparse_tick)?;
        let checkpoint = self
            .journal
            .current()?
            .cloned()
            .ok_or(RuntimeError::Journal(JournalError::Corrupt))?;

        let mut calibration = match apply_calibration(
            self.calibration_policy,
            self.calibration_artifact.as_ref(),
            self.config_digest,
            model_identity_digest,
            self.config.generation,
            input.logical_sequence,
            sparse_receipt.prediction_error_q24,
            execution.ood_score_q24,
            sparse_receipt.active_fraction_ppm,
            sparse_receipt.projection_count,
        ) {
            Ok(value) => value,
            Err(_error) => {
                self.poisoned = true;
                return Err(RuntimeError::PostCommitIndeterminate(
                    sparse_receipt.checkpoint_after,
                    "calibration",
                ));
            }
        };

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

        let active_indices = match active_indices(&sparse_receipt.activation_q24) {
            Ok(value) => value,
            Err(_error) => {
                self.poisoned = true;
                return Err(RuntimeError::PostCommitIndeterminate(
                    sparse_receipt.checkpoint_after,
                    "receipt",
                ));
            }
        };
        let tick_receipt = NeuronTickReceiptV1 {
            tick_id: input.tick_id.clone(),
            checkpoint_before: sparse_receipt.checkpoint_before,
            checkpoint_after: sparse_receipt.checkpoint_after,
            activation_digest: checkpoint.activation_digest(),
            active_indices,
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

        let next_anchor = JournalAnchor {
            sequence: input.logical_sequence,
            checkpoint_digest: sparse_receipt.checkpoint_after,
        };
        if let Err(_error) = self
            .witness
            .compare_and_store(self.witness_anchor, next_anchor)
        {
            self.poisoned = true;
            return Err(RuntimeError::WitnessIndeterminate(
                sparse_receipt.checkpoint_after,
            ));
        }
        self.witness_anchor = Some(next_anchor);

        Ok(RuntimeTickResultV1 {
            tick_receipt,
            signal_receipt,
            sparse_receipt,
            model_runtime_receipt: execution.runtime_receipt,
            calibration,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    /// Rotate a full segment without resetting temporal/homeostatic state.
    /// Rotation is admitted only after the current checkpoint is independently
    /// witnessed; the new empty segment uses that exact checkpoint as genesis.
    pub fn rotate(self, file: File, max_records: usize) -> Result<Self, RuntimeError> {
        if self.poisoned {
            return Err(RuntimeError::Poisoned);
        }
        let Self {
            config,
            native,
            sparse_config,
            config_digest,
            scope,
            journal,
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
            file,
            sparse_config.clone(),
            journal_scope,
            max_records,
            expected_anchor,
            genesis,
        )?;
        Ok(Self {
            config,
            native,
            sparse_config,
            config_digest,
            scope,
            journal,
            executor,
            witness,
            lineage,
            witness_anchor,
            calibration_policy,
            calibration_artifact,
            poisoned: false,
        })
    }

    /// Replay ordered, already-authorized inputs into a fresh runtime. Revoked
    /// feature/modulator/model lineage is rejected by the same live policy, so a
    /// deletion rebuild cannot resurrect a removed row through this path.
    pub fn rebuild_from_ordered_inputs(
        &mut self,
        entries: Vec<(NeuronTickInputV1, RuntimeTickObservationV1)>,
    ) -> Result<Vec<RuntimeTickResultV1>, RuntimeError> {
        if self.journal.current()?.is_some() {
            return Err(RuntimeError::UnwitnessedHistory);
        }
        let mut results = Vec::with_capacity(entries.len());
        for (input, observation) in entries {
            match self.tick(input, observation) {
                Ok(result) => results.push(result),
                Err(error) => {
                    self.poisoned = true;
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

    pub fn native_profile(&self) -> &NativeSparseProfileV1 {
        &self.native
    }
}

pub fn witness_context_digest(
    config_digest: Digest32,
    scope: &RuntimeScopeBindingV1,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.recovery-witness-context.v1".to_vec();
    bytes.extend_from_slice(config_digest.as_array());
    bytes.extend_from_slice(scope.scope_digest.as_array());
    bytes.extend_from_slice(scope.objective_digest.as_array());
    bytes.extend_from_slice(scope.body_digest.as_array());
    let raw = scope.subject_id.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
    Digest32::of_bytes(&bytes)
}

/// Convenience constructor for the built-in crash-durable file witness. The
/// caller still owns authentication/freshness of the file and its directory.
pub fn open_file_witness(
    file: File,
    config_digest: Digest32,
    scope: &RuntimeScopeBindingV1,
) -> Result<FileRecoveryWitness, RuntimeError> {
    Ok(FileRecoveryWitness::open(
        file,
        witness_context_digest(config_digest, scope),
    )?)
}

fn reconcile_recovered_suffix<W: RecoveryWitnessStore>(
    witness: &mut W,
    journal: &SparseJournal,
    mut anchor: JournalAnchor,
) -> Result<JournalAnchor, RuntimeError> {
    for next in journal.anchors_after(anchor.sequence)? {
        witness.compare_and_store(Some(anchor), next)?;
        anchor = next;
    }
    Ok(anchor)
}

fn require_calibration_lineage<L: LineagePolicy>(
    lineage: &mut L,
    artifact: &NeuronCalibrationArtifactV1,
) -> Result<(), RuntimeError> {
    for digest in [
        artifact.artifact_digest,
        artifact.subgroup_audit_digest,
        artifact.detector_digest,
        artifact.support_digest,
    ] {
        require_lineage(lineage, digest)?;
    }
    Ok(())
}

fn require_lineage<L: LineagePolicy>(
    lineage: &mut L,
    digest: Digest32,
) -> Result<(), RuntimeError> {
    match lineage.allows(digest).map_err(RuntimeError::Lineage)? {
        true => Ok(()),
        false => Err(RuntimeError::RevokedLineage),
    }
}

