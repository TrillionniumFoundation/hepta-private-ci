//! Original Selector and Observer receipts from the published generation actor.
//! The host supplies its enrolled key, original journal and independent witness.
//! A read observes real CURRENT, consumed FinalUse and committed task work; it
//! never publishes a model, creates a task, acknowledges output or issues a grant.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationIntentV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::NeuronGenerationRuntimeHandleV2;
use crate::OriginalCircuitFeatureLearningSourcesV1;
use crate::OriginalHistoricalCircuitFeatureSourcesV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as Error;
use crate::learning_owner_journal::LearningOwnerJournalV1;

/// The original host chooses a single role before handing over its capability.
/// The two journals cannot turn an Observer key into a Selector capability.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OriginalGenerationLearningRoleV1 {
    Selection,
    NextUse,
}

impl OriginalGenerationLearningRoleV1 {
    fn stage(self) -> LearningIterationStageV1 {
        match self {
            Self::Selection => LearningIterationStageV1::Selection,
            Self::NextUse => LearningIterationStageV1::NextUse,
        }
    }

    fn role(self) -> LearningEvidenceRoleV1 {
        match self {
            Self::Selection => LearningEvidenceRoleV1::Selector,
            Self::NextUse => LearningEvidenceRoleV1::Observer,
        }
    }
}

#[derive(Clone)]
pub struct OriginalGenerationLearningReceiptConfigV1 {
    pub initial: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub role: OriginalGenerationLearningRoleV1,
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub maximum_signature_lifetime_seconds: u64,
}

/// This handle is created by the real generation service, not a caller callback.
/// The intent is only a lookup key: the owner resolves its actual committed
/// receipt. The manifest must match the original published predecessor.
pub struct OriginalGenerationLearningReceiptSourcesV1 {
    pub runtime: NeuronGenerationRuntimeHandleV2,
    pub baseline: CellBackendManifestV2,
    pub next_use: Option<CellGenerationIntentV2>,
}

enum OriginalLearningReceiptSourceV1 {
    Generation(OriginalGenerationLearningReceiptSourcesV1),
    Feature(OriginalCircuitFeatureLearningSourcesV1),
    HistoricalFeature(OriginalHistoricalCircuitFeatureSourcesV1),
}

pub struct OriginalGenerationLearningReceiptOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalGenerationLearningReceiptConfigV1,
    key: SigningKey,
    source: OriginalLearningReceiptSourceV1,
    binding: Digest32,
}

