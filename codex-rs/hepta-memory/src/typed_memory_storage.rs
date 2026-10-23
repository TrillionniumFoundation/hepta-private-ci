//! Immutable typed admission retained with the existing revision INSERT.

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::sqlite::SqliteRow;

use crate::CognitiveStoreError;
use crate::cognitive_store::unavailable;
use crate::typed_memory_admission::TYPED_MEMORY_ADMISSION_PURPOSE_V1;
use crate::typed_memory_admission::TypedMemoryKindV1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct StoredTypedAdmissionV1 {
    pub purpose: String,
    pub kind: TypedMemoryKindV1,
    pub memory_id: String,
    pub admitted_revision: u64,
    pub owner_agent_id: String,
    pub input_payload_sha256: Sha256Digest,
    pub owner_cut_sha256: Sha256Digest,
    pub source_frontier: u64,
    pub tombstone_frontier: u64,
    pub host_evidence_sha256: Sha256Digest,
    pub binding: FinalUseBinding,
    pub signed_grant: SignedFinalUseGrant,
    pub claim_witness_sha256: Sha256Digest,
}

/// Constructible only within the durable-owner crate. Legacy callers cannot
/// choose a kind or attach unsigned metadata to the production capability.
#[derive(Clone, Debug)]
pub(crate) struct RevisionAdmissionV1 {
    pub kind: TypedMemoryKindV1,
    pub sha256: Option<Sha256Digest>,
    pub json: Option<String>,
}

impl RevisionAdmissionV1 {
    pub fn legacy_fact() -> Self {
        Self {
            kind: TypedMemoryKindV1::Fact,
            sha256: None,
            json: None,
        }
    }

    pub fn signed(value: &StoredTypedAdmissionV1) -> Result<Self, CognitiveStoreError> {
        let json = serde_json::to_string(value).map_err(unavailable)?;
        if json.len() > 16 * 1024 {
            return Err(CognitiveStoreError::Invalid(
                "typed admission exceeds 16 KiB".into(),
            ));
        }
        Ok(Self {
            kind: value.kind,
            sha256: Some(Sha256Digest::for_bytes(json.as_bytes())),
            json: Some(json),
        })
    }

    pub fn from_row(row: &SqliteRow) -> Result<Self, CognitiveStoreError> {
        let kind = TypedMemoryKindV1::parse(
            &row.try_get::<String, _>("memory_kind")
                .map_err(unavailable)?,
        )?;
        let json: Option<String> = row.try_get("typed_admission_json").map_err(unavailable)?;
        let sha256: Option<String> = row.try_get("typed_admission_sha256").map_err(unavailable)?;
        match (&json, &sha256) {
            (None, None) if kind == TypedMemoryKindV1::Fact => Ok(Self::legacy_fact()),
            (Some(json), Some(digest)) if json.len() <= 16 * 1024 => {
                let value: StoredTypedAdmissionV1 = serde_json::from_str(json)
                    .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
                let revision: i64 = row.try_get("revision").map_err(unavailable)?;
                let lifecycle: String = row.try_get("lifecycle").map_err(unavailable)?;
                let expected = digest_bytes(&value.input_payload_sha256)?;
                if Sha256Digest::for_bytes(json.as_bytes()).as_str() != digest
                    || value.purpose != TYPED_MEMORY_ADMISSION_PURPOSE_V1
                    || value.kind != kind
                    || value.memory_id
                        != row.try_get::<String, _>("memory_id").map_err(unavailable)?
                    || value.owner_agent_id
                        != row
                            .try_get::<String, _>("owner_agent_id")
                            .map_err(unavailable)?
                    || value.admitted_revision == 0
                    || value.admitted_revision > revision as u64
                    || (lifecycle != "tombstoned" && value.admitted_revision != revision as u64)
                    || value.binding != value.signed_grant.grant.binding
                    || value.binding.payload_sha256 != expected
                {
                    return Err(CognitiveStoreError::Corrupt(
                        "typed admission binding changed".into(),
                    ));
                }
                value
                    .signed_grant
                    .grant
                    .signing_bytes()
                    .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
                Ok(Self {
                    kind,
                    sha256: Some(
                        Sha256Digest::parse(digest).map_err(CognitiveStoreError::Corrupt)?,
                    ),
                    json: Some(json.clone()),
                })
            }
            _ => Err(CognitiveStoreError::Corrupt(
                "memory kind has no immutable admission".into(),
            )),
        }
    }
}

pub(crate) fn digest_bytes(value: &Sha256Digest) -> Result<[u8; 32], CognitiveStoreError> {
    value
        .as_str()
        .parse::<Digest32>()
        .map(|digest| *digest.as_array())
        .map_err(|error| CognitiveStoreError::Corrupt(format!("invalid typed digest: {error}")))
}
