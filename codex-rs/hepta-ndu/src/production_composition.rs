use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32, StableId};

const ROLE_COUNT: usize = 11;
const MAX_ADAPTER_ID_BYTES: usize = 256;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NduProductionAdapterRoleV1 {
    PersistentProjectionStore,
    AuthenticatedOwnerWriter,
    ProcessFence,
    CrossHostFence,
    TrustedTime,
    RevocationFrontier,
    ArtifactRegistry,
    EncryptedRemoteBackup,
    RestoreExecutor,
    MetricsExporter,
    ProductCaller,
}

impl NduProductionAdapterRoleV1 {
    const ALL: [Self; ROLE_COUNT] = [
        Self::PersistentProjectionStore,
        Self::AuthenticatedOwnerWriter,
        Self::ProcessFence,
        Self::CrossHostFence,
        Self::TrustedTime,
        Self::RevocationFrontier,
        Self::ArtifactRegistry,
        Self::EncryptedRemoteBackup,
        Self::RestoreExecutor,
        Self::MetricsExporter,
        Self::ProductCaller,
    ];

    const fn tag(self) -> u8 {
        match self {
            Self::PersistentProjectionStore => 0,
            Self::AuthenticatedOwnerWriter => 1,
            Self::ProcessFence => 2,
            Self::CrossHostFence => 3,
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduProductionCompositionErrorV1 {
    EmptyDigest(&'static str),
    InvalidAdapterId,
    InvalidPolicyRevision,
    DuplicateRole(NduProductionAdapterRoleV1),
    DuplicateAdapterId(String),
    MissingRole(NduProductionAdapterRoleV1),
    BindingDigestMismatch,
    CompositionDigestMismatch,
    InvalidEvidenceWindow,
    QualificationIncomplete,
}

impl fmt::Display for NduProductionCompositionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduProductionCompositionErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProductionAdapterBindingV1 {
    role: NduProductionAdapterRoleV1,
    adapter_id: StableId,
    implementation_digest: Digest32,
    configuration_digest: Digest32,
    policy_digest: Digest32,
    policy_revision: u64,
    deployment_instance_digest: Digest32,
    capability_receipt_digest: Digest32,
    binding_digest: Digest32,
}

impl NduProductionAdapterBindingV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        role: NduProductionAdapterRoleV1,
        adapter_id: StableId,
        implementation_digest: Digest32,
        configuration_digest: Digest32,
        policy_digest: Digest32,
        policy_revision: u64,
        deployment_instance_digest: Digest32,
        capability_receipt_digest: Digest32,
    ) -> Result<Self, NduProductionCompositionErrorV1> {
        if adapter_id.as_str().is_empty()
            || adapter_id.as_str().len() > MAX_ADAPTER_ID_BYTES
        {
            return Err(NduProductionCompositionErrorV1::InvalidAdapterId);
        }
        require_digest(implementation_digest, "adapter implementation")?;
        require_digest(configuration_digest, "adapter configuration")?;
        require_digest(policy_digest, "adapter policy")?;
        require_digest(deployment_instance_digest, "deployment instance")?;
        require_digest(capability_receipt_digest, "capability receipt")?;
        if policy_revision == 0 {
            return Err(NduProductionCompositionErrorV1::InvalidPolicyRevision);
        }
        let binding_digest = digest_adapter_binding(
            role,
            &adapter_id,
            implementation_digest,
            configuration_digest,
            policy_digest,
            policy_revision,
            deployment_instance_digest,
            capability_receipt_digest,
        );
        Ok(Self {
            role,
            adapter_id,
            implementation_digest,
            configuration_digest,
            policy_digest,
            policy_revision,
            deployment_instance_digest,
            capability_receipt_digest,
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
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    #[must_use]
    pub const fn policy_revision(&self) -> u64 {
        self.policy_revision
    }

    #[must_use]
    pub const fn deployment_instance_digest(&self) -> Digest32 {
        self.deployment_instance_digest
    }

    #[must_use]
    pub const fn capability_receipt_digest(&self) -> Digest32 {
        self.capability_receipt_digest
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
            self.policy_digest,
            self.policy_revision,
            self.deployment_instance_digest,
            self.capability_receipt_digest,
        )?;
        if rebuilt.binding_digest != self.binding_digest {
            return Err(NduProductionCompositionErrorV1::BindingDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProductionCompositionV1 {
    bindings: BTreeMap<NduProductionAdapterRoleV1, NduProductionAdapterBindingV1>,
    composition_digest: Digest32,
}

impl NduProductionCompositionV1 {
    pub fn admit(
        bindings: Vec<NduProductionAdapterBindingV1>,
    ) -> Result<Self, NduProductionCompositionErrorV1> {
        let mut by_role = BTreeMap::new();
        let mut adapter_ids = BTreeSet::new();
        for binding in bindings {
            binding.validate()?;
            if !adapter_ids.insert(binding.adapter_id.to_string()) {
                return Err(NduProductionCompositionErrorV1::DuplicateAdapterId(
                    binding.adapter_id.to_string(),
                ));
            }
            let role = binding.role;
            if by_role.insert(role, binding).is_some() {
                return Err(NduProductionCompositionErrorV1::DuplicateRole(role));
            }
        }
        for role in NduProductionAdapterRoleV1::ALL {
            if !by_role.contains_key(&role) {
                return Err(NduProductionCompositionErrorV1::MissingRole(role));
            }
        }
        let composition_digest = digest_composition(&by_role);
        Ok(Self {
            bindings: by_role,
            composition_digest,
        })
    }

    #[must_use]
    pub fn binding(
        &self,
        role: NduProductionAdapterRoleV1,
    ) -> &NduProductionAdapterBindingV1 {
        self.bindings
            .get(&role)
            .expect("admitted compositions contain every closed role")
    }

    #[must_use]
    pub const fn composition_digest(&self) -> Digest32 {
        self.composition_digest
    }

    pub fn validate(&self) -> Result<(), NduProductionCompositionErrorV1> {
        for role in NduProductionAdapterRoleV1::ALL {
            let binding = self
                .bindings
                .get(&role)
                .ok_or(NduProductionCompositionErrorV1::MissingRole(role))?;
            binding.validate()?;
        }
        if self.bindings.len() != ROLE_COUNT
            || digest_composition(&self.bindings) != self.composition_digest
        {
            return Err(NduProductionCompositionErrorV1::CompositionDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProductionQualificationEvidenceV1 {
    pub exact_head_qualification_digest: Digest32,
    pub synthetic_merge_qualification_digest: Digest32,
    pub target_host_profile_digest: Digest32,
    pub target_filesystem_receipt_digest: Digest32,
    pub shared_volume_fence_receipt_digest: Digest32,
    pub encrypted_backup_readback_receipt_digest: Digest32,
    pub restore_drill_receipt_digest: Digest32,
    pub metrics_delivery_receipt_digest: Digest32,
    pub product_caller_receipt_digest: Digest32,
    pub independent_stochastic_acceptance_digest: Digest32,
    pub observed_at_ms: u64,
    pub valid_until_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProductionReadinessReceiptV1 {
    source_candidate_digest: Digest32,
    composition_digest: Digest32,
    exact_head_qualification_digest: Digest32,
    synthetic_merge_qualification_digest: Digest32,
    target_host_profile_digest: Digest32,
    target_filesystem_receipt_digest: Digest32,
    shared_volume_fence_receipt_digest: Digest32,
    encrypted_backup_readback_receipt_digest: Digest32,
    restore_drill_receipt_digest: Digest32,
    metrics_delivery_receipt_digest: Digest32,
    product_caller_receipt_digest: Digest32,
    independent_stochastic_acceptance_digest: Digest32,
    observed_at_ms: u64,
    valid_until_ms: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduProductionReadinessReceiptV1 {
    #[must_use]
    pub const fn source_candidate_digest(&self) -> Digest32 {
        self.source_candidate_digest
    }

    #[must_use]
    pub const fn composition_digest(&self) -> Digest32 {
        self.composition_digest
    }

    #[must_use]
    pub const fn valid_until_ms(&self) -> u64 {
        self.valid_until_ms
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), NduProductionCompositionErrorV1> {
        validate_evidence_fields(
            self.exact_head_qualification_digest,
            self.synthetic_merge_qualification_digest,
            self.target_host_profile_digest,
            self.target_filesystem_receipt_digest,
            self.shared_volume_fence_receipt_digest,
            self.encrypted_backup_readback_receipt_digest,
            self.restore_drill_receipt_digest,
            self.metrics_delivery_receipt_digest,
            self.product_caller_receipt_digest,
            self.independent_stochastic_acceptance_digest,
            self.observed_at_ms,
            self.valid_until_ms,
        )?;
        require_digest(self.source_candidate_digest, "source candidate")?;
        require_digest(self.composition_digest, "composition")?;
        if self.authority != AuthorityPosture::DENY_ALL
            || digest_readiness(self) != self.receipt_digest
        {
            return Err(NduProductionCompositionErrorV1::CompositionDigestMismatch);
        }
        Ok(())
    }
}

pub fn seal_production_readiness_v1(
    source_candidate_digest: Digest32,
    composition: &NduProductionCompositionV1,
    evidence: &NduProductionQualificationEvidenceV1,
) -> Result<NduProductionReadinessReceiptV1, NduProductionCompositionErrorV1> {
    require_digest(source_candidate_digest, "source candidate")?;
    composition.validate()?;
    validate_evidence_fields(
        evidence.exact_head_qualification_digest,
        evidence.synthetic_merge_qualification_digest,
        evidence.target_host_profile_digest,
        evidence.target_filesystem_receipt_digest,
        evidence.shared_volume_fence_receipt_digest,
        evidence.encrypted_backup_readback_receipt_digest,
        evidence.restore_drill_receipt_digest,
        evidence.metrics_delivery_receipt_digest,
        evidence.product_caller_receipt_digest,
        evidence.independent_stochastic_acceptance_digest,
        evidence.observed_at_ms,
        evidence.valid_until_ms,
    )?;
    let mut receipt = NduProductionReadinessReceiptV1 {
        source_candidate_digest,
        composition_digest: composition.composition_digest,
        exact_head_qualification_digest: evidence.exact_head_qualification_digest,
        synthetic_merge_qualification_digest: evidence
            .synthetic_merge_qualification_digest,
        target_host_profile_digest: evidence.target_host_profile_digest,
        target_filesystem_receipt_digest: evidence.target_filesystem_receipt_digest,
        shared_volume_fence_receipt_digest: evidence
            .shared_volume_fence_receipt_digest,
        encrypted_backup_readback_receipt_digest: evidence
            .encrypted_backup_readback_receipt_digest,
        restore_drill_receipt_digest: evidence.restore_drill_receipt_digest,
        metrics_delivery_receipt_digest: evidence.metrics_delivery_receipt_digest,
        product_caller_receipt_digest: evidence.product_caller_receipt_digest,
        independent_stochastic_acceptance_digest: evidence
            .independent_stochastic_acceptance_digest,
        observed_at_ms: evidence.observed_at_ms,
        valid_until_ms: evidence.valid_until_ms,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = digest_readiness(&receipt);
    receipt.validate()?;
    Ok(receipt)
}

#[allow(clippy::too_many_arguments)]
fn validate_evidence_fields(
    exact_head: Digest32,
    synthetic_merge: Digest32,
    target_host: Digest32,
    target_filesystem: Digest32,
    shared_volume_fence: Digest32,
    backup_readback: Digest32,
    restore_drill: Digest32,
    metrics_delivery: Digest32,
    product_caller: Digest32,
    stochastic_acceptance: Digest32,
    observed_at_ms: u64,
    valid_until_ms: u64,
) -> Result<(), NduProductionCompositionErrorV1> {
    for (digest, field) in [
        (exact_head, "exact-head qualification"),
        (synthetic_merge, "synthetic-merge qualification"),
        (target_host, "target-host profile"),
        (target_filesystem, "target-filesystem receipt"),
        (shared_volume_fence, "shared-volume fence receipt"),
        (backup_readback, "backup readback receipt"),
        (restore_drill, "restore drill receipt"),
        (metrics_delivery, "metrics delivery receipt"),
        (product_caller, "product caller receipt"),
        (stochastic_acceptance, "stochastic acceptance"),
    ] {
        require_digest(digest, field)?;
    }
    if observed_at_ms == 0 || valid_until_ms <= observed_at_ms {
        return Err(NduProductionCompositionErrorV1::InvalidEvidenceWindow);
    }
    Ok(())
}

fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), NduProductionCompositionErrorV1> {
    if digest.is_zero() {
        Err(NduProductionCompositionErrorV1::EmptyDigest(field))
    } else {
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
fn digest_adapter_binding(
    role: NduProductionAdapterRoleV1,
    adapter_id: &StableId,
    implementation_digest: Digest32,
    configuration_digest: Digest32,
    policy_digest: Digest32,
    policy_revision: u64,
    deployment_instance_digest: Digest32,
    capability_receipt_digest: Digest32,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.production-adapter-binding.v1\0",
        &[role.tag()],
        adapter_id.as_str().as_bytes(),
        b"\0",
        implementation_digest.as_array(),
        configuration_digest.as_array(),
        policy_digest.as_array(),
        &policy_revision.to_be_bytes(),
        deployment_instance_digest.as_array(),
        capability_receipt_digest.as_array(),
    ])
}

fn digest_composition(
    bindings: &BTreeMap<NduProductionAdapterRoleV1, NduProductionAdapterBindingV1>,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.production-composition.v1\0".to_vec();
    for role in NduProductionAdapterRoleV1::ALL {
        bytes.push(role.tag());
        if let Some(binding) = bindings.get(&role) {
            bytes.extend_from_slice(binding.binding_digest.as_array());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_readiness(receipt: &NduProductionReadinessReceiptV1) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.production-readiness-receipt.v1\0",
        receipt.source_candidate_digest.as_array(),
        receipt.composition_digest.as_array(),
        receipt.exact_head_qualification_digest.as_array(),
        receipt.synthetic_merge_qualification_digest.as_array(),
        receipt.target_host_profile_digest.as_array(),
        receipt.target_filesystem_receipt_digest.as_array(),
        receipt.shared_volume_fence_receipt_digest.as_array(),
        receipt.encrypted_backup_readback_receipt_digest.as_array(),
        receipt.restore_drill_receipt_digest.as_array(),
        receipt.metrics_delivery_receipt_digest.as_array(),
        receipt.product_caller_receipt_digest.as_array(),
        receipt.independent_stochastic_acceptance_digest.as_array(),
        &receipt.observed_at_ms.to_be_bytes(),
        &receipt.valid_until_ms.to_be_bytes(),
        &[0],
    ])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn binding(
        role: NduProductionAdapterRoleV1,
        index: usize,
    ) -> NduProductionAdapterBindingV1 {
        NduProductionAdapterBindingV1::new(
            role,
            id(&format!("adapter-{index}")),
            digest(&format!("implementation-{index}")),
            digest(&format!("configuration-{index}")),
            digest(&format!("policy-{index}")),
            1,
            digest(&format!("deployment-{index}")),
            digest(&format!("capability-{index}")),
        )
        .expect("binding")
    }

    #[test]
    fn composition_requires_every_concrete_role_and_identity() {
        let bindings = NduProductionAdapterRoleV1::ALL
            .into_iter()
            .enumerate()
            .map(|(index, role)| binding(role, index))
            .collect::<Vec<_>>();
        let composition = NduProductionCompositionV1::admit(bindings.clone())
            .expect("complete composition");
        composition.validate().expect("valid composition");

        let mut incomplete = bindings;
        incomplete.pop();
        assert_eq!(
            NduProductionCompositionV1::admit(incomplete),
            Err(NduProductionCompositionErrorV1::MissingRole(
                NduProductionAdapterRoleV1::ProductCaller
            ))
        );
    }
}