impl<W: AnchorWitnessStore> OriginalGenerationLearningReceiptOwnerV1<W> {
    pub(crate) fn recover_historical_feature(
        file: File,
        witness: W,
        config: OriginalGenerationLearningReceiptConfigV1,
        key: SigningKey,
        source: OriginalHistoricalCircuitFeatureSourcesV1,
    ) -> Result<Self, Error> {
        let source = OriginalLearningReceiptSourceV1::HistoricalFeature(source);
        let binding = validate_config(&config, &key, &source)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::recover(file, witness, binding)?,
            config,
            key,
            source,
            binding,
        })
    }

    pub(crate) fn require_context(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        role: OriginalGenerationLearningRoleV1,
    ) -> Result<(), Error> {
        if &self.config.initial != initial
            || &self.config.scope != scope
            || self.config.role != role
        {
            return Err(Error::Binding("original generation handoff context"));
        }
        validate_config(&self.config, &self.key, &self.source)?;
        Ok(())
    }

    pub(crate) async fn observe_original_selection(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        if self.config.role != OriginalGenerationLearningRoleV1::Selection {
            return Err(Error::Binding("original Selection owner required"));
        }
        self.observe(&self.predecessor(snapshot)?).await
    }

    pub fn create(
        file: File,
        witness: W,
        config: OriginalGenerationLearningReceiptConfigV1,
        key: SigningKey,
        source: OriginalGenerationLearningReceiptSourcesV1,
    ) -> Result<Self, Error> {
        let source = OriginalLearningReceiptSourceV1::Generation(source);
        let binding = validate_config(&config, &key, &source)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::create(file, witness, binding)?,
            config,
            key,
            source,
            binding,
        })
    }

    /// Reopen original bytes and witness. A recovered Pending claim never signs
    /// again, and completed readback retains its original validity window.
    pub fn recover(
        file: File,
        witness: W,
        config: OriginalGenerationLearningReceiptConfigV1,
        key: SigningKey,
        source: OriginalGenerationLearningReceiptSourcesV1,
    ) -> Result<Self, Error> {
        let source = OriginalLearningReceiptSourceV1::Generation(source);
        let binding = validate_config(&config, &key, &source)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::recover(file, witness, binding)?,
            config,
            key,
            source,
            binding,
        })
    }

    /// A separate source namespace for the actual completed ordinary Feature
    /// task. The existing generation actor constructors and bytes are unchanged.
    pub fn create_feature(
        file: File,
        witness: W,
        config: OriginalGenerationLearningReceiptConfigV1,
        key: SigningKey,
        source: OriginalCircuitFeatureLearningSourcesV1,
    ) -> Result<Self, Error> {
        let source = OriginalLearningReceiptSourceV1::Feature(source);
        let binding = validate_config(&config, &key, &source)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::create(file, witness, binding)?,
            config,
            key,
            source,
            binding,
        })
    }

    /// Recover the original Feature receipt journal with freshly revalidated
    /// original task owners. Missing or Pending never authorizes a new signature.
    pub fn recover_feature(
        file: File,
        witness: W,
        config: OriginalGenerationLearningReceiptConfigV1,
        key: SigningKey,
        source: OriginalCircuitFeatureLearningSourcesV1,
    ) -> Result<Self, Error> {
        let source = OriginalLearningReceiptSourceV1::Feature(source);
        let binding = validate_config(&config, &key, &source)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::recover(file, witness, binding)?,
            config,
            key,
            source,
            binding,
        })
    }

    /// Sign only the observation returned by this original published actor.
    /// An owner failure is an error; it never becomes evaluator NoUpdate.
    pub async fn attest_original_completion(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let predecessor = self.predecessor(snapshot)?;
        let observed = self.observe(&predecessor).await?;
        let saved = self.saved(&predecessor);
        let config = &self.config;
        let key = &self.key;
        let bytes = match self.journal.read(&saved) {
            Ok(bytes) => bytes,
            Err(Error::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {
                if matches!(
                    &self.source,
                    OriginalLearningReceiptSourceV1::HistoricalFeature(_)
                ) {
                    return Err(Error::Binding(
                        "historical generation requires an existing original signature",
                    ));
                }
                let current = now()?;
                if current >= config.initial.request.envelope.expiry_unix_seconds {
                    return Err(Error::Binding("new generation receipt after deadline"));
                }
                config.verifier.require_signer_binding(
                    config.role.role(),
                    &config.signer,
                    current,
                )?;
                make_receipt(config, &predecessor, observed.clone(), current)?;
                self.journal.commit_once(&saved, || {
                    let issued_at = now()?;
                    if issued_at >= config.initial.request.envelope.expiry_unix_seconds {
                        return Err(Error::Binding("new generation receipt after deadline"));
                    }
                    config.verifier.require_signer_binding(
                        config.role.role(),
                        &config.signer,
                        issued_at,
                    )?;
                    let receipt = make_receipt(config, &predecessor, observed.clone(), issued_at)?;
                    let payload = learning_iteration_receipt_signing_bytes_v1(&receipt)
                        .map_err(|_| Error::Binding("generation receipt encoding"))?;
                    let mut signed = SignedLearningEvidenceV1 {
                        evidence_id: evidence_id(saved.binding_digest)?,
                        principal_id: config.signer.principal.principal_id.clone(),
                        role: config.role.role(),
                        trust_digest: config.verifier.trust_digest(),
                        scope_digest: config.verifier.scope_digest(),
                        objective_digest: config.verifier.objective_digest(),
                        authority_epoch: config.signer.principal.authority_epoch,
                        issued_at,
                        expires_at: issued_at
                            .checked_add(config.maximum_signature_lifetime_seconds)
                            .ok_or(Error::Binding("generation signature overflow"))?
                            .min(config.signer.principal.expires_at),
                        payload_digest: Digest32::of_bytes(&payload),
                        signature: [0; 64],
                    };
                    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
                    config
                        .verifier
                        .verify(config.role.role(), &signed, &payload, issued_at)?;
                    learning_owner_evidence::encode(&payload, &signed)
                })?
            }
            Err(error) => return Err(error),
        };
        self.authenticate(snapshot, &predecessor, observed, &saved, &bytes)
            .await
    }

    /// No claim, work or signature is created. Re-read the actual publication
    /// and committed work around the original signed journal read.
    pub async fn readback(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let predecessor = self.predecessor(snapshot)?;
        let observed = self.observe(&predecessor).await?;
        let saved = self.saved(&predecessor);
        let bytes = self.journal.read(&saved)?;
        self.authenticate(snapshot, &predecessor, observed, &saved, &bytes)
            .await
    }

    fn predecessor(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationCoordinatorV1, Error> {
        if snapshot.request != self.config.initial.request
            || snapshot.owners != self.config.initial.owners
        {
            return Err(Error::Binding("original generation operation"));
        }
        self.config
            .scope
            .validate_snapshot(snapshot)
            .map_err(|_| Error::Binding("original generation scope"))?;
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())
            .map_err(|_| Error::Binding("original generation history"))?;
        let mut prefix = LearningIterationCoordinatorV1::from_snapshot(self.config.initial.clone())
            .map_err(|_| Error::Binding("original generation initial cut"))?;
        for receipt in &snapshot.receipts {
            if matches!(
                receipt.observation,
                LearningIterationObservationV1::Selection { .. }
            ) && self.config.role == OriginalGenerationLearningRoleV1::Selection
                || receipt.observation.stage() == LearningIterationStageV1::NextUse
            {
                break;
            }
            prefix
                .record(receipt.clone(), receipt.observed_unix_seconds)
                .map_err(|_| Error::Binding("original generation predecessor"))?;
        }
        if prefix.next_stage() != Some(self.config.role.stage()) {
            return Err(Error::Binding("generation is not the required next stage"));
        }
        Ok(prefix)
    }

    fn saved(
        &self,
        predecessor: &LearningIterationCoordinatorV1,
    ) -> ProductEvaluationExecutionKeyV1 {
        ProductEvaluationExecutionKeyV1 {
            plan_id: self.config.initial.request.operation_id.clone(),
            binding_digest: Digest32::of_parts(&[
                b"hepta.agentd.original-generation-receipt.v1\0",
                self.binding.as_array(),
                predecessor.snapshot().head_digest.as_array(),
            ]),
        }
    }

    async fn observe(
        &self,
        predecessor: &LearningIterationCoordinatorV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        let source = match &self.source {
            OriginalLearningReceiptSourceV1::HistoricalFeature(source) => {
                return OriginalHistoricalCircuitFeatureSourcesV1::read_original_feature_observation(
                    source, predecessor, self.config.role,
                )
                .map_err(|_| Error::Binding("original retired Feature data unavailable"));
            }
            OriginalLearningReceiptSourceV1::Feature(source) => {
                let feature: &OriginalCircuitFeatureLearningSourcesV1 = source;
                return feature
                    .read_original_feature_observation(predecessor, self.config.role)
                    .map_err(|_| {
                        Error::Binding(
                            "original Feature CURRENT, source or committed use unavailable",
                        )
                    });
            }
            OriginalLearningReceiptSourceV1::Generation(source) => source,
        };
        let retained =
            predecessor.next_task_bundle() == Some(&self.config.initial.request.selected_bundle);
        let runtime: &NeuronGenerationRuntimeHandleV2 = &source.runtime;
        let result = match (self.config.role, retained) {
            (OriginalGenerationLearningRoleV1::Selection, true) => {
                runtime.read_learning_selection(predecessor).await
            }
            (OriginalGenerationLearningRoleV1::Selection, false) => {
                runtime
                    .read_learning_updated_selection(predecessor, &source.baseline)
                    .await
            }
            (OriginalGenerationLearningRoleV1::NextUse, true) => {
                let intent = source
                    .next_use
                    .as_ref()
                    .ok_or(Error::Binding("original use intent"))?;
                runtime.read_learning_next_use(predecessor, intent).await
            }
            (OriginalGenerationLearningRoleV1::NextUse, false) => {
                let intent = source
                    .next_use
                    .as_ref()
                    .ok_or(Error::Binding("original use intent"))?;
                runtime
                    .read_learning_updated_next_use(predecessor, &source.baseline, intent)
                    .await
            }
        };
        result
            .map_err(|_| Error::Binding("original generation CURRENT or committed use unavailable"))
    }

    async fn authenticate(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
        predecessor: &LearningIterationCoordinatorV1,
        observed: LearningIterationObservationV1,
        saved: &ProductEvaluationExecutionKeyV1,
        bytes: &[u8],
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        let receipt = make_receipt(
            &self.config,
            predecessor,
            observed.clone(),
            signed.issued_at,
        )?;
        if learning_iteration_receipt_signing_bytes_v1(&receipt)
            .map_err(|_| Error::Binding("generation receipt encoding"))?
            != payload
            || signed.evidence_id != evidence_id(saved.binding_digest)?
            || snapshot
                .receipts
                .get(predecessor.snapshot().receipts.len())
                .is_some_and(|expected| expected != &receipt)
        {
            return Err(Error::Binding("exact original generation receipt"));
        }
        if self.observe(predecessor).await? != observed || self.journal.read(saved)? != bytes {
            return Err(Error::CommitUncertain);
        }
        let verified =
            self.config
                .verifier
                .verify(self.config.role.role(), &signed, &payload, now()?)?;
        if verified.principal() != &self.config.signer.principal
            || verified.controller_id() != &self.config.signer.controller_id
        {
            return Err(Error::Binding("original generation signer"));
        }
        Ok((receipt, signed))
    }
}

