//! Ephemeral keys and an explicitly local research trust root; no production credentials.
use crate::Result;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::{Digest32, StableId};
use ed25519_dalek::{Signer, SigningKey};
use serde::Deserialize;
use serde_json::{Value, json};

pub const NOW: u64 = 50;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HostFixture {
    pub schema: String,
    pub research_only: bool,
    pub study_digest: String,
    pub owner_binary_sha256: String,
    pub trained_checkpoint_sha256: String,
    pub model_sha256: String,
    pub root_seed: [u8; 32],
    pub generator_seed: [u8; 32],
    pub observer_seed: [u8; 32],
    pub allocator_seed: [u8; 32],
}

pub fn id(value: &str) -> Result<StableId> {
    Ok(StableId::new(value)?)
}
pub fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

impl HostFixture {
    pub fn validate(&self) -> Result<()> {
        if self.schema != "hepta.local-research.signed-credit-host.v1" || !self.research_only {
            return Err("Explicit user-authorized local research host required".into());
        }
        for value in [
            &self.study_digest,
            &self.owner_binary_sha256,
            &self.trained_checkpoint_sha256,
            &self.model_sha256,
        ] {
            if value.parse::<Digest32>()?.is_zero() {
                return Err("Unbound research input".into());
            }
        }
        if self.root_seed == self.generator_seed
            || self.generator_seed == self.observer_seed
            || self.observer_seed == self.allocator_seed
            || self.generator_seed == self.allocator_seed
            || self.root_seed == self.observer_seed
            || self.root_seed == self.allocator_seed
        {
            return Err("Distinct research signing keys required".into());
        }
        Ok(())
    }
    pub fn scope(&self) -> Digest32 {
        digest(&format!(
            "user-authorized-local-research-credit:{}",
            self.study_digest
        ))
    }
    pub fn objective(&self) -> Digest32 {
        digest("adaptive-credit-bridge.bernoulli-terminal-utility.v1")
    }
    pub fn seed(&self, role: &str) -> Result<&[u8; 32]> {
        match role {
            "generator" => Ok(&self.generator_seed),
            "observer" => Ok(&self.observer_seed),
            "allocator" => Ok(&self.allocator_seed),
            _ => Err("Unknown research signer".into()),
        }
    }
    pub fn principal(&self, role: &str) -> Result<AuthenticatedPrincipalV1> {
        let key = SigningKey::from_bytes(self.seed(role)?);
        Ok(AuthenticatedPrincipalV1 {
            principal_id: id(&format!("research-{role}"))?,
            credential_chain_digest: digest(&format!(
                "{}:{role}:ephemeral-credential",
                self.study_digest
            )),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: self.scope(),
            authority_epoch: 1,
            authenticated_at: 10,
            expires_at: 200,
        })
    }
    pub fn activate(&self) -> Result<(ActivatedLearningTrustV1, Value)> {
        self.validate()?;
        let root_key = SigningKey::from_bytes(&self.root_seed);
        let root = LearningTrustRootV1 {
            root_id: id("local-research-root")?,
            scope_digest: self.scope(),
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: 1,
            expires_at: 200,
            revoked_at: None,
        };
        let roles = [
            ("generator", LearningEvidenceRoleV1::Generator),
            ("observer", LearningEvidenceRoleV1::Observer),
            ("allocator", LearningEvidenceRoleV1::CreditAllocator),
        ];
        let signers = roles
            .into_iter()
            .map(|(name, role)| {
                Ok(TrustedLearningSignerV1 {
                    principal: self.principal(name)?,
                    controller_id: id(&format!("local-research-{name}-controller"))?,
                    verifying_key: SigningKey::from_bytes(self.seed(name)?)
                        .verifying_key()
                        .to_bytes(),
                    roles: vec![role],
                    revoked_at: None,
                })
            })
            .collect::<Result<Vec<_>>>()?;
        let public = signers.iter().map(|s| json!({"principal":s.principal.principal_id.as_str(),"controller":s.controller_id.as_str(),"verifying_key":hex(&s.verifying_key),"roles":format!("{:?}",s.roles)})).collect::<Vec<_>>();
        let trust = LearningEvidenceTrustV1 {
            scope_digest: self.scope(),
            objective_digest: self.objective(),
            authority_epoch: 1,
            signers,
        };
        let mut signed = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("local-research-trust-distribution")?,
                generation: 1,
                effective_at: 20,
                trust,
            },
            root_id: root.root_id.clone(),
            issued_at: 15,
            expires_at: 90,
            signature: [0; 64],
        };
        let payload = signed.signing_bytes()?;
        signed.signature = root_key.sign(&payload).to_bytes();
        let public_receipt = json!({"research_only":true,"organizational_independence_claimed":false,"root_verifying_key":hex(&root.verifying_key),"distribution_signing_bytes":hex(&payload),"distribution_signature":hex(&signed.signature),"scope_digest":self.scope().to_string(),"objective_digest":self.objective().to_string(),"signers":public});
        Ok((
            activate_learning_trust(&root, signed, None, NOW)?,
            public_receipt,
        ))
    }
    pub fn sign(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        name: &str,
        role: LearningEvidenceRoleV1,
        payload: &[u8],
        corrupt: bool,
    ) -> Result<(SignedLearningEvidenceV1, Value)> {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("research-{name}-{}", Digest32::of_bytes(payload)))?,
            principal_id: self.principal(name)?.principal_id,
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: self.scope(),
            objective_digest: self.objective(),
            authority_epoch: 1,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        let key = SigningKey::from_bytes(self.seed(name)?);
        evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
        if corrupt {
            evidence.signature[0] ^= 0x80;
        }
        let receipt = json!({"principal":evidence.principal_id.as_str(),"role":format!("{:?}",role),"evidence_id":evidence.evidence_id.as_str(),"payload_digest":evidence.payload_digest.to_string(),"payload_bytes":hex(payload),"signing_bytes":hex(&evidence.signing_bytes()),"signature":hex(&evidence.signature),"verifying_key":hex(&key.verifying_key().to_bytes()),"deliberately_corrupted_fixture":corrupt});
        Ok((evidence, receipt))
    }
}
