//! Strict journal DTOs for M15's existing signed roots and events. The native
//! M15 implementation remains the sole owner of signing bytes and verification.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;
use trnm_release_bundle::pq_release::MAX_RELEASE_KEYS_V1;
use trnm_release_bundle::pq_release::PqReleaseEventV1;
use trnm_release_bundle::pq_release::PqReleaseMetadataV1;
use trnm_release_bundle::pq_release::PqReleaseRoleKeysV1;
use trnm_release_bundle::pq_release::PqReleaseRoleV1;
use trnm_release_bundle::pq_release::PqReleaseRootV1;
use trnm_release_bundle::pq_release::PqReleaseSignatureV1;

use crate::FleetRegistryError;
use crate::release_authority::invalid;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum RoleRecord {
    NodeSoftware,
    ProtocolConfiguration,
    CellManifest,
    CellActivation,
}

impl From<RoleRecord> for PqReleaseRoleV1 {
    fn from(value: RoleRecord) -> Self {
        match value {
            RoleRecord::NodeSoftware => Self::NodeSoftware,
            RoleRecord::ProtocolConfiguration => Self::ProtocolConfiguration,
            RoleRecord::CellManifest => Self::CellManifest,
            RoleRecord::CellActivation => Self::CellActivation,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct KeyRecord {
    pub key_id: [u8; 32],
    pub public_key_spki: Vec<u8>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct KeysRecord {
    pub threshold: u16,
    pub keys: Vec<KeyRecord>,
}

impl TryFrom<&KeysRecord> for PqReleaseRoleKeysV1 {
    type Error = FleetRegistryError;

    fn try_from(value: &KeysRecord) -> Result<Self, Self::Error> {
        if value.keys.is_empty() || value.keys.len() > MAX_RELEASE_KEYS_V1 {
            return Err(invalid("root key count exceeds the M15 bound"));
        }
        let mut keys = BTreeMap::new();
        for key in &value.keys {
            if keys
                .insert(key.key_id, key.public_key_spki.clone())
                .is_some()
            {
                return Err(invalid("duplicate root key identity"));
            }
        }
        Ok(Self {
            threshold: value.threshold,
            keys,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RoleKeysRecord {
    pub role: RoleRecord,
    pub keys: KeysRecord,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootRecord {
    pub network_id: [u8; 32],
    pub generation: u64,
    pub expires_at: u64,
    pub previous_root_digest: [u8; 32],
    pub offline_root: KeysRecord,
    pub roles: Vec<RoleKeysRecord>,
}

impl TryFrom<&RootRecord> for PqReleaseRootV1 {
    type Error = FleetRegistryError;

    fn try_from(value: &RootRecord) -> Result<Self, Self::Error> {
        if value.roles.len() != 4 {
            return Err(invalid("root must contain the four distinct M15 roles"));
        }
        let mut roles = BTreeMap::new();
        for role in &value.roles {
            if roles
                .insert(
                    PqReleaseRoleV1::from(role.role),
                    PqReleaseRoleKeysV1::try_from(&role.keys)?,
                )
                .is_some()
            {
                return Err(invalid("duplicate root role"));
            }
        }
        Ok(Self {
            network_id: value.network_id,
            generation: value.generation,
            expires_at: value.expires_at,
            previous_root_digest: value.previous_root_digest,
            offline_root: PqReleaseRoleKeysV1::try_from(&value.offline_root)?,
            roles,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct SignatureRecord {
    pub key_id: [u8; 32],
    pub signature: Vec<u8>,
}

impl From<&SignatureRecord> for PqReleaseSignatureV1 {
    fn from(value: &SignatureRecord) -> Self {
        Self {
            key_id: value.key_id,
            signature: value.signature.clone(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MetadataRecord {
    pub network_id: [u8; 32],
    pub role: RoleRecord,
    pub root_generation: u64,
    pub role_version: u64,
    pub expires_at: u64,
    pub expected_checkpoint: [u8; 32],
    pub previous_content: Option<[u8; 32]>,
    pub content: [u8; 32],
    pub approved_content_rollback: bool,
}

impl From<&MetadataRecord> for PqReleaseMetadataV1 {
    fn from(value: &MetadataRecord) -> Self {
        Self {
            network_id: value.network_id,
            role: PqReleaseRoleV1::from(value.role),
            root_generation: value.root_generation,
            role_version: value.role_version,
            expires_at: value.expires_at,
            expected_checkpoint: value.expected_checkpoint,
            previous_content: value.previous_content,
            content: value.content,
            approved_content_rollback: value.approved_content_rollback,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum AuthorityEventRecord {
    RootRotation {
        root: RootRecord,
        old_signatures: Vec<SignatureRecord>,
        new_signatures: Vec<SignatureRecord>,
        observed_at: u64,
    },
    ReleaseSet {
        metadata: MetadataRecord,
        signatures: Vec<SignatureRecord>,
        observed_at: u64,
    },
    ProtocolConfiguration {
        metadata: MetadataRecord,
        signatures: Vec<SignatureRecord>,
        observed_at: u64,
    },
}

impl TryFrom<&AuthorityEventRecord> for PqReleaseEventV1 {
    type Error = FleetRegistryError;

    fn try_from(value: &AuthorityEventRecord) -> Result<Self, Self::Error> {
        match value {
            AuthorityEventRecord::RootRotation {
                root,
                old_signatures,
                new_signatures,
                observed_at,
            } => Ok(Self::RootRotation {
                root: PqReleaseRootV1::try_from(root)?,
                old_signatures: old_signatures
                    .iter()
                    .map(PqReleaseSignatureV1::from)
                    .collect(),
                new_signatures: new_signatures
                    .iter()
                    .map(PqReleaseSignatureV1::from)
                    .collect(),
                observed_at: *observed_at,
            }),
            AuthorityEventRecord::ReleaseSet {
                metadata,
                signatures,
                observed_at,
            } if metadata.role == RoleRecord::NodeSoftware => Ok(Self::Release {
                metadata: PqReleaseMetadataV1::from(metadata),
                signatures: signatures.iter().map(PqReleaseSignatureV1::from).collect(),
                observed_at: *observed_at,
            }),
            AuthorityEventRecord::ReleaseSet { .. } => {
                Err(invalid("non-software Fleet publication"))
            }
            AuthorityEventRecord::ProtocolConfiguration {
                metadata,
                signatures,
                observed_at,
            } if metadata.role == RoleRecord::ProtocolConfiguration => Ok(Self::Release {
                metadata: PqReleaseMetadataV1::from(metadata),
                signatures: signatures.iter().map(PqReleaseSignatureV1::from).collect(),
                observed_at: *observed_at,
            }),
            AuthorityEventRecord::ProtocolConfiguration { .. } => {
                Err(invalid("wrong protocol configuration role"))
            }
        }
    }
}