fn make_receipt(
    config: &OriginalGenerationLearningReceiptConfigV1,
    predecessor: &LearningIterationCoordinatorV1,
    observation: LearningIterationObservationV1,
    observed_unix_seconds: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    let evidence_digest = match &observation {
        LearningIterationObservationV1::Selection {
            selection_digest, ..
        } if config.role == OriginalGenerationLearningRoleV1::Selection => *selection_digest,
        LearningIterationObservationV1::NextUse {
            committed_step_receipt,
            ..
        }
        | LearningIterationObservationV1::RetainedModelNextUse {
            committed_step_receipt,
            ..
        } if config.role == OriginalGenerationLearningRoleV1::NextUse => *committed_step_receipt,
        _ => return Err(Error::Binding("original generation observation kind")),
    };
    let receipt = LearningIterationReceiptV1 {
        operation_id: config.initial.request.operation_id.clone(),
        actor_id: config.signer.principal.principal_id.clone(),
        predecessor: predecessor.snapshot().head_digest,
        evidence_digest,
        observed_unix_seconds,
        observation,
    };
    let mut check = predecessor.clone();
    check
        .record(receipt.clone(), observed_unix_seconds)
        .map_err(|_| Error::Binding("original generation receipt extension"))?;
    Ok(receipt)
}

