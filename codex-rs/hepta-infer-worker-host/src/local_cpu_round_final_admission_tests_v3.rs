use super::*;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agent_components::plasticity::parameter_generator_signing_payload_v3;
use codex_hepta_agent_components::plasticity::plasticity_admission_signing_payload_v1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

struct SignedRequestFixture {
    original: fixture::Fixture,
    verifier: LearningEvidenceVerifierV1,
    keys: [SigningKey; 2],
}
impl SignedRequestFixture {
    fn new(colliding_controllers: bool) -> TestResultWith<Self> {
        let mut original = fixture::Fixture::new("/protected/original/generations".into())?;
        let keys = [
            SigningKey::from_bytes(&[73; 32]),
            SigningKey::from_bytes(&[91; 32]),
        ];
        let trust = LearningEvidenceTrustV1 {
            scope_digest: original.baseline.scope.scope_digest,
            objective_digest: original.baseline.scope.objective_digest,
            authority_epoch: 1,
            signers: keys
                .iter()
                .enumerate()
                .map(|(index, key)| {
                    let principal_id =
                        StableId::new(format!("fixture.original.owner.{index}")).unwrap();
                    TrustedLearningSignerV1 {
                        principal: AuthenticatedPrincipalV1 {
                            principal_id,
                            credential_chain_digest: Digest32::of_bytes(&[index as u8, 23]),
                            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                            scope_digest: original.baseline.scope.scope_digest,
                            authority_epoch: 1,
                            authenticated_at: 1000,
                            expires_at: 100_000,
                        },
                        controller_id: StableId::new(format!(
                            "fixture.controller.{}",
                            if colliding_controllers { 0 } else { index }
                        ))
                        .unwrap(),
                        verifying_key: key.verifying_key().to_bytes(),
                        roles: vec![if index == 0 {
                            LearningEvidenceRoleV1::Generator
                        } else {
                            LearningEvidenceRoleV1::Observer
                        }],
                        revoked_at: None,
                    }
                })
                .collect(),
        };
        let verifier = LearningEvidenceVerifierV1::new(trust)?;
        original.request.generator_attestation.principal_id =
            StableId::new("fixture.original.owner.0")?;
        original.request.admission_attestation.principal_id =
            StableId::new("fixture.original.owner.1")?;
        let mut fixture = Self {
            original,
            verifier,
            keys,
        };
        let mut request = fixture.original.request.clone();
        fixture.sign(&mut request);
        fixture.original.request = request;
        Ok(fixture)
    }
    fn sign(&self, request: &mut ParameterPlasticityProductRequestV1) {
        let payloads = [
            parameter_generator_signing_payload_v3(&request.generated),
            plasticity_admission_signing_payload_v1(&request.admission),
        ];
        for (index, evidence) in [
            &mut request.generator_attestation,
            &mut request.admission_attestation,
        ]
        .into_iter()
        .enumerate()
        {
            evidence.trust_digest = self.verifier.trust_digest();
            evidence.issued_at = 2000;
            evidence.expires_at = 90_000;
            evidence.payload_digest = Digest32::of_bytes(&payloads[index]);
            evidence.signature = self.keys[index].sign(&evidence.signing_bytes()).to_bytes();
        }
    }
    fn post_publication(&self) -> ParameterPlasticityProductRequestV1 {
        let mut actual = self.original.request.clone();
        actual.admission.artifact_registry_head_digest =
            Digest32::of_bytes(b"actual post-publication head vector");
        actual.admission.qualification_evidence_head_digest =
            Digest32::of_bytes(b"post-publication full evidence vector");
        actual.admission.owner_evidence_set_digest =
            Digest32::of_bytes(b"post-publication complete owner set vector");
        actual.expected_registry_predecessor =
            Digest32::of_bytes(b"actual held proposal writer anchor vector");
        self.sign(&mut actual);
        actual
    }
    fn validate(
        &self,
        actual: &ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<(), AgentdError> {
        super::super::final_admission::validate_final_request(
            &self.original.round("original.goal.one", 1).unwrap(),
            &self.original.request,
            actual,
            &self.verifier,
            Digest32::of_bytes(b"actual held proposal writer anchor vector"),
            now,
        )
    }
}
type TestResultWith<T> = Result<T, Box<dyn std::error::Error>>;

#[test]
fn whole_post_publication_request_keeps_pre_e1_search_and_requires_fresh_original_signature()
-> TestResult {
    let fixture = SignedRequestFixture::new(/*colliding_controllers*/ false)?;
    let before = fixture.original.request.clone();
    let actual = fixture.post_publication();
    fixture.validate(&actual, 3000)?;
    assert_eq!(fixture.original.request, before);
    let mut replay = actual.clone();
    replay.admission_attestation = before.admission_attestation;
    assert!(fixture.validate(&replay, 3000).is_err());
    let mut changed = actual;
    changed.admission_attestation.signature[17] ^= 1;
    assert!(fixture.validate(&changed, 3000).is_err());
    Ok(())
}

#[test]
fn signed_post_publication_request_cannot_change_dataset_lineage_or_proposal_anchor() -> TestResult
{
    let fixture = SignedRequestFixture::new(/*colliding_controllers*/ false)?;
    for field in 0..5 {
        let mut actual = fixture.post_publication();
        let foreign = Digest32::of_bytes(b"foreign original lineage");
        match field {
            0 => actual.admission.dataset_digest = foreign,
            1 => actual.admission.modulator_broadcast_digest = foreign,
            2 => actual.admission.artifact_registry_binding = foreign,
            3 => {
                actual.expected_registry_predecessor =
                    actual.admission.artifact_registry_head_digest
            }
            4 => actual.proposal_id = StableId::new("another.proposal")?,
            _ => unreachable!(),
        }
        fixture.sign(&mut actual);
        assert!(fixture.validate(&actual, 3000).is_err());
    }
    Ok(())
}

#[test]
fn final_request_refuses_same_controller_roles_and_original_round_expiry() -> TestResult {
    let fixture = SignedRequestFixture::new(/*colliding_controllers*/ true)?;
    assert!(fixture.validate(&fixture.post_publication(), 3000).is_err());
    let fixture = SignedRequestFixture::new(/*colliding_controllers*/ false)?;
    let actual = fixture.post_publication();
    assert!(fixture.validate(&actual, 999).is_err());
    assert!(fixture.validate(&actual, 100_000).is_err());
    Ok(())
}
