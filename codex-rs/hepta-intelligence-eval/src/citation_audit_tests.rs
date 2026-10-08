//! Test signers and virtual times are not production or independent acceptance.
use super::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn d(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
fn id(value: &str) -> StableId { StableId::new(value).expect("fixture id") }
fn request() -> CitationAuditRequestV1 {
    CitationAuditRequestV1 {
        query_id: "q.1".into(), scope: "scope.1".into(), experiment_digest: d("experiment"),
        family_digest: d("family"), prompt_digest: d("prompt"), question: "Which code?".into(),
        question_time: "2026-10-09T00:00:00Z".into(), answer: "The code is blue [E1].".into(),
        sources: vec![CitationSourceV1 { label: "E1".into(), identity: "session.1".into(), source_root: d("root"), excerpt: "[E1] The code is blue.".into() }],
    }
}
fn judgement() -> CitationAuditJudgementV1 {
    CitationAuditJudgementV1 {
        claims: vec![CitationClaimV1 { start: 0, end: 21, kind: CitationClaimKindV1::Factual }],
        citations: vec![CitationJudgementV1 { start: 17, verdict: CitationVerdictV1::Entailed }],
    }
}
struct Fixture { keys: [SigningKey; 2], verifier: LearningEvidenceVerifierV1 }
impl Fixture {
    fn new(same_controller: bool) -> Self {
        let keys = [SigningKey::from_bytes(&[25; 32]), SigningKey::from_bytes(&[37; 32])];
        let signers = keys.iter().enumerate().map(|(index, key)| TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 { principal_id: id(&format!("actor-{index}")), credential_chain_digest: d(&format!("credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()), scope_digest: d("scope"), authority_epoch: 4, authenticated_at: 10, expires_at: 100 },
            controller_id: id(&format!("controller-{}", if same_controller { 0 } else { index })),
            verifying_key: key.verifying_key().to_bytes(), roles: vec![if index == 0 { LearningEvidenceRoleV1::Generator } else { LearningEvidenceRoleV1::Evaluator }], revoked_at: None,
        }).collect();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 { scope_digest: d("scope"), objective_digest: d("objective"), authority_epoch: 4, signers }).expect("fixture trust");
        Self { keys, verifier }
    }
    fn sign(&self, index: usize, payload: &[u8]) -> SignedLearningEvidenceV1 {
        let mut signed = SignedLearningEvidenceV1 { evidence_id: id(&format!("evidence-{index}")), principal_id: id(&format!("actor-{index}")),
            role: if index == 0 { LearningEvidenceRoleV1::Generator } else { LearningEvidenceRoleV1::Evaluator },
            trust_digest: self.verifier.trust_digest(), scope_digest: d("scope"), objective_digest: d("objective"), authority_epoch: 4,
            issued_at: 20, expires_at: 90, payload_digest: Digest32::of_bytes(payload), signature: [0; 64] };
        signed.signature = self.keys[index].sign(&signed.signing_bytes()).to_bytes();
        signed
    }
    fn signatures(&self, r: &CitationAuditRequestV1, j: &CitationAuditJudgementV1) -> [SignedLearningEvidenceV1; 2] {
        [self.sign(0, &citation_request_payload_v1(r).expect("request")), self.sign(1, &citation_judgement_payload_v1(r, j).expect("judgement"))]
    }
}

#[test]
fn binary_payloads_match_the_python_interchange_vector() {
    assert_eq!(Digest32::of_bytes(&citation_request_payload_v1(&request()).expect("request")).to_string(), "6dba246cd74c04aaecd3d818feb5b9d3f7cdc4d4c71b1b44a26b634e35766d91");
    assert_eq!(Digest32::of_bytes(&citation_judgement_payload_v1(&request(), &judgement()).expect("judgement")).to_string(), "c0f934320b8f6a5493d8bb60f96803178e46199a5096c89fb242bafa5d023f18");
}

#[test]
fn independent_signed_judgement_returns_counts_not_authority() {
    let fixture = Fixture::new(/*same_controller*/ false);
    let (r, j) = (request(), judgement());
    let [g, e] = fixture.signatures(&r, &j);
    let receipt = verify_signed_citation_audit_v1(&r, &j, &g, &e, &fixture.verifier, &BTreeSet::new(), 30).expect("verified audit");
    assert_eq!(receipt.counts().precision_ppm(), Some(1_000_000));
    assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
    let mut changed = r;
    changed.answer = "The code is red [E1].".into();
    assert!(verify_signed_citation_audit_v1(&changed, &j, &g, &e, &fixture.verifier, &BTreeSet::new(), 30).is_err());
}

#[test]
fn same_controller_forgery_and_expiry_are_not_independent_acceptance() {
    for same_controller in [false, true] {
        let fixture = Fixture::new(same_controller);
        let (r, j) = (request(), judgement());
        let [g, mut e] = fixture.signatures(&r, &j);
        if same_controller {
            assert!(matches!(verify_signed_citation_audit_v1(&r, &j, &g, &e, &fixture.verifier, &BTreeSet::new(), 30), Err(CitationAuditError::Authentication(SignedEvidenceError::ControllerCollision))));
        } else {
            assert!(verify_signed_citation_audit_v1(&r, &j, &g, &e, &fixture.verifier, &BTreeSet::new(), 91).is_err());
            e.signature[0] ^= 1;
            assert!(verify_signed_citation_audit_v1(&r, &j, &g, &e, &fixture.verifier, &BTreeSet::new(), 30).is_err());
        }
    }
}

#[test]
fn omitted_claim_text_missing_citation_and_utf8_split_fail_closed() {
    let r = request();
    for end in [1, 17, 20, 22] {
        let mut j = judgement();
        j.claims[0].end = end;
        assert!(validate_citation_judgement_v1(&r, &j, &BTreeSet::new()).is_err());
    }
    let mut j = judgement();
    j.citations.clear();
    assert!(validate_citation_judgement_v1(&r, &j, &BTreeSet::new()).is_err());
    let mut r = r;
    r.answer = "蓝色 [E1]".into();
    j.claims[0].start = 1;
    j.claims[0].end = r.answer.len() as u32;
    assert!(validate_citation_judgement_v1(&r, &j, &BTreeSet::new()).is_err());
}

#[test]
fn source_existence_unreviewed_and_abstention_cannot_become_perfect_precision() {
    let r = request();
    for verdict in [CitationVerdictV1::Unsupported, CitationVerdictV1::Unreviewed, CitationVerdictV1::Contradicted] {
        let mut j = judgement();
        j.citations[0].verdict = verdict;
        assert_eq!(validate_citation_judgement_v1(&r, &j, &BTreeSet::new()).expect("diagnostic").precision_ppm(), Some(0));
    }
    let mut r = r;
    r.answer = "I do not know".into();
    let j = CitationAuditJudgementV1 { claims: vec![CitationClaimV1 { start: 0, end: r.answer.len() as u32, kind: CitationClaimKindV1::Abstention }], citations: Vec::new() };
    assert_eq!(validate_citation_judgement_v1(&r, &j, &BTreeSet::new()).expect("abstention").precision_ppm(), None);
}

#[test]
fn revocation_and_undelivered_citations_reject_even_signed_positive_verdicts() {
    let fixture = Fixture::new(/*same_controller*/ false);
    let (mut r, j) = (request(), judgement());
    let [g, e] = fixture.signatures(&r, &j);
    assert!(verify_signed_citation_audit_v1(&r, &j, &g, &e, &fixture.verifier, &BTreeSet::from([d("root")]), 30).is_err());
    r.sources.clear();
    let [g, e] = fixture.signatures(&r, &j);
    assert!(verify_signed_citation_audit_v1(&r, &j, &g, &e, &fixture.verifier, &BTreeSet::new(), 30).is_err());
}
