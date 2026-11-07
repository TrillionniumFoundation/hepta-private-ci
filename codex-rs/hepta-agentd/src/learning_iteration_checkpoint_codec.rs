//! Bounded persistence encoding, separate from every existing signing payload.

use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::LearningIterationCheckpointErrorV1 as Error;

pub(super) const MAX_BYTES: usize = 8192;
const MAGIC: &[u8; 8] = b"HEPLCP01";
pub(super) const MAX_RECEIPTS: usize = 7;
const MAX_ID_BYTES: usize = 128;

pub(super) fn encode(snapshot: &LearningIterationSnapshotV1) -> Result<Vec<u8>, Error> {
    if snapshot.receipts.len() > MAX_RECEIPTS {
        return Err(Error::Capacity);
    }
    let mut w = Writer(Vec::with_capacity(MAX_BYTES));
    w.put(MAGIC)?;
    let request = &snapshot.request;
    for id in [&request.operation_id, &request.principal_id, &request.agent_id,
        &request.cell_id, &request.source_run_id] {
        w.id(id)?;
    }
    w.digest(request.completed_task_receipt)?;
    w.digest(request.selected_artifact_digest)?;
    w.bundle(&request.selected_bundle)?;
    let e = &request.envelope;
    w.id(&e.envelope_id)?;
    for digest in [e.base_commit, e.base_tree, e.objective_digest, e.grammar_digest] {
        w.digest(digest)?;
    }
    w.u16(e.maximum_files)?;
    w.u64(e.maximum_diff_bytes)?;
    w.u16(e.maximum_candidates)?;
    w.u8(e.maximum_parallel_sandboxes)?;
    w.u64(e.expiry_unix_seconds)?;
    let b = &request.budget;
    w.u32(b.maximum_dataset_rows)?;
    for value in [b.maximum_dataset_bytes, b.maximum_training_steps,
        b.maximum_training_milliseconds, b.maximum_artifact_bytes] {
        w.u64(value)?;
    }
    let owners = &snapshot.owners;
    w.digest(owners.evidence_trust_digest)?;
    for id in [&owners.experience, &owners.dataset, &owners.trainer, &owners.evaluator,
        &owners.proposal, &owners.selector, &owners.next_use_observer] {
        w.id(id)?;
    }
    w.u8(u8::try_from(snapshot.receipts.len()).map_err(|_| Error::Capacity)?)?;
    for receipt in &snapshot.receipts {
        w.id(&receipt.operation_id)?;
        w.digest(receipt.predecessor)?;
        w.id(&receipt.actor_id)?;
        w.digest(receipt.evidence_digest)?;
        w.u64(receipt.observed_unix_seconds)?;
        match &receipt.observation {
            LearningIterationObservationV1::Experience { episode_digest, completed_task_receipt } => {
                w.u8(0)?;
                w.digest(*episode_digest)?;
                w.digest(*completed_task_receipt)?;
            }
            LearningIterationObservationV1::Dataset { snapshot_digest, episode_digest,
                withdrawal_frontier, rows, bytes } => {
                w.u8(1)?;
                for digest in [snapshot_digest, episode_digest, withdrawal_frontier] {
                    w.digest(*digest)?;
                }
                w.u32(*rows)?;
                w.u64(*bytes)?;
            }
            LearningIterationObservationV1::Training { candidate, steps, milliseconds, artifact_bytes } => {
                w.u8(2)?;
                w.bundle(candidate)?;
                for value in [steps, milliseconds, artifact_bytes] { w.u64(*value)?; }
            }
            LearningIterationObservationV1::Evaluation { candidate_bundle, evaluation_profile, disposition } => {
                w.u8(3)?;
                w.digest(*candidate_bundle)?;
                w.digest(*evaluation_profile)?;
                w.u8(match disposition {
                    LearningEvaluationDispositionV1::Qualified => 0,
                    LearningEvaluationDispositionV1::NoUpdate => 1,
                })?;
            }
            LearningIterationObservationV1::Proposal { candidate_bundle, proposal_id, composition_digest, disposition } => {
                w.u8(4)?;
                w.digest(*candidate_bundle)?;
                w.id(proposal_id)?;
                w.digest(*composition_digest)?;
                w.u8(match disposition {
                    LearningProposalDispositionV1::UpdateCandidates => 0,
                    LearningProposalDispositionV1::NoAdmissibleUpdate => 1,
                })?;
            }
            LearningIterationObservationV1::Selection { candidate_bundle, selection_digest } => {
                w.u8(5)?;
                w.digest(*candidate_bundle)?;
                w.digest(*selection_digest)?;
            }
            LearningIterationObservationV1::NextUse { candidate_bundle, state_partition,
                checkpoint_digest, selection_digest, committed_step_receipt, state_cutover_receipt } => {
                w.u8(6)?;
                w.digest(*candidate_bundle)?;
                w.partition(state_partition)?;
                for digest in [checkpoint_digest, selection_digest, committed_step_receipt, state_cutover_receipt] {
                    w.digest(*digest)?;
                }
            }
            LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, state_partition,
                checkpoint_digest, selection_digest, committed_step_receipt, task_owner_publication } => {
                w.u8(7)?;
                w.digest(*retained_bundle)?;
                w.partition(state_partition)?;
                for digest in [checkpoint_digest, selection_digest, committed_step_receipt, task_owner_publication] {
                    w.digest(*digest)?;
                }
            }
        }
    }
    w.digest(snapshot.head_digest)?;
    Ok(w.0)
}

