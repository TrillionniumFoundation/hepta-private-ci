//! Bounded, canonical records for the shared Cell owner journal.

use crate::NeuronModelRequestV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::SparseCheckpoint;
use crate::SparseTick;
use crate::cell_journal::CellJournalPartitionV1;
use crate::cell_owner::CellPartitionOwnerV1;
use crate::cell_types::*;
use crate::sparse_tick;

pub(crate) const MAX_FRAME_BYTES: usize = 131_072;

pub(crate) fn encode_commit(
    index: usize,
    proposal: &CellStateProposalV1,
    committed_at_micros: u64,
) -> Vec<u8> {
    let mut bytes = vec![0];
    put_u64(&mut bytes, index as u64);
    put_u64(&mut bytes, proposal.snapshot.revision);
    put_u64(&mut bytes, proposal.snapshot.writer_epoch);
    put_u64(&mut bytes, proposal.deadline_micros);
    put_u64(&mut bytes, proposal.decided_at_micros);
    put_u64(&mut bytes, committed_at_micros);
    let tick = &proposal.tick;
    for digest in [
        tick.scope_digest,
        tick.objective_digest,
        tick.ndu_digest,
        tick.body_digest,
        tick.input_digest,
    ] {
        put_digest(&mut bytes, digest);
    }
    put_u64(&mut bytes, tick.sequence);
    put_u64(&mut bytes, tick.monotonic_micros);
    for values in [&tick.drive_q24, &tick.prediction_q24] {
        put_u64(&mut bytes, values.len() as u64);
        for value in values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    let r = &proposal.receipt;
    put_id(&mut bytes, &r.operation_id);
    for digest in [
        r.operation_digest,
        r.semantic_request_digest,
        r.bundle_digest,
        r.source_frontier,
        r.checkpoint_before,
        r.checkpoint_after,
        r.model_output_digest,
    ] {
        put_digest(&mut bytes, digest);
    }
    put_id(&mut bytes, &r.selected_candidate);
    put_u64(&mut bytes, u64::from(r.confidence_ppm));
    put_u64(&mut bytes, u64::from(r.ood_ppm));
    bytes.push(u8::from(r.deadline_exceeded));
    put_u64(&mut bytes, r.policy.len() as u64);
    for entry in &r.policy {
        put_id(&mut bytes, &entry.candidate_id);
        bytes.push(u8::from(entry.allowed));
        put_u64(&mut bytes, u64::from(entry.probability_ppm));
    }
    let c = &r.cost;
    for number in [
        c.model_latency_micros,
        c.queue_age_micros,
        c.resident_bytes,
        c.transient_allocation_bytes,
        c.checkpoint_bytes,
        c.consumed_input_bytes as u64,
        c.truncated_input_bytes as u64,
    ] {
        put_u64(&mut bytes, number);
    }
    bytes
}

pub(crate) fn encode_admission(index: usize, admission: &CellInferenceAdmissionV1) -> Vec<u8> {
    let mut bytes = vec![2];
    put_u64(&mut bytes, index as u64);
    put_u64(&mut bytes, admission.snapshot.revision);
    put_u64(&mut bytes, admission.snapshot.writer_epoch);
    for digest in [
        admission.snapshot.scope.digest(),
        admission.snapshot.definition_digest,
        admission.snapshot.source_frontier,
        admission
            .snapshot
            .checkpoint
            .as_ref()
            .map_or(Digest32::ZERO, SparseCheckpoint::digest),
    ] {
        put_digest(&mut bytes, digest);
    }
    put_id(&mut bytes, &admission.operation_id);
    put_digest(&mut bytes, admission.semantic_request_digest);
    put_u64(&mut bytes, admission.deadline_micros);
    put_u64(&mut bytes, admission.admitted_at_micros);
    let r = &admission.model_request;
    for id in [&r.request_id, &r.config_id, &r.model_id] {
        put_id(&mut bytes, id);
    }
    put_u64(&mut bytes, r.generation.get());
    for digest in [
        r.encoder_digest,
        r.head_digest,
        r.weights_digest,
        r.input_digest,
    ] {
        put_digest(&mut bytes, digest);
    }
    put_u64(&mut bytes, r.feature_vector_q24.len() as u64);
    for value in &r.feature_vector_q24 {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    put_u64(&mut bytes, r.expected_output_width as u64);
    bytes
}

pub(crate) fn encode_reset(index: usize, frontier: Digest32, epoch: u64) -> Vec<u8> {
    let mut bytes = vec![1];
    put_u64(&mut bytes, index as u64);
    put_digest(&mut bytes, frontier);
    put_u64(&mut bytes, epoch);
    bytes
}

pub(crate) fn apply_record(
    bytes: &[u8],
    specs: &[CellJournalPartitionV1],
    owner: &mut CellPartitionOwnerV1,
) -> Result<(), CellExecutionError> {
    let mut read = Reader(bytes);
    let tag = read.byte()?;
    let index = read.usize()?;
    let spec = specs.get(index).ok_or(CellExecutionError::JournalCorrupt)?;
    if tag == 1 {
        let frontier = read.digest()?;
        let epoch = read.u64()?;
        read.finish()?;
        return owner.reset_at_frontier(&spec.scope, frontier, epoch);
    }
    if tag == 2 {
        let snapshot = owner.snapshot(&spec.scope)?;
        if read.u64()? != snapshot.revision
            || read.u64()? != snapshot.writer_epoch
            || read.digest()? != snapshot.scope.digest()
            || read.digest()? != snapshot.definition_digest
            || read.digest()? != snapshot.source_frontier
            || read.digest()?
                != snapshot
                    .checkpoint
                    .as_ref()
                    .map_or(Digest32::ZERO, SparseCheckpoint::digest)
        {
            return Err(CellExecutionError::JournalCorrupt);
        }
        let operation_id = read.id()?;
        let semantic_request_digest = read.digest()?;
        let deadline_micros = read.u64()?;
        let admitted_at_micros = read.u64()?;
        let model_request = NeuronModelRequestV1 {
            request_id: read.id()?,
            config_id: read.id()?,
            model_id: read.id()?,
            generation: Generation::new(read.u64()?)
                .map_err(|_| CellExecutionError::JournalCorrupt)?,
            encoder_digest: read.digest()?,
            head_digest: read.digest()?,
            weights_digest: read.digest()?,
            input_digest: read.digest()?,
            feature_vector_q24: read.q24(/*bound*/ 512)?,
            expected_output_width: read.usize()?,
        };
        read.finish()?;
        let config = &spec.definition.runtime;
        if model_request.config_id != config.config_id
            || model_request.model_id != config.model_id
            || model_request.generation != config.generation
            || model_request.encoder_digest != config.encoder_digest
            || model_request.head_digest != config.head_digest
            || model_request.weights_digest != config.weights_digest
            || model_request.feature_vector_q24.len() != config.input_feature_dimension
            || model_request.expected_output_width != config.state_width
        {
            return Err(CellExecutionError::JournalCorrupt);
        }
        return owner.admit_inference(CellInferenceAdmissionV1 {
            snapshot,
            operation_id,
            semantic_request_digest,
            model_request,
            deadline_micros,
            admitted_at_micros,
        });
    }
    if tag != 0 {
        return Err(CellExecutionError::JournalCorrupt);
    }
    let snapshot = owner.snapshot(&spec.scope)?;
    if read.u64()? != snapshot.revision || read.u64()? != snapshot.writer_epoch {
        return Err(CellExecutionError::JournalCorrupt);
    }
    let deadline_micros = read.u64()?;
    let decided_at_micros = read.u64()?;
    let committed_at_micros = read.u64()?;
    let tick = SparseTick {
        scope_digest: read.digest()?,
        objective_digest: read.digest()?,
        ndu_digest: read.digest()?,
        body_digest: read.digest()?,
        input_digest: read.digest()?,
        sequence: read.u64()?,
        monotonic_micros: read.u64()?,
        drive_q24: read.q24(/*bound*/ 256)?,
        prediction_q24: read.q24(/*bound*/ 256)?,
    };
    let operation_id = read.id()?;
    let operation_digest = read.digest()?;
    let semantic_request_digest = read.digest()?;
    let bundle_digest = read.digest()?;
    let source_frontier = read.digest()?;
    let checkpoint_before = read.digest()?;
    let checkpoint_after = read.digest()?;
    let model_output_digest = read.digest()?;
    let selected_candidate = read.id()?;
    let confidence_ppm = read.ppm()?;
    let ood_ppm = read.ppm()?;
    let deadline_exceeded = read.boolean()?;
    let count = read.count(/*bound*/ 256)?;
    let mut policy = Vec::with_capacity(count);
    for _ in 0..count {
        policy.push(CellPolicyEntryV1 {
            candidate_id: read.id()?,
            allowed: read.boolean()?,
            probability_ppm: read.ppm()?,
        });
    }
    let cost = CellExecutionCostV1 {
        model_latency_micros: read.u64()?,
        queue_age_micros: read.u64()?,
        resident_bytes: read.u64()?,
        transient_allocation_bytes: read.u64()?,
        checkpoint_bytes: read.u64()?,
        consumed_input_bytes: read.usize()?,
        truncated_input_bytes: read.usize()?,
    };
    read.finish()?;
    let (checkpoint, _) = sparse_tick(&spec.definition.native, &tick, snapshot.checkpoint.as_ref())
        .map_err(|_| CellExecutionError::JournalCorrupt)?;
    if deadline_micros <= tick.monotonic_micros
        || decided_at_micros < tick.monotonic_micros
        || committed_at_micros < decided_at_micros
        || deadline_exceeded != (committed_at_micros >= deadline_micros)
        || tick.monotonic_micros == 0
        || tick.scope_digest != spec.scope.digest()
        || tick.body_digest != spec.definition.bundle_digest
        || tick.input_digest != operation_digest
        || semantic_request_digest.is_zero()
        || bundle_digest != spec.definition.bundle_digest
        || source_frontier != snapshot.source_frontier
        || checkpoint_before
            != snapshot
                .checkpoint
                .as_ref()
                .map_or(Digest32::ZERO, SparseCheckpoint::digest)
        || checkpoint_after != checkpoint.digest()
        || model_output_digest.is_zero()
        || cost.checkpoint_bytes != checkpoint.bounded_encoded_bytes() as u64
        || cost
            .consumed_input_bytes
            .checked_add(cost.truncated_input_bytes)
            .is_none_or(|total| total > spec.definition.max_input_bytes)
        || policy.len() != spec.definition.candidates.len()
        || policy
            .iter()
            .zip(&spec.definition.candidates)
            .any(|(p, c)| {
                p.candidate_id != c.candidate_id
                    || (c.kind == CellCandidateKindV1::Abstain && !p.allowed)
                    || (!p.allowed && p.probability_ppm != 0)
            })
        || policy
            .iter()
            .filter(|p| p.probability_ppm == 1_000_000 && p.candidate_id == selected_candidate)
            .count()
            != 1
        || policy
            .iter()
            .map(|p| u64::from(p.probability_ppm))
            .sum::<u64>()
            != 1_000_000
    {
        return Err(CellExecutionError::JournalCorrupt);
    }
    let abstain_candidate = spec
        .definition
        .candidates
        .iter()
        .find(|c| c.kind == CellCandidateKindV1::Abstain)
        .ok_or(CellExecutionError::JournalCorrupt)?
        .candidate_id
        .clone();
    if deadline_exceeded && selected_candidate != abstain_candidate {
        return Err(CellExecutionError::JournalCorrupt);
    }
    let receipt = CellDecisionReceiptV1 {
        operation_id,
        operation_digest,
        semantic_request_digest,
        scope: spec.scope.clone(),
        bundle_digest,
        source_frontier,
        checkpoint_before,
        checkpoint_after,
        model_output_digest,
        policy,
        selected_candidate,
        confidence_ppm,
        ood_ppm,
        deadline_exceeded,
        cost,
        authority: AuthorityPosture::DENY_ALL,
    };
    owner.commit(
        CellStateProposalV1 {
            snapshot,
            checkpoint,
            receipt,
            deadline_micros,
            tick,
            abstain_candidate,
            decided_at_micros,
            settled_at_micros: committed_at_micros,
        },
        committed_at_micros,
    )?;
    Ok(())
}

fn put_u64(bytes: &mut Vec<u8>, number: u64) {
    bytes.extend_from_slice(&number.to_be_bytes());
}

fn put_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) {
    put_u64(bytes, id.as_str().len() as u64);
    bytes.extend_from_slice(id.as_str().as_bytes());
}

struct Reader<'a>(&'a [u8]);

