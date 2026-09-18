use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::AdmissionRequest;
use crate::FactorSource;
use crate::Lifecycle;
use crate::PromptFactor;
use crate::PromptRegistry;
use crate::RegistryReceipt;

pub(crate) fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid test id: {error}"))
}

pub(crate) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(crate) fn factor_with_id(value: &str, source: FactorSource) -> PromptFactor {
    PromptFactor {
        factor_id: id(value),
        proposer_id: id(&format!("proposer:{value}")),
        semantic_version: id("v1"),
        content_digest: digest(&format!("factor:{value}")),
        source,
        lifecycle: Lifecycle::Draft,
    }
}

pub(crate) fn registry() -> PromptRegistry {
    PromptRegistry::new(64).unwrap_or_else(|error| panic!("valid registry: {error}"))
}

pub(crate) struct TestAuthority {
    pub authority: FinalUseAuthority,
    signing_key: SigningKey,
    _directory: tempfile::TempDir,
}

impl TestAuthority {
    pub(crate) fn new() -> Self {
        let signing_seed = Digest32::of_bytes(b"prompt-registry-test-authority-key").into_array();
        let signing_key = SigningKey::from_bytes(&signing_seed);
        let directory = tempfile::tempdir().expect("authority temp dir");
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "prompt-registry-review-owner".to_string(),
            signing_key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("open test authority");
        Self {
            authority,
            signing_key,
            _directory: directory,
        }
    }

    pub(crate) fn token(
        &self,
        registry: &PromptRegistry,
        request: &AdmissionRequest,
        nonce_byte: u8,
    ) -> VerifiedUseToken {
        let binding = registry
            .admission_binding(request)
            .expect("admission binding");
        let now = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock after epoch")
                .as_millis(),
        )
        .expect("millis fit u64");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "prompt-registry-review-owner".to_string(),
            authority_epoch: 1,
            grant_id: format!("prompt-admission-{nonce_byte}"),
            nonce: Digest32::of_bytes(
                format!("prompt-registry-admission-nonce:{nonce_byte}").as_bytes(),
            )
            .into_array(),
            binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now.saturating_add(30_000),
        };
        let signature = self
            .signing_key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec();
        let signed = SignedFinalUseGrant { grant, signature };
        self.authority
            .claim(&signed, &signed.grant.binding)
            .expect("claim signed admission")
    }
}

pub(crate) fn admission_request(factor_id: &str, reviewer_id: &str) -> AdmissionRequest {
    AdmissionRequest {
        factor_id: id(factor_id),
        reviewer_id: id(reviewer_id),
        evidence_digest: digest(&format!("evidence:{factor_id}")),
        reviewed_scope_digest: digest(&format!("scope:{factor_id}")),
    }
}

pub(crate) fn admit(
    registry: &mut PromptRegistry,
    authority: &TestAuthority,
    factor_id: &str,
    nonce_byte: u8,
) -> RegistryReceipt {
    let request = admission_request(factor_id, "reviewer:independent");
    let token = authority.token(registry, &request, nonce_byte);
    registry
        .admit_factor_authorized(&authority.authority, token, request)
        .expect("authorized admission")
}