pub(super) fn decode(bytes: &[u8]) -> Result<LearningIterationSnapshotV1, Error> {
    if bytes.len() > MAX_BYTES { return Err(Error::Capacity); }
    let mut r = Reader { bytes, offset: 0 };
    if &r.take::<8>()? != MAGIC { return Err(Error::InvalidRecord); }
    let request = LearningIterationRequestV1 {
        operation_id: r.id()?, principal_id: r.id()?, agent_id: r.id()?,
        cell_id: r.id()?, source_run_id: r.id()?, completed_task_receipt: r.digest()?,
        selected_artifact_digest: r.digest()?, selected_bundle: r.bundle()?,
        envelope: IterationEnvelopeV1 {
            envelope_id: r.id()?, base_commit: r.digest()?, base_tree: r.digest()?,
            objective_digest: r.digest()?, grammar_digest: r.digest()?,
            maximum_files: r.u16()?, maximum_diff_bytes: r.u64()?,
            maximum_candidates: r.u16()?, maximum_parallel_sandboxes: r.u8()?,
            expiry_unix_seconds: r.u64()?,
        },
        budget: LearningIterationBudgetV1 {
            maximum_dataset_rows: r.u32()?, maximum_dataset_bytes: r.u64()?,
            maximum_training_steps: r.u64()?, maximum_training_milliseconds: r.u64()?,
            maximum_artifact_bytes: r.u64()?,
        },
    };
    let owners = LearningIterationOwnersV1 {
        evidence_trust_digest: r.digest()?, experience: r.id()?, dataset: r.id()?,
        trainer: r.id()?, evaluator: r.id()?, proposal: r.id()?,
        selector: r.id()?, next_use_observer: r.id()?,
    };
    let count = usize::from(r.u8()?);
    if count > MAX_RECEIPTS { return Err(Error::Capacity); }
    let mut receipts = Vec::with_capacity(count);
    for _ in 0..count {
        receipts.push(LearningIterationReceiptV1 {
            operation_id: r.id()?, predecessor: r.digest()?, actor_id: r.id()?,
            evidence_digest: r.digest()?, observed_unix_seconds: r.u64()?,
            observation: match r.u8()? {
                0 => LearningIterationObservationV1::Experience {
                    episode_digest: r.digest()?, completed_task_receipt: r.digest()?,
                },
                1 => LearningIterationObservationV1::Dataset {
                    snapshot_digest: r.digest()?, episode_digest: r.digest()?,
                    withdrawal_frontier: r.digest()?, rows: r.u32()?, bytes: r.u64()?,
                },
                2 => LearningIterationObservationV1::Training {
                    candidate: Box::new(r.bundle()?), steps: r.u64()?, milliseconds: r.u64()?, artifact_bytes: r.u64()?,
                },
                3 => LearningIterationObservationV1::Evaluation {
                    candidate_bundle: r.digest()?, evaluation_profile: r.digest()?,
                    disposition: match r.u8()? {
                        0 => LearningEvaluationDispositionV1::Qualified,
                        1 => LearningEvaluationDispositionV1::NoUpdate,
                        _ => return Err(Error::InvalidRecord),
                    },
                },
                4 => LearningIterationObservationV1::Proposal {
                    candidate_bundle: r.digest()?, proposal_id: r.id()?, composition_digest: r.digest()?,
                    disposition: match r.u8()? {
                        0 => LearningProposalDispositionV1::UpdateCandidates,
                        1 => LearningProposalDispositionV1::NoAdmissibleUpdate,
                        _ => return Err(Error::InvalidRecord),
                    },
                },
                5 => LearningIterationObservationV1::Selection {
                    candidate_bundle: r.digest()?, selection_digest: r.digest()?,
                },
                6 => LearningIterationObservationV1::NextUse {
                    candidate_bundle: r.digest()?, state_partition: r.partition()?,
                    checkpoint_digest: r.digest()?, selection_digest: r.digest()?,
                    committed_step_receipt: r.digest()?, state_cutover_receipt: r.digest()?,
                },
                7 => LearningIterationObservationV1::RetainedModelNextUse {
                    retained_bundle: r.digest()?, state_partition: r.partition()?,
                    checkpoint_digest: r.digest()?, selection_digest: r.digest()?,
                    committed_step_receipt: r.digest()?, task_owner_publication: r.digest()?,
                },
                _ => return Err(Error::InvalidRecord),
            },
        });
    }
    let snapshot = LearningIterationSnapshotV1 { request, owners, receipts, head_digest: r.digest()? };
    if r.offset != bytes.len() { return Err(Error::InvalidRecord); }
    LearningIterationCoordinatorV1::from_snapshot(snapshot.clone()).map_err(Error::Snapshot)?;
    Ok(snapshot)
}

