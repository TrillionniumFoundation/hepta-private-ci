"""Apply the bounded intuition commitment migration; fail on unexpected source drift."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new, count=1):
    target = ROOT / path
    text = target.read_text()
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{path}: expected {count} matches, found {actual}")
    target.write_text(text.replace(old, new))


new_path = ROOT / "codex-rs/hepta-intuition/src/runtime_commitment_v2.rs"
if new_path.exists():
    raise SystemExit("V2 module already exists; reconcile instead of overwriting")
new_path.write_text(r'''//! Separated legal identity, scorer outputs and behavior assignment commitments.
//!
//! Historical V1 functions keep their byte encoding. New producer/consumer pairs
//! use V2 payloads through authenticated V3; the full request still binds every
//! assignment field, admission mask, score, profile and owner-supplied draw.

use codex_hepta_types::Digest32;

use crate::AssignmentCommitmentV1;
use crate::CalibratedActionCandidateV1;
use crate::CalibratedDecisionRequestV1;
use crate::CalibratedError;
use crate::CanonicalPolicyProfileV1;
use crate::RuntimeCommitmentError;
use crate::ScoringCommitmentV1;
use crate::canonical_calibrated_request_digest_v1;
use crate::canonical_policy_profile_digest_v1;
use crate::canonical_scoring_commitment_digest_v1;

/// Ordered legal identity and deterministic admission masks, not learned scores
/// or assignment probabilities. Runtime evidence binds the complete request.
pub fn canonical_candidate_identity_digest_v2(
    candidates: &[CalibratedActionCandidateV1],
) -> Result<Digest32, RuntimeCommitmentError> {
    if !(1..=128).contains(&candidates.len()) {
        return Err(CalibratedError::CandidateCountOutOfRange.into());
    }
    let mut bytes = b"hepta.intuition.candidate-identity.v2\0".to_vec();
    bytes.extend_from_slice(&(candidates.len() as u64).to_be_bytes());
    for candidate in candidates {
        let id = candidate.candidate_id.as_str().as_bytes();
        bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.push(u8::from(candidate.legal));
        bytes.push(u8::from(candidate.hard_veto));
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Scorer outputs over the ordered legal identity. Assignment-only changes do
/// not alter this value, but must alter the exact runtime evidence payload.
pub fn canonical_scored_outputs_digest_v2(
    request: &CalibratedDecisionRequestV1,
) -> Result<Digest32, RuntimeCommitmentError> {
    let identity = canonical_candidate_identity_digest_v2(&request.candidates)?;
    let mut bytes = b"hepta.intuition.scored-outputs.v2\0".to_vec();
    bytes.extend_from_slice(identity.as_array());
    for candidate in &request.candidates {
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.calibrated_confidence.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.ood_score.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// The bounded V1 carrier is reused, not its commitment interpretation. With
/// authenticated V3, candidate_set_digest is the V2 legal identity and the
/// scored_outputs_digest is V2. Domain separation rejects cross-version use.
pub fn canonical_scoring_commitment_digest_v2(
    scoring: &ScoringCommitmentV1,
) -> Result<Digest32, RuntimeCommitmentError> {
    let fields = canonical_scoring_commitment_digest_v1(scoring)?;
    Ok(Digest32::of_parts(&[
        b"hepta.intuition.scoring-commitment.v2\0",
        fields.as_array(),
    ]))
}

/// Exact per-request Observer payload for authenticated V3. Existing V1 payloads
/// and signatures remain historical compatibility surfaces and are not upgraded.
pub fn canonical_runtime_commitment_payload_v2(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV1,
    assignment: &AssignmentCommitmentV1,
) -> Result<Vec<u8>, RuntimeCommitmentError> {
    let identity = canonical_candidate_identity_digest_v2(&request.candidates)?;
    for (actual, expected, field) in [
        (scoring.model_artifact_digest, profile.scorer.model_digest, "model artifact"),
        (scoring.feature_schema_digest, profile.scorer.feature_schema_digest, "feature schema"),
        (scoring.scorer_contract_digest, profile.scorer.scorer_contract_digest, "scorer contract"),
        (scoring.policy_digest, profile.policy_digest, "policy"),
        (scoring.policy_digest, request.policy_digest, "request policy"),
        (scoring.candidate_set_digest, identity, "candidate identity"),
    ] {
        if actual != expected {
            return Err(RuntimeCommitmentError::ScoringIdentityMismatch(field));
        }
    }
    if scoring.policy_generation != profile.generation
        || scoring.policy_generation != request.policy_generation
    {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch("generation"));
    }
    if scoring.scored_outputs_digest != canonical_scored_outputs_digest_v2(request)? {
        return Err(RuntimeCommitmentError::ScoringDigestMismatch);
    }
    crate::runtime_commitment::validate_assignment(request, assignment)?;
    let request_digest = canonical_calibrated_request_digest_v1(request)?;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let scoring_digest = canonical_scoring_commitment_digest_v2(scoring)?;
    let mut bytes = b"hepta.intuition.runtime-commitment.v2\0".to_vec();
    for digest in [request_digest, profile_digest, scoring_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    match assignment {
        AssignmentCommitmentV1::Deterministic => bytes.push(0),
        AssignmentCommitmentV1::CounterBased {
            rng_owner_digest, random_stream_digest, counter, draw,
        } => {
            bytes.push(1);
            bytes.extend_from_slice(rng_owner_digest.as_array());
            bytes.extend_from_slice(random_stream_digest.as_array());
            bytes.extend_from_slice(&counter.to_be_bytes());
            bytes.extend_from_slice(&draw.raw().to_be_bytes());
        }
    }
    Ok(bytes)
}
''')
replace("codex-rs/hepta-intuition/src/lib.rs", "mod runtime_commitment;", "mod runtime_commitment;\nmod runtime_commitment_v2;")
replace("codex-rs/hepta-intuition/src/lib.rs", "pub use runtime_commitment::canonical_scoring_commitment_digest_v1;", """pub use runtime_commitment::canonical_scoring_commitment_digest_v1;
pub use runtime_commitment_v2::canonical_candidate_identity_digest_v2;
pub use runtime_commitment_v2::canonical_scored_outputs_digest_v2;
pub use runtime_commitment_v2::canonical_scoring_commitment_digest_v2;
pub use runtime_commitment_v2::canonical_runtime_commitment_payload_v2;""")
replace("codex-rs/hepta-intuition/src/runtime_commitment.rs", "fn validate_assignment(", "pub(super) fn validate_assignment(")
replace("codex-rs/hepta-intuition/src/runtime_commitment.rs", "/// Bind only the scorer-produced fields. Candidate-set identity is committed\n/// separately so assignment probabilities can remain an assignment concern.", "/// Historical V1 includes the full candidate digest, including assignment.\n/// Retain its bytes for signed-history compatibility; new scorers use V2.")

p = ROOT / "codex-rs/hepta-intelligence/src/intuition_qualification.rs"
s = p.read_text()
s = s.replace("use codex_hepta_intuition::canonical_runtime_commitment_payload_v1;", "use codex_hepta_intuition::canonical_runtime_commitment_payload_v1;\nuse codex_hepta_intuition::canonical_runtime_commitment_payload_v2;")
s = s.replace("use codex_hepta_intuition::canonical_scoring_commitment_digest_v1;", "use codex_hepta_intuition::canonical_scoring_commitment_digest_v1;\nuse codex_hepta_intuition::canonical_scoring_commitment_digest_v2;")
start = s.index("pub fn decide_authenticated_intuition_v2(")
body = s.index("    // Bind the permitted objective", start)
s = s[:body] + '''    decide_authenticated_intuition(request, profile, scoring, assignment, evidence,
        verifier, now, CommitmentEncoding::HistoricalV1)
}

/// New admission version for separated V2 scorer/assignment commitments.
/// Receipt/evidence carriers are retained; payload/authentication domains differ.
pub fn decide_authenticated_intuition_v3(
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV1,
    assignment: AssignmentCommitmentV1,
    evidence: IntuitionQualificationEvidenceV2<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedIntuitionDecisionV2, IntuitionQualificationError> {
    decide_authenticated_intuition(request, profile, scoring, assignment, evidence,
        verifier, now, CommitmentEncoding::SeparatedV2)
}

#[derive(Clone, Copy)]
enum CommitmentEncoding {
    HistoricalV1,
    SeparatedV2,
}

#[allow(clippy::too_many_arguments)]
fn decide_authenticated_intuition(
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV1,
    assignment: AssignmentCommitmentV1,
    evidence: IntuitionQualificationEvidenceV2<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
    encoding: CommitmentEncoding,
) -> Result<AuthenticatedIntuitionDecisionV2, IntuitionQualificationError> {
''' + s[body:]
old = "    let runtime_payload =\n        canonical_runtime_commitment_payload_v1(&request, &profile, &scoring, &assignment)?;"
assert s.count(old) == 1
s = s.replace(old, '''    let runtime_payload = match encoding {
        CommitmentEncoding::HistoricalV1 => canonical_runtime_commitment_payload_v1(&request, &profile, &scoring, &assignment)?,
        CommitmentEncoding::SeparatedV2 => canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)?,
    };''')
s = s.replace("    let scoring_commitment_digest = canonical_scoring_commitment_digest_v1(&scoring)?;", '''    let scoring_commitment_digest = match encoding {
        CommitmentEncoding::HistoricalV1 => canonical_scoring_commitment_digest_v1(&scoring)?,
        CommitmentEncoding::SeparatedV2 => canonical_scoring_commitment_digest_v2(&scoring)?,
    };''')
s = s.replace('    let mut bytes = b"hepta.intelligence.authenticated-intuition.v2\\0".to_vec();', '''    let mut bytes = match encoding {
        CommitmentEncoding::HistoricalV1 => b"hepta.intelligence.authenticated-intuition.v2\\0".to_vec(),
        CommitmentEncoding::SeparatedV2 => b"hepta.intelligence.authenticated-intuition.v3\\0".to_vec(),
    };''')
p.write_text(s)
replace("codex-rs/hepta-intelligence/src/lib.rs", "pub use intuition_qualification::decide_authenticated_intuition_v2;", "pub use intuition_qualification::decide_authenticated_intuition_v2;\npub use intuition_qualification::decide_authenticated_intuition_v3;")

p = ROOT / "codex-rs/hepta-intelligence/tests/intuition_admission_boundaries.rs"
s = p.read_text()
s = s.replace("use codex_hepta_intelligence::decide_authenticated_intuition_v2;", "use codex_hepta_intelligence::decide_authenticated_intuition_v2;\nuse codex_hepta_intelligence::decide_authenticated_intuition_v3;\nuse codex_hepta_intuition::canonical_candidate_identity_digest_v2;\nuse codex_hepta_intuition::canonical_scored_outputs_digest_v2;\nuse codex_hepta_intuition::canonical_runtime_commitment_payload_v2;")
s = s.replace("struct Fixture {", "enum FixtureEncoding { Historical, Separated }\n\nstruct Fixture {\n    encoding: FixtureEncoding,")
s = s.replace("        decide_authenticated_intuition_v2(\n", "        let decide = match self.encoding {\n            FixtureEncoding::Historical => decide_authenticated_intuition_v2,\n            FixtureEncoding::Separated => decide_authenticated_intuition_v3,\n        };\n        decide(\n", 1)
s = s.replace("impl Fixture {", '''impl Fixture {
    fn separated(mut self) -> Self {
        self.scoring.candidate_set_digest = canonical_candidate_identity_digest_v2(&self.request.candidates).expect("identity");
        self.scoring.scored_outputs_digest = canonical_scored_outputs_digest_v2(&self.request).expect("scores");
        let payload = canonical_runtime_commitment_payload_v2(&self.request, &self.profile,
            &self.scoring, &AssignmentCommitmentV1::Deterministic).expect("runtime V2");
        self.signed[2].payload_digest = Digest32::of_bytes(&payload);
        self.signed[2].signature = SigningKey::from_bytes(&[59; 32]).sign(&self.signed[2].signing_bytes()).to_bytes();
        self.verifier.verify(LearningEvidenceRoleV1::Observer, &self.signed[2], &payload, 150).expect("valid V2 signature");
        self.encoding = FixtureEncoding::Separated;
        self
    }
''', 1)
s = s.replace("    Fixture {\n        request,", "    Fixture {\n        encoding: FixtureEncoding::Historical,\n        request,", 1)
s += '''
#[test]
fn separated_v2_admits_independent_signed_v3() {
    assert!(fixture(d("objective"), "observer-controller").separated().decide().is_ok());
}

#[test]
fn separated_v2_rejects_valid_cross_objective_signatures() {
    assert_eq!(fixture(d("different-objective"), "observer-controller").separated().decide(),
        Err(IntuitionQualificationError::Evidence(SignedEvidenceError::ContextMismatch)));
}

#[test]
fn separated_v2_rejects_same_controller() {
    assert_eq!(fixture(d("objective"), "evaluator-controller").separated().decide(),
        Err(IntuitionQualificationError::Evidence(SignedEvidenceError::ControllerCollision)));
}

#[test]
fn assignment_changes_only_runtime_not_scorer_v2() {
    let mut value = fixture(d("objective"), "observer-controller").separated();
    let before_v1 = canonical_scored_outputs_digest_v1(&value.request).expect("historical");
    let before_runtime = canonical_runtime_commitment_payload_v2(&value.request, &value.profile,
        &value.scoring, &AssignmentCommitmentV1::Deterministic).expect("runtime");
    value.request.candidates[0].assignment_probability = ProbabilityQ32::ONE;
    assert_eq!(canonical_scored_outputs_digest_v2(&value.request).expect("scores"), value.scoring.scored_outputs_digest);
    assert_eq!(canonical_candidate_identity_digest_v2(&value.request.candidates).expect("identity"), value.scoring.candidate_set_digest);
    assert_ne!(canonical_scored_outputs_digest_v1(&value.request).expect("historical"), before_v1);
    assert_ne!(canonical_runtime_commitment_payload_v2(&value.request, &value.profile,
        &value.scoring, &AssignmentCommitmentV1::Deterministic).expect("changed runtime"), before_runtime);
    assert!(value.decide().is_err());
}

#[test]
fn historical_runtime_signature_cannot_be_promoted_to_v3() {
    let mut value = fixture(d("objective"), "observer-controller");
    value.encoding = FixtureEncoding::Separated;
    assert!(value.decide().is_err());
}
'''
p.write_text(s)

p = ROOT / "codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs"
s = p.read_text()
needle = "    let assignment = AssignmentCommitmentV1::Deterministic;"
assert s.count(needle) == 1
s = s.replace(needle, '''    // Frozen V1 encoding from the independently reproduced pre-migration source.
    assert_eq!(canonical_scored_outputs_digest_v1(&request).unwrap(),
        "96b0b69d7ba874d224c1f674e5e648de356483d543b3a5cb25183d98f7efbeac".parse::<Digest32>().unwrap());
''' + needle)
p.write_text(s)

p = ROOT / "codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs"
s = p.read_text().replace("decide_authenticated_intuition_v2", "decide_authenticated_intuition_v3").replace("canonical_runtime_commitment_payload_v1", "canonical_runtime_commitment_payload_v2").replace("canonical_scored_outputs_digest_v1", "canonical_scored_outputs_digest_v2")
s = s.replace("use codex_hepta_intuition::canonical_candidate_set_digest_v1;", "use codex_hepta_intuition::canonical_candidate_set_digest_v1;\nuse codex_hepta_intuition::canonical_candidate_identity_digest_v2;")
s = s.replace("candidate_set_digest: request.completeness.candidate_set_digest,", "candidate_set_digest: canonical_candidate_identity_digest_v2(&request.candidates)?,")
p.write_text(s)
print("Applied versioned commitments; no V1 encoding or production claim was changed.")
