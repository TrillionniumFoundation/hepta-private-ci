//! Private complete recovery encoding. Parsing never constructs a sealed
//! Dataset: its receipt and batch are opaque bytes until original-owner replay
//! reproduces them exactly. All lengths are bounded before allocation.

use codex_hepta_intelligence_eval::MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 as LIMIT;

use super::*;

const MAGIC: &[u8] = b"HQ24DSR1";

#[derive(Clone)]
pub(super) struct SavedMaterial {
    pub(super) profile: CellQ24DatasetProfileV1,
    pub(super) plan: DatasetFreezePlanV2,
    pub(super) original_head: Digest32,
    pub(super) evidence: SignedLearningEvidenceV1,
    pub(super) freeze_payload: Vec<u8>,
    pub(super) receipt: Vec<u8>,
    pub(super) batch: Vec<u8>,
}

impl SavedMaterial {
    pub(super) fn from_original(
        plan: &DatasetFreezePlanV2,
        value: &OriginalCellQ24DatasetV1,
    ) -> Result<Self, RecoveryError> {
        Ok(Self {
            profile: value.profile.clone(),
            plan: plan.clone(),
            original_head: value.dataset.snapshot.ledger_head_digest,
            evidence: value.evidence.clone(),
            freeze_payload: value.freeze_payload.clone(),
            receipt: receipt_bytes(&value.dataset)?,
            batch: value.batch.encoded().to_vec(),
        })
    }
}

pub(super) fn encode(saved: &SavedMaterial) -> Result<Vec<u8>, RecoveryError> {
    saved.profile.digest()?;
    let mut w = Writer(Vec::new());
    w.put(MAGIC)?;
    let p = &saved.profile;
    for text in [
        p.principal_id.as_str(),
        p.agent_id.as_str(),
        p.cell_id.as_str(),
    ] {
        w.write_text(text)?;
    }
    for d in [
        p.principal_digest,
        p.ledger_binding,
        p.evidence_trust_digest,
        p.objective_digest,
        p.selected_bundle,
        p.outcome_unit_profile,
    ] {
        w.put(d.as_array())?;
    }
    w.put(&p.input_width.to_be_bytes())?;
    w.write_count(p.training_episodes.len())?;
    for row in &p.training_episodes {
        w.write_text(row.episode_id.as_str())?;
        w.put(row.run_snapshot_digest.as_array())?;
        w.put(row.decision_support_digest.as_array())?;
    }
    w.write_count(p.excluded_episodes.len())?;
    for id in &p.excluded_episodes {
        w.write_text(id.as_str())?;
    }
    w.write_text(saved.plan.snapshot_id.as_str())?;
    w.put(saved.plan.objective_digest.as_array())?;
    w.put(saved.plan.inclusion_policy_digest.as_array())?;
    w.put(saved.original_head.as_array())?;
    let e = &saved.evidence;
    w.write_text(e.evidence_id.as_str())?;
    w.write_text(e.principal_id.as_str())?;
    if e.role != LearningEvidenceRoleV1::Evaluator {
        return Err(invalid());
    }
    w.put(&[2])?;
    for d in [e.trust_digest, e.scope_digest, e.objective_digest] {
        w.put(d.as_array())?;
    }
    for n in [e.authority_epoch, e.issued_at, e.expires_at] {
        w.put(&n.to_be_bytes())?;
    }
    w.put(e.payload_digest.as_array())?;
    w.put(&e.signature)?;
    for bytes in [&saved.freeze_payload, &saved.receipt, &saved.batch] {
        w.write_blob(bytes)?;
    }
    Ok(w.0)
}

pub(super) fn decode(bytes: &[u8]) -> Result<SavedMaterial, RecoveryError> {
    if bytes.len() > LIMIT {
        return Err(capacity());
    }
    let mut r = Reader(bytes);
    if r.take(MAGIC.len())? != MAGIC {
        return Err(invalid());
    }
    let principal_id = r.id()?;
    let agent_id = AgentId::parse(r.read_text()?).map_err(|_| invalid())?;
    let cell_id = r.id()?;
    let principal_digest = r.digest()?;
    let ledger_binding = r.digest()?;
    let evidence_trust_digest = r.digest()?;
    let objective_digest = r.digest()?;
    let selected_bundle = r.digest()?;
    let outcome_unit_profile = r.digest()?;
    let input_width = u16::from_be_bytes(r.array()?);
    let n = r.read_count(64)?;
    let mut training_episodes = Vec::with_capacity(n);
    for _ in 0..n {
        training_episodes.push(CellQ24DatasetEpisodeV1 {
            episode_id: r.id()?,
            run_snapshot_digest: r.digest()?,
            decision_support_digest: r.digest()?,
        });
    }
    let n = r.read_count(64)?;
    let mut excluded_episodes = Vec::with_capacity(n);
    for _ in 0..n {
        excluded_episodes.push(r.id()?);
    }
    let profile = CellQ24DatasetProfileV1 {
        principal_id,
        agent_id,
        cell_id,
        principal_digest,
        ledger_binding,
        evidence_trust_digest,
        objective_digest,
        selected_bundle,
        outcome_unit_profile,
        input_width,
        training_episodes,
        excluded_episodes,
    };
    let plan = DatasetFreezePlanV2 {
        snapshot_id: r.id()?,
        objective_digest: r.digest()?,
        inclusion_policy_digest: r.digest()?,
    };
    let original_head = r.digest()?;
    let evidence_id = r.id()?;
    let principal_id = r.id()?;
    if r.take(1)? != [2] {
        return Err(invalid());
    }
    let evidence = SignedLearningEvidenceV1 {
        evidence_id,
        principal_id,
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: r.digest()?,
        scope_digest: r.digest()?,
        objective_digest: r.digest()?,
        authority_epoch: u64::from_be_bytes(r.array()?),
        issued_at: u64::from_be_bytes(r.array()?),
        expires_at: u64::from_be_bytes(r.array()?),
        payload_digest: r.digest()?,
        signature: r.array()?,
    };
    let saved = SavedMaterial {
        profile,
        plan,
        original_head,
        evidence,
        freeze_payload: r.read_blob()?.to_vec(),
        receipt: r.read_blob()?.to_vec(),
        batch: r.read_blob()?.to_vec(),
    };
    if !r.0.is_empty() || encode(&saved)? != bytes {
        return Err(invalid());
    }
    Ok(saved)
}