struct Writer(Vec<u8>);
impl Writer {
    fn put(&mut self, bytes: &[u8]) -> Result<(), Error> {
        if self.0.len().checked_add(bytes.len()).is_none_or(|n| n > MAX_BYTES) {
            return Err(Error::Capacity);
        }
        self.0.extend_from_slice(bytes);
        Ok(())
    }
    fn u8(&mut self, value: u8) -> Result<(), Error> { self.put(&[value]) }
    fn u16(&mut self, value: u16) -> Result<(), Error> { self.put(&value.to_be_bytes()) }
    fn u32(&mut self, value: u32) -> Result<(), Error> { self.put(&value.to_be_bytes()) }
    fn u64(&mut self, value: u64) -> Result<(), Error> { self.put(&value.to_be_bytes()) }
    fn digest(&mut self, value: Digest32) -> Result<(), Error> { self.put(value.as_array()) }
    fn id(&mut self, value: &StableId) -> Result<(), Error> {
        let bytes = value.as_str().as_bytes();
        if bytes.len() > MAX_ID_BYTES { return Err(Error::Capacity); }
        self.u8(u8::try_from(bytes.len()).map_err(|_| Error::Capacity)?)?;
        self.put(bytes)
    }
    fn optional_digest(&mut self, value: Option<Digest32>) -> Result<(), Error> {
        self.u8(u8::from(value.is_some()))?;
        if let Some(value) = value { self.digest(value)?; }
        Ok(())
    }
    fn partition(&mut self, value: &CellStatePartitionV1) -> Result<(), Error> {
        for id in [&value.principal_id, &value.agent_id, &value.cell_id, &value.run_id] { self.id(id)?; }
        Ok(())
    }
    fn bundle(&mut self, value: &CellCompatibilityBundleV1) -> Result<(), Error> {
        self.id(&value.artifact_id)?;
        self.u64(value.generation.get())?;
        let c = &value.components;
        for digest in [c.base, c.heads, c.composition, c.encoder, c.tokenizer, c.normalizer,
            c.calibration, c.numeric_profile, c.output_schema, c.state_schema, c.state_semantics] {
            self.digest(digest)?;
        }
        self.optional_digest(c.organ_adapter)?;
        self.optional_digest(c.cell_adapter)?;
        self.optional_digest(value.rollback_predecessor)?;
        self.u8(u8::from(value.training_lineage.is_some()))?;
        if let Some(lineage) = &value.training_lineage {
            for digest in [lineage.source_bundle, lineage.dataset, lineage.update_rule, lineage.evaluation_profile] {
                self.digest(digest)?;
            }
        }
        Ok(())
    }
}

