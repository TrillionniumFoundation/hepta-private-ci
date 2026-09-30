use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NduProductionAdapterRoleV1 {
    PersistentProjectionStore,
    AuthenticatedOwnerWriter,
    ProcessCrossHostFence,
    TrustedTime,
    RevocationFrontier,
    ArtifactRegistry,
    EncryptedRemoteBackup,
    RestoreExecutor,
    MetricsExporter,
    ProductCaller,
}

impl NduProductionAdapterRoleV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::PersistentProjectionStore => 1,
            Self::AuthenticatedOwnerWriter => 2,
            Self::ProcessCrossHostFence => 3,
            Self::TrustedTime => 4,
            Self::RevocationFrontier => 5,
            Self::ArtifactRegistry => 6,
            Self::EncryptedRemoteBackup => 7,
            Self::RestoreExecutor => 8,
            Self::MetricsExporter => 9,
            Self::ProductCaller => 10,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduAdapterQualificationStateV1 {
    SourceBound,
    HostQualified,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduProductionCompositionErrorV1 {
    EmptyDigest(&'static str),
    InvalidPolicyRevision,
    InvalidAdapterIdentity,
    DuplicateRole,
    MissingRole(NduProductionAdapterRoleV1),
    MissingHostQualification(NduProductionAdapterRoleV1),
    ReceiptDigest,
}

impl fmt::Display for NduProductionCompositionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduProductionCompositionErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCandidateIdentityV1 {
    pub source_commit_digest: Digest32,
    pub source_tree_digest: Digest32,
    pub target_triple_digest: Digest32,
    pub runner_host_digest: Digest32,
    pub test_set_digest: Digest32,
    pub cargo_lock_digest: Digest32,
    pub documentation_map_digest: Digest32,
}

impl NduCandidateIdentityV1 {
    pub fn validate(&self) -> Result<(), NduProductionCompositionErrorV1> {
        for (field, digest) in [
            ("source commit", self.source_commit_digest),
            ("source tree", self.source_tree_digest),
            ("target triple", self.target_triple_digest),
            ("runner host", self.runner_host_digest),
            ("test set", self.test_set_digest),
            ("Cargo.lock", self.cargo_lock_digest),
            ("documentation map", self.documentation_map_digest),
        ] {
            require_digest(digest, field)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProductionAdapterBindingV1 {
    role: NduProductionAdapterRoleV1,
    adapter_id: StableId,
    implementation_digest: Digest32,
    configuration_digest: Digest32,
    policy_revision: u64,
    qualification_state: NduAdapterQualificationStateV1,
    qualification_receipt_digest: Option<Digest32>,
    binding_digest: Digest32,
}

impl NduProductionAdapterBindingV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        role: NduProductionAdapterRoleV1,
        adapter_id: StableId,
        implementation_digest: Digest32,
        configuration_digest: Digest32,
        policy_revision: u64,
        qualification_state: NduAdapterQualificationStateV1,
        qualification_receipt_digest: Option<Digest32>,
    ) -> Result<Self, NduProductionCompositionErrorV1> {
        if adapter_id.as_str().is_empty() {
            return Err(NduProductionCompositionErrorV1::InvalidAdapterIdentity);
        }
        require_digest(implementation_digest, "adapter implementation")?;
        require_digest(configuration_digest, "adapter configuration")?;
        if policy_revision == 0 {
            return Err(NduProductionCompositionErrorV1::InvalidPolicyRevision);
        }
        match (qualification_state, qualification_receipt_digest) {
            (NduAdapterQualificationStateV1::HostQualified, Some(receipt)) => {
                require_digest(receipt, "adapter qualification receipt")?;
            }
            (NduAdapterQualificationStateV1::HostQualified, None) => {
                return Err(NduProductionCompositionErrorV1::MissingHostQualification(role));
            }
            (NduAdapterQualificationStateV1::SourceBound, Some(receipt)) => {
                require_digest(receipt, "source-bound adapter evidence")?;
            }
            (NduAdapterQualificationStateV1::SourceBound, None) => {}
        }
        let binding_digest = digest_adapter_binding(
            role,
            &adapter_id,
            implementation_digest,
            configuration_digest,
            policy_revision,
            qualification_state,
            qualification_receipt_digest,
        );
        Ok(Self {
            role,
            adapter_id,
            implementation_digest,
            configuration_digest,
            policy_revision,
            qualification_state,
            qualification_receipt_digest,
            binding_digest,
        })
    }

    #[must_use]
    pub const fn role(&self) -> NduProductionAdapterRoleV1 {
        self.role
    }

    #[must_use]
    pub fn adapter_id(&self) -> &StableId {
        &self.adapter_id
    }

    #[must_use]
    pub const fn implementation_digest(&self) -> Digest32 {
        self.implementation_digest
    }

    #[must_use]
    pub const fn configuration_digest(&self) -> Digest32 {
        self.configuration_digest
    }

    #[must_use]
    pub const fn policy_revision(&self) -> u64 {
        self.policy_revision
    }

    #[must_use]
    pub const fn qualification_state(&self) -> NduAdapterQualificationStateV1 {
        self.qualification_state
    }

    #[must_use]
    pub const fn qualification_receipt_digest(&self) -> Option<Digest32> {
        self.qualification_receipt_digest
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    pub fn validate(&self) -> Result<(), NduProductionCompositionErrorV1> {
        let rebuilt = Self::new(
            self.role,
            self.adapter_id.clone(),
            self.implementation_digest,
            self.configuration_digest,
            self.policy_revision,
            self.qualification_state,
            self.qualification_receipt_digest,
        )?;
        if rebuilt.binding_digest != self.binding_digest {
            return Err(NduProductionCompositionErrorV1::ReceiptDigest);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProductionCompositionManifestV1 {
    pub candidate: NduCandidateIdentityV1,
    pub owner_generation: Generation,
    pub production_policy_digest: Digest32,
    pub production_policy_revision: u64,
    pub adapters: Vec<NduProductionAdapterBindingV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProductionCompositionReceiptV1 {
    candidate: NduCandidateIdentityV1,
    owner_generation: Generation,
    production_policy_digest: Digest32,
    production_policy_revision: u64,
    adapters: Vec<NduProductionAdapterBindingV1>,
    activation_eligible: bool,
    receipt_digest: Digest32,
}

impl NduProductionCompositionReceiptV1 {
    #[must_use]
    pub fn candidate(&self) -> &NduCandidateIdentityV1 {
        &self.candidate
    }

    #[must_use]
    pub const fn owner_generation(&self) -> Generation {
        self.owner_generation
    }

    #[must_use]
    pub const fn production_policy_digest(&self) -> Digest32 {
        self.production_policy_digest
    }

    #[must_use]
    pub const fn production_policy_revision(&self) -> u64 {
        self.production_policy_revision
    }

    #[must_use]
    pub fn adapters(&self) -> &[NduProductionAdapterBindingV1] {
        &self.adapters
    }

    #[must_use]
    pub const fn activation_eligible(&self) -> bool {
        self.activation_eligible
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    pub fn validate(&self) -> Result<(), NduProductionCompositionErrorV1> {
        self.candidate.validate()?;
        require_digest(self.production_policy_digest, "production policy")?;
        if self.production_policy_revision == 0 {
            return Err(NduProductionCompositionErrorV1::InvalidPolicyRevision);
        }
        validate_adapter_set(&self.adapters)?;
        let activation_eligible = self.adapters.iter().all(|binding| {
            binding.qualification_state == NduAdapterQualificationStateV1::HostQualified
                && binding.qualification_receipt_digest.is_some()
        });
        if activation_eligible != self.activation_eligible {
            return Err(NduProductionCompositionErrorV1::ReceiptDigest);
        }
        let expected = digest_composition(
            &self.candidate,
            self.owner_generation,
            self.production_policy_digest,
            self.production_policy_revision,
            &self.adapters,
            self.activation_eligible,
        );
        if expected != self.receipt_digest {
            return Err(NduProductionCompositionErrorV1::ReceiptDigest);
        }
        Ok(())
    }
}

pub fn seal_ndu_production_composition_v1(
    mut manifest: NduProductionCompositionManifestV1,
) -> Result<NduProductionCompositionReceiptV1, NduProductionCompositionErrorV1> {
    manifest.candidate.validate()?;
    require_digest(manifest.production_policy_digest, "production policy")?;
    if manifest.production_policy_revision == 0 {
        return Err(NduProductionCompositionErrorV1::InvalidPolicyRevision);
    }
    manifest.adapters.sort_by_key(NduProductionAdapterBindingV1::role);
    validate_adapter_set(&manifest.adapters)?;
    let activation_eligible = manifest.adapters.iter().all(|binding| {
        binding.qualification_state == NduAdapterQualificationStateV1::HostQualified
            && binding.qualification_receipt_digest.is_some()
    });
    let receipt_digest = digest_composition(
        &manifest.candidate,
        manifest.owner_generation,
        manifest.production_policy_digest,
        manifest.production_policy_revision,
        &manifest.adapters,
        activation_eligible,
    );
    let receipt = NduProductionCompositionReceiptV1 {
        candidate: manifest.candidate,
        owner_generation: manifest.owner_generation,
        production_policy_digest: manifest.production_policy_digest,
        production_policy_revision: manifest.production_policy_revision,
        adapters: manifest.adapters,
        activation_eligible,
        receipt_digest,
    };
    receipt.validate()?;
    Ok(receipt)
}

fn validate_adapter_set(
    adapters: &[NduProductionAdapterBindingV1],
) -> Result<(), NduProductionCompositionErrorV1> {
    const REQUIRED: [NduProductionAdapterRoleV1; 10] = [
        NduProductionAdapterRoleV1::PersistentProjectionStore,
        NduProductionAdapterRoleV1::AuthenticatedOwnerWriter,
        NduProductionAdapterRoleV1::ProcessCrossHostFence,
        NduProductionAdapterRoleV1::TrustedTime,
        NduProductionAdapterRoleV1::RevocationFrontier,
        NduProductionAdapterRoleV1::ArtifactRegistry,
        NduProductionAdapterRoleV1::EncryptedRemoteBackup,
        NduProductionAdapterRoleV1::RestoreExecutor,
        NduProductionAdapterRoleV1::MetricsExporter,
        NduProductionAdapterRoleV1::ProductCaller,
    ];
    for binding in adapters {
        binding.validate()?;
    }
    for role in REQUIRED {
        let count = adapters.iter().filter(|binding| binding.role == role).count();
        match count {
            0 => return Err(NduProductionCompositionErrorV1::MissingRole(role)),
            1 => {}
            _ => return Err(NduProductionCompositionErrorV1::DuplicateRole),
        }
    }
    if adapters.len() != REQUIRED.len() {
        return Err(NduProductionCompositionErrorV1::DuplicateRole);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn digest_adapter_binding(
    role: NduProductionAdapterRoleV1,
    adapter_id: &StableId,
    implementation_digest: Digest32,
    configuration_digest: Digest32,
    policy_revision: u64,
    qualification_state: NduAdapterQualificationStateV1,
    qualification_receipt_digest: Option<Digest32>,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.production-adapter-binding.v1\0".to_vec();
    bytes.push(role.tag());
    push_id(&mut bytes, adapter_id);
    bytes.extend_from_slice(implementation_digest.as_array());
    bytes.extend_from_slice(configuration_digest.as_array());
    bytes.extend_from_slice(&policy_revision.to_be_bytes());
    bytes.push(match qualification_state {
        NduAdapterQualificationStateV1::SourceBound => 1,
        NduAdapterQualificationStateV1::HostQualified => 2,
    });
    match qualification_receipt_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}

fn digest_composition(
    candidate: &NduCandidateIdentityV1,
    owner_generation: Generation,
    production_policy_digest: Digest32,
    production_policy_revision: u64,
    adapters: &[NduProductionAdapterBindingV1],
    activation_eligible: bool,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.production-composition-receipt.v1\0".to_vec();
    for digest in [
        candidate.source_commit_digest,
        candidate.source_tree_digest,
        candidate.target_triple_digest,
        candidate.runner_host_digest,
        candidate.test_set_digest,
        candidate.cargo_lock_digest,
        candidate.documentation_map_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&owner_generation.get().to_be_bytes());
    bytes.extend_from_slice(production_policy_digest.as_array());
    bytes.extend_from_slice(&production_policy_revision.to_be_bytes());
    bytes.push(u8::from(activation_eligible));
    bytes.extend_from_slice(&u32::try_from(adapters.len()).unwrap_or(u32::MAX).to_be_bytes());
    for adapter in adapters {
        bytes.extend_from_slice(adapter.binding_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn require_digest(
    value: Digest32,
    field: &'static str,
) -> Result<(), NduProductionCompositionErrorV1> {
    if value.is_zero() {
        return Err(NduProductionCompositionErrorV1::EmptyDigest(field));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "production_composition_tests.rs"]
mod tests;