fn validate_config(
    config: &OriginalGenerationLearningReceiptConfigV1,
    key: &SigningKey,
    source: &OriginalLearningReceiptSourceV1,
) -> Result<Digest32, Error> {
    let initial = LearningIterationCoordinatorV1::new(
        config.initial.request.clone(),
        config.initial.owners.clone(),
    )
    .map_err(|_| Error::Binding("generation initial operation"))?;
    config
        .scope
        .validate_snapshot(&config.initial)
        .map_err(|_| Error::Binding("generation scope"))?;
    if initial.snapshot() != &config.initial
        || key.verifying_key().to_bytes() != config.signer.verifying_key
        || config.initial.owners.owner(config.role.stage()) != &config.signer.principal.principal_id
        || config.initial.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.initial.request.envelope.objective_digest != config.verifier.objective_digest()
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(Error::Binding("original generation capability"));
    }
    config
        .verifier
        .require_signer_binding(config.role.role(), &config.signer, now()?)?;
    let expected = config
        .initial
        .request
        .selected_bundle
        .digest()
        .map_err(|_| Error::Binding("generation baseline bundle"))?;
    let (domain, baseline, intent): (&[u8], [u8; 32], Vec<u8>) = match source {
        OriginalLearningReceiptSourceV1::Generation(source) => {
            if source.baseline.bundle_digest != expected.into_array()
                || (config.role == OriginalGenerationLearningRoleV1::NextUse)
                    != source.next_use.is_some()
            {
                return Err(Error::Binding("original generation capability"));
            }
            let baseline = source
                .baseline
                .digest()
                .map_err(|_| Error::Binding("generation baseline manifest"))?;
            let intent = intent_binding(source.next_use.as_ref())?
                .as_array()
                .to_vec();
            (
                b"hepta.agentd.original-generation-receipt-owner.v1\0",
                baseline,
                intent,
            )
        }
        OriginalLearningReceiptSourceV1::Feature(source) => {
            let source: &OriginalCircuitFeatureLearningSourcesV1 = source;
            (
                b"hepta.agentd.original-feature-receipt-owner.v1\0",
                source
                    .require_original_feature_binding(expected)
                    .map_err(|_| Error::Binding("original Feature source binding"))?
                    .into_array(),
                Vec::new(),
            )
        }
        OriginalLearningReceiptSourceV1::HistoricalFeature(source) => (
            b"hepta.agentd.original-feature-receipt-owner.v1\0",
            OriginalHistoricalCircuitFeatureSourcesV1::require_original_feature_binding(
                source, expected,
            )
            .map_err(|_| Error::Binding("original historical Feature source binding"))?
            .into_array(),
            Vec::new(),
        ),
    };
    Ok(Digest32::of_parts(&[
        domain,
        config.initial.head_digest.as_array(),
        config.scope.binding().as_array(),
        config.verifier.trust_digest().as_array(),
        &[match config.role {
            OriginalGenerationLearningRoleV1::Selection => 1,
            OriginalGenerationLearningRoleV1::NextUse => 2,
        }],
        &baseline,
        &intent,
        &config.maximum_signature_lifetime_seconds.to_be_bytes(),
    ]))
}