struct Reader<'a> { bytes: &'a [u8], offset: usize }
impl Reader<'_> {
    fn take<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        let end = self.offset.checked_add(N).ok_or(Error::Capacity)?;
        let bytes = self.bytes.get(self.offset..end).ok_or(Error::InvalidRecord)?;
        let value = bytes.try_into().map_err(|_| Error::InvalidRecord)?;
        self.offset = end;
        Ok(value)
    }
    fn u8(&mut self) -> Result<u8, Error> { Ok(self.take::<1>()?[0]) }
    fn u16(&mut self) -> Result<u16, Error> { Ok(u16::from_be_bytes(self.take()?)) }
    fn u32(&mut self) -> Result<u32, Error> { Ok(u32::from_be_bytes(self.take()?)) }
    fn u64(&mut self) -> Result<u64, Error> { Ok(u64::from_be_bytes(self.take()?)) }
    fn digest(&mut self) -> Result<Digest32, Error> { Ok(Digest32::from_array(self.take()?)) }
    fn id(&mut self) -> Result<StableId, Error> {
        let count = usize::from(self.u8()?);
        if count > MAX_ID_BYTES { return Err(Error::Capacity); }
        let end = self.offset.checked_add(count).ok_or(Error::Capacity)?;
        let bytes = self.bytes.get(self.offset..end).ok_or(Error::InvalidRecord)?;
        let text = std::str::from_utf8(bytes).map_err(|_| Error::InvalidRecord)?;
        let value = StableId::new(text).map_err(|_| Error::InvalidRecord)?;
        self.offset = end;
        Ok(value)
    }
    fn optional_digest(&mut self) -> Result<Option<Digest32>, Error> {
        match self.u8()? {
            0 => Ok(None), 1 => Ok(Some(self.digest()?)), _ => Err(Error::InvalidRecord),
        }
    }
    fn partition(&mut self) -> Result<CellStatePartitionV1, Error> {
        Ok(CellStatePartitionV1 { principal_id: self.id()?, agent_id: self.id()?, cell_id: self.id()?, run_id: self.id()? })
    }
    fn bundle(&mut self) -> Result<CellCompatibilityBundleV1, Error> {
        let artifact_id = self.id()?;
        let generation = Generation::new(self.u64()?).map_err(|_| Error::InvalidRecord)?;
        let components = CellBundleComponentsV1 {
            base: self.digest()?, heads: self.digest()?, composition: self.digest()?,
            encoder: self.digest()?, tokenizer: self.digest()?, normalizer: self.digest()?,
            calibration: self.digest()?, numeric_profile: self.digest()?, output_schema: self.digest()?,
            state_schema: self.digest()?, state_semantics: self.digest()?,
            organ_adapter: self.optional_digest()?, cell_adapter: self.optional_digest()?,
        };
        let rollback_predecessor = self.optional_digest()?;
        let training_lineage = match self.u8()? {
            0 => None,
            1 => Some(CellTrainingLineageV1 { source_bundle: self.digest()?, dataset: self.digest()?, update_rule: self.digest()?, evaluation_profile: self.digest()? }),
            _ => return Err(Error::InvalidRecord),
        };
        Ok(CellCompatibilityBundleV1 { artifact_id, generation, components, training_lineage, rollback_predecessor })
    }
}
