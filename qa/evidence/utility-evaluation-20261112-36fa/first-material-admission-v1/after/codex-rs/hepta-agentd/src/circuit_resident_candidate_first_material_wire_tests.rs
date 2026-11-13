//! Bounded test control data. None of these decoded values is an owner or
//! authenticated Source publication; the parent supplies all trust and policy.
use super::*;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use serde::{Deserialize, Serialize};

const PURPOSE: &str = "hepta.fixture.pending-original-material.v1";
pub(super) const CONTROL_LIMIT: usize = 64 * 1024;
const SNAPSHOT_LIMIT: usize = 8192;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Evidence {
    evidence_id: String,
    principal_id: String,
    trust: String,
    scope: String,
    objective: String,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    payload_digest: String,
    signature: String,
}

impl Evidence {
    fn from_original(value: &SignedLearningEvidenceV1, role: LearningEvidenceRoleV1) -> anyhow::Result<Self> {
        anyhow::ensure!(value.role == role, "the field fixes the original evidence role");
        Ok(Self {
            evidence_id: value.evidence_id.to_string(), principal_id: value.principal_id.to_string(),
            trust: value.trust_digest.to_string(), scope: value.scope_digest.to_string(),
            objective: value.objective_digest.to_string(), authority_epoch: value.authority_epoch,
            issued_at: value.issued_at, expires_at: value.expires_at,
            payload_digest: value.payload_digest.to_string(), signature: STANDARD_NO_PAD.encode(value.signature),
        })
    }