/// Bind the same six fields that Request::intent projects and the original
/// journal compares by Eq. This is an owner-local namespace, not a request
/// digest or a new serialization of the generation protocol. The original
/// admitted-at timestamp and full predecessor remain in the actual journal.
fn intent_binding(intent: Option<&CellGenerationIntentV2>) -> Result<Digest32, Error> {
    const DOMAIN: &[u8] = b"hepta.agentd.original-generation-intent.v1\0";
    match intent {
        None => Ok(Digest32::of_parts(&[DOMAIN, &[0]])),
        Some(intent) => {
            StableId::new(&intent.operation_id)
                .map_err(|_| Error::Binding("generation intent operation"))?;
            let operation = intent.operation_id.as_bytes();
            let length = u64::try_from(operation.len())
                .map_err(|_| Error::Binding("generation intent length"))?;
            Ok(Digest32::of_parts(&[
                DOMAIN,
                &[1],
                &length.to_be_bytes(),
                operation,
                &intent.task_digest,
                &intent.source_frontier,
                &intent.predecessor_digest,
                &intent.input_digest,
                &intent.deadline_micros.to_be_bytes(),
            ]))
        }
    }
}

fn evidence_id(binding: Digest32) -> Result<StableId, Error> {
    StableId::new(format!("original-generation:{binding}"))
        .map_err(|_| Error::Binding("generation evidence id"))
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("generation owner clock"))
}

#[cfg(test)]
#[path = "neuron_generation_receipt_intent_tests.rs"]
mod intent_tests;