impl Reader<'_> {
    fn take<const N: usize>(&mut self) -> Result<[u8; N], CellExecutionError> {
        if self.0.len() < N {
            return Err(CellExecutionError::JournalCorrupt);
        }
        let (head, tail) = self.0.split_at(N);
        self.0 = tail;
        head.try_into()
            .map_err(|_| CellExecutionError::JournalCorrupt)
    }

    fn byte(&mut self) -> Result<u8, CellExecutionError> {
        Ok(self.take::<1>()?[0])
    }

    fn u64(&mut self) -> Result<u64, CellExecutionError> {
        Ok(u64::from_be_bytes(self.take()?))
    }

    fn usize(&mut self) -> Result<usize, CellExecutionError> {
        usize::try_from(self.u64()?).map_err(|_| CellExecutionError::JournalCorrupt)
    }

    fn ppm(&mut self) -> Result<u32, CellExecutionError> {
        let value = self.u64()?;
        if value > 1_000_000 {
            return Err(CellExecutionError::JournalCorrupt);
        }
        Ok(value as u32)
    }

    fn count(&mut self, bound: usize) -> Result<usize, CellExecutionError> {
        let n = self.usize()?;
        if n > bound {
            return Err(CellExecutionError::JournalCorrupt);
        }
        Ok(n)
    }

    fn digest(&mut self) -> Result<Digest32, CellExecutionError> {
        Ok(Digest32::from_array(self.take()?))
    }

    fn boolean(&mut self) -> Result<bool, CellExecutionError> {
        match self.byte()? {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(CellExecutionError::JournalCorrupt),
        }
    }

    fn id(&mut self) -> Result<StableId, CellExecutionError> {
        let n = self.count(/*bound*/ 1024)?;
        if self.0.len() < n {
            return Err(CellExecutionError::JournalCorrupt);
        }
        let (id, tail) = self.0.split_at(n);
        self.0 = tail;
        StableId::new(
            std::str::from_utf8(id)
                .map_err(|_| CellExecutionError::JournalCorrupt)?
                .to_string(),
        )
        .map_err(|_| CellExecutionError::JournalCorrupt)
    }

    fn q24(&mut self, bound: usize) -> Result<Vec<i64>, CellExecutionError> {
        let n = self.count(bound)?;
        (0..n)
            .map(|_| Ok(i64::from_be_bytes(self.take()?)))
            .collect()
    }

    fn finish(self) -> Result<(), CellExecutionError> {
        if self.0.is_empty() {
            Ok(())
        } else {
            Err(CellExecutionError::JournalCorrupt)
        }
    }
}