    fn original(&self, role: LearningEvidenceRoleV1) -> anyhow::Result<SignedLearningEvidenceV1> {
        let signature = original_bytes(&self.signature, 64)?;
        let signature: [u8; 64] = signature.try_into().map_err(|_| anyhow::anyhow!("complete original signature"))?;
        Ok(SignedLearningEvidenceV1 {
            evidence_id: StableId::new(self.evidence_id.as_str())?,
            principal_id: StableId::new(self.principal_id.as_str())?, role,
            trust_digest: self.trust.parse()?, scope_digest: self.scope.parse()?,
            objective_digest: self.objective.parse()?, authority_epoch: self.authority_epoch,
            issued_at: self.issued_at, expires_at: self.expires_at,
            payload_digest: self.payload_digest.parse()?, signature,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Completeness {
    set_id: String,
    state_digest: String,
    generator_id: String,
    generator_code_digest: String,
    grammar_digest: String,
    hard_filter_digest: String,
    truncation_digest: String,
    candidates_digest: String,
    candidate_count: u32,
    omitted_count_bound: u32,
    canonical_order_digest: String,
    complete_for_generator: bool,
}

impl Completeness {
    fn from_original(value: &CandidateSetCompletenessReceiptV1) -> Self {
        Self {
            set_id: value.set_id.to_string(), state_digest: value.state_digest.to_string(),
            generator_id: value.generator_id.to_string(), generator_code_digest: value.generator_code_digest.to_string(),
            grammar_digest: value.grammar_digest.to_string(), hard_filter_digest: value.hard_filter_digest.to_string(),
            truncation_digest: value.truncation_digest.to_string(), candidates_digest: value.candidates_digest.to_string(),
            candidate_count: value.candidate_count, omitted_count_bound: value.omitted_count_bound,
            canonical_order_digest: value.canonical_order_digest.to_string(), complete_for_generator: value.complete_for_generator,
        }
    }

    fn original(&self) -> anyhow::Result<CandidateSetCompletenessReceiptV1> {
        Ok(CandidateSetCompletenessReceiptV1 {
            set_id: StableId::new(self.set_id.as_str())?, state_digest: self.state_digest.parse()?,
            generator_id: StableId::new(self.generator_id.as_str())?, generator_code_digest: self.generator_code_digest.parse()?,
            grammar_digest: self.grammar_digest.parse()?, hard_filter_digest: self.hard_filter_digest.parse()?,
            truncation_digest: self.truncation_digest.parse()?, candidates_digest: self.candidates_digest.parse()?,
            candidate_count: self.candidate_count, omitted_count_bound: self.omitted_count_bound,
            canonical_order_digest: self.canonical_order_digest.parse()?, complete_for_generator: self.complete_for_generator,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Report {
    purpose: String,
    initial: String,
    ledger: String,
    completeness: Completeness,
    decision: Evidence,
    decision_admitted_at: u64,
    outcome: Evidence,
    outcome_admitted_at: u64,
    freeze: Evidence,
    scope_binding: String,
}

pub(super) struct DecodedReport {
    pub(super) initial: LearningIterationSnapshotV1,
    pub(super) ledger: LedgerSnapshot,
    pub(super) completeness: CandidateSetCompletenessReceiptV1,
    pub(super) decision: SignedLearningEvidenceV1,
    pub(super) decision_admitted_at: u64,
    pub(super) outcome: SignedLearningEvidenceV1,
    pub(super) outcome_admitted_at: u64,
    pub(super) freeze: SignedLearningEvidenceV1,
    pub(super) scope_binding: Digest32,
}

fn original_bytes(value: &str, maximum: usize) -> anyhow::Result<Vec<u8>> {
    let bytes = STANDARD_NO_PAD.decode(value)?;
    anyhow::ensure!(!bytes.is_empty() && bytes.len() <= maximum
        && STANDARD_NO_PAD.encode(&bytes) == value, "complete canonical bounded bytes");
    Ok(bytes)
}

pub(super) fn encode_original_report(
    material: &Material,
    ledger: &LedgerSnapshot,
    decision: &material::OriginalDecisionEvidence,
    outcome: &material::OriginalOutcomeEvidence,
) -> anyhow::Result<Vec<u8>> {
    let snapshot = encode_original_owner_snapshot_v1(&material.initial)?;
    anyhow::ensure!(snapshot.len() <= SNAPSHOT_LIMIT, "original checkpoint codec limit");
    let records = ledger.records();
    anyhow::ensure!(records.len() == 2, "complete single-A fixture history, never a filtered subset");
    let report = Report {
        purpose: PURPOSE.into(), initial: STANDARD_NO_PAD.encode(snapshot),
        ledger: STANDARD_NO_PAD.encode(encode_original_ledger_snapshot_v1(ledger)?),
        completeness: Completeness::from_original(&decision.request.completeness),
        decision: Evidence::from_original(&decision.evidence, LearningEvidenceRoleV1::Generator)?,
        decision_admitted_at: decision.admitted_at,
        outcome: Evidence::from_original(&outcome.evidence, LearningEvidenceRoleV1::Observer)?,
        outcome_admitted_at: outcome.admitted_at,
        freeze: Evidence::from_original(&material.freeze_evidence, LearningEvidenceRoleV1::Evaluator)?,
        scope_binding: material.scope.binding().to_string(),
    };
    let bytes = serde_json::to_vec(&report)?;
    anyhow::ensure!(!bytes.is_empty() && bytes.len() <= CONTROL_LIMIT,
        "one complete control frame including JSON and base64 overhead");
    Ok(bytes)
}

pub(super) fn decode_report(bytes: &[u8]) -> anyhow::Result<DecodedReport> {
    anyhow::ensure!(!bytes.is_empty() && bytes.len() <= CONTROL_LIMIT, "bounded complete control frame");
    let report: Report = serde_json::from_slice(bytes)?;
    anyhow::ensure!(report.purpose == PURPOSE && serde_json::to_vec(&report)? == bytes,
        "fixed purpose, complete canonical report, no unknown fields or trailing bytes");
    let initial_bytes = original_bytes(&report.initial, SNAPSHOT_LIMIT)?;
    let initial = decode_original_owner_snapshot_v1(&initial_bytes)?;
    anyhow::ensure!(encode_original_owner_snapshot_v1(&initial)? == initial_bytes, "original full snapshot codec");
    let ledger_bytes = original_bytes(&report.ledger, MAX_ORIGINAL_LEDGER_SNAPSHOT_BYTES_V1)?;
    let ledger = decode_original_ledger_snapshot_v1(&ledger_bytes)?;
    anyhow::ensure!(encode_original_ledger_snapshot_v1(&ledger)? == ledger_bytes, "full original ledger replay and encoding");
    Ok(DecodedReport {
        initial, ledger, completeness: report.completeness.original()?,
        decision: report.decision.original(LearningEvidenceRoleV1::Generator)?,
        decision_admitted_at: report.decision_admitted_at,
        outcome: report.outcome.original(LearningEvidenceRoleV1::Observer)?,
        outcome_admitted_at: report.outcome_admitted_at,
        freeze: report.freeze.original(LearningEvidenceRoleV1::Evaluator)?,
        scope_binding: report.scope_binding.parse()?,
    })
}

pub(super) fn canonical_mutation(value: serde_json::Value) -> anyhow::Result<Vec<u8>> {
    Ok(serde_json::to_vec(&serde_json::from_value::<Report>(value)?)?)
}
