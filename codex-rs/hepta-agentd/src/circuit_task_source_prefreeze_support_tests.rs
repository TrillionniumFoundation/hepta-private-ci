//! Explicit evidence fixtures only. These keys never enter product defaults,
//! Root disclosure registration, a real peer check or a source-read grant.

use codex_hepta_learning_ledger::{AuthenticatedPrincipalV1, LearningEvidenceRoleV1,
    LearningEvidenceTrustV1, LearningEvidenceVerifierV1, SignedLearningEvidenceV1,
    TrustedLearningSignerV1};
use codex_hepta_types::{Digest32, StableId};
use ed25519_dalek::{Signer as _, SigningKey};
use crate::{AgentdRootAuthorityPeer, CircuitTaskSourceInputV1};
use super::{Error, OriginalCircuitPrefreezeSourceRequestV1};

pub(crate) const AT: u64 = 200;

pub(crate) struct EvidenceFixture {
    pub(crate) request: OriginalCircuitPrefreezeSourceRequestV1,
    pub(crate) verifier: LearningEvidenceVerifierV1,
    pub(crate) evidence: SignedLearningEvidenceV1,
    other: TrustedLearningSignerV1,
    other_key: SigningKey,
}

impl EvidenceFixture {
    pub(crate) fn new(source: CircuitTaskSourceInputV1, task_digest: Digest32,
        operation: &str, intent: Digest32) -> anyhow::Result<Self>
    {
        let scope = Digest32::of_bytes(b"prefreeze fixture trust scope");
        let (generator, generator_key) = signer("generator", /*seed*/ 51, LearningEvidenceRoleV1::Generator, scope)?;
        let (experience, _) = signer("experience", /*seed*/ 52, LearningEvidenceRoleV1::Observer, scope)?;
        let (dataset, _) = signer("dataset", /*seed*/ 53, LearningEvidenceRoleV1::Observer, scope)?;
        let (other, other_key) = signer("another-generator", /*seed*/ 54, LearningEvidenceRoleV1::Generator, scope)?;
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope, objective_digest: source.objective_digest, authority_epoch: 1,
            signers: vec![generator.clone(), experience.clone(), dataset.clone(), other.clone()],
        })?;
        let request = OriginalCircuitPrefreezeSourceRequestV1 {
            generation_operation_id: operation.into(), generation_intent_digest: intent, task_digest, source,
            ledger_binding_digest: Digest32::of_bytes(b"existing test ledger binding"),
            evidence_trust_digest: verifier.trust_digest(),
            trust_distribution_digest: Digest32::of_bytes(b"test signed distribution identity"), trust_generation: 1,
            generator, experience_signer: experience, dataset_signer: dataset,
            consumer: AgentdRootAuthorityPeer {
                boot_id: "00000000-0000-0000-0000-000000000001".into(), pid: 4242, process_start_ticks: 99,
            }, consumer_uid: 60002, nonce: [17; 16],
        };
        let evidence = sign(&request, &verifier, &request.generator, &generator_key)?;
        Ok(Self { request, verifier, evidence, other, other_key })
    }

    pub(crate) fn verify(&self) -> Result<Digest32, Error> {
        self.request.require_evidence(&self.verifier, self.request.trust_distribution_digest,
            self.request.trust_generation, &self.evidence, AT)
    }

    pub(crate) fn another_valid_generator(&self) -> anyhow::Result<SignedLearningEvidenceV1> {
        sign(&self.request, &self.verifier, &self.other, &self.other_key)
    }
}

fn signer(label: &str, seed: u8, role: LearningEvidenceRoleV1, scope: Digest32)
    -> anyhow::Result<(TrustedLearningSignerV1, SigningKey)>
{
    let key = SigningKey::from_bytes(&[seed; 32]);
    let verifying_key = key.verifying_key().to_bytes();
    Ok((TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: StableId::new(label)?,
            credential_chain_digest: Digest32::of_bytes(format!("{label}-credential").as_bytes()),
            signing_key_digest: Digest32::of_bytes(&verifying_key), scope_digest: scope,
            authority_epoch: 1, authenticated_at: 100, expires_at: 1_000,
        }, controller_id: StableId::new(format!("{label}-controller"))?,
        verifying_key, roles: vec![role], revoked_at: None,
    }, key))
}

fn sign(request: &OriginalCircuitPrefreezeSourceRequestV1, verifier: &LearningEvidenceVerifierV1,
    signer: &TrustedLearningSignerV1, key: &SigningKey) -> anyhow::Result<SignedLearningEvidenceV1>
{
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new("prefreeze-fixture-disclosure")?,
        principal_id: signer.principal.principal_id.clone(), role: LearningEvidenceRoleV1::Generator,
        trust_digest: verifier.trust_digest(), scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(), authority_epoch: verifier.authority_epoch(),
        issued_at: 100, expires_at: 1_000, payload_digest: Digest32::of_bytes(&request.signing_payload()?),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    Ok(evidence)
}