/// Every semantic receipt field, including all source IDs, producer and posture.
/// This is an injective private encoding, not the lossy DatasetSnapshotV1 wire.
pub(super) fn receipt_bytes(receipt: &DatasetSnapshotReceiptV3) -> Result<Vec<u8>, RecoveryError> {
    let mut w = Writer(Vec::new());
    let s = &receipt.snapshot;
    w.write_text(s.snapshot_id.as_str())?;
    for d in [s.ledger_head_digest, s.objective_digest] {
        w.put(d.as_array())?;
    }
    for n in [s.eligible_frontier, s.outcome_watermark] {
        w.put(&n.to_be_bytes())?;
    }
    if s.source_record_digests.len() > 4096 {
        return Err(capacity());
    }
    w.write_count(s.source_record_digests.len())?;
    for d in &s.source_record_digests {
        w.put(d.as_array())?;
    }
    for n in [s.pending_outcomes, s.censored_outcomes] {
        w.put(&n.to_be_bytes())?;
    }
    w.put(s.dataset_digest.as_array())?;
    w.put(&[s.authority.flags().wire_mask()])?;
    let p = &receipt.producer;
    w.write_text(p.principal_id.as_str())?;
    for d in [
        p.credential_chain_digest,
        p.signing_key_digest,
        p.scope_digest,
    ] {
        w.put(d.as_array())?;
    }
    for n in [p.authority_epoch, p.authenticated_at, p.expires_at] {
        w.put(&n.to_be_bytes())?;
    }
    for d in [
        receipt.correction_cut_digest,
        receipt.revocation_cut_digest,
        receipt.inclusion_policy_digest,
    ] {
        w.put(d.as_array())?;
    }
    Ok(w.0)
}

fn invalid() -> RecoveryError {
    RecoveryError::Binding("canonical complete Dataset recovery encoding")
}
fn capacity() -> RecoveryError {
    RecoveryError::Binding("Dataset recovery material exceeds 65536 bytes")
}

struct Writer(Vec<u8>);
impl Writer {
    fn put(&mut self, bytes: &[u8]) -> Result<(), RecoveryError> {
        if bytes.len() > LIMIT - self.0.len() {
            return Err(capacity());
        }
        self.0.extend_from_slice(bytes);
        Ok(())
    }
    fn write_count(&mut self, n: usize) -> Result<(), RecoveryError> {
        self.put(&u16::try_from(n).map_err(|_| invalid())?.to_be_bytes())
    }
    fn write_text(&mut self, text: &str) -> Result<(), RecoveryError> {
        if text.len() > 128 {
            return Err(invalid());
        }
        self.write_count(text.len())?;
        self.put(text.as_bytes())
    }
    fn write_blob(&mut self, bytes: &[u8]) -> Result<(), RecoveryError> {
        if bytes.len() > LIMIT {
            return Err(capacity());
        }
        self.put(&(bytes.len() as u32).to_be_bytes())?;
        self.put(bytes)
    }
}
struct Reader<'a>(&'a [u8]);
impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8], RecoveryError> {
        let bytes = self.0.get(..n).ok_or_else(invalid)?;
        self.0 = &self.0[n..];
        Ok(bytes)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], RecoveryError> {
        self.take(N)?.try_into().map_err(|_| invalid())
    }
    fn read_count(&mut self, limit: usize) -> Result<usize, RecoveryError> {
        let n = usize::from(u16::from_be_bytes(self.array()?));
        if n > limit {
            return Err(invalid());
        }
        Ok(n)
    }
    fn read_text(&mut self) -> Result<&'a str, RecoveryError> {
        let n = self.read_count(128)?;
        std::str::from_utf8(self.take(n)?).map_err(|_| invalid())
    }
    fn id(&mut self) -> Result<StableId, RecoveryError> {
        StableId::new(self.read_text()?).map_err(|_| invalid())
    }
    fn digest(&mut self) -> Result<Digest32, RecoveryError> {
        Ok(Digest32::from_array(self.array()?))
    }
    fn read_blob(&mut self) -> Result<&'a [u8], RecoveryError> {
        let n = u32::from_be_bytes(self.array()?) as usize;
        if n > LIMIT {
            return Err(capacity());
        }
        self.take(n)
    }
}
